#!/usr/bin/env python3
"""Compile and execute independent StorageBridge RTL regression benches."""
import argparse,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RTL=ROOT/'storage_bridge/rtl'
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output',type=Path,default=ROOT/'build/storage_bridge-tests')
p.add_argument('--test',action='append',choices=['credit_snapshot','rx_interval','tx_spanning','transaction','response_guard'])
p.add_argument('--width',type=int,default=256,choices=[256,512,1024])
p.add_argument('--planes',type=int,default=1,choices=[1,2,3,4])
p.add_argument('--matrix',action='store_true',help='Run transaction lifecycle for all 3 widths and RP1/2/3/4')
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
cases=a.test or ['credit_snapshot','rx_interval','tx_spanning','transaction','response_guard'];results=[]
plan=[]
for name in cases:
    if name=='transaction' and a.matrix:
        plan += [(name,w,r) for w in (256,512,1024) for r in (1,2,3,4)]
    else: plan.append((name,a.width,a.planes))
for name,width,planes in plan:
    label=f'{name}-w{width}-rp{planes}' if name=='transaction' else name
    out=(a.output/label).resolve();out.mkdir(parents=True,exist_ok=True)
    top=name+'_tb'
    command=['verilator','--binary','--timing','--assert','--unroll-count','512','--top-module',top,
      '--Mdir',str(out/'obj'),'--build-jobs','4','--verilate-jobs','1',
      '-Wno-TIMESCALEMOD','-Wno-PINMISSING',
      '-Wno-WIDTHEXPAND','-Wno-WIDTHTRUNC']
    if name=='transaction': command += [f'-GWIDTH={width}',f'-GPLANES={planes}']
    files=[RTL/x for x in (RTL/'files.f').read_text().splitlines()]
    with (out/'build.log').open('w') as log:
        subprocess.run([*command,*map(str,files),str(ROOT/'storage_bridge/tests'/f'{top}.sv')],stdout=log,stderr=log,check=True)
    with (out/'run.log').open('w') as log:
        subprocess.run([str(out/'obj'/('V'+top))],stdout=log,stderr=log,check=True)
    print(label+': '+(out/'run.log').read_text().strip().splitlines()[-2],flush=True)
    results.append({'test':label,'passed':True,'log':str(out/'run.log')})
(a.output/'summary.json').write_text(json.dumps({'passed':True,'cases':results},indent=2)+'\n')
