#!/usr/bin/env python3
"""Fast contract tests for stage-2 topology parsing and address ownership."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'env'))
from topology_config import interleaved_ranges, load, simobject_params


def arguments(**overrides):
    values = dict(topology_config='', topology_modules=None, topology_stripe_bytes=None,
                  ucie_lanes='', ucie_rate_gtps='', ucie_modulation='',
                  axi_data_width=int(os.environ.get('SS_AXI_DATA_WIDTH', '256')))
    values.update(overrides)
    return SimpleNamespace(**values)


def rejected(**overrides):
    try:
        load(arguments(**overrides))
    except ValueError:
        return
    raise AssertionError('invalid topology was accepted: ' + repr(overrides))


class Range:
    def __init__(self, start, size=None, end=None, **kwargs):
        self.start = start
        self.end = start + size - 1 if end is None else end
        self.options = kwargs


original_width = os.environ.get('SS_AXI_DATA_WIDTH')
os.environ['SS_AXI_DATA_WIDTH'] = '256'
for name, count in [('single-hbm3.json', 1), ('single-hbm3e.json', 1),
                    ('single-hbm4.json', 1), ('dual-ucie-hbm4.json', 2),
                    ('quad-ucie-hbm4.json', 4), ('octal-ucie-hbm4.json', 8),
                    ('dual-ucie-lpddr.json', 2), ('dual-ucie-lpddr6.json', 2)]:
    topology = load(arguments(topology_config=str(ROOT/'configs/topology'/name)))
    assert len(topology['modules']) == count
    assert topology['routing']['policy'] == ('single' if count == 1 else 'address_interleave')
    params = simobject_params(topology)
    assert params['topology_modules'] == count
    assert len(params['ucie_lanes']) == count == len(params['ucie_rates'])

lpddr5 = load(arguments(topology_config=str(ROOT/'configs/topology/dual-ucie-lpddr.json')))
lpddr6 = load(arguments(topology_config=str(ROOT/'configs/topology/dual-ucie-lpddr6.json')))
hbm3 = load(arguments(topology_config=str(ROOT/'configs/topology/single-hbm3.json')))
hbm3e = load(arguments(topology_config=str(ROOT/'configs/topology/single-hbm3e.json')))
assert {m['memory']['standard'] for m in hbm3['modules']} == {'HBM3'}
assert {m['memory']['standard'] for m in hbm3e['modules']} == {'HBM3E'}
assert {m['memory']['standard'] for m in lpddr5['modules']} == {'LPDDR5'}
assert {m['memory']['standard'] for m in lpddr6['modules']} == {'LPDDR6'}

os.environ['SS_AXI_DATA_WIDTH'] = '512'
profile = load(arguments(
    topology_config=str(ROOT/'configs/system/llm8b-4axi512-ucie64-hbm3.json'),
    axi_data_width=512))
assert len(profile['axi_ports']) == 4
assert len(profile['modules']) == 1
assert profile['mapping']['axi_port_to_link'] == [0, 0, 0, 0]
params = simobject_params(profile)
assert params['topology_modules'] == 1 and params['topology_ports'] == 4
assert params['axi_port_dividers'] == [4, 4, 4, 4]
assert params['axi_port_phases'] == [0, 1, 2, 3]
ranges = interleaved_ranges(Range, [Range(0x90000000, size=0x10000)], profile)
assert len(ranges) == 4
assert [r[0].options['intlvMatch'] for r in ranges] == [0, 1, 2, 3]
os.environ['SS_AXI_DATA_WIDTH'] = '256'

try:
    for width in (512, 1024):
        os.environ['SS_AXI_DATA_WIDTH'] = str(width)
        wide = load(arguments(
            topology_config=str(ROOT/f'configs/topology/single-hbm4-axi{width}.json'),
            axi_data_width=width))
        assert wide['axi']['data_width_bits'] == width
        assert wide['modules'][0]['ucie']['raw_bandwidth_GBps'] == width / 8 * 1.5
finally:
    os.environ['SS_AXI_DATA_WIDTH'] = '256'

dual = load(arguments(topology_config=str(ROOT/'configs/topology/dual-ucie-hbm4.json')))
ranges = interleaved_ranges(Range, [Range(0x90000000, size=0x10000)], dual)
assert len(ranges) == 2
for module, own in enumerate(ranges):
    assert own[0].options == {'intlvHighBit': 8, 'intlvBits': 1, 'intlvMatch': module}

rejected(topology_modules=3)
rejected(topology_modules=2, topology_stripe_bytes=48)
rejected(topology_modules=2, topology_stripe_bytes=16)
rejected(topology_modules=2, ucie_lanes='16,16,16')
rejected(topology_modules=2, ucie_modulation='NRZ,BAD')

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)/'bad.json'
    path.write_text(json.dumps({'schema':'wrong','module_count':1,'modules':[{}]}))
    rejected(topology_config=str(path))
    path.write_text(json.dumps({'schema':'storagestacked.topology.v1','module_count':2,
                                'modules':[{'name':'same'},{'name':'same'}]}))
    rejected(topology_config=str(path))
    path.write_text(json.dumps({'schema':'storagestacked.topology.v1','module_count':2,
                                'routing':{'policy':'single'},'modules':[{},{}]}))
    rejected(topology_config=str(path))
    for memory in ({'standard':'DDR5'}, {'standard':'LPDDR5','channels':3}):
        path.write_text(json.dumps({'schema':'storagestacked.topology.v1','module_count':1,
                                    'modules':[{'memory':memory}]}))
        rejected(topology_config=str(path))

if original_width is None:
    os.environ.pop('SS_AXI_DATA_WIDTH', None)
else:
    os.environ['SS_AXI_DATA_WIDTH'] = original_width
print('stage-2 topology config: PASS')
