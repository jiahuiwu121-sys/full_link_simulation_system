#!/usr/bin/env python3
"""Versioned per-module/full-link metrics; consumes reports, never schedules traffic.

Installed before m5.simulate: gem5 exit cleanup flushes device traces, then
stats.dump runs, then this collector. CLI can regenerate an existing new run.
All time values are global femtoseconds unless an original native name says otherwise.
"""
import argparse
import atexit
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict, deque
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import sys

SCHEMA = 'storagestacked.metrics.v1'
COLLECTOR_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
MODULES = ('cpu', 'gpu', 'npu', 'gem5_interconnect', 'tlm', 'axi', 'axi2flit', 'ucie', 'aou_target',
           'ramulator_backend', 'backing', 'ramulator2', 'dram_power')


def load(d, name, default=None):
    p = d / name
    return json.loads(p.read_text()) if p.exists() else default


def rows(d, name):
    p = d / name
    if not p.exists():
        return []
    with p.open() as f:
        return list(csv.DictReader(f))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def table(path, data, fields):
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(data)


def ratio(a, b):
    return a / b if b else None


def distribution(values):
    v = sorted(values)
    # Nearest rank, not interpolation. Small sample counts remain visible.
    return dict(count=len(v), mean_fs=ratio(sum(v), len(v)),
                p50_fs=v[math.ceil(len(v)*.50)-1] if v else None,
                p95_fs=v[math.ceil(len(v)*.95)-1] if v else None,
                p99_fs=v[math.ceil(len(v)*.99)-1] if v else None,
                max_fs=v[-1] if v else None)


def source(name):
    name = name.lower()
    if 'vortex' in name:
        return 'gpu'
    if 'coralnpu' in name:
        return 'npu'
    if 'cpu' in name:
        return 'cpu'
    if 'tester' in name:
        return 'tester'
    return 'unknown'


def gem5_stats(d):
    result = {}
    p = d / 'stats.txt'
    if p.exists():
        # Multiple dumps: retain the last value, never add repeated dumps.
        for line in p.read_text().splitlines():
            fields = line.split('#', 1)[0].split()
            if len(fields) >= 2:
                try:
                    v = float(fields[1])
                    result[fields[0]] = int(v) if v.is_integer() else v if math.isfinite(v) else None
                except ValueError:
                    pass
    return result


def queue_summary(original, cycles):
    q = dict(original)
    if 'depth_cycle_sum' in q:
        q['mean_depth'] = ratio(q['depth_cycle_sum'], cycles)
    if 'full_cycles' in q:
        q['full_cycle_fraction'] = ratio(q['full_cycles'], cycles)
    if 'nonempty_cycles' in q:
        q['nonempty_cycle_fraction'] = ratio(q['nonempty_cycles'], cycles)
    return q


def install(directory, args):
    """Register BEFORE the first m5.simulate (its exit handlers use LIFO)."""
    d = Path(directory)
    context = dict(schema=SCHEMA, arguments=vars(args), completed=False,
                   exit_cause=None, exit_code=None, end_tick_fs=None)
    save(d / 'metrics_run.json', context)

    def finish():
        sys.stdout.flush()
        sys.stderr.flush()
        save(d / 'metrics_run.json', context)
        try:
            report = collect(d)
            if report['status'] == 'invalid':
                raise ValueError('Metric consistency checks failed: ' + str(report['overall']['metric_consistency_checks']))
            print('METRICS:', d / 'metrics.json', 'status=' + report['status'])
        except Exception as exc:
            save(d / 'metrics_error.json', dict(error=str(exc), schema=SCHEMA))
            # A metrics failure must not leave a seemingly successful run.
            import traceback
            import os
            traceback.print_exc()
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(1)
    atexit.register(finish)
    return context


