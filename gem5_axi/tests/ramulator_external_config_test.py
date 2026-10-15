#!/usr/bin/env python3
"""Check generated External configs cannot silently change memory standard."""
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'env'))
from generate_ramulator_config import generate_config


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    expected = {
        'HBM3': ('HBM34', 'HBM3', 'HBM3_16Gb_8hi', 'HBM3_6400Mbps', 6400, 312500),
        'HBM3E': ('HBM34', 'HBM3', 'HBM3E_24Gb_8Hi', 'HBM3E_8000Mbps', 8000, 250000),
        'HBM4': ('HBM34', 'HBM4', 'HBM4_32Gb_8Hi', 'HBM4_8000Mbps', 8000, 250000),
        'LPDDR5': ('LPDDR5', 'LPDDR5', 'LPDDR5_16Gb_x16', 'LPDDR5_6400', 6400, 1250000),
        'LPDDR6': ('LPDDR6', 'LPDDR6', 'LPDDR6_16Gb_x12', 'LPDDR6_10667_BL24', 10667, 375000),
    }
    for standard, (controller_implementation, dram_implementation,
                   organization_preset, timing_preset, data_rate_mbps,
                   tick_fs) in expected.items():
        case = root / standard.lower()
        path = Path(generate_config(case, channels=2, queue=8, standard=standard))
        config = json.loads(path.read_text())
        metadata = json.loads((case / 'ramulator_config_metadata.json').read_text())
        controllers = config['memory_system']['controllers']
        assert config['frontend']['impl'] == 'External'
        assert config['frontend']['clock_ratio'] == 1
        assert len(controllers) == 2
        assert metadata['standard'] == standard
        assert metadata['dram_implementation'] == dram_implementation
        assert metadata['organization_preset'] == organization_preset
        assert metadata['timing_preset'] == timing_preset
        assert metadata['data_rate_mbps'] == data_rate_mbps
        assert metadata['tick_fs'] == tick_fs
        assert all(c['impl'] == controller_implementation for c in controllers)
        assert all(c['dram']['impl'] == dram_implementation for c in controllers)
        assert all(c['dram']['tick_fs'] == tick_fs for c in controllers)
        assert metadata['power'] is True
        assert metadata['transaction_bytes'] > 0
        memspec = json.loads(next(case.glob('*_memspec.json')).read_text())
        assert memspec['memoryType'] == dram_implementation
        assert memspec['generatedFrom']['orgPreset'] == organization_preset
        assert memspec['generatedFrom']['timingPreset'] == timing_preset

    try:
        generate_config(root / 'bad-scale', standard='LPDDR5', clock_scale=2)
    except ValueError:
        pass
    else:
        raise AssertionError('unsupported LPDDR clock scaling was accepted')

    for standard in ('HBM3', 'HBM3E'):
        try:
            generate_config(root / f'bad-{standard.lower()}-scale',
                            standard=standard, clock_scale=2)
        except ValueError:
            pass
        else:
            raise AssertionError(f'unsupported {standard} clock scaling was accepted')

print('Ramulator External standard generation: PASS')
