#!/usr/bin/env python3
"""Validated protocol profiles shared by configuration, build and reporting."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


PROFILES = {
    'aou-format6-256': {
        'axi_address_width_bits': 64,
        'axi_id_width_bits': 16,
        'routed_axi_id_bits': 10,
        'aou_frame_bytes': 256,
        'aou_payload_bytes': 250,
        'max_resource_planes': 4,
        'format_header': 'protocol/include/aou_format6.h',
        'description': 'Current AoU format-6 scatter/gather and CRC layout.',
    },
}


def resolve(section):
    if section is None:
        section = {}
    if not isinstance(section, dict):
        raise ValueError('protocol must be an object')
    name = section.get('profile', 'aou-format6-256')
    if name not in PROFILES:
        raise ValueError('protocol.profile must be one of ' + ', '.join(PROFILES))
    resolved = {'schema': 'storagestacked.protocol-profile.v1', 'profile': name,
                **PROFILES[name]}
    fixed = {
        'axi_address_width_bits': resolved['axi_address_width_bits'],
        'axi_id_width_bits': resolved['axi_id_width_bits'],
        'aou_frame_bytes': resolved['aou_frame_bytes'],
        'aou_payload_bytes': resolved['aou_payload_bytes'],
    }
    for key, expected in fixed.items():
        value = section.get(key, expected)
        if isinstance(value, bool) or not isinstance(value, int) or value != expected:
            raise ValueError(f'protocol {name} requires {key}={expected}')
        resolved[key] = value
    for key, default in (('fdi_fifo_depth', 8), ('memory_fifo_depth', 4)):
        value = section.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f'protocol.{key} must be an integer >= 1')
        resolved[key] = value
    return resolved


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=sorted(PROFILES), default='aou-format6-256')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    document = resolve({'profile': args.profile})
    text = json.dumps(document, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        print(text, end='')