def collect(directory):
    d = Path(directory).resolve()
    out = d / 'metrics'
    out.mkdir(exist_ok=True)
    context = load(d, 'metrics_run.json', {})
    protocol = load(d, 'protocol_summary.json', {})
    native = load(d, 'ramulator_native_summary.json', {})
    backend = load(d, 'ramulator_backend_summary.json', {})
    aou = load(d, 'aou_summary.json', {})
    fabric = load(d, 'fabric_metrics.json', {})
    power = load(d, 'dram_power.json', {})
    gstats = gem5_stats(d)
    end = context.get('end_tick_fs') or protocol.get('simulation_end_tick_fs') or backend.get('simulation_end_tick_fs') or gstats.get('simTicks', 0)
    duration = end * 1e-15
    modules = {name: dict(schema=SCHEMA, module=name, status='not_enabled',
                         reason='This component is not enabled in this run') for name in MODULES}
    latency_groups = defaultdict(list)
    mappings, event_rows = [], []
    metadata = {(r['id'], r['begin_tick']): r for r in rows(d, 'request_metadata.csv')}
    txns = []
    for i, original in enumerate(rows(d, 'transactions.csv'), 1):
        t = {k: v if k == 'command' else int(v) for k, v in original.items()}
        meta = metadata.get((str(t['id']), str(t['begin_tick'])), {})
        t.update(uid=int(meta.get('uid', i)), source=source(meta.get('source_name', 'unknown')),
                 source_name=meta.get('source_name'), enabled_bytes=int(meta.get('enabled_bytes', t['bytes'])),
                 packet_id=int(meta['packet_id']) if 'packet_id' in meta else None)
        txns.append(t)
        for stage, left, right in [('tlm.total', 'begin_tick', 'end_resp_tick'),
                                   ('tlm.admission', 'begin_tick', 'accepted_tick'),
                                   ('tlm.axi_service', 'accepted_tick', 'axi_done_tick'),
                                   ('tlm.response_hold', 'axi_done_tick', 'end_resp_tick')]:
            latency_groups[stage, t['source'], t['command']].append(t[right] - t[left])
        for event, key in [('begin', 'begin_tick'), ('accepted', 'accepted_tick'),
                           ('axi_done', 'axi_done_tick'), ('end_resp', 'end_resp_tick')]:
            event_rows.append(dict(tick_fs=t[key], module='tlm', event=event, uid=t['uid'],
                                   burst='', token='', source=t['source'], command=t['command']))
    by_uid = {t['uid']: t for t in txns}
    successful = [t for t in txns if t['status'] == 1]
    effective = sum(t['enabled_bytes'] for t in successful)
    activity_start = min((t['begin_tick'] for t in txns), default=None)
    activity_end = max((t['end_resp_tick'] for t in txns), default=None)

    def traffic(transactions):
        good = [t for t in transactions if t['status'] == 1]
        return dict(requests=len(transactions), successful_requests=len(good),
                    errors=len(transactions)-len(good), reads=sum(t['command']=='R' for t in transactions),
                    writes=sum(t['command']=='W' for t in transactions), requested_bytes=sum(t['bytes'] for t in transactions),
                    successful_enabled_bytes=sum(t['enabled_bytes'] for t in good),
                    successful_read_enabled_bytes=sum(t['enabled_bytes'] for t in good if t['command']=='R'),
                    successful_write_enabled_bytes=sum(t['enabled_bytes'] for t in good if t['command']=='W'),
                    latency=distribution([t['end_resp_tick']-t['begin_tick'] for t in transactions]))

    modules['tlm'] = dict(schema=SCHEMA, module='tlm', status='measured', **traffic(txns),
                          native_protocol_summary=protocol, max_outstanding=protocol.get('max_outstanding'),
                          stages={s: distribution([v for (stage, _, _), values in latency_groups.items() if stage == s for v in values])
                                  for s in ('tlm.admission', 'tlm.axi_service', 'tlm.response_hold')})
    modules['cpu'] = dict(schema=SCHEMA, module='cpu', status='measured' if any('cpu' in k for k in gstats) else 'not_enabled',
                          target_traffic=traffic([t for t in txns if t['source']=='cpu']),
                          native_gem5_statistics={k:v for k,v in gstats.items() if re.search(r'(^|\.)cpu\d*(\.|$)', k)},
                          power_w=None, power_status='no CPU power model',
                          ipc_note='Native CPU IPC/cycles retain gem5 definitions; target request latency is not CPU stall time')
    interconnect_stats = {k:v for k,v in gstats.items() if any(part in k for part in
                          ('.membus.','.bridge.','.het_monitor.','.l2bus.','.l2cache.'))}
    modules['gem5_interconnect'] = dict(schema=SCHEMA,module='gem5_interconnect',
        status='measured' if interconnect_stats else 'not_enabled',native_gem5_statistics=interconnect_stats,
        note='Native crossbar statistics include local host/PIO traffic. Target TLM traffic is counted separately.')
    windows = [dict(name='full_run', start_tick_fs=0, end_tick_fs=end, kind='simulation')]
    application_markers = rows(d, 'application_markers.csv')
    roi_begin = None
    roi_index = 0
    for marker in application_markers:
        if int(marker['marker']) == 1:
            if roi_begin is not None:
                raise ValueError('Nested application ROI markers are unsupported')
            roi_begin = int(marker['tick_fs'])
        elif int(marker['marker']) == 2:
            if roi_begin is None:
                raise ValueError('Application ROI end without begin')
            windows.append(dict(name=f'application_roi_{roi_index}',start_tick_fs=roi_begin,
                                end_tick_fs=int(marker['tick_fs']),kind='explicit host begin to verified task end'))
            roi_begin = None
            roi_index += 1
    if activity_start is not None:
        windows.append(dict(name='target_activity', start_tick_fs=activity_start, end_tick_fs=activity_end,
                            kind='first target BEGIN_REQ to last END_RESP; not application ROI'))
    for name in ('gpu', 'npu'):
        device = load(d, name + '_device_metrics.json')
        if device is not None:
            modules[name] = dict(schema=SCHEMA, module=name, status='measured', native_device_statistics=device,
                                 target_traffic=traffic([t for t in txns if t['source']==name]),
                                 power_w=None, power_status='no device power model')
            intervals = device.get('kernel_windows', []) if name == 'gpu' else ([dict(start_tick_fs=device['kernel_start_tick_fs'], end_tick_fs=device['kernel_end_tick_fs'])] if device.get('started') else [])
            for index, interval in enumerate(intervals):
                if interval['end_tick_fs'] > interval['start_tick_fs']:
                    windows.append(dict(name=f'{name}_kernel_{index}', kind='device kernel', **interval))

    cycles = protocol.get('measured_cycles', 0)
    channels = {ch: dict(v, handshake_cycle_fraction=ratio(v['handshakes'], cycles),
                         stall_cycle_fraction=ratio(v['stall_cycles'], cycles),
                         stall_time_fs=v['stall_cycles']*protocol.get('period_ticks', 0))
                for ch, v in protocol.get('channels', {}).items()}
    lane_bytes = 32*sum(channels.get(ch, {}).get('handshakes', 0) for ch in ('W', 'R'))
    modules['axi'] = dict(schema=SCHEMA, module='axi', status='measured', data_bits=protocol.get('axi_data_bits'),
                          clock_period_fs=protocol.get('period_ticks'), measured_cycles=cycles, channels=channels,
                          data_lane_bytes=lane_bytes, successful_enabled_byte_efficiency=ratio(effective, lane_bytes),
                          denominator='AXI rising edges with reset deasserted')
    fabric_cycles = fabric.get('cycles', 0)
    if aou:
        pack = fabric.get('axi2flit', {})
        modules['axi2flit'] = dict(schema=SCHEMA, module='axi2flit', status='measured',
                                  native_statistics=pack, packed_granule_utilization=ratio(pack.get('packed_granules',0), 48*pack.get('packed_flits',0)),
                                  resource_planes=[dict(rp=r['rp'], queues={k:queue_summary(v, fabric_cycles) for k,v in r['queues'].items()})
                                                   for r in pack.get('resource_planes', [])],
                                  sampled_cycles=fabric_cycles, includes_reset=True)
        modules['aou_target'] = dict(schema=SCHEMA, module='aou_target', status='measured',
                                    reads=aou.get('target_reads'), writes=aou.get('target_writes'),
                                    read_beats=aou.get('target_read_beats'), write_beats=aou.get('target_write_beats'),
                                    errors=aou.get('memory_errors'), completed=aou.get('memory_completed'),
                                    queues={k:queue_summary(v, fabric_cycles) for k,v in fabric.get('fifo_queues',{}).items() if k.startswith('target_')})
    # Raw FDI/frame observations; only TX_FRAME counts physical transmitted bytes.
    flits = rows(d, 'ucie_flits.csv')
    if flits:
        # Reuse the independent byte decoder/correlator without scanning the
        # potentially large VCD here. The acceptance runner still audits VCD.
        from inspect_link import Decoder, correlate
        decoders, messages, received_flits = {}, [], {}
        for r in flits:
            if r['event'] in ('TX_FDI', 'RX_FDI'):
                key = r['direction'], r['event']
                decoder = decoders.setdefault(key, Decoder())
                for message in decoder.feed(r):
                    message.update(direction=r['direction'],event=r['event'])
                    messages.append(message)
            if r['event'] == 'RX_FDI':
                received_flits[r['direction'],int(r['seq'])] = dict(rx=r)
        axi_rows = []
        for r in rows(d, 'aou_events.csv'):
            if r['channel'] not in ('AW','W','B','AR','R'):
                continue
            axi_rows.append(dict(tick_fs=int(r['tick']),channel=r['channel'],
                axi_id=int(r['id']),address=int(r['address']),length=int(r['len']),size=int(r['size']),
                data_hex=r['data_hex'],strb_hex=r['strb_hex'],last=int(r['last']),resp=int(r['resp'])))
        correlate(d,axi_rows,messages,received_flits)
        clean_messages = [{k:v for k,v in m.items() if not k.startswith('_')} for m in messages]
        table(d/'aou_messages.csv',clean_messages,list(clean_messages[0]) if clean_messages else ['type','rp','event'])
        dirs = {}
        for direction in ('FWD', 'REV'):
            events = [r for r in flits if r['direction']==direction]
            starts = {r['seq']:int(r['tick_fs']) for r in events if r['event']=='TX_FDI'}
            deliveries = [int(r['tick_fs'])-starts[r['seq']] for r in events if r['event']=='RX_FDI']
            counts = Counter(r['event'] for r in events)
            phy_bytes = sum(int(r['bytes']) for r in events if r['event']=='TX_FRAME')
            replay_bytes = sum(int(r['bytes']) for r in events if r['event']=='TX_FRAME' and int(r['replay']))
            dirs[direction] = dict(events=dict(counts), physical_tx_bytes=phy_bytes, replay_tx_bytes=replay_bytes,
                                   fdi_tx_bytes=sum(int(r['bytes']) for r in events if r['event']=='TX_FDI'),
                                   delivered_latency=distribution(deliveries),
                                   native_statistics=fabric.get('ucie',{}).get('forward' if direction=='FWD' else 'reverse',{}))
            link = dirs[direction]['native_statistics']
            dirs[direction]['bit_error_rate'] = ratio(link.get('bit_errors',0),link.get('total_bits',0))
            dirs[direction]['symbol_error_rate'] = ratio(link.get('symbol_errors',0),link.get('total_symbols',0))
            dirs[direction]['replay_byte_fraction'] = ratio(replay_bytes,phy_bytes)
        modules['ucie'] = dict(schema=SCHEMA, module='ucie', status='measured', directions=dirs,
                               physical_tx_bytes=sum(x['physical_tx_bytes'] for x in dirs.values()),
                               queues={k:queue_summary(v, fabric_cycles) for k,v in fabric.get('fifo_queues',{}).items() if not k.startswith('target_')})
        modules['axi2flit']['messages'] = dict(Counter(m['type'] for m in clean_messages if m['event']=='TX_FDI'))
        modules['axi2flit']['message_bytes'] = sum(len(m['raw_hex'])//2 for m in clean_messages if m['event']=='TX_FDI')

    # Stable uid -> AXI segment -> backend parent -> physical child. Wire IDs can wrap.
    segment_queues = defaultdict(deque)
    for segment in rows(d, 'request_segments.csv'):
        seg = {k:v if k=='command' else int(v) for k,v in segment.items()}
        segment_queues[seg['id'], seg['command'], seg['address'], seg['bytes']].append(seg)
    parent_groups = defaultdict(list)
    for e in rows(d, 'ramulator_bridge.csv'):
        parent_groups[int(e['burst'])].append(e)
    parent_to_txn, token_to_txn, parent_to_segment = {}, {}, {}
    for burst, events in parent_groups.items():
        accepted = next(e for e in events if e['event']=='accept')
        key = int(accepted['axi_id']), accepted['command'], int(accepted['address']), int(accepted['bytes'])
        queue = segment_queues[key]
        if not queue:
            raise ValueError(f'backend parent {burst} has no AXI segment identity')
        seg = queue.popleft()
        t = by_uid[seg['uid']]
        if not (seg['enqueue_tick_fs'] <= int(accepted['tick']) <= t['axi_done_tick']):
            raise ValueError('AXI ID reuse/parent association escaped the transaction lifetime')
        parent_to_txn[burst] = t
        parent_to_segment[burst] = seg
        returned = next((e for e in events if e['event']=='return'), None)
        if returned:
            latency_groups['backend.parent', t['source'], t['command']].append(int(returned['tick'])-int(accepted['tick']))
            last_service = max((int(e['tick']) for e in events if e['event']=='service'), default=int(accepted['tick']))
            latency_groups['backend.return_after_service', t['source'], t['command']].append(int(returned['tick'])-last_service)
        child_groups = defaultdict(list)
        for e in events:
            event_rows.append(dict(tick_fs=int(e['tick']), module='ramulator_backend', event=e['event'],
                                   uid=t['uid'], burst=burst, token=e['token'], source=t['source'], command=t['command']))
            if e['event'] == 'submit':
                token_to_txn[int(e['token'])] = t
            if int(e['token']):
                child_groups[int(e['token'])].append(e)
        for token, child_events in child_groups.items():
            submitted = next((e for e in child_events if e['event']=='submit'), None)
            service = next((e for e in child_events if e['event']=='service'), None)
            if submitted is None:
                continue
            issued = int(service['issued_cycle'])*native['period_fs'] if service else None
            mapping = dict(uid=t['uid'], packet_id=t['packet_id'], source=t['source'], source_name=t['source_name'],
                           axi_id=t['id'], segment=seg['segment'], burst=burst, token=token,
                           command=t['command'], address=int(submitted['address']), bytes=int(submitted['bytes']),
                           parent_accept_tick_fs=int(accepted['tick']), submit_tick_fs=int(submitted['tick']),
                           issued_tick_fs=issued, service_tick_fs=int(service['tick']) if service else None,
                           parent_return_tick_fs=int(returned['tick']) if returned else None)
            mappings.append(mapping)
            for stage, a, b in [('backend.admission', int(accepted['tick']), int(submitted['tick'])),
                                ('dram.queue_and_schedule', int(submitted['tick']), issued),
                                ('dram.data_service', issued, int(service['tick']) if service else None),
                                ('backend.child', int(accepted['tick']), int(service['tick']) if service else None)]:
                if a is not None and b is not None:
                    latency_groups[stage, t['source'], t['command']].append(b-a)
    if backend:
        queue = load(d, 'backend_queue_metrics.json', {})
        bc = queue.get('cycles', 0)
        queue['parent_mean_depth'] = ratio(queue.get('parent_depth_cycle_sum',0), bc)
        queue['child_mean_depth'] = ratio(queue.get('child_depth_cycle_sum',0), bc)
        queue['stall_time_fs'] = {k:v*backend['period_fs'] for k,v in queue.get('stall_cycles',{}).items()}
        modules['ramulator_backend'] = dict(schema=SCHEMA, module='ramulator_backend', status='measured',
                                            original_summary=backend, queue_statistics=queue,
                                            latency={stage:distribution([v for (s,_,_), values in latency_groups.items() if s==stage for v in values])
                                                     for stage in ('backend.parent','backend.admission','backend.return_after_service','backend.child')},
                                            stalls_note='Legacy counters retain event/attempt semantics. New cycle counters count each reason once per cycle and can overlap.')
        services = [e for events in parent_groups.values() for e in events if e['event']=='service']
        read_bytes = sum(int(e['bytes']) for e in services if e['command']=='R')
        write_bytes = sum(e['mask'].count('1') for e in services if e['command']=='W')
        modules['backing'] = dict(schema=SCHEMA, module='backing', status='measured', unique_data_owner=True,
                                  reads=sum(e['command']=='R' for e in services), writes=sum(e['command']=='W' for e in services),
                                  read_bytes=read_bytes, masked_write_bytes=write_bytes,
                                  allocated_pages=backend['allocated_pages'], capacity_bytes=backend['size'],
                                  image_file='ramulator_final_image.csv',
                                  note='Read bytes are physically serviced bytes; TLM enabled read bytes can be smaller')
    commands = rows(d, 'ramulator_commands.csv')
    if native:
        original = load(d, 'ramulator_stats.json', {})
        qmetrics = load(d, 'ramulator_queue_metrics.json', {})
        for channel in qmetrics.get('channels', []):
            channel['queues'] = {k:queue_summary(v,qmetrics['cycles']) for k,v in channel['queues'].items()}
        ctrls = original.get('memory_system',{}).get('controller', [])
        if isinstance(ctrls, dict):
            ctrls = [ctrls]
        controller_metrics = []
        for i, ctrl in enumerate(ctrls):
            denominator = sum(ctrl.get(k,0) for k in ('row_hits','row_misses','row_conflicts'))
            derived = dict(channel=i, row_hit_rate=ratio(ctrl.get('row_hits',0),denominator),
                           row_conflict_rate=ratio(ctrl.get('row_conflicts',0),denominator),
                           avg_read_latency_fs=ctrl.get('avg_read_latency',0)*native['period_fs'] if ctrl.get('num_read_reqs_served') else None,
                           avg_write_latency_fs=ctrl.get('avg_write_latency',0)*native['period_fs'] if ctrl.get('num_write_latency_samples') else None,
                           command_counts=dict(Counter(c['command'] for c in commands if int(c['channel'])==i)))
            controller_metrics.append(derived)
        source_commands = defaultdict(Counter)
        maintenance = Counter()
        for c in commands:
            token = int(c['token'])
            if token:
                source_commands[token_to_txn[token]['source']][c['command']] += 1
            else:
                maintenance[c['command']] += 1
        modules['ramulator2'] = dict(schema=SCHEMA, module='ramulator2', status='measured',
                                     original_statistics=original, original_yaml='ramulator_stats.yaml',
                                     original_summary=native, controllers=controller_metrics, queue_statistics=qmetrics,
                                     command_counts=dict(Counter(c['command'] for c in commands)),
                                     demand_commands_by_source={s:dict(v) for s,v in source_commands.items()},
                                     unattributed_maintenance_commands=dict(maintenance),
                                     physical_transaction_bytes=native['transaction_bytes']*native['serviced'],
                                     original_units={'cycles':'native cycles', '*latency':'native cycles',
                                                     '*throughput_MBps':'native decimal MB/s', '*energy_j':'joules', '*power_w':'watts'},
                                     core_0_note='Native source_id remains 0 for the external frontend; core_0 is NOT the CPU. Source attribution uses stable integration uid.')

    # Power intervals use differences of ONE continuous DRAMPower instance.
    # Their sum equals the unchanged native full-run totals. Arbitrary kernel
    # bounds additionally provide an explicitly interpolated estimate.
    series = rows(d, 'ramulator_timeseries.csv')
    pfields = ('core_energy_j','interface_energy_j','total_energy_j','activation_energy_j',
               'precharge_energy_j','read_energy_j','write_energy_j','refresh_energy_j','rfm_energy_j','background_energy_j')
    samples = defaultdict(dict)
    for sample in series:
        samples[int(sample['channel'])][int(sample['tick_fs'])] = sample
    queue_fields = ('read_queue','write_queue','priority_queue','active_queue','pending_reads','native_global_inflight')
    queue_hist = []
    for channel, values in samples.items():
        ordered = sorted(values.items())
        for field in queue_fields:
            counts = Counter(int(r[field]) for _,r in ordered)
            weighted = Counter()
            for (start,r),(finish,_) in zip(ordered,ordered[1:]):
                weighted[int(r[field])] += finish-start
            for depth,count in sorted(counts.items()):
                queue_hist.append(dict(channel=channel,queue=field,depth=depth,samples=count,
                                       estimated_duration_fs=weighted[depth],
                                       method='periodic post-tick samples; zero-order hold duration estimate'))
    power_intervals = []
    sampled_times, aggregate = [], []
    for tick in sorted({int(r['tick_fs']) for r in series}):
        entries = [samples[ch].get(tick) for ch in sorted(samples)]
        if all(entries):
            sampled_times.append(tick)
            aggregate.append({f:sum(float(r[f]) for r in entries) for f in pfields})
    enabled = bool(power.get('channels')) and any(c['enabled'] for c in power.get('channels',[]))
    for channel, values in samples.items():
        previous = None
        for tick, r in sorted(values.items()):
            if previous is not None and tick > previous[0]:
                start, before = previous
                delta = {f:float(r[f])-float(before[f]) if int(r['power_enabled']) else None for f in pfields}
                power_intervals.append(dict(channel=channel, start_tick_fs=start, end_tick_fs=tick,
                                            duration_seconds=(tick-start)*1e-15, power_enabled=bool(int(r['power_enabled'])),
                                            average_power_w=ratio(delta['total_energy_j'],(tick-start)*1e-15) if delta['total_energy_j'] is not None else None,
                                            **delta))
            previous = tick, r

    def at(tick):
        if not sampled_times:
            return None
        if tick <= sampled_times[0]:
            return aggregate[0]
        if tick >= sampled_times[-1]:
            return aggregate[-1]
        hi = bisect_left(sampled_times,tick)
        if sampled_times[hi] == tick:
            return aggregate[hi]
        lo = hi-1
        frac = (tick-sampled_times[lo])/(sampled_times[hi]-sampled_times[lo])
        return {f:aggregate[lo][f]+frac*(aggregate[hi][f]-aggregate[lo][f]) for f in pfields}

    power_windows = []
    for window in windows:
        begin, finish = window['start_tick_fs'], window['end_tick_fs']
        covered_end = sampled_times[-1] if sampled_times else 0
        covered = min(finish, covered_end) >= begin
        a, b = at(begin), at(min(finish, covered_end))
        delta = {f:b[f]-a[f] if enabled and covered and a and b else None for f in pfields}
        wd = max(0, min(finish, covered_end)-begin)*1e-15
        exact = (begin in sampled_times and min(finish,covered_end) in sampled_times)
        power_windows.append(dict(window, native_covered_end_tick_fs=min(finish,covered_end),
                                  duration_seconds=wd, boundary_method='exact cumulative snapshots' if exact else 'linear interpolation of cumulative energy; estimate',
                                  max_boundary_gap_fs=max((b-a for a,b in zip(sampled_times,sampled_times[1:])),default=0),
                                  power_enabled=enabled, average_power_w=ratio(delta['total_energy_j'],wd) if delta['total_energy_j'] is not None else None,
                                  **delta))
    if power:
        total = power['total_energy_j']
        component = {f:sum(c.get(f,0) for c in power['channels']) for f in pfields}
        modules['dram_power'] = dict(schema=SCHEMA, module='dram_power', status='measured' if enabled else 'disabled',
                                    original_statistics=power, power_enabled=enabled,
                                    total_energy_j=total if enabled else None,
                                    average_power_w=power['average_power_w'] if enabled else None,
                                    components_j=component if enabled else {f:None for f in pfields},
                                    component_fractions={f:ratio(v,total) if enabled else None for f,v in component.items()},
                                    windows=power_windows,
                                    interface_note='Zero native interface energy with interface model disabled is NOT proof of zero physical interface power',
                                    system_total_power_w=None, system_power_status='CPU/GPU/NPU/AXI/UCIe/controller logic power models not implemented',
                                    source_energy_status='Background/refresh are shared; per-source command counts are available, no causal energy allocation claimed')

    grouped = [dict(stage=stage,source=s,command=cmd,**distribution(values)) for (stage,s,cmd),values in sorted(latency_groups.items())]
    bins = []
    for (stage,s,cmd),values in sorted(latency_groups.items()):
        counts = Counter(0 if v==0 else v.bit_length() for v in values)
        for bin_id,count in sorted(counts.items()):
            bins.append(dict(stage=stage,source=s,command=cmd,lower_fs=0 if bin_id==0 else 2**(bin_id-1),
                             upper_exclusive_fs=1 if bin_id==0 else 2**bin_id,count=count))
    checks = dict(tlm_count=protocol.get('completed')==len(txns),
                  tlm_drained=bool(protocol.get('drained')), uid_unique=len(by_uid)==len(txns),
                  sources_identified=all(t['source']!='unknown' for t in txns),
                  application_markers_balanced=roi_begin is None,
                  window_bounds_valid=all(0<=w['start_tick_fs']<=w['end_tick_fs']<=end for w in windows))
    arguments = context.get('arguments',{})
    if arguments.get('mode')=='cpu' or arguments.get('cmd'):
        checks['cpu_native_statistics_present'] = bool(modules['cpu']['native_gem5_statistics'])
    if arguments.get('vortex_library'):
        checks['gpu_device_statistics_present'] = modules['gpu']['status']=='measured'
    if arguments.get('npu_library'):
        checks['npu_device_statistics_present'] = modules['npu']['status']=='measured'
    if native:
        checks.update(parent_count=len(parent_groups)==backend.get('bursts'),
                      child_count=len(mappings)==native.get('submitted')==native.get('serviced'),
                      command_count=len(commands)==native.get('commands'),
                      backing_child_count=modules['backing']['reads']+modules['backing']['writes']==native['serviced'],
                      source_command_conservation=sum(sum(x.values()) for x in modules['ramulator2']['demand_commands_by_source'].values())+sum(modules['ramulator2']['unattributed_maintenance_commands'].values())==len(commands),
                      native_stats_present=bool(modules['ramulator2']['original_statistics']),
                      power_final_snapshot=bool(aggregate) and math.isclose(aggregate[-1]['total_energy_j'],power['total_energy_j'],rel_tol=1e-10,abs_tol=1e-20))
        checks['native_queue_integrals_match'] = all(
            qmetrics['channels'][i]['queues'][q]['depth_cycle_sum']==ctrls[i].get(native_name)
            for i in range(len(ctrls)) for q,native_name in [('read_queue','read_queue_len'),('write_queue','write_queue_len'),('priority_queue','priority_queue_len')])
        checks['power_interval_conservation'] = all(math.isclose(sum(r[f] for r in power_intervals if r[f] is not None),
                                                               sum(c.get(f,0) for c in power['channels']),rel_tol=1e-9,abs_tol=1e-18)
                                                   for f in pfields) if enabled else True
    complete = context.get('completed', False)
    status = 'complete' if complete and all(checks.values()) else 'incomplete' if not complete else 'invalid'
    overall = dict(schema=SCHEMA,status=status,simulation_end_tick_fs=end,duration_seconds=duration,
                   native_end_tick_fs=native.get('cycles',0)*native.get('period_fs',0) if native else None,
                   traffic=traffic(txns), sources={s:traffic([t for t in txns if t['source']==s]) for s in sorted({t['source'] for t in txns})},
                   effective_bytes=effective, full_run_effective_bandwidth_Bps=ratio(effective,duration),
                   target_activity_start_tick_fs=activity_start,target_activity_end_tick_fs=activity_end,
                   target_activity_effective_bandwidth_Bps=ratio(effective,(activity_end-activity_start)*1e-15) if activity_start is not None else None,
                   flow=dict(tlm_requests=len(txns),axi_segments=sum(t['segments'] for t in txns),backend_parents=len(parent_groups),
                             physical_children=len(mappings),axi_lane_bytes=lane_bytes,
                             dram_transaction_bytes=native.get('serviced',0)*native.get('transaction_bytes',0),
                             ucie_physical_tx_bytes=modules['ucie'].get('physical_tx_bytes')),
                   amplification=dict(axi_lane_per_effective_byte=ratio(lane_bytes,effective),
                                      dram_per_effective_byte=ratio(native.get('serviced',0)*native.get('transaction_bytes',0),effective),
                                      phy_per_effective_byte=ratio(modules['ucie'].get('physical_tx_bytes',0),effective)),
                   latency=distribution([t['end_resp_tick']-t['begin_tick'] for t in txns]),
                   dram_energy_j=power.get('total_energy_j') if enabled else None,
                   dram_average_power_w=power.get('average_power_w') if enabled else None,
                   dram_energy_per_effective_byte_j=ratio(power.get('total_energy_j',0),effective) if enabled else None,
                   dram_energy_delay_product_js=power.get('total_energy_j',0)*power.get('duration_seconds',0) if enabled else None,
                   system_total_energy_j=None,system_power_status='Only DRAM has an energy model',
                   metric_consistency_checks=checks, independent_correctness_validation='See *_check.json; metrics consistency is not byte/timing correctness',
                   windows=windows)
    overall['application_roi_status'] = 'measured' if roi_index else 'incomplete' if roi_begin is not None else 'unavailable: workload did not emit application markers'
    for value in overall['sources'].values():
        value['full_run_effective_bandwidth_Bps'] = ratio(value['successful_enabled_bytes'],duration)
    overall['native_gem5_global_statistics'] = {k:v for k,v in gstats.items() if '.' not in k}
    raw_names = ('axi_wave.vcd','axi_events.csv','transactions.csv','request_metadata.csv','request_segments.csv',
                 'aou_events.csv','ucie_flits.csv','ucie_soc.csv','ucie_mem.csv','ramulator_bridge.csv',
                 'ramulator_commands.csv','ramulator_final_image.csv','ramulator_timeseries.csv','stats.txt')
    overall['raw_evidence_bytes'] = sum((d/name).stat().st_size for name in raw_names if (d/name).exists())
    overall['raw_evidence_bytes'] += sum(p.stat().st_size for p in (d/'hettrace').glob('*') if p.is_file() and not p.is_symlink())
    overall['window_statistics'] = []
    for window in windows:
        begin, finish = window['start_tick_fs'], window['end_tick_fs']
        completed_tx = [t for t in txns if begin <= t['end_resp_tick'] <= finish]
        good = [t for t in completed_tx if t['status'] == 1]
        bytes_completed = sum(t['enabled_bytes'] for t in good)
        window_duration = (finish-begin)*1e-15
        own_power = next(w for w in power_windows if w['name'] == window['name'])
        overall['window_statistics'].append(dict(window, duration_seconds=window_duration,
            completed_target_traffic=traffic(completed_tx),
            completion_accounted_effective_bandwidth_Bps=ratio(bytes_completed,window_duration),
            started_target_requests=sum(begin<=t['begin_tick']<=finish for t in txns),
            requests_crossing_start=sum(t['begin_tick']<begin<t['end_resp_tick'] for t in txns),
            requests_crossing_end=sum(t['begin_tick']<finish<t['end_resp_tick'] for t in txns),
            sources={s:traffic([t for t in completed_tx if t['source']==s]) for s in sorted({t['source'] for t in txns})},
            dram_energy_j=own_power['total_energy_j'],dram_average_power_w=own_power['average_power_w'],
            power_boundary_method=own_power['boundary_method'],
            accounting='Requests counted at END_RESP; windows overlap and MUST NOT be summed'))
        for value in overall['window_statistics'][-1]['sources'].values():
            value['completion_accounted_effective_bandwidth_Bps'] = ratio(value['successful_enabled_bytes'],window_duration)
    for name,value in modules.items():
        if name != 'dram_power':
            value['energy_j'] = None
            value['average_power_w'] = None
            value.setdefault('power_status','No module energy model; DRAM energy is reported separately')
        save(out/(name+'.json'),value)
    save(out/'overall.json',overall)
    report = dict(schema=SCHEMA,status=status,overall=overall,modules=modules,latency_by_source=grouped)
    save(d/'metrics.json',report)
    table(d/'request_map.csv',mappings,['uid','packet_id','source','source_name','axi_id','segment','burst','token','command','address','bytes','parent_accept_tick_fs','submit_tick_fs','issued_tick_fs','service_tick_fs','parent_return_tick_fs'])
    flit_map = []
    transactions_by_id = defaultdict(list)
    for t in txns:
        transactions_by_id[t['id']].append(t)
    for path in rows(d,'axi_flit_path.csv') if flits else []:
        tick, axi_id = int(path['axi_tick_fs']), int(path['axi_id'])
        matches = [t for t in transactions_by_id[axi_id] if t['accepted_tick'] <= tick <= t['axi_done_tick']]
        if len(matches) != 1:
            raise ValueError('Flit/AXI path has ambiguous reused ID lifetime')
        t = matches[0]
        flit_map.append(dict(uid=t['uid'],source=t['source'],packet_id=t['packet_id'],**path))
    table(d/'request_flit_map.csv',flit_map,['uid','source','packet_id','channel','axi_id','axi_tick_fs','address','message','rp','direction','start_seq','end_seq','tx_first_tick_fs','tx_last_tick_fs','rx_first_tick_fs','rx_last_tick_fs'])
    table(d/'metrics_events.csv',sorted(event_rows,key=lambda r:r['tick_fs']),['tick_fs','module','event','uid','burst','token','source','command'])
    table(d/'latency_hist.csv',bins,['stage','source','command','lower_fs','upper_exclusive_fs','count'])
    table(d/'latency_summary.csv',grouped,['stage','source','command','count','mean_fs','p50_fs','p95_fs','p99_fs','max_fs'])
    table(d/'power_intervals.csv',power_intervals,['channel','start_tick_fs','end_tick_fs','duration_seconds','power_enabled','average_power_w',*pfields])
    table(d/'queue_occupancy.csv',[{k:r[k] for k in ('tick_fs','cycle','channel',*queue_fields)} for r in series],
          ['tick_fs','cycle','channel',*queue_fields])
    table(d/'queue_hist.csv',queue_hist,['channel','queue','depth','samples','estimated_duration_fs','method'])
    table(d/'power_windows.csv',power_windows,['name','start_tick_fs','end_tick_fs','kind','native_covered_end_tick_fs','duration_seconds','boundary_method','max_boundary_gap_fs','power_enabled','average_power_w',*pfields])
    table(d/'markers.csv',windows,['name','start_tick_fs','end_tick_fs','kind'])
    stalls = []
    if backend:
        for reason,count in queue.get('stall_cycles',{}).items():
            stalls.append(dict(module='ramulator_backend',reason=reason,cycles=count,period_fs=backend['period_fs'],duration_fs=count*backend['period_fs']))
    for ch,value in channels.items():
        stalls.append(dict(module='axi',reason=ch+'_valid_not_ready',cycles=value['stall_cycles'],period_fs=protocol['period_ticks'],duration_fs=value['stall_time_fs']))
    table(d/'stall_reasons.csv',stalls,['module','reason','cycles','period_fs','duration_fs'])
    evidence = [p for p in d.iterdir() if p.is_file() and p.name in ('metrics_run.json','config.ini','config.json','ramulator_config.yaml','ramulator_model.json','ramulator_stats.yaml','dram_power.json')]
    evidence.extend(d/name for name in raw_names if (d/name).exists())
    evidence.extend(p for p in (d/'hettrace').glob('*') if p.is_file() and not p.is_symlink())
    save(d/'metrics_manifest.json',dict(schema=SCHEMA,time_unit='fs',energy_unit='J',power_unit='W',
        collector_source_sha256=COLLECTOR_SHA256,
        quantiles='nearest rank',histogram='powers of two, half-open bins',arguments=context.get('arguments'),
        evidence_sha256={str(p.relative_to(d)):file_sha256(p) for p in evidence},
        module_files={name:'metrics/'+name+'.json' for name in MODULES},
        notes=['Full-run DRAM totals retain native measurement duration. Target activity is a traffic window, not application ROI.',
               'Kernel/window energy boundaries between snapshots are interpolated estimates.',
               'Counters for different stall reasons can overlap; do not add them as exclusive execution time.',
               'Disabled or unmodeled energy is null; original native disabled-power zeros remain in original_statistics.']))
    text = ['# 全链路运行统计', '', f'状态：{status}；仿真时长 {duration:.9g} s；TLM 请求 {len(txns)}；有效字节 {effective}。', '',
            '| 部分 | 状态 | 独立报告 |','|---|---|---|']
    text += [f'| {name} | {v["status"]} | [metrics/{name}.json](metrics/{name}.json) |' for name,v in modules.items()]
    text += ['', '[整体报告](metrics/overall.json) · [全部机器可读指标](metrics.json) · [指标口径与证据](metrics_manifest.json)', '',
             'DRAM 能耗/平均功率：'+(f'{power["total_energy_j"]:.9g} J / {power["average_power_w"]:.9g} W。' if enabled else '未启用。'), '',
             '本报告中的整体能耗只汇总 DRAM，其他模块尚无功耗模型。窗口功耗估计见 power_windows.csv；连续采样差分见 power_intervals.csv。', '',
             '原有原生统计、波形、Flit 日志与独立数据校验仍保留。统计一致性检查不代替独立数据/命令时序校验。']
    (d/'metrics_summary.md').write_text('\n'.join(text)+'\n')
    # Small entry page; load only the selected module instead of raw traces.
    html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>全链路实验统计</title><style>
body{font:16px system-ui;margin:24px;max-width:1200px;color:#213047;background:#f7f9fc}
select{padding:8px}pre{background:white;padding:16px;white-space:pre-wrap;overflow-wrap:anywhere}
table{border-collapse:collapse;background:white}td,th{border:1px solid #dce2ed;padding:8px}
</style><h1>全链路实验统计</h1>
<p>__OPTIONAL_LINKS__
<a href="metrics_manifest.json">统计口径与配置</a> · <a href="metrics.json">全部JSON</a> ·
<a href="latency_summary.csv">延迟CSV</a> · <a href="power_windows.csv">窗口功耗CSV</a> ·
<a href="power_intervals.csv">功耗曲线CSV</a> · <a href="queue_occupancy.csv">队列CSV</a></p>
<p id="status">正在加载…</p><table><thead><tr><th>统计窗口</th><th>时间/s</th><th>完成请求</th><th>DRAM能量/J</th><th>DRAM平均功率/W</th><th>功耗边界方法</th></tr></thead><tbody id="windows"></tbody></table>
<p>各设备/任务窗口可重叠；请分别比较。当前能量模型覆盖DRAM。窗口采样点之间的能量采用插值估计。</p>
<label>独立报告 <select id="module"></select></label><pre id="details"></pre>
<script>
const names=__MODULES__,el=id=>document.getElementById(id),fmt=v=>v==null?'未测量/未启用':typeof v==='number'?Number(v.toPrecision(9)):v;
for(const name of ['overall',...names]){const o=document.createElement('option');o.value=name;o.textContent=name;el('module').appendChild(o);}
let sequence=0;
async function show(){const n=++sequence;try{const r=await fetch('metrics/'+el('module').value+'.json');if(!r.ok)throw Error(r.status);const v=await r.json();if(n===sequence)el('details').textContent=JSON.stringify(v,null,2);}catch(e){el('details').textContent=e.message;}}
fetch('metrics/overall.json').then(r=>r.json()).then(v=>{el('status').textContent='状态：'+v.status+'；请求 '+v.traffic.requests+'；有效字节 '+v.effective_bytes+'；时长 '+fmt(v.duration_seconds)+' s；任务ROI：'+v.application_roi_status;
for(const w of v.window_statistics){const row=document.createElement('tr');for(const x of [w.name,w.duration_seconds,w.completed_target_traffic.requests,w.dram_energy_j,w.dram_average_power_w,w.power_boundary_method]){const cell=document.createElement('td');cell.textContent=fmt(x);row.appendChild(cell);}el('windows').appendChild(row);}})
.catch(e=>{el('status').textContent='加载失败，请通过本机HTTP服务打开：'+e.message;});
el('module').onchange=show;show();
</script></html>'''.replace('__MODULES__',json.dumps(MODULES))
    optional_links = [(name,label) for name,label in [('trace_view.html','AXI/UCIe日志与波形'),
        ('ramulator.html','DRAM命令与数据'),('axi_wave.vcd','完整AXI波形'),('ramulator_commands.csv','DRAM命令CSV')] if (d/name).exists()]
    html = html.replace('__OPTIONAL_LINKS__',''.join(f'<a href="{name}">{label}</a> · ' for name,label in optional_links))
    (d/'metrics.html').write_text(html)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directories',nargs='+',type=Path)
    args = p.parse_args()
    for directory in args.directories:
        result = collect(directory)
        print(directory,result['status'])
        if result['status'] != 'complete':
            raise SystemExit(1)
