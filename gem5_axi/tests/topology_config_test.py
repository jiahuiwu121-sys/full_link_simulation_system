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


for name, count in [('single-hbm4.json', 1), ('dual-ucie-hbm4.json', 2),
                    ('quad-ucie-hbm4.json', 4), ('dual-ucie-lpddr.json', 2)]:
    topology = load(arguments(topology_config=str(ROOT/'configs/topology'/name)))
    assert len(topology['modules']) == count
    assert topology['routing']['policy'] == ('single' if count == 1 else 'address_interleave')
    params = simobject_params(topology)
    assert params['topology_modules'] == count
    assert len(params['ucie_lanes']) == count == len(params['ucie_rates'])

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

print('stage-2 topology config: PASS')
