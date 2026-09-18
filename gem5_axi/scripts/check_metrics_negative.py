#!/usr/bin/env python3
"""Tampered statistics must fail independent metrics contract validation."""
import argparse
import csv
import json
from pathlib import Path
import shutil
import tempfile
from check_metrics import check


def mutate_csv(d,name,edit):
    p=d/name
    with p.open() as f:r=list(csv.DictReader(f));fields=list(r[0])
    edit(r)
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(r)


def negative(directory):
    source=Path(directory).resolve();check(source)
    def yaml_counter(d):
        p=d/'ramulator_stats.yaml';s=p.read_text();s=s.replace('      row_hits: ','      row_hits: 999',1);p.write_text(s)
    tests={
        'missing_child_mapping':lambda d:mutate_csv(d,'request_map.csv',lambda r:r.pop()),
        'wrong_uid':lambda d:mutate_csv(d,'request_map.csv',lambda r:r[0].update(uid='9999999')),
        'wrong_service_cycle':lambda d:mutate_csv(d,'request_map.csv',lambda r:r[0].update(service_tick_fs=r[0]['issued_tick_fs'])),
        'wrong_native_statistic':yaml_counter,
        'missing_power_interval':lambda d:mutate_csv(d,'power_intervals.csv',lambda r:r.pop()),
        'wrong_histogram_samples':lambda d:mutate_csv(d,'latency_hist.csv',lambda r:r[0].update(count=str(int(r[0]['count'])+1))),
    }
    result={}
    for name,edit in tests.items():
        with tempfile.TemporaryDirectory(prefix='ss-metrics-negative-') as tmp:
            d=Path(tmp)
            # Only contract evidence: never copy large VCD/raw waveforms.
            shutil.copytree(source/'metrics',d/'metrics')
            for p in source.iterdir():
                if p.is_file() and (p.suffix in ('.json','.csv','.yaml')):shutil.copy2(p,d/p.name)
            edit(d)
            try:check(d)
            except (AssertionError,ValueError,KeyError) as exc:result[name]=dict(rejected=True,error=str(exc))
            else:raise AssertionError('Tampering accepted: '+name)
    (source/'metrics_negative.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path)
    print(json.dumps(negative(p.parse_args().directory),indent=2))
