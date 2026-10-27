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

from protocol_profiles import resolve as resolve_protocol
from topology_config import load

ROOT = Path(__file__).resolve().parents[1]
EXECUTION_MODES = ('traffic', 'cpu', 'gpu', 'npu', 'cpu_gpu', 'cpu_npu',
                   'cpu_gpu_npu')


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


def _integer(section, key, default, minimum=1, maximum=None):
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f'{key} must be an integer >= {minimum}')
    if maximum is not None and value > maximum:
        raise ValueError(f'{key} must be <= {maximum}')
    return value


def _boolean(section, key, default):
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f'{key} must be true or false')
    return value


def _number(section, key, default, minimum=None, maximum=None):
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{key} must be a finite number')
    value = float(value)
    if minimum is not None and value < minimum:
        raise ValueError(f'{key} must be >= {minimum}')
    if maximum is not None and value > maximum:
        raise ValueError(f'{key} must be <= {maximum}')
    return value


def _strip_documentation(value):
    """Remove underscore-prefixed authoring notes from runtime inputs."""
    if isinstance(value, dict):
        return {key: _strip_documentation(item) for key, item in value.items()
                if not key.startswith('_') and key != '$schema'}
    if isinstance(value, list):
        return [_strip_documentation(item) for item in value]
    return value


def _project_path(value, field):
    if not isinstance(value, str) or not value:
        raise ValueError(f'{field} must be a non-empty project-relative or absolute path')
    path = Path(value)
    return str((path if path.is_absolute() else ROOT / path).resolve())


def _execution_plan(section, max_ticks):
    if not isinstance(section, dict):
        raise ValueError('execution must be an object')
    mode = section.get('mode', 'traffic')
    if mode not in EXECUTION_MODES:
        raise ValueError('execution.mode must be one of ' + ', '.join(EXECUTION_MODES))
    has_gpu = mode in ('gpu', 'cpu_gpu', 'cpu_gpu_npu')
    has_npu = mode in ('npu', 'cpu_npu', 'cpu_gpu_npu')
    requires_xpu = has_gpu or has_npu
    host = section.get('host', {})
    cpu = section.get('cpu', {})
    gpu = section.get('gpu', {})
    npu = section.get('npu', {})
    if not all(isinstance(value, dict) for value in (host, cpu, gpu, npu)):
        raise ValueError('execution host/cpu/gpu/npu sections must be objects')
    model = cpu.get('model', 'X86TimingSimpleCPU')
    if model != 'X86TimingSimpleCPU':
        raise ValueError('execution.cpu.model currently supports X86TimingSimpleCPU only')
    cpu_count = _integer(cpu, 'count', 4 if requires_xpu else 1)
    if mode == 'cpu' and cpu_count != 1:
        raise ValueError('standalone CPU mode currently requires execution.cpu.count=1')
    if has_gpu and cpu_count < 2:
        raise ValueError('Vortex host runtime requires execution.cpu.count >= 2')
    arguments = host.get('arguments', [])
    if not isinstance(arguments, list) or any(not isinstance(x, str) for x in arguments):
        raise ValueError('execution.host.arguments must be a string array')
    environment = host.get('environment', {})
    if (not isinstance(environment, dict) or
            any(not isinstance(k, str) or not isinstance(v, str)
                for k, v in environment.items())):
        raise ValueError('execution.host.environment must map strings to strings')
    defaults = {
        'cpu': ('gem5_axi/build/ramulator_check', []),
        'gpu': ('vortex-gpu/vxbuild/tests/regression/vecadd/vecadd', ['-n', '4']),
        'npu': ('gem5_new/workloads/shared_buffer/build/host_main', ['npu']),
        'cpu_gpu': ('vortex-gpu/vxbuild/tests/regression/vecadd/vecadd', ['-n', '4']),
        'cpu_npu': ('gem5_new/workloads/shared_buffer/build/host_main', ['npu']),
        'cpu_gpu_npu': ('gem5_new/workloads/three_source/build/host_main', []),
    }
    binary = host.get('binary')
    if mode != 'traffic':
        if not binary and mode in defaults:
            binary, default_arguments = defaults[mode]
            if not arguments:
                arguments = default_arguments
        if not binary:
            raise ValueError('execution.host.binary is required for CPU/device modes')
        binary = _project_path(binary, 'execution.host.binary')
    target_size = host.get('target_size_bytes')
    if target_size is not None and (isinstance(target_size, bool) or
                                    not isinstance(target_size, int) or target_size < 8192):
        raise ValueError('execution.host.target_size_bytes must be an integer >= 8192')
    plan = {
        'schema': 'storagestacked.frontend-plan.v1',
        'mode': mode,
        'runner': 'xpu' if requires_xpu else 'classic',
        'requires_xpu': requires_xpu,
        'devices': ([] if mode == 'traffic' else ['cpu']) +
                   (['gpu'] if has_gpu else []) + (['npu'] if has_npu else []),
        'host': {'binary': binary, 'arguments': arguments, 'environment': environment,
                 'target_size_bytes': target_size},
        'cpu': {'model': model, 'count': cpu_count},
        'gpu': {'enabled': has_gpu},
        'npu': {'enabled': has_npu},
        'max_ticks': max_ticks,
    }
    if has_gpu:
        library = gpu.get('library', 'vortex-gpu/vxbuild/sim/simx/libvortex-gem5.so')
        runtime = gpu.get('runtime_directory', 'vortex-gpu/vxbuild/sw/runtime')
        kernel = gpu.get('kernel', 'vortex-gpu/vxbuild/tests/regression/vecadd/kernel.vxbin')
        plan['gpu'].update(library=_project_path(library, 'execution.gpu.library'),
                           runtime_directory=_project_path(runtime, 'execution.gpu.runtime_directory'),
                           kernel=_project_path(kernel, 'execution.gpu.kernel'))
        if '-k' not in arguments:
            plan['host']['arguments'] = [*arguments, '-k', plan['gpu']['kernel']]
    if has_npu:
        library = npu.get('library', 'coralnpu/bazel-bin/gem5int/libcoralnpu-gem5.so')
        kernel = npu.get('kernel', 'build/xpu/ddr_touch.elf')
        plan['npu'].update(library=_project_path(library, 'execution.npu.library'),
                           kernel=_project_path(kernel, 'execution.npu.kernel'))
    return plan


