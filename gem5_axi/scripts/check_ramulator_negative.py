#!/usr/bin/env python3
"""Prove corruption of byte, completion, timing and energy evidence is rejected."""
import csv
import json
from pathlib import Path
import shutil
import sys
import tempfile
from check_ramulator import check, rows, command_check

source = Path(sys.argv[1])
files = ['ramulator_backend_summary.json','ramulator_native_summary.json','dram_power.json','ramulator_model.json',
         'axi_flit_path.csv','aou_events.csv','ramulator_bridge.csv','ramulator_commands.csv','ramulator_final_image.csv']
files += [p.name for p in source.glob('ramulator_memspec_channel_*.json')]
cases = [
    ('unknown_service','ramulator_bridge.csv',lambda r:r['event']=='service','token',lambda _: '99999999'),
    ('early_response','ramulator_bridge.csv',lambda r:r['event']=='return','tick',lambda _:'0'),
    ('write_mask','ramulator_bridge.csv',lambda r:r['event']=='accept' and r['command']=='W','mask',lambda s:('0' if s[0]=='1' else '1')+s[1:]),
    ('read_snapshot','ramulator_bridge.csv',lambda r:r['event']=='service' and r['command']=='R','data',lambda s:('ff' if s[:2]=='00' else '00')+s[2:]),
    ('command_time','ramulator_commands.csv',lambda r:r['command']=='WR','cycle',lambda s:str(int(s)+1)),
    ('final_image','ramulator_final_image.csv',lambda r:True,'data',lambda s:('ff' if s[:2]=='00' else '00')+s[2:]),
]
result = {}
with tempfile.TemporaryDirectory(prefix='ramulator-negative-') as tmp:
    dst = Path(tmp)
    for name,file,predicate,field,value in cases:
        for f in files: shutil.copyfile(source/f,dst/f)
        data = rows(dst/file); row = next(r for r in data if predicate(r)); row[field] = value(row[field])
        with (dst/file).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=data[0].keys()); w.writeheader(); w.writerows(data)
        try: check(dst)
        except (AssertionError,KeyError,IndexError) as e: result[name]={'rejected':True,'reason':str(e)}
        else: raise AssertionError('Checker accepted corruption: '+name)
    for f in files: shutil.copyfile(source/f,dst/f)
    power=json.loads((dst/'dram_power.json').read_text()); power['total_energy_j'] *= 2
    (dst/'dram_power.json').write_text(json.dumps(power))
    try: check(dst)
    except AssertionError as e: result['double_energy']={'rejected':True,'reason':str(e)}
    else: raise AssertionError('Checker accepted double energy')
# Isolate the timing checker: an RD one tick after its ACT must be rejected
# independently of the bridge/event joins.
commands=rows(source/'ramulator_commands.csv')
models=json.loads((source/'ramulator_model.json').read_text())['controllers']
read=next(c for c in commands if c['command']=='RD')
channel=int(read['channel']); bank=models[channel]['bank_level']
act=next(c for c in reversed(commands[:commands.index(read)]) if c['command']=='ACT' and c['channel']==read['channel'] and all(c[f'level{i}']==read[f'level{i}'] for i in range(bank+1)))
read=dict(read); read['cycle']=str(int(act['cycle'])+1)
try: command_check([act,read],models)
except AssertionError as e: result['illegal_rd_after_act']={'rejected':True,'reason':str(e)}
else: raise AssertionError('Independent timing checker accepted illegal RD')
(source/'ramulator_negative.json').write_text(json.dumps(result,indent=2)+'\n')
print('Ramulator corruption checks PASS:', ', '.join(result))
