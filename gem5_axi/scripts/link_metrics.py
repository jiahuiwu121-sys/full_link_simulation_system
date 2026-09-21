"""Offline link diagnostics. Byte events and occupied intervals are distinct.

No simulator API is called. Missing resolved capacity yields null, never a
capacity inferred from a default. Windows overlap; samples cannot be summed.
"""
from bisect import bisect_left, bisect_right
from collections import defaultdict, deque
import math


def divide(a, b):
    return a / b if a is not None and b else None


def summary(values):
    values = sorted(values)
    return dict(count=len(values), mean_fs=divide(sum(values), len(values)),
                **{name: values[math.ceil(len(values)*q)-1] if values else None
                   for name, q in [('p50_fs', .5), ('p95_fs', .95), ('p99_fs', .99), ('max_fs', 1)]})


def union(intervals):
    merged = []
    for a, b in sorted(intervals):
        if b <= a:
            continue
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(b, merged[-1][1])
        else:
            merged.append([a, b])
    return merged


def overlap(intervals, a, b):
    # Clipped union, never sum overlapping reservations on the same bus.
    return sum(max(0, min(y, b)-max(x, a)) for x, y in intervals)


class OccupancyIntegral:
    """Exact interval integral with O(log N) window queries."""
    def __init__(self, intervals):
        self.intervals = union(intervals)
        self.starts = [a for a, _ in self.intervals]
        self.prefix = [0]
        for a, b in self.intervals:
            self.prefix.append(self.prefix[-1]+b-a)

    def until(self, tick):
        i = bisect_right(self.starts, tick)-1
        if i < 0:
            return 0
        a, b = self.intervals[i]
        return self.prefix[i]+min(tick,b)-a

    def between(self, a, b):
        return self.until(b)-self.until(a)


class InflightProfile:
    """Piecewise constant concurrency, including carry-in/out requests."""
    def __init__(self, transactions):
        changes = defaultdict(int)
        for t in transactions:
            if t['end_resp_tick'] > t['begin_tick']:
                changes[t['begin_tick']] += 1
                changes[t['end_resp_tick']] -= 1
        self.ticks = sorted(changes)
        self.depths, self.areas = [], []
        depth = area = previous = 0
        for tick in self.ticks:
            area += depth*(tick-previous)
            depth += changes[tick]
            self.areas.append(area)
            self.depths.append(depth)
            previous = tick

    def until(self, tick):
        i = bisect_right(self.ticks,tick)-1
        return self.areas[i]+self.depths[i]*(tick-self.ticks[i]) if i >= 0 else 0

    def between(self, a, b):
        left, right = bisect_right(self.ticks,a), bisect_left(self.ticks,b)
        carry = self.depths[left-1] if left else 0
        peak = max([carry, *self.depths[left:right]]) if b > a else 0
        area = self.until(b)-self.until(a)
        return dict(time_weighted_mean=divide(area,b-a),peak=peak,request_time_integral_fs=area,
                    method='exact clipped BEGIN_REQ to END_RESP intervals of logged transactions')


def axi_latencies(events):
    reads = defaultdict(deque)
    addresses, data = deque(), deque()
    writes = defaultdict(deque)
    result, errors = [], []
    for r in events:
        ch, tick, ident = r['channel'], int(r['tick']), int(r['id'])
        if ch == 'AR':
            reads[ident].append(dict(start=tick, first=None, remaining=int(r['len'])+1))
        elif ch == 'R':
            if not reads[ident]:
                errors.append('R without AR')
                continue
            t = reads[ident][0]
            if t['first'] is None:
                t['first'] = tick
                result.append(dict(stage='axi.read_first_beat', command='R', axi_id=ident, tick_fs=tick, latency_fs=tick-t['start']))
            t['remaining'] -= 1
            if int(r['last']):
                if t['remaining'] != 0:
                    errors.append('R beat count mismatch')
                result.append(dict(stage='axi.read_complete', command='R', axi_id=ident, tick_fs=tick, latency_fs=tick-t['start']))
                result.append(dict(stage='axi.read_transfer', command='R', axi_id=ident, tick_fs=tick, latency_fs=tick-t['first']))
                reads[ident].popleft()
        elif ch == 'AW':
            addresses.append((ident, tick, int(r['len'])+1))
        elif ch == 'W':
            data.append((tick, bool(int(r['last']))))
        elif ch == 'B':
            if not writes[ident]:
                errors.append('B without complete AW/W')
                continue
            start = writes[ident].popleft()
            result.append(dict(stage='axi.write_response', command='W', axi_id=ident, tick_fs=tick, latency_fs=tick-start))
        # AXI4 has no WID: pair write data bursts in AW order. W may precede AW.
        while addresses and any(last for _, last in data):
            ident, aw, beats = addresses.popleft()
            count = 0
            while data:
                w, last = data.popleft()
                count += 1
                if last:
                    break
            if count != beats:
                errors.append('W beat count mismatch')
            writes[ident].append(max(aw, w))
    if addresses or data or any(reads.values()) or any(writes.values()):
        errors.append('incomplete AXI burst')
    return result, errors


