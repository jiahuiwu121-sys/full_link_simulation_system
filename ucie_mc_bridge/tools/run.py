#!/usr/bin/env python3
"""Build/test the independent MC HIF bridge; never compiles storage_bridge/rtl."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo
from reports import publish_case, publish_index

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
LIMITS = {
    'RESOURCE_PLANES':(1,4),'REQUEST_SLOTS':(1,16),'CHILD_SLOTS':(1,256),
    'MAX_BURST_BYTES':(32,4096),'WDATA_GRANULES':(8,4096),'TX_FLUSH_CYCLES':(1,64),
    'INITIAL_LPR':(0,65535),'INITIAL_HPR':(0,65535),'INITIAL_WR':(0,65535),
    'POSTED_WRITE_ACK':(0,1),'TWO_WORD_COMMANDS':(0,1),'LENGTH_ONE':(0,1),'LENGTH_TWO':(0,1),
    'MASK_ONE_WRITES':(0,1),'HPR_CODE':(1,2),'COMMAND_LATENCY':(0,2047),'AUTO_PRECHARGE':(0,1),
}
WAVEFORM_PARAMETERS = {
    'RESOURCE_PLANES':1,'REQUEST_SLOTS':4,'CHILD_SLOTS':32,'MAX_BURST_BYTES':4096,
    'WDATA_GRANULES':64,'TX_FLUSH_CYCLES':2,'INITIAL_LPR':24,'INITIAL_HPR':8,'INITIAL_WR':32,
    'POSTED_WRITE_ACK':0,'TWO_WORD_COMMANDS':1,'LENGTH_ONE':0,'LENGTH_TWO':1,
    'MASK_ONE_WRITES':1,'HPR_CODE':2,'COMMAND_LATENCY':0,'AUTO_PRECHARGE':0,
}

def configuration(path):
    config=json.loads(path.read_text())
    if config.get('schema')!='ucie-mc-bridge.rtl-config.v1' or config.get('contract_profile')!='waveform-demo':
        raise ValueError('unsupported MC bridge configuration schema/contract')
    values=config.get('parameters',{})
    if set(values)!=set(LIMITS):
        raise ValueError('RTL parameters must exactly match supported parameter names')
    for name,(low,high) in LIMITS.items():
        value=values[name]
        if type(value) is not int or not low<=value<=high:
            raise ValueError(f'{name} must be an integer in [{low},{high}]')
    if 2*values['RESOURCE_PLANES']*values['REQUEST_SLOTS']>64:
        raise ValueError('parent count must not exceed 64')
    if values['MAX_BURST_BYTES']%32 or values['LENGTH_ONE']==values['LENGTH_TWO']:
        raise ValueError('invalid memory size/length encoding')
    return values

def run(argv, log=None):
    result = subprocess.run([str(x) for x in argv], cwd=ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if log:
        log.write_text(result.stdout)
    if result.returncode:
        print(result.stdout[-16000:], file=sys.stderr)
        raise RuntimeError(f'command failed ({result.returncode}): {argv[0]}')
    return result.stdout

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--lint', action='store_true')
    ap.add_argument('--build-only', action='store_true')
    ap.add_argument('--planes', type=int, choices=[1, 2, 3, 4])
    ap.add_argument('--rtl-config', type=Path, help='production RTL parameter file; custom parameters require --build-only/--lint')
    ap.add_argument('--posted-ack', type=int, choices=[0, 1], default=None,
                    help='test model contract only; production RTL defaults to 0')
    ap.add_argument('--case', type=int, action='append', dest='cases')
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    defaults=configuration(PROJECT/'profiles/default-rtl.json')
    parameters=configuration(args.rtl_config.resolve()) if args.rtl_config else defaults.copy()
    if args.planes is None:
        args.planes=parameters['RESOURCE_PLANES']
    parameters['RESOURCE_PLANES']=args.planes
    if args.posted_ack is None:
        args.posted_ack = parameters['POSTED_WRITE_ACK'] if args.build_only or args.lint else 1
    parameters['POSTED_WRITE_ACK']=args.posted_ack
    if 2*args.planes*parameters['REQUEST_SLOTS']>64:
        raise ValueError('parent count must not exceed 64')
    if not args.build_only and not args.lint:
        changed={k for k in parameters if parameters[k]!=WAVEFORM_PARAMETERS[k]}-{'RESOURCE_PLANES','POSTED_WRITE_ACK'}
        if changed:
            raise ValueError('waveform regression uses fixed model geometry; custom parameters require --build-only/--lint: '+','.join(sorted(changed)))
    parameter_flags=[f'-G{k}={v}' for k,v in parameters.items()]
    rtl = [PROJECT / 'rtl' / s.strip() for s in (PROJECT/'rtl/files.f').read_text().splitlines() if s.strip()]
    if any('storage_bridge/rtl/' in str(p.relative_to(ROOT)) for p in rtl):
        raise ValueError('independent bridge must not reference old RTL')
    flags = ['verilator', '--assert', '--timescale', '1ns/1fs', '--unroll-count', '512',
             '-Wall', '-Wno-DECLFILENAME', '-Wno-PINCONNECTEMPTY', '-Wno-PINMISSING',
             '-Wno-UNUSEDSIGNAL', '-Wno-UNUSEDPARAM', '-Wno-WIDTH', '-Wno-TIMESCALEMOD']
    if args.lint:
        run(flags + ['--lint-only', '--top-module', 'ucie_mc_bridge_top',
                     *parameter_flags] + rtl)
        print('ucie_mc_bridge: independent RTL lint PASS')
        return
    tb = sorted((PROJECT/'tb').glob('*.sv'))
    version = run(['verilator', '--version']).strip()
    fingerprint = hashlib.sha256((version + f'RP={args.planes},ACK={args.posted_ack}').encode())
    fingerprint.update(json.dumps(parameters,sort_keys=True).encode())
    fingerprint.update(b'assert=1;timescale=1ns/1fs;trace=1;trace-max-array=64;unroll=512')
    for p in rtl + ([] if args.build_only else tb):
        fingerprint.update(str(p.relative_to(ROOT)).encode()+b'\0'+p.read_bytes())
    fingerprint.update(b'library' if args.build_only else b'testbench')
    digest = fingerprint.hexdigest()
    build = ROOT / 'build' / f'ucie-mc-bridge-rp{args.planes}-ack{args.posted_ack}-{digest[:12]}'
    build.mkdir(parents=True, exist_ok=True)
    binary = build/'Vmc_bridge_tb'
    if args.build_only:
        archive = build/'Vucie_mc_bridge_top__ALL.a'
        if not archive.exists():
            run(flags + ['--cc', '--build', '--trace', '--trace-max-array', '64',
                         '-j', os.environ.get('AXI_JOBS', '4'), '--Mdir', build,
                         '--top-module', 'ucie_mc_bridge_top', *parameter_flags] + rtl, build/'build.log')
        (build/'manifest.json').write_text(json.dumps({'schema':'ucie-mc-bridge.library.v1',
            'source_sha256':digest,'verilator':version,'resource_planes':args.planes,
            'posted_write_ack':bool(args.posted_ack),'parameters':parameters,'top':'ucie_mc_bridge_top',
            'sources':[str(p.relative_to(ROOT)) for p in rtl],
            'real_mc_verified':False},indent=2)+'\n')
        print(archive)
        return
    if not binary.exists():
        print(f'Building independent MC bridge: {build.name}', flush=True)
        run(flags + ['-Wno-BLKSEQ', '-Wno-SYNCASYNCNET', '--binary', '--timing', '--trace', '--trace-max-array', '64',
                     '-j', os.environ.get('AXI_JOBS', '4'), '--Mdir', build,
                     '--top-module', 'mc_bridge_tb', f'-GPLANES={args.planes}',
                     f'-GACK={args.posted_ack}'] + rtl + tb, build/'build.log')
    (build/'manifest.json').write_text(json.dumps({'schema':'ucie-mc-bridge.build.v1',
        'source_sha256':digest,'verilator':version,'resource_planes':args.planes,
        'posted_ack_test_contract':bool(args.posted_ack),
        'sources':[str(p.relative_to(ROOT)) for p in rtl+tb]},indent=2)+'\n')
    if args.output:
        output = args.output.resolve()
        output.mkdir(parents=True, exist_ok=False)
    else:
        stamp = dt.datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')
        index = 1
        while True:
            output = ROOT/'results'/f'{stamp}-mc-hif-rp{args.planes}-ack{args.posted_ack}-r{index:02d}'
            try:
                output.mkdir(parents=True, exist_ok=False)
                break
            except FileExistsError:
                index += 1
    cases = args.cases if args.cases is not None else list(range(17))+[100] if args.posted_ack else [6]
    reports=[]
    for case in cases:
        directory = output/f'case{case:02d}'
        directory.mkdir()
        selected_binary=binary
        if case==100:
            unit_build=build/'tx-unit'
            unit_build.mkdir(exist_ok=True)
            selected_binary=unit_build/'Vtx_span_tb'
            if not selected_binary.exists():
                run(flags + ['-Wno-BLKSEQ','-Wno-SYNCASYNCNET','--binary','--timing','--trace',
                             '--Mdir',unit_build,'--top-module','tx_span_tb','-j',os.environ.get('AXI_JOBS','4'),
                             PROJECT/'rtl/umcb_pkg.sv',PROJECT/'rtl/umcb_fdi_tx.sv',PROJECT/'tb/tx_span_tb.sv'],
                    unit_build/'build.log')
        stdout = run([selected_binary, f'+CASE={case}', f'+OUT={directory}'], directory/'simulation.log')
        if 'TEST_PASS' not in stdout:
            raise RuntimeError(f'case {case}: missing success marker')
        report=json.loads((directory/'summary.json').read_text())
        report['case']=case
        publish_case(directory,report)
        reports.append(report)
        print(f'case {case}: PASS', flush=True)
    result={'schema':'ucie-mc-bridge.validation.v1','status':'mock_verified',
            'real_mc_verified':False,'contract_profile':'waveform-demo',
            'resource_planes':args.planes,'posted_write_ack':bool(args.posted_ack),
            'source_sha256':digest,'cases':reports}
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    config=json.loads((PROJECT/'profiles/waveform-demo.json').read_text())
    config['actual_test_parameters']={'resource_planes':args.planes,'posted_write_ack':bool(args.posted_ack),
        'request_slots_per_rp_direction':4,'child_slots':32,'max_burst_bytes':4096,
        'wdata_granules_per_rp':64,'tx_flush_cycles':8,'clock_period_fs':10000000,'time_resolution_fs':1}
    (output/'configuration.json').write_text(json.dumps(config,indent=2)+'\n')
    publish_index(output,result)
    print(f'Results: {output}')

if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError) as exc:
        sys.exit(str(exc))
