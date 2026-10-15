#!/usr/bin/env python3
"""Fast profile compiler acceptance and rejection checks."""
import json
import math
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'env'))
from system_profile import compile_profile

source = ROOT / 'configs/system/llm8b-4axi512-ucie64-hbm3.json'
with tempfile.TemporaryDirectory() as directory:
    output = Path(directory) / 'compiled'
    topology, capacity = compile_profile(source, output)
    assert len(topology['axi_ports']) == 4
    assert len(topology['modules']) == 1
    assert math.isclose(capacity['axi_aggregate_Bps'], 256e9)
    assert math.isclose(capacity['gearbox_output_aggregate_Bps'], 256e9)
    assert capacity['fabric_clock_period_fs'] == 250_000
    assert math.isclose(capacity['ucie_raw_aggregate_Bps'], 256e9)
    assert math.isclose(capacity['ucie_aou_payload_aggregate_Bps'], 250e9)
    assert capacity['memory_capacity_bytes'] == 16 * (1 << 30)
    assert capacity['memory_theoretical_Bps'] == 819.2e9
    assert capacity['bottleneck'] == 'UCIe AoU payload'
    assert (output / 'build.env').is_file()
    assert (output / 'validation_plan.json').is_file()

    invalid = json.loads(source.read_text())
    invalid['bridge']['resource_planes'] = 5
    bad = Path(directory) / 'bad.json'
    bad.write_text(json.dumps(invalid))
    try:
        compile_profile(bad, Path(directory) / 'bad-output')
    except ValueError as error:
        assert 'resource_planes' in str(error)
    else:
        raise AssertionError('invalid resource plane count was accepted')

print('system profile compiler: PASS')
