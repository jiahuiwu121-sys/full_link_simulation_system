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
    if (d/'link_diagnostics.json').exists():
        diagnostic=read(d,'link_diagnostics.json')
        full=next(w for w in diagnostic['windows'] if w['name']=='full_run')
        assert full==overall['link_resource_summary']
        old_windows={w['name']:w for w in overall['window_statistics']}
        for w in diagnostic['windows']:
            if w['name'] in old_windows:
                expected=old_windows[w['name']]['completed_target_traffic']['successful_enabled_bytes']
                assert w['resources']['TLM effective R']['bytes']+w['resources']['TLM effective W']['bytes']==expected
        duration_fs=overall['simulation_end_tick_fs']
        near(full['inflight']['request_time_integral_fs'],sum(values))
        if duration_fs:
            near(full['inflight']['time_weighted_mean'],sum(values)/duration_fs)
        previous=0; sums=Counter()
        for b in diagnostic['timebins']:
            assert b['start_tick_fs']==previous and b['end_tick_fs']>previous
            previous=b['end_tick_fs']
            for name,v in b['resources'].items():
                sums[name]+=v['bytes']
                near(v['bandwidth_Bps'],v['bytes']/((b['end_tick_fs']-b['start_tick_fs'])*1e-15))
                assert v['utilization'] is None or 0<=v['utilization']<=1+1e-12
        assert previous==duration_fs and len(diagnostic['timebins'])<=1000
        for r in diagnostic['resources']:
            assert sums[r['name']]==full['resources'][r['name']]['bytes']
            if r['peak_Bps'] is None:
                assert full['resources'][r['name']]['utilization'] is None
        expected_rw=Counter()
        expected_size=Counter()
        def request_source(name):
            name=name.lower()
            return 'gpu' if 'vortex' in name else 'npu' if 'coralnpu' in name else 'cpu' if 'cpu' in name else 'tester' if 'tester' in name else 'unknown'
        for t in tx:
            metadata_row=metadata[t['id'],t['begin_tick']]
            src=request_source(metadata_row['source_name']); status=int(t['status'])
            expected_size[src,t['command'],int(t['bytes']),status]+=1
            if status==1:expected_rw[t['command']]+=int(metadata_row['enabled_bytes'])
        assert full['resources']['TLM effective R']['bytes']==expected_rw['R']
        assert full['resources']['TLM effective W']['bytes']==expected_rw['W']
        assert Counter((r['source'],r['command'],int(r['requested_bytes']),int(r['status'])) for r in diagnostic['latency_by_size'] for _ in range(r['count']))==expected_size
        for points in diagnostic['cdfs'].values():
            assert points and all(a[0]<=b[0] and a[1]<=b[1] for a,b in zip(points,points[1:]))
            near(points[-1][1],100)
        protocol=read(d,'protocol_summary.json')
        for ch,v in protocol['channels'].items():
            if 'ready_idle_cycles' in v:
                assert sum(v[k] for k in ('handshakes','stall_cycles','ready_idle_cycles','blocked_idle_cycles'))==protocol['measured_cycles']
        for ch in ('W','R'):
            r=next(r for r in diagnostic['resources'] if r['name']=='AXI '+ch)
            near(r['peak_Bps'],protocol['axi_data_bits']/8/(protocol['period_ticks']*1e-15))
            assert full['resources'][r['name']]['bytes']==protocol['channels'][ch]['handshakes']*protocol['axi_data_bits']//8
            if protocol['measured_cycles']:
                near(full['resources'][r['name']]['utilization'],protocol['channels'][ch]['handshakes']/protocol['measured_cycles'])
        config=diagnostic['link_config']
        if config:
            fabric=read(d,'fabric_metrics.json')
            assert config==fabric['link_config']
            frames=rows(d,'ucie_flits.csv')
            for direction in ('FWD','REV'):
                r=next(r for r in diagnostic['resources'] if r['name']=='UCIe '+direction)
                near(r['peak_Bps'],config['frame_bytes']/(config['serialize_ui']*config['ui_fs']*1e-15))
                assert full['resources'][r['name']]['bytes']==sum(int(f['bytes']) for f in frames if f['direction']==direction and f['event']=='TX_FRAME')
        stages=diagnostic['critical_child_partition']['stages']
        partitions=rows(d,'request_latency_partition.csv')
        bytoken={r['token']:r for r in rows(d,'request_map.csv')}
        txuid={metadata[t['id'],t['begin_tick']]['uid']:t for t in tx}
        latest={}
        for m in bytoken.values():
            uid=m['uid']
            if uid not in latest or (int(m['service_tick_fs']),int(m['token']))>(int(latest[uid]['service_tick_fs']),int(latest[uid]['token'])):
                latest[uid]=m
        assert len(partitions)==len({r['uid'] for r in bytoken.values()})==diagnostic['critical_child_partition']['samples']
        for r in partitions:
            assert sum(int(r[k]) for k in stages)==int(r['total_fs'])
            assert all(int(r[k])>=0 for k in stages)
            m=bytoken[r['token']]
            assert r['uid']==m['uid'] and r['burst']==m['burst'] and r['source']==m['source']
            assert m==latest[r['uid']]
            t=txuid[r['uid']]
            assert int(r['total_fs'])==int(t['end_resp_tick'])-int(t['begin_tick'])
            for k,a,b in [('backend_admission','parent_accept_tick_fs','submit_tick_fs'),
                          ('dram_queue_and_schedule','submit_tick_fs','issued_tick_fs'),
                          ('dram_data_service','issued_tick_fs','service_tick_fs'),
                          ('backend_return_wait','service_tick_fs','parent_return_tick_fs')]:
                assert int(r[k])==int(m[b])-int(m[a])
        for g in diagnostic['critical_child_partition']['groups']:
            own=[r for r in partitions if r['source']==g['source'] and r['command']==g['command']]
            assert len(own)==g['count']
            near(g['total']['mean_fs'],sum(int(r['total_fs']) for r in own)/len(own))
            for k in stages:
                near(g['stages'][k]['mean_fs'],sum(int(r[k]) for r in own)/len(own))
        if (d/'ramulator_model.json').exists():
            for channel,model in enumerate(read(d,'ramulator_model.json')['controllers']):
                if model.get('standard') in ('HBM3','HBM4') and model.get('timings'):
                    peak=model['transaction_bytes']/(model['period_fs']*model['timings']['nBL']*1e-15)
                    for r in diagnostic['resources']:
                        if r['name'].startswith(f'DRAM ch{channel}/pc'):
                            near(r['peak_Bps'],peak)
        backend_capacity=read(d,'ramulator_backend_summary.json') if (d/'ramulator_backend_summary.json').exists() else {}
        native_capacity=read(d,'ramulator_native_summary.json') if (d/'ramulator_native_summary.json').exists() else {}
        if native_capacity and backend_capacity.get('submit_width'):
            ingress=next(r for r in diagnostic['resources'] if r['name']=='Backend ingress')
            near(ingress['peak_Bps'],backend_capacity['submit_width']*native_capacity['transaction_bytes']/(native_capacity['period_fs']*1e-15))
            balance=diagnostic['capacity_balance'];caps=balance['capacities_Bps']
            near(caps['axi_per_direction'],protocol['axi_data_bits']/8/(protocol['period_ticks']*1e-15))
            assert balance['status'] in ('balanced_ingress','unbalanced_or_unknown')
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
        if 'submit_width' in backend:
            assert stalls['native_reject_attempts']==backend['native_reject_attempts']
            assert backend['submit_stalls']>=backend['native_reject_attempts']
            assert stalls['native_reject']<=stalls['native_reject_attempts']
            assert sum(bq['submit_batch_histogram'])==backend['submit_dispatch_cycles']
            assert backend['max_submitted_per_tick']<=backend['submit_width']
            assert sum(i*n for i,n in enumerate(bq['submit_batch_histogram']))==native['submitted']
        else:
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
                        'child causality','queue integrals','stall reason counts','power interval conservation','disabled power semantics',
                        'bandwidth bin conservation','resolved interface capacities','AXI four-state conservation','exclusive request latency partition'])
    (d/'metrics_check.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directories',nargs='+',type=Path)
    for d in p.parse_args().directories:print(d,check(d))
