#!/usr/bin/env python3
"""Validate and summarize a controlled offered-load bandwidth sweep."""
import argparse
import csv
import json
from pathlib import Path


LOADS = (10, 25, 50, 75, 100, 125)


def read(path):
    return json.loads(path.read_text())


def steady_window(overall):
    return next(w for w in overall['window_statistics'] if w['name'] == 'traffic_steady_state')


def diagnostic_window(diagnostic):
    return next(w for w in diagnostic['windows'] if w['name'] == 'traffic_steady_state')


def utilization(window, name):
    value = window['resources'].get(name, {}).get('utilization')
    return value


def verify(root):
    rows = []
    for load in LOADS:
        case = root / f'load_{load:03d}'
        report = read(case / 'metrics.json')
        check = read(case / 'metrics_check.json')
        profile = read(case / 'traffic_profile.json')
        diagnostic = read(case / 'link_diagnostics.json')
        backend = read(case / 'ramulator_backend_summary.json')
        if report['status'] != 'complete' or not check['passed']:
            raise ValueError(f'incomplete metrics in {case}')
        if profile['offered_load_percent'] != load or profile['mode'] != 'bandwidth':
            raise ValueError(f'wrong traffic profile in {case}')
        steady = steady_window(report['overall'])
        link = diagnostic_window(diagnostic)
        traffic = steady['measurement_cohort_traffic']
        if traffic['successful_requests'] != profile['measurement_requests']:
            raise ValueError(f'measurement request count mismatch in {case}')
        capacities = diagnostic['capacity_balance']['capacities_Bps']
        axi_peak = capacities['axi_per_direction']
        achieved = steady['measurement_cohort_effective_bandwidth_Bps']
        row = dict(
            load_percent=load,
            offered_payload_Bps=axi_peak * load / 100,
            achieved_payload_Bps=achieved,
            achieved_over_offered=achieved / (axi_peak * load / 100),
            latency_mean_ns=traffic['latency']['mean_fs'] / 1e6,
            latency_p50_ns=traffic['latency']['p50_fs'] / 1e6,
            latency_p95_ns=traffic['latency']['p95_fs'] / 1e6,
            latency_p99_ns=traffic['latency']['p99_fs'] / 1e6,
            inflight_mean=link['inflight']['time_weighted_mean'],
            inflight_peak=link['inflight']['peak'],
            axi_write_utilization=utilization(link, 'AXI W'),
            axi_read_utilization=utilization(link, 'AXI R'),
            ucie_forward_utilization=utilization(link, 'UCIe FWD'),
            ucie_reverse_utilization=utilization(link, 'UCIe REV'),
            backend_ingress_utilization=utilization(link, 'Backend ingress'),
            max_submitted_per_tick=backend['max_submitted_per_tick'],
            submit_width=backend['submit_width'],
            capacity_balance=diagnostic['capacity_balance']['status'],
            requests=traffic['successful_requests'],
            duration_seconds=steady['duration_seconds'],
        )
        rows.append(row)

    if any(row['capacity_balance'] != 'balanced_ingress' for row in rows):
        raise ValueError('one or more sweep cases use an unbalanced or unresolved capacity model')
    if rows[-1]['max_submitted_per_tick'] < 2:
        raise ValueError('highest offered load did not exercise multi-submit backend dispatch')
    if max(r['achieved_payload_Bps'] for r in rows[3:]) < max(r['achieved_payload_Bps'] for r in rows[:3]):
        raise ValueError('higher offered loads never reached the lower-load throughput envelope')
    if rows[-1]['inflight_peak'] <= rows[0]['inflight_peak']:
        raise ValueError('sweep did not create increasing request pressure')

    fields = list(rows[0])
    with (root / 'bandwidth_sweep.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    result = dict(
        schema='storagestacked.bandwidth_sweep.v1',
        passed=True,
        loads_percent=list(LOADS),
        rows=rows,
        interpretation=(
            'Compare achieved throughput, P95 latency, in-flight depth and per-resource utilization. '
            'The knee is the first load where throughput growth slows while latency or in-flight depth rises.'
        ),
    )
    (root / 'bandwidth_sweep.json').write_text(json.dumps(result, indent=2) + '\n')
    lines = [
        '# 带宽—延迟压力扫描', '',
        '稳态窗口排除预热和排空。供给带宽以 AXI256 单方向理论载荷容量为基准；各层利用率保持各自口径。', '',
        '|供给负载|供给 GB/s|实测 GB/s|P95/ns|平均在途|AXI W|AXI R|UCIe FWD|UCIe REV|后端提交|每tick最大提交|',
        '|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for row in rows:
        pct = lambda value: '未测量' if value is None else f'{value*100:.2f}%'
        lines.append(
            f"|{row['load_percent']}%|{row['offered_payload_Bps']/1e9:.3f}|"
            f"{row['achieved_payload_Bps']/1e9:.3f}|{row['latency_p95_ns']:.3f}|"
            f"{row['inflight_mean']:.3f}|{pct(row['axi_write_utilization'])}|"
            f"{pct(row['axi_read_utilization'])}|{pct(row['ucie_forward_utilization'])}|"
            f"{pct(row['ucie_reverse_utilization'])}|{pct(row['backend_ingress_utilization'])}|"
            f"{row['max_submitted_per_tick']}|"
        )
    (root / 'bandwidth_sweep.md').write_text('\n'.join(lines) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    answer = verify(parser.parse_args().directory.resolve())
    print(json.dumps({'passed': answer['passed'], 'cases': len(answer['rows'])}))
