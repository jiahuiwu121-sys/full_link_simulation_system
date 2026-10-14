#!/usr/bin/env python3
"""Verify every planned topology/width case and write aggregate matrix reports."""
import argparse
import csv
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    root = args.directory.resolve()
    plan = json.loads((root / 'matrix_plan.json').read_text())
    if plan.get('schema') != 'storagestacked.configuration-matrix.v1' or not plan.get('cases'):
        raise ValueError('invalid or empty configuration matrix plan')
    names = [case.get('name') for case in plan['cases']]
    if any(not isinstance(name, str) or not name for name in names) or len(names) != len(set(names)):
        raise ValueError('configuration matrix case names must be non-empty and unique')
    rows = []
    failures = []
    for expected in plan['cases']:
        case = root / expected['name']
        try:
            metrics = json.loads((case / 'metrics.json').read_text())
            run = json.loads((case / 'metrics_run.json').read_text())
            topology = json.loads((case / 'topology_resolved.json').read_text())
            actual_modules = len(topology['modules'])
            actual_width = topology['axi']['data_width_bits']
            actual_planes = run['arguments']['planes']
            passed = metrics['status'] == 'complete' and run['completed']
            if actual_modules > 1:
                passed = passed and json.loads((case / 'topology_check.json').read_text())['passed']
            for key, actual in [('modules', actual_modules), ('axi_data_width', actual_width),
                                ('resource_planes', actual_planes)]:
                if expected[key] != actual:
                    failures.append(f"{expected['name']}: {key} expected {expected[key]}, got {actual}")
                    passed = False
            traffic = metrics['overall']['traffic']
            if (not traffic['requests'] or traffic['errors'] or
                    traffic['successful_requests'] != traffic['requests']):
                failures.append(f"{expected['name']}: request completion mismatch")
                passed = False
            if not passed:
                failures.append(f"{expected['name']}: validation did not pass")
            rows.append({
                'case': expected['name'], 'axi_data_width': actual_width,
                'modules': actual_modules, 'resource_planes': actual_planes,
                'memory_standards': ','.join(sorted({m.get('memory', {}).get('standard', 'HBM4')
                                                      for m in topology['modules']})),
                'requests': traffic['requests'], 'errors': traffic['errors'],
                'bandwidth_GBps': metrics['overall']['full_run_effective_bandwidth_Bps'] / 1e9,
                'mean_latency_ns': traffic['latency']['mean_fs'] / 1e6,
                'dram_energy_uJ': metrics['overall']['dram_energy_j'] * 1e6,
                'passed': passed,
            })
        except Exception as error:
            failures.append(f"{expected['name']}: {error}")
            rows.append({'case': expected['name'], 'axi_data_width': expected['axi_data_width'],
                         'modules': expected['modules'], 'resource_planes': expected['resource_planes'],
                         'memory_standards': '', 'requests': '', 'errors': '', 'bandwidth_GBps': '',
                         'mean_latency_ns': '', 'dram_energy_uJ': '', 'passed': False})
    fieldnames = list(rows[0]) if rows else []
    with (root / 'matrix_summary.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    report = {'schema': 'storagestacked.configuration-matrix.v1',
              'matrix_type': plan.get('matrix_type', 'configuration'),
              'passed': not failures and len(rows) == len(plan['cases']),
              'cases': rows, 'failures': failures}
    (root / 'matrix_summary.json').write_text(json.dumps(report, indent=2) + '\n')
    headers = ['case', 'AXI bit', 'modules', 'RP', 'memory', 'requests', 'errors',
               'GB/s', 'mean ns', 'DRAM uJ', 'passed']
    lines = ['# 自动化配置矩阵验收', '', '| ' + ' | '.join(headers) + ' |',
             '|' + '|'.join(['---'] * len(headers)) + '|']
    for row in rows:
        lines.append('| ' + ' | '.join(str(row[key]) for key in fieldnames) + ' |')
    lines += ['', f"总体结果：{'通过' if report['passed'] else '失败'}。"]
    if failures:
        lines += ['', '失败原因：'] + [f'- {item}' for item in failures]
    (root / 'matrix_summary.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({'passed': report['passed'], 'cases': len(rows), 'failures': failures}, ensure_ascii=False))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
