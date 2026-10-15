#!/usr/bin/env python3
"""Summarize correctness and requirement coverage for a profile load sweep."""
import argparse
import csv
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def window(items, name='traffic_steady_state'):
    return next(item for item in items if item['name'] == name)


def resource(resources, name):
    return resources.get(name, {}).get('utilization')


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    return values[round((len(values) - 1) * fraction)]


def verify(root):
    plan = read(root / 'system_profile' / 'validation_plan.json')
    capacity = read(root / 'system_profile' / 'capacity_report.json')
    rows = []
    for manifest_path in sorted(root.glob('*/profile_sweep_case.json')):
        case = manifest_path.parent
        manifest = read(manifest_path)
        metrics = read(case / 'metrics.json')
        check = read(case / 'metrics_check.json')
        traffic_profile = read(case / 'traffic_profile.json')
        diagnostic = read(case / 'link_diagnostics.json')
        backend = read(case / 'ramulator_backend_summary.json')
        protocol = read(case / 'protocol_summary.json')
        with (case / 'request_flit_map.csv').open() as stream:
            mappings = list(csv.DictReader(stream))
        bridge_path = [(int(item['rx_first_tick_fs']) - int(item['axi_tick_fs'])) / 1e6
                       for item in mappings if item['direction'] == 'FWD' and
                       int(item['rx_first_tick_fs']) >= int(item['axi_tick_fs'])]
        steady = window(metrics['overall']['window_statistics'])
        link = window(diagnostic['windows'])
        cohort = steady['measurement_cohort_traffic']
        protocol_latency = diagnostic.get('protocol_latency', {})
        delivery_p95 = [value['p95_fs'] / 1e6 for key, value in protocol_latency.items()
                        if key.startswith('ucie.') and key.endswith('.logged_fdi_delivery')]
        direction = manifest['direction']
        relevant_ucie = ('UCIe REV' if direction == 'read' else
                         'UCIe FWD' if direction == 'write' else None)
        rows.append({
            'case': case.name,
            'direction': direction,
            'load_percent': manifest['load_percent'],
            'write_percent': manifest['write_percent'],
            'correctness_passed': bool(metrics['status'] == 'complete' and check['passed'] and
                                       backend['passed'] and backend['drained'] and
                                       protocol['drained']),
            'requests': cohort['successful_requests'],
            'effective_bandwidth_Bps': steady['measurement_cohort_effective_bandwidth_Bps'],
            'latency_mean_ns': cohort['latency']['mean_fs'] / 1e6,
            'latency_p95_ns': cohort['latency']['p95_fs'] / 1e6,
            'latency_p99_ns': cohort['latency']['p99_fs'] / 1e6,
            'axi_write_utilization': resource(link['resources'], 'AXI W'),
            'axi_read_utilization': resource(link['resources'], 'AXI R'),
            'ucie_forward_utilization': resource(link['resources'], 'UCIe FWD'),
            'ucie_reverse_utilization': resource(link['resources'], 'UCIe REV'),
            'relevant_ucie_utilization': resource(link['resources'], relevant_ucie) if relevant_ucie else None,
            'backend_utilization': resource(link['resources'], 'Backend ingress'),
            'ucie_delivery_p95_ns': max(delivery_p95) if delivery_p95 else None,
            'bridge_path_p95_ns': percentile(bridge_path, 0.95),
            'inflight_mean': link['inflight']['time_weighted_mean'],
            'inflight_peak': link['inflight']['peak'],
            'max_submitted_per_tick': backend['max_submitted_per_tick'],
            'capacity_balance': diagnostic['capacity_balance']['status'],
            'request_size_bytes': traffic_profile['request_size_bytes'],
        })
    if not rows:
        raise ValueError('profile sweep contains no cases')
    requirements = plan.get('requirements', {})
    minimum_bw = float(requirements.get('minimum_effective_bandwidth_GBps', 0)) * 1e9
    minimum_util = float(requirements.get('minimum_link_utilization', 0))
    maximum_bridge_latency = float(requirements.get('maximum_bridge_latency_ns', 0))
    mixed = [r for r in rows if r['direction'] == 'mixed']
    directional = [r for r in rows if r['direction'] in ('read', 'write') and r['load_percent'] >= 100]
    measured_bw = max((r['effective_bandwidth_Bps'] for r in mixed), default=0)
    measured_util = (max((r['relevant_ucie_utilization'] or 0 for r in directional))
                     if directional else None)
    low_load = min(mixed, key=lambda r: r['load_percent']) if mixed else None
    measured_bridge_latency = low_load['bridge_path_p95_ns'] if low_load else None
    requirement_checks = {
        'minimum_effective_bandwidth': {
            'required_GBps': minimum_bw / 1e9 if minimum_bw else None,
            'measured_GBps': measured_bw / 1e9,
            'passed': not minimum_bw or measured_bw >= minimum_bw,
            'scope': 'maximum mixed-traffic steady-state completion bandwidth',
        },
        'minimum_link_utilization': {
            'required': minimum_util or None,
            'measured': measured_util,
            'passed': not minimum_util or (measured_util is not None and measured_util >= minimum_util),
            'scope': 'best matching UCIe direction in read-only/write-only cases at >=100% offered load',
        },
        'maximum_bridge_latency': {
            'required_ns': maximum_bridge_latency or None,
            'measured_p95_ns': measured_bridge_latency,
            'passed': not maximum_bridge_latency or (measured_bridge_latency is not None and
                                                      measured_bridge_latency <= maximum_bridge_latency),
            'scope': ('P95 AXI handshake to remote AoU delivery in the lowest-load mixed case; '
                      'saturation queueing remains visible per case'),
        },
    }
    correctness = all(r['correctness_passed'] for r in rows)
    result = {
        'schema': 'storagestacked.profile-sweep.v1',
        'profile': plan['profile'],
        'passed': correctness,
        'requirements_met': all(item['passed'] for item in requirement_checks.values()),
        'correctness_passed': correctness,
        'theoretical_raw_payload_capacity_ceiling_GBps':
            capacity['raw_payload_capacity_ceiling_Bps'] / 1e9,
        'requirement_checks': requirement_checks,
        'rows': rows,
        'interpretation': (
            'passed covers data/protocol/backend closure and drain. requirements_met is separate: '
            'an unmet performance target remains a valid measured experimental result.'
        ),
    }
    fields = list(rows[0])
    with (root / 'profile_sweep.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    (root / 'profile_sweep.json').write_text(json.dumps(result, indent=2) + '\n')
    pct = lambda value: '未测量' if value is None else f'{100*value:.2f}%'
    lines = [
        '# 系统配置压力扫描', '',
        f'- 配置：`{plan["profile"]}`',
        f'- 数据与协议闭环：{"通过" if correctness else "失败"}',
        f'- 性能目标：{"满足" if result["requirements_met"] else "未全部满足"}', '',
        '|用例|方向|负载|有效GB/s|端到端P95/ns|桥路径P95/ns|AXI W|AXI R|UCIe FWD|UCIe REV|在途峰值|',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for r in rows:
        lines.append(f'|{r["case"]}|{r["direction"]}|{r["load_percent"]:.0f}%|'
                     f'{r["effective_bandwidth_Bps"]/1e9:.3f}|{r["latency_p95_ns"]:.3f}|'
                     f'{r["bridge_path_p95_ns"]:.3f}|{pct(r["axi_write_utilization"])}|'
                     f'{pct(r["axi_read_utilization"])}|{pct(r["ucie_forward_utilization"])}|'
                     f'{pct(r["ucie_reverse_utilization"])}|{r["inflight_peak"]}|')
    lines += ['', '## 指标要求判定', '']
    for name, item in requirement_checks.items():
        lines.append(f'- `{name}`：{"通过" if item["passed"] else "未通过"}；{item["scope"]}。')
    lines += ['', '“闭环通过”不等于“性能目标满足”；未达标结果会保留实测值，不会被验收脚本隐藏。']
    (root / 'profile_sweep.md').write_text('\n'.join(lines) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    result = verify(parser.parse_args().directory.resolve())
    print(json.dumps({'passed': result['passed'],
                      'requirements_met': result['requirements_met'],
                      'cases': len(result['rows'])}))
