#!/usr/bin/env python3
"""Single source for RTL model parameters, paths and source fingerprints."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PARAMETERS={
    'request_slots':('SS_BRIDGE_REQUEST_SLOTS','REQUEST_SLOTS',4,1,16),
    'max_outstanding':('SS_BRIDGE_MAX_OUTSTANDING','MAX_OUTSTANDING',8,1,64),
    'wdata_granules':('SS_BRIDGE_WDATA_GRANULES','WDATA_GRANULES',64,30,4096),
    'frame_fifo_depth':('SS_BRIDGE_FRAME_FIFO_DEPTH','FRAME_FIFO_DEPTH',2,1,16),
    'tx_flush_cycles':('SS_BRIDGE_TX_FLUSH_CYCLES','TX_FLUSH_CYCLES',2,1,64),
}

def validate(values):
    values=values or {}
    if not isinstance(values,dict): raise ValueError('bridge.rtl must be an object')
    unknown=set(values)-set(PARAMETERS)-{'trace'}
    if unknown: raise ValueError('unknown bridge.rtl options: '+', '.join(sorted(unknown)))
    result={}
    for key,(_,_,default,low,high) in PARAMETERS.items():
        v=values.get(key,default)
        if isinstance(v,bool) or not isinstance(v,int) or not low<=v<=high:
            raise ValueError(f'bridge.rtl.{key} must be an integer in [{low},{high}]')
        result[key]=v
    if not isinstance(values.get('trace',False),bool): raise ValueError('bridge.rtl.trace must be boolean')
    result['trace']=values.get('trace',False)
    return result

def environment(values):
    c=validate(values)
    return {spec[0]:str(c[key]) for key,spec in PARAMETERS.items()}

def from_environment(values=None):
    values=os.environ if values is None else values
    return validate({key:int(values.get(spec[0],spec[2])) for key,spec in PARAMETERS.items()})

def build_directory(width,planes,config):
    c=validate(config)
    return ROOT/'build'/f'storage_bridge-rtl-{width}-rp{planes}-v2-r{c["request_slots"]}-o{c["max_outstanding"]}-w{c["wdata_granules"]}-f{c["frame_fifo_depth"]}-t{c["tx_flush_cycles"]}'

def source_hash():
    paths=[*sorted((ROOT/'storage_bridge/rtl').glob('*')),
           ROOT/'gem5_axi/rtl_aou_target.cc',ROOT/'gem5_axi/rtl_aou_target.hh',
           ROOT/'gem5_axi/storage_bridge.cc',ROOT/'gem5_axi/storage_bridge.hh',
           ROOT/'env/build_storage_bridge_rtl.sh',Path(__file__),
           ROOT/'protocol/include/aou_format6.h']
    digest=hashlib.sha256()
    for p in paths:
        if p.is_file():
            digest.update(str(p.relative_to(ROOT)).encode()+b'\0'+p.read_bytes()+b'\0')
    return digest.hexdigest()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir',action='store_true')
    parser.add_argument('--verilator-args',action='store_true')
    parser.add_argument('--hash',action='store_true')
    a=parser.parse_args();c=from_environment()
    if a.build_dir: print(build_directory(os.environ.get('SS_AXI_DATA_WIDTH','256'),os.environ.get('SS_RESOURCE_PLANES','1'),c))
    elif a.verilator_args:
        for key,(_,parameter,*_) in PARAMETERS.items(): print(f'-G{parameter}={c[key]}')
    elif a.hash: print(source_hash())
    else: print(json.dumps(c,indent=2))
