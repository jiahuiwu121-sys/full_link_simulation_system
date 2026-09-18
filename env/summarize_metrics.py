#!/usr/bin/env python3
"""Keep distinct experiments distinct: index each case's overall statistics."""
import argparse
import json
from pathlib import Path


def summarize(directory):
    root=Path(directory)
    cases={}
    for path in sorted(root.glob('*/metrics.json')):
        value=json.loads(path.read_text())
        checked=json.loads((path.parent/'metrics_check.json').read_text())
        if value['status']!='complete' or not checked['passed']:
            raise ValueError('Incomplete/invalid metrics: '+str(path))
        cases[path.parent.name]=dict(report=str(path.relative_to(root)),**value['overall'])
    if not cases:raise ValueError('No run metrics found')
    result=dict(schema='storagestacked.metrics.batch.v1',passed=True,cases=cases,
                note='Cases are separate experiments; energy, duration and throughput are NOT summed across them')
    (root/'metrics_batch.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    lines=['# 实验批次统计','','| 用例 | 请求 | 有效字节 | 时长/s | DRAM能量/J | DRAM平均功率/W | 报告 |','|---|---:|---:|---:|---:|---:|---|']
    for name,c in cases.items():
        energy='未启用' if c['dram_energy_j'] is None else f'{c["dram_energy_j"]:.9g}'
        power='未启用' if c['dram_average_power_w'] is None else f'{c["dram_average_power_w"]:.9g}'
        lines.append(f'| {name} | {c["traffic"]["requests"]} | {c["effective_bytes"]} | {c["duration_seconds"]:.9g} | {energy} | {power} | [{name}]({name}/metrics_summary.md) |')
    (root/'metrics_batch.md').write_text('\n'.join(lines)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path)
    print(json.dumps({'passed':summarize(p.parse_args().directory)['passed']}))