def analyze(txns, mappings, axi, flits, commands, protocol, fabric, models, native, backend, windows, end, bin_ns=100):
    resources = []
    warnings = []
    profile = InflightProfile(txns)
    source_profiles = {s:InflightProfile([t for t in txns if t['source']==s]) for s in sorted({t['source'] for t in txns})}
    period = protocol.get('period_ticks', 0)
    lane = protocol.get('axi_data_bits', 256)//8
    def resource(name, events, intervals=(), peak=None, method=None, **extra):
        ordered = sorted(events)
        ticks = [t for t, _ in ordered]
        prefix = [0]
        for _, n in ordered:
            prefix.append(prefix[-1]+n)
        r = dict(name=name, peak_Bps=peak, capacity_method=method or 'unavailable: resolved model metadata missing',
                 _events=ordered, _ticks=ticks, _prefix=prefix, _busy=OccupancyIntegral(intervals), **extra)
        resources.append(r)
        return r
    for ch in ('W', 'R'):
        resource('AXI '+ch, [(int(r['tick']), lane) for r in axi if r['channel']==ch],
                 peak=divide(lane, period*1e-15), method='data_bits / 8 / AXI clock period; independent W and R lanes',
                 occupancy_method='handshakes / reset-deasserted clock opportunities')
    for cmd in ('R', 'W'):
        resource('TLM effective '+cmd, [(t['end_resp_tick'], t['enabled_bytes']) for t in txns if t['command']==cmd and t['status']==1],
                 method='no single peak: depends on workload, packet overhead and concurrent resources',
                 completion_accounted=True)
    config = fabric.get('link_config', {})
    serial = config.get('serialize_ui', 0)*config.get('ui_fs', 0)
    for direction in ('FWD', 'REV'):
        frames = [r for r in flits if r['direction']==direction and r['event']=='TX_FRAME']
        events = [(int(r['tick_fs']), int(r['bytes'])) for r in frames]
        resource('UCIe '+direction, events,
                 [(t, t+serial) for t, _ in events] if serial else [],
                 divide(config.get('frame_bytes', 0), serial*1e-15),
                 'resolved frame bytes / quantized SystemC serialization time' if serial else None,
                 occupancy_method='union of TX_FRAME serialization intervals; excludes propagation',
                 replay_bytes=sum(int(r['bytes']) for r in frames if int(r['replay'])),
                 replay_byte_fraction=divide(sum(int(r['bytes']) for r in frames if int(r['replay'])),sum(n for _, n in events)))
    backend_summary = backend.get('original_summary', {})
    native_period = native.get('period_fs', 0)
    transaction_bytes = native.get('transaction_bytes', 0)
    submit_width = backend_summary.get('submit_width')
    backend_peak = divide(submit_width * transaction_bytes, native_period * 1e-15) \
        if submit_width and transaction_bytes and native_period else None
    resource('Backend ingress',
             [(int(m['submit_tick_fs']), transaction_bytes) for m in mappings],
             peak=backend_peak,
             method='submit_width * native transaction bytes / DRAM tick' if backend_peak is not None else None,
             occupancy_method='accepted native child submissions / configured dispatch slots',
             _slot_period_fs=native_period, _slot_width=submit_width)
    # Supported HBM bus organization: each pseudochannel owns a data bus.
    # Burst capacity is payload capacity of the simulated model, not pin metadata.
    buses = {}
    bursts = []
    for channel, model in enumerate(models.get('controllers', [])):
        timings = model.get('timings', {})
        nbl = timings.get('nBL', 0)
        ck = model.get('period_fs', 0)
        tx = model.get('transaction_bytes', 0)
        known = model.get('standard') in ('HBM3', 'HBM4') and nbl > 0 and ck > 0 and tx > 0
        levels = model.get('levels', [])
        pc_level = levels.index('PseudoChannel') if 'PseudoChannel' in levels else None
        count = model['organization'][pc_level] if pc_level is not None else 1
        per_pc = divide(tx, nbl*ck*1e-15) if known else None
        own = [r for r in commands if int(r['channel'])==channel and r['command'] in ('RD','RDA','WR','WRA')]
        for pc in range(count):
            entries = [r for r in own if pc_level is None or int(r['level'+str(pc_level)])==pc]
            intervals = []
            for r in entries:
                if known:
                    write = r['command'] in ('WR','WRA')
                    delay = native['write_latency' if write else 'read_latency']-nbl
                    a = int(r['tick'])+delay*ck
                    intervals.append((a, a+nbl*ck))
                    bursts.append(dict(channel=channel,pseudochannel=pc,command='W' if write else 'R',
                                       token=int(r['token']),start_tick_fs=a,end_tick_fs=a+nbl*ck,bytes=tx))
            buses[channel, pc] = resource(f'DRAM ch{channel}/pc{pc}', [(int(r['tick']), native.get('transaction_bytes',0)) for r in entries],
                intervals, per_pc, 'HBM transaction bytes / resolved nBL / period_fs' if known else None,
                occupancy_method='modeled data burst intervals, command + CL/CWL through burst end')
        resource(f'DRAM ch{channel} total', [(int(r['tick']),native.get('transaction_bytes',0)) for r in own],
                 peak=per_pc*count if per_pc is not None else None,
                 method='sum of independent pseudochannel payload capacities' if known else None,
                 occupancy_method='mean of independent pseudochannel occupied fractions',
                 _bus_keys=[(channel, pc) for pc in range(count)])
    if native and not models.get('controllers'):
        warnings.append('DRAM capacity unavailable: no resolved model manifest')
    axi_peak = divide(lane, period*1e-15)
    ucie_peak = divide(config.get('frame_bytes', 0), serial*1e-15)
    dram_peaks = [r['peak_Bps'] for r in resources if r['name'].startswith('DRAM ch') and r['name'].endswith(' total')]
    dram_peak = sum(dram_peaks) if dram_peaks and all(v is not None for v in dram_peaks) else None
    ingress_known = all(v is not None for v in (axi_peak, ucie_peak, backend_peak, dram_peak))
    ratio_axi_ucie = divide(axi_peak, ucie_peak)
    capacity_balance = dict(
        status=('balanced_ingress' if ingress_known and .8 <= ratio_axi_ucie <= 1.25 and
                backend_peak >= min(axi_peak, ucie_peak) and dram_peak >= min(axi_peak, ucie_peak)
                else 'unbalanced_or_unknown'),
        bottleneck=min(((name, value) for name,value in [('AXI256 per direction',axi_peak),
                       ('UCIe per direction',ucie_peak),('backend dispatch',backend_peak),
                       ('aggregate DRAM data buses',dram_peak)] if value is not None),
                       key=lambda x:x[1])[0] if any(v is not None for v in (axi_peak,ucie_peak,backend_peak,dram_peak)) else None,
        capacities_Bps=dict(axi_per_direction=axi_peak,ucie_per_direction=ucie_peak,
                            backend_dispatch=backend_peak,dram_aggregate=dram_peak),
        ratios=dict(axi_to_ucie=ratio_axi_ucie,
                    backend_headroom_over_link=divide(backend_peak,min(axi_peak,ucie_peak)) if axi_peak and ucie_peak else None,
                    dram_headroom_over_link=divide(dram_peak,min(axi_peak,ucie_peak)) if axi_peak and ucie_peak else None),
        policy='AXI and UCIe within 20%; backend and DRAM at least as fast as the slower ingress link')
    if capacity_balance['status'] != 'balanced_ingress':
        warnings.append('Ingress capacity is unbalanced or unresolved; use capacity_balance before interpreting saturation')
    first, last = protocol.get('first_measured_tick_fs'), protocol.get('last_measured_tick_fs')
    def opportunities(a, b):
        if first is None or last is None or not period:
            return None
        lo = max(0, math.ceil((a-first)/period))
        hi = min(protocol['measured_cycles'], math.ceil((b-first)/period))
        if b == end and last == end:
            hi += 1
        return max(0,min(protocol['measured_cycles'],hi)-lo)
    def window_stat(r, a, b, include_completion_end=False):
        ticks, prefix = r['_ticks'], r['_prefix']
        left = bisect_left(ticks,a)
        right = bisect_right(ticks,b) if b==end or (include_completion_end and r.get('completion_accounted')) else bisect_left(ticks,b)
        n = prefix[right]-prefix[left]
        elapsed = b-a
        occupied = r['_busy'].between(a,b) if r['peak_Bps'] is not None else None
        utilization = divide(occupied,elapsed)
        if r['name'].startswith('AXI '):
            cycles = opportunities(a,b)
            utilization = divide(right-left,cycles) if cycles is not None else None
            if a==0 and b==end:
                utilization = divide(protocol.get('channels',{}).get(r['name'][-1],{}).get('handshakes',0),protocol.get('measured_cycles',0))
            occupied = None
        elif r['name'] == 'Backend ingress' and r.get('_slot_period_fs') and r.get('_slot_width'):
            utilization = divide(right-left, (elapsed/r['_slot_period_fs'])*r['_slot_width'])
            occupied = None
        elif '_bus_keys' in r:
            busy = [buses[k]['_busy'].between(a,b) for k in r['_bus_keys']]
            utilization = divide(sum(busy),elapsed*len(busy)) if r['peak_Bps'] is not None else None
            occupied = None
        return dict(bytes=n, bandwidth_Bps=divide(n,elapsed*1e-15), utilization=utilization,
                    occupied_time_fs=occupied, event_rate_to_peak_ratio=divide(divide(n,elapsed*1e-15),r['peak_Bps']))
    window_rows = []
    for w in windows:
        a,b = w['start_tick_fs'],w['end_tick_fs']
        completed = [t for t in txns if a<=t['end_resp_tick']<=b]
        window_rows.append(dict(name=w['name'],start_tick_fs=a,end_tick_fs=b,
            resources={r['name']:window_stat(r,a,b,True) for r in resources},
            inflight=profile.between(a,b),
            sources={s:dict(inflight=source_profiles[s].between(a,b),
                           completed_requests=sum(t['source']==s for t in completed),
                           bandwidth_Bps=divide(sum(t['enabled_bytes'] for t in completed if t['source']==s and t['status']==1),(b-a)*1e-15))
                     for s in sorted({t['source'] for t in txns})}))
    # Aggregate into complete time bins, rather than discard isolated peaks.
    if not math.isfinite(bin_ns) or bin_ns <= 0:
        raise ValueError('SS_METRICS_BIN_NS must be finite and positive')
    width = max(1,round(bin_ns*1e6),math.ceil(end/1000))
    timebins = []
    for a in range(0,end,width):
        b=min(end,a+width)
        timebins.append(dict(start_tick_fs=a,end_tick_fs=b,
            resources={r['name']:window_stat(r,a,b) for r in resources},inflight=profile.between(a,b)))
    # Exact request size grouping and bounded empirical CDF, retaining endpoints.
    grouped = defaultdict(list)
    for t in txns:
        grouped[t['source'],t['command'],t['bytes'],t['status']].append(t['end_resp_tick']-t['begin_tick'])
    size_latency = [dict(source=s,command=c,requested_bytes=n,status=st,**summary(v)) for (s,c,n,st),v in sorted(grouped.items())]
    cdfs = {}
    for s in sorted({t['source'] for t in txns}):
        for cmd in ('R','W'):
            values=sorted(t['end_resp_tick']-t['begin_tick'] for t in txns if t['source']==s and t['command']==cmd and t['status']==1)
            if values:
                indexes=sorted({i*(len(values)-1)//max(1,min(1000,len(values))-1) for i in range(min(1000,len(values)))})
                cdfs[s+'/'+cmd]=[[values[i]/1e6,(bisect_right(values,values[i])/len(values))*100] for i in indexes]
    # Each UID gets an exclusive partition on its latest serviced child's path.
    # Earlier segments/parallel children are INCLUDED in prefix/admission waits;
    # these are not isolated forward-link or DRAM-only times.
    children=defaultdict(list)
    for m in mappings:
        if m['service_tick_fs'] is not None and m['parent_return_tick_fs'] is not None:
            children[m['uid']].append(m)
    timeline=[]
    names=['tlm_admission','prefix_and_prior_segments','backend_admission','dram_queue_and_schedule',
           'dram_data_service','backend_return_wait','response_and_remaining_segments','tlm_response_hold']
    for t in txns:
        if not children[t['uid']]:
            continue
        m=max(children[t['uid']],key=lambda c:(c['service_tick_fs'],c['token']))
        stamps=[t['begin_tick'],t['accepted_tick'],m['parent_accept_tick_fs'],m['submit_tick_fs'],m['issued_tick_fs'],
                m['service_tick_fs'],m['parent_return_tick_fs'],t['axi_done_tick'],t['end_resp_tick']]
        if any(a>b for a,b in zip(stamps,stamps[1:])):
            raise ValueError('noncausal critical child timeline')
        timeline.append(dict(uid=t['uid'],source=t['source'],command=t['command'],requested_bytes=t['bytes'],
                             token=m['token'],burst=m['burst'],total_fs=stamps[-1]-stamps[0],
                             **{name:b-a for name,a,b in zip(names,stamps,stamps[1:])}))
    axi_samples, axi_errors=axi_latencies(axi)
    if axi_errors:
        warnings.extend(axi_errors)
    # Logged TX_FDI is dequeue/first transmission, NOT adapter FIFO enqueue.
    link_samples=[]
    for direction in ('FWD','REV'):
        starts={}
        for r in flits:
            if r['direction']!=direction:
                continue
            seq,tick=r['seq'],int(r['tick_fs'])
            if r['event']=='TX_FDI':
                starts[seq]=tick
            if r['event']=='RX_FDI' and seq in starts:
                link_samples.append(dict(stage='ucie.'+direction+'.logged_fdi_delivery',command=direction,
                                         axi_id=int(seq),tick_fs=tick,latency_fs=tick-starts[seq]))
    protocol_samples=axi_samples+link_samples
    groups=defaultdict(list)
    for r in protocol_samples:
        groups[r['stage']].append(r['latency_fs'])
    stalls=[]
    for ch,v in protocol.get('channels',{}).items():
        cycles=protocol.get('measured_cycles',0)
        stalls.append(dict(module='axi',reason=ch+'_valid_not_ready',fraction=divide(v['stall_cycles'],cycles),
                           cycles=v['stall_cycles'],period_fs=period))
    bq=backend.get('queue_statistics',{})
    for reason,count in bq.get('stall_cycles',{}).items():
        stalls.append(dict(module='ramulator_backend',reason=reason,fraction=divide(count,bq.get('cycles',0)),cycles=count,period_fs=bq.get('period_fs',0)))
    for rp in fabric.get('axi2flit',{}).get('resource_planes',[]):
        for kind,q in rp['queues'].items():
            if 'credit_blocked_cycles' in q:
                stalls.append(dict(module='axi2flit',reason=f"rp{rp['rp']}/{kind}/credit",fraction=divide(q['credit_blocked_cycles'],fabric.get('cycles',0)),cycles=q['credit_blocked_cycles'],period_fs=period))
    public=[{k:v for k,v in r.items() if not k.startswith('_')} for r in resources]
    result=dict(schema='storagestacked.link_diagnostics.v1',resources=public,windows=window_rows,timebins=timebins,
        binning=dict(requested_bin_ns=bin_ns,effective_bin_fs=width,maximum_bins=1000,method='complete event aggregation and interval clipping; no point thinning'),
        link_config=config,capacity_balance=capacity_balance,latency_by_size=size_latency,cdfs=cdfs,
        protocol_latency={k:summary(v) for k,v in groups.items()},protocol_errors=axi_errors,
        critical_child_partition=dict(stages=names,samples=len(timeline),summary={k:summary([r[k] for r in timeline]) for k in names},
            groups=[dict(source=s,command=c,count=len(own),total=summary([r['total_fs'] for r in own]),
                         stages={k:summary([r[k] for r in own]) for k in names})
                    for s,c in sorted({(r['source'],r['command']) for r in timeline})
                    for own in [[r for r in timeline if r['source']==s and r['command']==c]]],
            tail_examples=sorted(timeline,key=lambda r:r['total_fs'],reverse=True)[:50],
            method='latest SERVICE child per UID; exclusive partition, prefix/response include earlier/remaining segments; stage quantiles cannot be added'),
        stalls=stalls,warnings=warnings,
        unavailable=dict(refresh_blocked_time='not instrumented; command count does not identify blocked requests',
            read_write_turnaround_wait='not instrumented; data bus idle time has multiple causes',
            saturated_workload_capacity='use traffic_steady_state windows from env/run_bandwidth_sweep.sh; no whole-link utilization scalar',
            per_uid_stall_cause='global stall counters cannot prove individual request causality'),
        accounting='byte rates count handoff events; utilization uses sampled AXI cycles or clipped modeled busy intervals. Time bins are half-open [a,b), with the final simulation tick included once. Named-window TLM completions use closed END_RESP boundaries to match overall window statistics. Overlapping windows MUST NOT be summed. Event-rate/peak may exceed 1 at short-window boundaries.')
    return result,timeline,protocol_samples,bursts
