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
    expected = {'HBM4': 'HBM34', 'LPDDR5': 'LPDDR5', 'LPDDR6': 'LPDDR6'}
    for standard, controller_implementation in expected.items():
        case = root / standard.lower()
        path = Path(generate_config(case, channels=2, queue=8, standard=standard))
        config = json.loads(path.read_text())
        metadata = json.loads((case / 'ramulator_config_metadata.json').read_text())
        controllers = config['memory_system']['controllers']
        assert config['frontend']['impl'] == 'External'
        assert config['frontend']['clock_ratio'] == 1
        assert len(controllers) == 2
        assert metadata['standard'] == standard
        assert all(c['impl'] == controller_implementation for c in controllers)
        assert all(c['dram']['impl'] == standard for c in controllers)
        assert metadata['power'] is True
        assert metadata['transaction_bytes'] > 0

    try:
        generate_config(root / 'bad-scale', standard='LPDDR5', clock_scale=2)
    except ValueError:
        pass
    else:
        raise AssertionError('unsupported LPDDR clock scaling was accepted')

print('Ramulator External standard generation: PASS')
