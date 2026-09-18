#!/usr/bin/env python3
"""Prove passive queue/power snapshots do not change native commands or totals."""
import argparse
import ctypes as C
import json
from pathlib import Path
import sys
from check_online import Info, Event, bind

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'env'))
from generate_ramulator_config import generate_config


def check(library,directory):
    lib=bind(library);out=Path(directory).resolve();out.mkdir(parents=True,exist_ok=False)
    def run(name,interval):
        d=out/name;d.mkdir()
        config=generate_config(d,sample_cycles=interval)
        h=lib.ssr_create(config.encode(),4,1,str(d).encode())
        assert h,lib.ssr_error().decode()
        events=[]
        try:
            assert lib.ssr_submit(h,1,0,1)==1
            assert lib.ssr_submit(h,2,32,0)==1
            for cycle in range(1,6001):
                assert lib.ssr_step(h)==1,lib.ssr_error().decode()
                while True:
                    e=Event();n=lib.ssr_poll_event(h,C.byref(e));assert n>=0
                    if not n:break
                    events.append((e.kind,e.token,e.cycle,e.issue_cycle,e.address,e.channel,e.command_name.decode(),tuple(e.coordinates)))
            assert lib.ssr_is_idle(h)==1
            assert lib.ssr_finish(h)==1,lib.ssr_error().decode()
        finally:lib.ssr_destroy(h)
        return events,{name:json.loads((d/name).read_text()) for name in ('ramulator_stats.json','dram_power.json','ramulator_native_summary.json')}
    sparse=run('sparse',1000);dense=run('dense',1);final_only=run('final_only',100000)
    assert sparse==dense==final_only,'Changing only the passive snapshot interval changed native behavior/statistics'
    result=dict(passed=True,intervals=[1000,1,100000],cycles=6000,
                checks=['identical issue/service event sequence','identical original native statistics','identical full-run energy and power'])
    (out/'metrics_sampling_check.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('library',type=Path);p.add_argument('directory',type=Path)
    a=p.parse_args();print(json.dumps(check(a.library,a.directory),indent=2))
