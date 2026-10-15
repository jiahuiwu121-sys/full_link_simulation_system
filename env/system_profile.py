#!/usr/bin/env python3
"""Compile a user-facing system profile into reproducible build/run inputs."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import shlex
from pathlib import Path

from topology_config import load


class Args:
    """Minimal argparse-compatible view consumed by topology_config.load."""
    topology_modules = None
    topology_stripe_bytes = None
    ucie_lanes = ''
    ucie_rate_gtps = ''
    ucie_modulation = ''

    def __init__(self, path: Path, width: int):
        self.topology_config = str(path)
        self.axi_data_width = width


def _period_fs(value: str) -> int:
    text = str(value).strip().lower()
    scales = {'fs': 1, 'ps': 1_000, 'ns': 1_000_000, 'us': 1_000_000_000}
    for suffix, scale in scales.items():
        if text.endswith(suffix):
            number = float(text[:-len(suffix)])
            if number <= 0 or not math.isfinite(number):
                break
            return round(number * scale)
    raise ValueError(f'unsupported positive AXI period: {value}')


def _memory_capacity_and_peak(node):
    standard = node['standard']
    channels = node['channels']
    if standard == 'HBM3':
        # HBM3_16Gb_8hi: one 64-bit controller represents two x32 PCs.
        return channels * (1 << 30), channels * 51.2e9
    if standard == 'HBM3E':
        return channels * int(1.5 * (1 << 30)), channels * 64.0e9
    if standard == 'HBM4':
        return channels * (1 << 30), channels * 64.0e9
    # LPDDR presets are intentionally reported from their explicit payload
    # geometry only; capacity remains absent when the profile is exploratory.
    if standard == 'LPDDR5':
        return channels * 2 * (1 << 30), channels * 12.8e9
    if standard == 'LPDDR6':
        return channels * 2 * (1 << 30), channels * 16.0e9
    raise ValueError('unsupported memory standard ' + standard)


def compile_profile(profile: Path, output: Path):
    profile = profile.resolve()
    raw = json.loads(profile.read_text())
    if raw.get('schema') != 'storagestacked.system.v2':
        raise ValueError('system profile must use storagestacked.system.v2')
    width = int(raw.get('axi', {}).get('data_width_bits', 256))
    bridge = raw.get('bridge', {})
    backend = raw.get('backend', {})
    planes = int(bridge.get('resource_planes', 1))
    slots = int(bridge.get('tlm_slots', 64))
    queue = int(backend.get('queue', 64))
    parent_slots = int(backend.get('parent_slots', 64))
    child_slots = int(backend.get('child_slots', 512))
    submit_width = int(backend.get('submit_width', 8))
    if planes not in (1, 2, 3, 4):
        raise ValueError('bridge.resource_planes must be 1, 2, 3 or 4')
    if min(slots, queue, parent_slots, child_slots, submit_width) < 1:
        raise ValueError('bridge/backend queue and slot values must be positive')
    if submit_width > child_slots:
        raise ValueError('backend.submit_width cannot exceed backend.child_slots')
    old_width = os.environ.get('SS_AXI_DATA_WIDTH')
    os.environ['SS_AXI_DATA_WIDTH'] = str(width)
    try:
        resolved = load(Args(profile, width))
    finally:
        if old_width is None:
            os.environ.pop('SS_AXI_DATA_WIDTH', None)
        else:
            os.environ['SS_AXI_DATA_WIDTH'] = old_width
    ports_per_link = {link['id']: 0 for link in resolved['modules']}
    for port in resolved['axi_ports']:
        ports_per_link[port['link']] += 1
    smallest_local_id_space = min(1023 // count for count in ports_per_link.values())
    if slots > smallest_local_id_space:
        raise ValueError(f'bridge.tlm_slots={slots} exceeds the per-port AXI ID space '
                         f'{smallest_local_id_space} in the most aggregated link')

    period = str(resolved['axi']['clock_period'])
    period_fs = _period_fs(period)
    fabric_ratio = int(resolved['bridge']['fabric_clock_ratio'])
    if period_fs % fabric_ratio:
        raise ValueError('AXI input period must divide exactly by bridge.fabric_clock_ratio in femtoseconds')
    fabric_period_fs = period_fs // fabric_ratio
    per_port = width / 8 / (period_fs * 1e-15)
    axi_total = per_port * len(resolved['axi_ports'])
    gearbox_total = width / 8 / (fabric_period_fs * 1e-15) * len(resolved['modules'])
    ucie_rows = []
    for link in resolved['modules']:
        raw_peak = link['ucie']['raw_bandwidth_GBps'] * 1e9
        ucie_rows.append({'name': link['name'], 'raw_Bps': raw_peak,
                          'aou_payload_Bps': raw_peak * 250 / 256})
    memory_rows = []
    for node in resolved['memory_nodes']:
        capacity, peak = _memory_capacity_and_peak(node)
        memory_rows.append({'name': node['name'], 'standard': node['standard'],
                            'capacity_bytes': capacity, 'theoretical_Bps': peak})
    ucie_raw = sum(x['raw_Bps'] for x in ucie_rows)
    ucie_payload = sum(x['aou_payload_Bps'] for x in ucie_rows)
    memory_peak = sum(x['theoretical_Bps'] for x in memory_rows)
    effective_ceiling = min(axi_total, gearbox_total, ucie_payload, memory_peak)
    requirements = resolved.get('requirements', {})
    required_bw = float(requirements.get('minimum_effective_bandwidth_GBps', 0)) * 1e9
    target_util = float(requirements.get('minimum_link_utilization', 0))
    if target_util and not 0 < target_util <= 1:
        raise ValueError('minimum_link_utilization must be in (0, 1]')
    max_bridge_latency = float(requirements.get('maximum_bridge_latency_ns', 0))
    if max_bridge_latency < 0:
        raise ValueError('maximum_bridge_latency_ns cannot be negative')
    feasibility = {
        'required_effective_bandwidth_met_by_theory': not required_bw or effective_ceiling >= required_bw,
        'required_bandwidth_not_ruled_out_by_raw_capacity': not required_bw or effective_ceiling >= required_bw,
        'required_effective_bandwidth_Bps': required_bw or None,
        'target_link_utilization': target_util or None,
        'hbm_utilization_ceiling': effective_ceiling / memory_peak if memory_peak else None,
    }
    report = {
        'schema': 'storagestacked.capacity-report.v1',
        'profile': resolved['name'], 'axi_data_width_bits': width,
        'axi_clock_period_fs': period_fs, 'axi_ports': len(resolved['axi_ports']),
        'axi_per_port_Bps': per_port, 'axi_aggregate_Bps': axi_total,
        'fabric_clock_ratio': fabric_ratio, 'fabric_clock_period_fs': fabric_period_fs,
        'gearbox_output_aggregate_Bps': gearbox_total,
        'ucie_links': ucie_rows, 'ucie_raw_aggregate_Bps': ucie_raw,
        'ucie_aou_payload_aggregate_Bps': ucie_payload,
        'memory_nodes': memory_rows, 'memory_capacity_bytes': sum(x['capacity_bytes'] for x in memory_rows),
        'memory_theoretical_Bps': memory_peak, 'effective_ceiling_Bps': effective_ceiling,
        'raw_payload_capacity_ceiling_Bps': effective_ceiling,
        'bottleneck': min((('AXI inputs', axi_total), ('AXI gearbox output', gearbox_total),
                           ('UCIe AoU payload', ucie_payload),
                           ('memory', memory_peak)), key=lambda x: x[1])[0],
        'feasibility': feasibility,
        'notes': [
            'Capacity arithmetic is a feasibility bound, not a measured result.',
            'The raw payload ceiling does not include workload-dependent AXI/AoU messages, credits, queuing or command timing.',
            'HBM3/HBM4 power remains an explicit public-data estimate.',
            'A 90% HBM target is rejected when the upstream physical ceiling is lower.',
        ],
    }
    if required_bw and effective_ceiling < required_bw:
        raise ValueError(f'profile requires {required_bw/1e9:.3f} GB/s but theoretical ceiling is '
                         f'{effective_ceiling/1e9:.3f} GB/s')

    output.mkdir(parents=True, exist_ok=True)
    # Keep both forms: the normalized graph is convenient for audit/reporting,
    # while runtime_topology retains the public schema consumed by run.py.
    runtime_topology = copy.deepcopy(raw)
    for index, memory in enumerate(runtime_topology['memory_nodes']):
        resolved_memory = resolved['memory_nodes'][index]
        if resolved_memory.get('config'):
            memory['config'] = resolved_memory['config']
    (output / 'system_profile.json').write_text(json.dumps(raw, indent=2) + '\n')
    (output / 'topology_resolved.json').write_text(json.dumps(resolved, indent=2) + '\n')
    (output / 'runtime_topology.json').write_text(json.dumps(runtime_topology, indent=2) + '\n')
    (output / 'capacity_report.json').write_text(json.dumps(report, indent=2) + '\n')
    rows = [
        '# 系统配置容量报告', '',
        f"- 配置：`{resolved['name']}`",
        f'- AXI：{len(resolved["axi_ports"])} × {width} bit，周期 {period}，聚合 {axi_total/1e9:.3f} GB/s',
        f'- 聚合器：{fabric_ratio}:1 确定性时分，内部周期 {fabric_period_fs} fs，输出 {gearbox_total/1e9:.3f} GB/s',
        f'- UCIe原始聚合：{ucie_raw/1e9:.3f} GB/s',
        f'- UCIe AoU载荷上限：{ucie_payload/1e9:.3f} GB/s',
        f'- 内存容量：{sum(x["capacity_bytes"] for x in memory_rows)/(1<<30):.3f} GiB',
        f'- 内存理论带宽：{memory_peak/1e9:.3f} GB/s',
        f'- 配置层原始载荷容量上界：{effective_ceiling/1e9:.3f} GB/s',
        f'- 理论瓶颈：{report["bottleneck"]}',
        f'- 内存理论利用率上限：{feasibility["hbm_utilization_ceiling"]*100:.2f}%', '',
        '该报告只做配置与容量可行性检查；最终结论必须读取稳态仿真测量。',
    ]
    (output / 'capacity_report.md').write_text('\n'.join(rows) + '\n')
    build = {'SS_MEMORY_BACKEND': 'ramulator2', 'SS_AXI_DATA_WIDTH': str(width)}
    run = {
        'SS_AXI_DATA_WIDTH': str(width), 'SS_AXI_PERIOD': f'{fabric_period_fs}fs',
        'SS_RESOURCE_PLANES': str(planes),
        'SS_TLM_SLOTS': str(slots),
        'SS_RAMULATOR_QUEUE': str(queue),
        'SS_RAMULATOR_SLOTS': str(parent_slots),
        'SS_RAMULATOR_CHILDREN': str(child_slots),
        'SS_RAMULATOR_SUBMIT_WIDTH': str(submit_width),
    }
    for name, values in [('build.env', build), ('run.env', run)]:
        (output / name).write_text(''.join(f'export {k}={shlex.quote(v)}\n' for k, v in values.items()))
    signature = hashlib.sha256(json.dumps(build, sort_keys=True).encode()).hexdigest()
    (output / 'build_signature.json').write_text(json.dumps({'sha256': signature, 'inputs': build}, indent=2) + '\n')
    validation = {
        'schema': 'storagestacked.validation-plan.v1', 'profile': resolved['name'],
        'checks': ['profile_schema', 'capacity_feasibility', 'source_and_edge_references',
                   'AXI read/write data closure', 'global transaction ID routing',
                   'UCIe exact delivery', 'Ramulator command/data closure',
                   'DRAMPower final snapshot', '10-125% offered-load sweep',
                   'long 100/125% drain and deadlock check'],
        'load_sweep_percent': [10, 25, 50, 75, 90, 100, 110, 125],
        'requirements': requirements,
    }
    (output / 'validation_plan.json').write_text(json.dumps(validation, indent=2) + '\n')
    return resolved, report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    resolved, report = compile_profile(args.profile, args.output)
    print(json.dumps({'profile': resolved['name'], 'bottleneck': report['bottleneck'],
                      'raw_payload_capacity_ceiling_GBps':
                          report['raw_payload_capacity_ceiling_Bps'] / 1e9}, indent=2))
