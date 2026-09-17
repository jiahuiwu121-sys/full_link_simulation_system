#!/usr/bin/env python3
"""Independent byte/causality, issued-command timing and energy checks."""
import argparse
from collections import Counter, defaultdict, deque
import csv
import itertools
import json
import math
from pathlib import Path


def rows(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def command_check(commands, models):
    histories = defaultdict(list)
    opened = {}
    comparisons = 0
    previous = -1
    for c in commands:
        channel, cycle = int(c['channel']), int(c['cycle'])
        assert cycle >= previous, 'command cycle regressed'
        previous = cycle
        model = models[channel]
        command = model['commands'].index(c['command'])
        bank, row = model['bank_level'], model['row_level']
        coords = [int(c[f'level{i}']) for i in range(len(model['levels']))]
        assert coords[0] == channel
        for level in range(1, bank + 1):
            assert -1 <= coords[level] < model['organization'][level]

        def targets(level):
            return list(itertools.product(*[
                [coords[i]] if coords[i] != -1 else range(model['organization'][i])
                for i in range(level + 1)]))

        # Compare current commands against prior issue histories. This checker
        # has no access to DRAMNode's ready clocks or controller decisions.
        for level, preceding, following, latency, window, sibling in model['constraints']:
            if following != command or level > bank:
                continue
            assert window >= 1
            for node in targets(level):
                if sibling:
                    siblings = [node[:-1] + (i,) for i in range(model['organization'][level]) if i != node[-1]]
                    for other in siblings:
                        history = histories[channel, level, other, preceding]
                        if history:
                            comparisons += 1
                            assert cycle - history[-1] >= latency, 'sibling timing constraint violated'
                else:
                    history = histories[channel, level, node, preceding]
                    if len(history) >= window:
                        comparisons += 1
                        assert cycle - history[-window] >= latency, f'{c["command"]} timing constraint violated at level {level}'
        banks = targets(bank)
        name = c['command']
        if name == 'ACT':
            assert coords[row] >= 0
            for node in banks:
                assert (channel,node) not in opened, 'ACT to opened bank'
                opened[channel,node] = coords[row]
        elif name.startswith('PRE'):
            for node in banks:
                opened.pop((channel,node), None)
        elif name in ('RD','WR','RDA','WRA'):
            for node in banks:
                assert opened.get((channel,node)) == coords[row], 'access to wrong/closed row'
            if name in ('RDA','WRA'):
                for node in banks:
                    opened.pop((channel,node), None)
        elif name.startswith(('REF','RFM')):
            assert all((channel,node) not in opened for node in banks), 'maintenance to opened bank'
        for level in range(bank + 1):
            for node in targets(level):
                histories[channel,level,node,command].append(cycle)
    return comparisons


def check(directory):
    directory = Path(directory)
    bridge = json.loads((directory/'ramulator_backend_summary.json').read_text())
    native = json.loads((directory/'ramulator_native_summary.json').read_text())
    power = json.loads((directory/'dram_power.json').read_text())
    models = json.loads((directory/'ramulator_model.json').read_text())['controllers']
    base, size, period, granule = bridge['base'], bridge['size'], native['period_fs'], native['transaction_bytes']
    assert bridge['passed'] and bridge['drained'] and native['passed'] and native['drained']
    assert bridge['period_fs'] == period and size <= native['capacity_bytes']
    assert bridge['native_end_tick_fs'] == native['cycles'] * period
    assert 0 <= bridge['simulation_end_tick_fs'] - bridge['native_end_tick_fs'] < period
    paths = {(r['channel'],r['axi_id'],r['axi_tick_fs']):r for r in rows(directory/'axi_flit_path.csv')}
    bus = rows(directory/'aou_events.csv')
    by_ch = {ch:[r for r in bus if r['channel'] == ch] for ch in ('AW','W','B','AR','R')}
    replies = {ch:defaultdict(deque) for ch in ('B','R')}
    for ch in replies:
        for r in by_ch[ch]: replies[ch][r['id']].append(r)
    requests = defaultdict(deque)
    writes = iter(by_ch['W'])
    for ch in ('AW','AR'):
        for a in by_ch[ch]:
            width, beats = 1 << int(a['size']), int(a['len']) + 1
            data, mask, returned = bytearray(), [], bytearray()
            forward = [paths[ch,a['id'],a['tick']]]; reverse = []
            for beat in range(beats):
                lane = (int(a['address']) + beat*width) % 32
                if ch == 'AW':
                    w = next(writes)
                    data.extend(int(w['data_hex'],16).to_bytes(32,'little')[lane:lane+width])
                    mask.extend(str((int(w['strb_hex'],16) >> (lane+j)) & 1) for j in range(width))
                    forward.append(paths['W',a['id'],w['tick']])
                else:
                    r = replies['R'][a['id']].popleft()
                    returned.extend(int(r['data_hex'],16).to_bytes(32,'little')[lane:lane+width])
                    reverse.append(paths['R',a['id'],r['tick']])
            if ch == 'AW':
                r = replies['B'][a['id']].popleft(); reverse.append(paths['B',a['id'],r['tick']])
            requests['W' if ch == 'AW' else 'R',a['id'],a['address'],str(width*beats)].append(
                dict(data=data.hex(),mask=''.join(mask),returned=returned.hex(),status=int(r['resp']),forward=forward,reverse=reverse))
    assert next(writes,None) is None and all(not q for queues in replies.values() for q in queues.values())
    events = rows(directory/'ramulator_bridge.csv')
    groups, children, services = defaultdict(list), {}, {}
    for e in events:
        assert int(e['tick']) % period == 0
        groups[e['burst']].append(e)
        if e['event'] in ('submit','service'):
            table = children if e['event'] == 'submit' else services
            assert e['token'] not in table, 'duplicate submission/service'
            table[e['token']] = e
    assert children.keys() == services.keys(), 'missing/orphan data service'
    assert len(children) == bridge['submitted'] == bridge['services'] == native['submitted'] == native['serviced']
    assert len(groups) == bridge['bursts']
    commands = rows(directory/'ramulator_commands.csv')
    assert len(commands) == native['commands']
    physical = defaultdict(list)
    for c in commands:
        assert int(c['tick']) == int(c['cycle']) * period
        if c['command'] in ('RD','WR','RDA','WRA'): physical[c['token']].append(c)
    assert physical.keys() == children.keys(), 'unaccounted actual DRAM access'
    for token,s in children.items():
        e = services[token]; assert len(physical[token]) == 1
        c = physical[token][0]
        assert c['command'] == ('WR' if s['command'] == 'W' else 'RD')
        relative = int(s['address']) - base
        assert int(c['address']) == relative - relative % granule
        assert all(s[k] == e[k] for k in ('burst','address','bytes','offset','command'))
        assert int(s['tick']) < int(c['tick']) < int(e['tick'])
        assert int(e['issued_cycle']) == int(c['cycle'])
        assert int(e['completion_cycle']) == int(e['issued_cycle']) + native['write_latency' if s['command'] == 'W' else 'read_latency']
        assert int(e['tick']) == int(e['completion_cycle']) * period
    errors = 0
    for group in groups.values():
        accepts = [e for e in group if e['event'] == 'accept']; returns = [e for e in group if e['event'] == 'return']
        assert len(accepts) == len(returns) == 1
        a,r = accepts[0],returns[0]
        req = requests[a['command'],a['axi_id'],a['address'],a['bytes']].popleft()
        assert a['data'] == req['data'] and a['mask'] == req['mask'], 'AXI/backing input differs'
        assert int(a['tick']) >= max(int(p['rx_last_tick_fs']) for p in req['forward'])
        assert int(r['tick']) <= min(int(p['tx_first_tick_fs']) for p in req['reverse'])
        assert int(r['status']) == req['status'] and r['data'] == req['returned']
        submitted = sorted([s for s in group if s['event'] == 'submit'], key=lambda s:int(s['offset']))
        offset = 0; read_data = bytearray()
        for s in submitted:
            n,addr = int(s['bytes']),int(s['address'])
            assert int(s['offset']) == offset and addr == int(a['address']) + offset
            assert 0 < n <= granule and addr//granule == (addr+n-1)//granule
            assert int(a['tick']) <= int(s['tick']) and int(services[s['token']]['tick']) <= int(r['tick'])
            if a['command'] == 'W':
                assert s['data'] == a['data'][offset*2:(offset+n)*2] and s['mask'] == a['mask'][offset:offset+n]
                assert services[s['token']]['data'] == s['data'] and services[s['token']]['mask'] == s['mask']
            else: read_data.extend(bytes.fromhex(services[s['token']]['data']))
            offset += n
        if int(a['status']):
            errors += 1; assert not submitted
        else:
            assert offset == int(a['bytes'])
            if a['command'] == 'R': assert read_data.hex() == r['data']
        for s in group:
            if s['event'] == 'submit_stall':
                accepted = children[s['token']]
                assert all(s[k] == accepted[k] for k in ('burst','address','bytes','offset'))
                assert int(s['tick']) < int(accepted['tick'])
    assert errors == bridge['errors'] and all(not q for q in requests.values())
    # Independent byte reference follows actual service order. Every write's
    # bytes/mask have already been proven to originate at AXI, not backing code.
    image = defaultdict(int)
    for e in events:
        if e['event'] != 'service': continue
        addr,data = int(e['address']),bytes.fromhex(e['data'])
        assert len(data) == int(e['bytes']) and base <= addr and addr+len(data) <= base+size
        if e['command'] == 'W':
            for j,value in enumerate(data):
                if e['mask'][j] == '1': image[addr+j] = value
        else:
            assert data == bytes(image[addr+j] for j in range(len(data))), 'read snapshot disagrees with independent byte reference'
    actual = {}; covered = set()
    for r in rows(directory/'ramulator_final_image.csv'):
        addr,data = int(r['address']),bytes.fromhex(r['data'])
        assert base <= addr and addr+len(data) <= base+size
        assert not covered.intersection(range(addr,addr+len(data)))
        covered.update(range(addr,addr+len(data))); actual.update((addr+j,value) for j,value in enumerate(data))
    assert all(actual.get(a,0) == b for a,b in image.items()) and all(image.get(a,0) == b for a,b in actual.items())
    timing = command_check(commands,models)
    duration = native['cycles'] * period * 1e-15
    assert power['passed'] and math.isclose(power['duration_seconds'],duration,rel_tol=1e-10,abs_tol=1e-18)
    for c in power['channels']:
        for key,value in c.items():
            if key.endswith('_j'): assert math.isfinite(value) and value >= 0
        assert math.isclose(c['total_energy_j'],c['core_energy_j']+c['interface_energy_j'],rel_tol=1e-10,abs_tol=1e-20)
        if c['enabled']:
            assert math.isclose(c['duration_seconds'],duration,rel_tol=1e-10,abs_tol=1e-18)
            assert c['mapped_commands'] == sum(int(r['channel']) == c['channel'] for r in commands)
            assert c['unsupported_commands'] == 0
            spec = json.loads((directory/f'ramulator_memspec_channel_{c["channel"]}.json').read_text())
            if models[c['channel']]['standard'] in ('HBM3','HBM4'):
                timing_spec = spec['memtimingspec']
                assert math.isclose(timing_spec['tCK']/timing_spec['ticksPerCK'],period*1e-15,rel_tol=1e-8)
                architecture = spec['memarchitecturespec']
                model = models[c['channel']]
                for name,key in [('PseudoChannel','nbrOfPseudoChannels'),('Sid','nbrOfSIDs'),
                                 ('BankGroup','nbrOfBankGroups'),('Bank','nbrOfBanksPerGroup'),
                                 ('Row','nbrOfRows'),('Column','nbrOfColumns')]:
                    assert architecture[key] == model['organization'][model['levels'].index(name)], 'power/model organization mismatch'
    for key in ('core_energy_j','interface_energy_j','total_energy_j'):
        assert math.isclose(power[key],sum(c[key] for c in power['channels']),rel_tol=1e-10,abs_tol=1e-20)
    assert math.isclose(power['average_power_w'],power['total_energy_j']/duration,rel_tol=1e-10,abs_tol=1e-20)
    result = dict(passed=True,bursts=len(groups),children=len(children),errors=errors,image_bytes=len(covered),
                  commands=dict(Counter(c['command'] for c in commands)),timing_comparisons=timing,
                  submit_stalls=bridge['submit_stalls'],response_stalls=bridge['response_stalls'],
                  period_fs=period,total_energy_j=power['total_energy_j'],average_power_w=power['average_power_w'])
    (directory/'ramulator_check.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('directory',type=Path)
    print(json.dumps(check(p.parse_args().directory),indent=2))
