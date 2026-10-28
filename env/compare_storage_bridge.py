#!/usr/bin/env python3
"""Compare observable data semantics of RTL and SystemC bridge runs."""
import argparse
import csv
import json
from pathlib import Path


def compare(left, right):
    def load(d, name):
        return json.loads((d/name).read_text())
    def rows(d, name):
        with (d/name).open() as stream:
            return list(csv.DictReader(stream))
    for d in (left,right):
        assert load(d,'metrics_check.json')['passed']
        assert load(d,'ramulator_check.json')['passed']
    implementations=[load(d,'aou_summary.json')['storage_bridge_implementation'] for d in (left,right)]
    assert set(implementations)=={'rtl','systemc'}
    for name,keys in (
            ('aou_summary.json',('memory_completed','memory_errors','target_reads','target_writes','target_read_beats','target_write_beats')),
            ('ramulator_backend_summary.json',('bursts','errors','submitted','services'))):
        a,b=(load(d,name) for d in (left,right))
        assert {k:a[k] for k in keys}=={k:b[k] for k in keys}, (name,'outcome mismatch')
    keys=('serial','command','address','bytes','error')
    lifecycles=[sorted(tuple(r[k] for k in keys) for r in rows(d,'packet_lifecycle.csv')) for d in (left,right)]
    assert lifecycles[0]==lifecycles[1], 'frontend workload/outcome differs'
    images=[{int(r['address']):r['data'] for r in rows(d,'ramulator_final_image.csv')} for d in (left,right)]
    assert images[0]==images[1], 'final backing images differ'
    return dict(passed=True,left=str(left),right=str(right),requests=len(lifecycles[0]),
                backing_chunks=len(images[0]),checks=['frontend workload and outcomes','target requests and beats',
                'DRAM submit/service conservation','final backing data'],
                boundary='Each run independently checks reads, AXI/Flit data, DRAM commands and metrics. Timing, command order and power may differ.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('left',type=Path);p.add_argument('right',type=Path)
    p.add_argument('--output',type=Path)
    a=p.parse_args();result=compare(a.left.resolve(),a.right.resolve())
    output=json.dumps(result,indent=2)+'\n'
    if a.output:a.output.write_text(output)
    print(output,end='')
