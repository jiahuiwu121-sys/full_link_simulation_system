#!/usr/bin/env python3
"""Independent contract checks for versioned statistics and evidence conservation."""
import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path


def read(d, name):
    return json.loads((d/name).read_text())


def rows(d, name):
    with (d/name).open() as f:
        return list(csv.DictReader(f))


def near(a, b):
    assert math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-18), (a,b)


def check(directory):
    d=Path(directory)
    report=read(d,'metrics.json'); overall=report['overall']; modules=report['modules']
    assert report['schema']=='storagestacked.metrics.v1' and report['status']=='complete'
    assert all(overall['metric_consistency_checks'].values())
    assert read(d,'metrics/overall.json')==overall
    for name, value in modules.items():
        assert read(d,'metrics/'+name+'.json')==value
        if name in ('gpu','npu') and value['status']=='measured':
            assert read(d,name+'_device_metrics.json')==value['native_device_statistics']
    tx=rows(d,'transactions.csv'); meta=rows(d,'request_metadata.csv')
    assert len(tx)==len(meta)==overall['traffic']['requests']
    assert len({r['uid'] for r in meta})==len(meta)
    assert {(r['id'],r['begin_tick']) for r in tx}=={(r['id'],r['begin_tick']) for r in meta}
    metadata={(r['id'],r['begin_tick']):r for r in meta}
    effective=sum(int(metadata[r['id'],r['begin_tick']]['enabled_bytes']) for r in tx if int(r['status'])==1)
    assert overall['effective_bytes']==effective
    values=sorted(int(r['end_resp_tick'])-int(r['begin_tick']) for r in tx)
    if values:
        assert overall['latency']['p99_fs']==values[math.ceil(.99*len(values))-1]
        near(overall['latency']['mean_fs'],sum(values)/len(values))
    else:
        assert overall['latency']['count']==0
        assert overall['latency']['p99_fs'] is None and overall['latency']['mean_fs'] is None
    assert sum(s['requests'] for s in overall['sources'].values())==len(tx)
    assert sum(s['successful_enabled_bytes'] for s in overall['sources'].values())==effective
    hist=rows(d,'latency_hist.csv'); summaries=rows(d,'latency_summary.csv')
    grouped=Counter()
    for r in hist:
        grouped[r['stage'],r['source'],r['command']]+=int(r['count'])
    assert grouped==Counter({(r['stage'],r['source'],r['command']):int(r['count']) for r in summaries})
    if (d/'ramulator_native_summary.json').exists():
        native=read(d,'ramulator_native_summary.json'); backend=read(d,'ramulator_backend_summary.json')
        native_stats=read(d,'ramulator_stats.json')
        assert modules['ramulator2']['original_statistics']==native_stats
        ctrls=native_stats['memory_system']['controller']
        single=isinstance(ctrls,dict)
        if single:ctrls=[ctrls]
        # Scalar registered stats must have the identical native YAML values.
        channel=-1; parsed=[]
        scalar_indent='    ' if single else '      '
        for line in (d/'ramulator_stats.yaml').read_text().splitlines():
            if line=='    -':
                channel+=1;parsed.append({})
            elif single and line=='  controller:':
                channel=0;parsed=[{}]
            elif channel>=0 and line.startswith(scalar_indent) and not line.startswith(scalar_indent+' '):
                key, sep, val=line.strip().partition(': ')
                if sep:parsed[channel][key]=val
        assert len(parsed)==len(ctrls)
        for c,p in zip(ctrls,parsed):
            for key,value in c.items():
                if isinstance(value,(int,float)):
                    near(float(p[key]),value)
        mapping=rows(d,'request_map.csv')
        assert len(mapping)==native['serviced']
        assert len({r['token'] for r in mapping})==len(mapping)
        uid={r['uid']:r for r in meta}
        txbyuid={metadata[r['id'],r['begin_tick']]['uid']:r for r in tx}
        for r in mapping:
            t=txbyuid[r['uid']]
            assert r['source_name']==uid[r['uid']]['source_name'] and r['axi_id']==t['id'] and r['command']==t['command']
            assert int(t['accepted_tick'])<=int(r['parent_accept_tick_fs'])<=int(r['submit_tick_fs'])
            assert int(r['submit_tick_fs'])<int(r['issued_tick_fs'])<int(r['service_tick_fs'])<=int(r['parent_return_tick_fs'])<=int(t['axi_done_tick'])
            latency=native['write_latency' if r['command']=='W' else 'read_latency']*native['period_fs']
            assert int(r['service_tick_fs'])-int(r['issued_tick_fs'])==latency
        queues=read(d,'ramulator_queue_metrics.json')
        for c in queues['channels']:
            for q in c['queues'].values():
                assert 0<=q['depth_cycle_sum']<=q['peak']*queues['cycles']
                assert 0<=q['nonempty_cycles']<=queues['cycles']
        bq=read(d,'backend_queue_metrics.json'); stalls=bq['stall_cycles']
        assert stalls['forced_response_hold']+stalls['response_fifo_full']==backend['response_stalls']
        assert stalls['child_limit']+stalls['native_reject']==backend['submit_stalls']
        assert stalls['address_hazard']<=backend['hazard_stalls']
        assert bq['parent_peak']<=bq['parent_capacity'] and bq['child_peak']<=bq['child_capacity']
        power=read(d,'dram_power.json'); assert modules['dram_power']['original_statistics']==power
        enabled=any(c['enabled'] for c in power['channels'])
        intervals=rows(d,'power_intervals.csv')
        if enabled:
            for c in power['channels']:
                own=[r for r in intervals if int(r['channel'])==c['channel']]
                assert own and int(own[0]['start_tick_fs'])==0
                assert int(own[-1]['end_tick_fs'])==native['cycles']*native['period_fs']
                for a,b in zip(own,own[1:]):assert a['end_tick_fs']==b['start_tick_fs']
                for key in c:
                    if key.endswith('_j') and key in own[0]:
                        near(sum(float(r[key]) for r in own),c[key])
                near(sum(float(r['duration_seconds']) for r in own),power['duration_seconds'])
            near(overall['dram_energy_j'],power['total_energy_j'])
        else:
            assert overall['dram_energy_j'] is None and overall['dram_average_power_w'] is None
            assert modules['dram_power']['status']=='disabled'
            assert all(r['total_energy_j']=='' for r in intervals)
        assert overall['system_total_energy_j'] is None
    result=dict(passed=True,transactions=len(tx),effective_bytes=effective,module_files=len(modules),
                checks=['stable uid/source mapping','native statistics preserved','latency histogram sample conservation',
                        'child causality','queue integrals','stall reason counts','power interval conservation','disabled power semantics'])
    (d/'metrics_check.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directories',nargs='+',type=Path)
    for d in p.parse_args().directories:print(d,check(d))
