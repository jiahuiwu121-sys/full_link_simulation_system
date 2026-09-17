#!/usr/bin/env python3
"""Acceptance gates for the real online Ramulator2 chain and CPU feedback."""
import csv
import json
from pathlib import Path
import re
import sys
from native_tests import passed_count
from hettrace.reader import CHAN_R, CHAN_W, read_header, read_records
from hettrace.validate import format_report, validate_dir

root = Path(sys.argv[1])
def read(p): return json.loads(p.read_text())
def rows(p):
    with p.open() as f: return list(csv.DictReader(f))
def finish(p): return int(re.findall(r'EXIT: .* tick (\d+)',(p/'run.log').read_text())[-1])
def insts(p): return int(re.search(r'^simInsts\s+(\d+)',(p/'stats.txt').read_text(),re.M)[1])

native_count = passed_count(root, 'ramulator2')
api = read(root/'api/api_check.json'); assert api['passed'] and api['power_transparent'] and api['high_address_no_alias']
cases = {}
for name in ('directed','replay','shallow','held','period_3ns','power_off','cpu','cpu_slow'):
    p = root/name
    checks = {key:read(p/(key+'.json')) for key in ('check_summary','aou_check_summary','ramulator_check','ramulator_native_summary')}
    assert all(c['passed'] for c in checks.values())
    issues,summaries = validate_dir(str(p/'hettrace'),require_heterogeneous=False,ticks_per_second=10**15)
    (p/'hettrace/validation.txt').write_text(format_report(issues,summaries)+'\n')
    assert not [i for i in issues if i.level == 'ERROR']
    assert read_header(str(p/'hettrace/host.hettrace')).ticks_per_second == 10**15
    records = list(read_records(str(p/'hettrace/host.hettrace'))); tx = rows(p/'transactions.csv')
    for ch,cmd in ((CHAN_R,'R'),(CHAN_W,'W')):
        assert sum(r.size for r in records if r.chan == ch) == sum(int(t['bytes']) for t in tx if t['command'] == cmd)
    assert max(r.tick for r in records) <= finish(p)
    if name.startswith('cpu'):
        assert 'CPU RAMULATOR PASS checksum=24416 boundary64=ok' in (p/'run.log').read_text()
        assert len(tx) == 452 and insts(p) > 0
    cases[name] = {'exit_tick_fs':finish(p),'transactions':len(tx),**checks}
assert cases['shallow']['ramulator_check']['submit_stalls'] > 0
assert cases['held']['ramulator_check']['response_stalls'] > 0
assert cases['replay']['aou_check_summary']['crc_errors'] > 0
for file in ('axi_events.csv','transactions.csv','aou_events.csv','ramulator_commands.csv','ramulator_bridge.csv','ramulator_final_image.csv','ucie_soc.csv','ucie_mem.csv'):
    assert (root/'directed'/file).read_bytes() == (root/'power_off'/file).read_bytes(), 'power changed behavior: '+file
assert finish(root/'directed') == finish(root/'power_off')
fast,slow = root/'cpu',root/'cpu_slow'
a,b = rows(fast/'transactions.csv'),rows(slow/'transactions.csv')
assert insts(fast) == insts(slow) and len(a) == len(b)
assert read(slow/'ramulator_native_summary.json')['period_fs'] == 4 * read(fast/'ramulator_native_summary.json')['period_fs']
for x,y in zip(a,b): assert all(x[k] == y[k] for k in ('command','address','bytes','status'))
finish_delta = finish(slow) - finish(fast); assert finish_delta > 0
negative = read(root/'directed/ramulator_negative.json'); assert len(negative) >= 7 and all(v['rejected'] for v in negative.values())
wave = read(root/'wave_audit/summary.json'); assert len(wave) == 8 and all(v['passed'] for v in wave.values())
result = {'passed':True,'scope':'X86/native TLM/AXI256/AXI2Flit/UCIe/AouTarget/Ramulator2/backing/DRAMPower',
          'native_tests_passed':native_count,'api_check':api,'cases':cases,'negative_checks':negative,
          'cpu_feedback':{'passed':True,'clock_scale':4,'finish_delta_ns':finish_delta/1e6},
          'power_transparency':True,
          'limitations':['Estimated DRAM power; no XPU/UCIe/controller-logic power',
                         'Command-level DRAM model; no DFI pin waveform',
                         'Same-transaction requests serialized; parent FIFO response order',
                         'No general atomic/functional/checkpoint/cache-coherence support']}
(root/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'passed':True,'cases':list(cases),'cpu_feedback':result['cpu_feedback']},indent=2))