def compile_profile(profile: Path, output: Path):
    profile = profile.resolve()
    raw = json.loads(profile.read_text())
    if raw.get('schema') != 'storagestacked.system.v2':
        raise ValueError('system profile must use storagestacked.system.v2')
    width = int(raw.get('axi', {}).get('data_width_bits', 256))
    bridge = raw.get('bridge', {})
    backend = raw.get('backend', {})
    workload = raw.get('workload', {})
    execution = raw.get('execution', {})
    protocol_section = raw.get('protocol', {})
    simulation = raw.get('simulation', {})
    observability = raw.get('observability', {})
    sweep = raw.get('sweep', {})
    if not all(isinstance(value, dict) for value in
               (bridge, backend, workload, execution, protocol_section, simulation,
                observability, sweep)):
        raise ValueError('profile configuration sections must be objects')
    planes = int(bridge.get('resource_planes', 1))
    slots = int(bridge.get('tlm_slots', 64))
    bridge_implementation = bridge.get('implementation', 'systemc')
    queue = int(backend.get('queue', 64))
    parent_slots = int(backend.get('parent_slots', 64))
    child_slots = int(backend.get('child_slots', 512))
    submit_width = int(backend.get('submit_width', 8))
    response_hold = _integer(backend, 'response_hold_ticks', 0, minimum=0)
    clock_scale = _integer(backend, 'clock_scale', 1)
    power_enabled = _boolean(backend, 'power_enabled', True)
    metrics_sample_cycles = _integer(observability, 'metrics_sample_cycles', 1000)
    if planes not in (1, 2, 3, 4):
        raise ValueError('bridge.resource_planes must be 1, 2, 3 or 4')
    if bridge_implementation not in ('systemc', 'rtl'):
        raise ValueError('bridge.implementation must be systemc or rtl')
    if min(slots, queue, parent_slots, child_slots, submit_width) < 1:
        raise ValueError('bridge/backend queue and slot values must be positive')
    if submit_width > child_slots:
        raise ValueError('backend.submit_width cannot exceed backend.child_slots')
    workload_mode = workload.get('mode', 'traffic')
    if workload_mode != 'traffic':
        raise ValueError('workload.mode describes the pressure generator and must be traffic')
    traffic = workload.get('traffic', {})
    if not isinstance(traffic, dict):
        raise ValueError('workload.traffic must be an object')
    traffic_load = _number(traffic, 'load_percent', 100.0, minimum=0.000001, maximum=400.0)
    traffic_warmup = _integer(traffic, 'warmup_requests', 128)
    traffic_measure = _integer(traffic, 'measure_requests', 1024)
    traffic_cooldown = _integer(traffic, 'cooldown_requests', 128)
    traffic_size = _integer(traffic, 'request_size_bytes', 256, maximum=4096)
    traffic_working_set = _integer(traffic, 'working_set_bytes', 1024 * 1024)
    traffic_writes = _integer(traffic, 'write_percent', 50, minimum=0, maximum=100)
    traffic_inflight = _integer(traffic, 'max_inflight', 256)
    if traffic_working_set % traffic_size:
        raise ValueError('workload.traffic.working_set_bytes must be a multiple of request_size_bytes')
    if traffic_working_set // traffic_size <= traffic_inflight:
        raise ValueError('workload.traffic working set must contain more request blocks than max_inflight')
    max_ticks = _integer(simulation, 'max_ticks', 10**13)
    frontend = _execution_plan(execution, max_ticks)
    protocol = resolve_protocol(protocol_section)
    deterministic_stalls = _boolean(simulation, 'deterministic_axi_stalls', True)
    ucie_replay = _boolean(simulation, 'ucie_replay', False)
    visualization_open = _boolean(observability, 'visualization_open', True)
    visualization_serve = _boolean(observability, 'visualization_serve', True)
    view_port = _integer(observability, 'view_port', 8000, maximum=65535)
    old_width = os.environ.get('SS_AXI_DATA_WIDTH')
    os.environ['SS_AXI_DATA_WIDTH'] = str(width)
    try:
        resolved = _strip_documentation(load(Args(profile, width)))
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
    if len(resolved['axi_ports']) > 1:
        stripe = int(resolved['routing']['stripe_bytes'])
        if traffic_size > stripe or stripe % traffic_size:
            raise ValueError('workload.traffic.request_size_bytes must divide the address stripe '
                             'and cannot exceed it')
    if clock_scale != 1 and any(node['standard'] != 'HBM4' for node in resolved['memory_nodes']):
        raise ValueError('backend.clock_scale is only supported by generated HBM4 configurations')
    per_port = width / 8 / (period_fs * 1e-15)
    axi_total = per_port * len(resolved['axi_ports'])
    gearbox_total = width / 8 / (fabric_period_fs * 1e-15) * len(resolved['modules'])
    ucie_rows = []
    for link in resolved['modules']:
        raw_peak = link['ucie']['raw_bandwidth_GBps'] * 1e9
        ucie_rows.append({
            'name': link['name'],
            'raw_Bps': raw_peak,
            'aou_payload_Bps': raw_peak * protocol['aou_payload_bytes'] /
                               protocol['aou_frame_bytes'],
        })
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
    runtime_topology = _strip_documentation(copy.deepcopy(raw))
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
    build = {
        'SS_MEMORY_BACKEND': 'ramulator2',
        'SS_AXI_DATA_WIDTH': str(width),
        'SS_FRONTEND_FAMILY': 'xpu' if frontend['requires_xpu'] else 'classic',
        'SS_PROTOCOL_PROFILE': protocol['profile'],
        'SS_AXI_ADDRESS_WIDTH': str(protocol['axi_address_width_bits']),
        'SS_AXI_ID_WIDTH': str(protocol['axi_id_width_bits']),
        'SS_STORAGE_BRIDGE_IMPL': bridge_implementation,
        'SS_RESOURCE_PLANES': str(planes),
    }
    run = {
        'SS_AXI_DATA_WIDTH': str(width), 'SS_AXI_PERIOD': f'{fabric_period_fs}fs',
        'SS_EXECUTION_MODE': frontend['mode'],
        'SS_FRONTEND_PLAN': str((output / 'frontend_plan.json').resolve()),
        'SS_PROCESS_ENV_JSON': str((output / 'process_environment.json').resolve()),
        'SS_FDI_FIFO_DEPTH': str(protocol['fdi_fifo_depth']),
        'SS_MEMORY_FIFO_DEPTH': str(protocol['memory_fifo_depth']),
        'SS_STORAGE_BRIDGE_IMPL': bridge_implementation,
        'SS_RESOURCE_PLANES': str(planes),
        'SS_TLM_SLOTS': str(slots),
        'SS_RAMULATOR_QUEUE': str(queue),
        'SS_RAMULATOR_SLOTS': str(parent_slots),
        'SS_RAMULATOR_CHILDREN': str(child_slots),
        'SS_RAMULATOR_SUBMIT_WIDTH': str(submit_width),
    }
    if 'response_hold_ticks' in backend:
        run['SS_RAMULATOR_RESPONSE_HOLD'] = str(response_hold)
    if 'clock_scale' in backend:
        run['SS_RAMULATOR_SCALE'] = str(clock_scale)
    if 'power_enabled' in backend:
        run['SS_RAMULATOR_NO_POWER'] = '0' if power_enabled else '1'
    if workload:
        run.update({
            'SS_TRAFFIC_LOAD_PERCENT': str(traffic_load),
            'SS_TRAFFIC_WARMUP': str(traffic_warmup),
            'SS_TRAFFIC_MEASURE': str(traffic_measure),
            'SS_TRAFFIC_COOLDOWN': str(traffic_cooldown),
            'SS_TRAFFIC_SIZE': str(traffic_size),
            'SS_TRAFFIC_WORKING_SET': str(traffic_working_set),
            'SS_TRAFFIC_WRITE_PERCENT': str(traffic_writes),
            'SS_TRAFFIC_MAX_INFLIGHT': str(traffic_inflight),
        })
    if simulation:
        run.update({
            'SS_MAX_TICKS': str(max_ticks),
            'SS_AXI_NO_STALLS': '0' if deterministic_stalls else '1',
            'SS_UCIE_REPLAY': '1' if ucie_replay else '0',
        })
    if observability:
        run.update({
            'SS_METRICS_SAMPLE_CYCLES': str(metrics_sample_cycles),
            'SS_VISUALIZATION_OPEN': '1' if visualization_open else '0',
            'SS_VISUALIZATION_SERVE': '1' if visualization_serve else '0',
            'SS_VIEW_PORT': str(view_port),
        })
    mixed_loads = sweep.get('mixed_load_percent', [10, 25, 50, 75, 90, 100, 110, 125])
    saturation_loads = sweep.get('saturation_load_percent', [100, 125])
    directions = sweep.get('directions', ['mixed', 'read', 'write'])
    mixed_write_percent = _integer(sweep, 'mixed_write_percent', 50, minimum=0, maximum=100)
    for field, values in (('mixed_load_percent', mixed_loads),
                          ('saturation_load_percent', saturation_loads)):
        if not isinstance(values, list) or not values:
            raise ValueError(f'sweep.{field} must be a non-empty array')
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or
               not math.isfinite(x) or x <= 0 or x > 400 for x in values):
            raise ValueError(f'sweep.{field} values must be in (0, 400]')
    if (not isinstance(directions, list) or not directions or
            any(x not in ('mixed', 'read', 'write') for x in directions) or
            len(directions) != len(set(directions))):
        raise ValueError('sweep.directions must contain unique mixed/read/write values')
    if sweep:
        run.update({
            'SS_PROFILE_SWEEP_LOADS': ' '.join(str(x) for x in mixed_loads),
            'SS_PROFILE_SWEEP_SATURATION_LOADS': ' '.join(str(x) for x in saturation_loads),
            'SS_PROFILE_SWEEP_DIRECTIONS': ' '.join(directions),
            'SS_PROFILE_SWEEP_MIXED_WRITE_PERCENT': str(mixed_write_percent),
        })
    for name, values in [('build.env', build), ('run.env', run)]:
        (output / name).write_text(''.join(f'export {k}={shlex.quote(v)}\n' for k, v in values.items()))
    (output / 'build_parameters.json').write_text(json.dumps(build, indent=2) + '\n')
    (output / 'run_parameters.json').write_text(json.dumps(run, indent=2) + '\n')
    (output / 'frontend_plan.json').write_text(json.dumps(frontend, indent=2) + '\n')
    (output / 'process_environment.json').write_text(
        json.dumps(frontend['host']['environment'], indent=2) + '\n')
    (output / 'protocol_profile.json').write_text(json.dumps(protocol, indent=2) + '\n')
    signature = hashlib.sha256(json.dumps(build, sort_keys=True).encode()).hexdigest()
    (output / 'build_signature.json').write_text(json.dumps({'sha256': signature, 'inputs': build}, indent=2) + '\n')
    validation = {
        'schema': 'storagestacked.validation-plan.v1', 'profile': resolved['name'],
        'checks': ['profile_schema', 'capacity_feasibility', 'source_and_edge_references',
                   'AXI read/write data closure', 'global transaction ID routing',
                   'UCIe exact delivery', 'Ramulator command/data closure',
                   'DRAMPower final snapshot', '10-125% offered-load sweep',
                   'long 100/125% drain and deadlock check'],
        'load_sweep_percent': mixed_loads,
        'saturation_load_percent': saturation_loads,
        'directions': directions,
        'mixed_write_percent': mixed_write_percent,
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
