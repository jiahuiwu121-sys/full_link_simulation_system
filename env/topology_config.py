#!/usr/bin/env python3
"""Load and validate the stage-2 AXI/UCIe/memory topology description."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path


def add_options(parser):
    parser.add_argument('--topology-config', default='',
                        help='JSON topology file; command-line values override its defaults')
    parser.add_argument('--topology-modules', type=int, default=None,
                        help='Number of parallel AXI/UCIe/Ramulator paths')
    parser.add_argument('--topology-stripe-bytes', type=lambda x: int(x, 0), default=None,
                        help='Power-of-two address stripe used between modules')
    parser.add_argument('--ucie-lanes', default='',
                        help='Comma separated lane counts; one value broadcasts')
    parser.add_argument('--ucie-rate-gtps', default='',
                        help='Comma separated per-lane rates; one value broadcasts')
    parser.add_argument('--ucie-modulation', default='',
                        help='Comma separated NRZ/PAM4 values; one value broadcasts')
    parser.add_argument('--axi-data-width', type=int,
                        default=int(os.environ.get('SS_AXI_DATA_WIDTH', '256')),
                        choices=(256, 512, 1024),
                        help='Must match SS_AXI_DATA_WIDTH used by env/build.sh')


def _csv(value, cast):
    return [cast(x.strip()) for x in value.split(',') if x.strip()]


def _broadcast(values, count, name):
    if len(values) == 1:
        return values * count
    if len(values) != count:
        raise ValueError(f'{name} must contain one value or {count} values')
    return values


def load(args):
    raw = {}
    source = 'command-line defaults'
    if args.topology_config:
        path = Path(args.topology_config).resolve()
        if not path.is_file():
            raise ValueError('missing topology config: ' + str(path))
        raw = json.loads(path.read_text())
        source = str(path)
        source_dir = path.parent
    else:
        source_dir = Path.cwd()
    if raw and raw.get('schema') != 'storagestacked.topology.v1':
        raise ValueError('topology schema must be storagestacked.topology.v1')
    modules_raw = raw.get('modules', [])
    count = args.topology_modules or raw.get('module_count') or len(modules_raw) or 1
    if count < 1 or count > 64 or count & (count - 1):
        raise ValueError('topology module count must be a power of two in [1,64]')
    if modules_raw and len(modules_raw) != count:
        raise ValueError('topology modules length must match module_count')
    names = [item.get('name', f'module{i}') for i, item in enumerate(modules_raw)]
    if len(names) != len(set(names)):
        raise ValueError('topology module names must be unique')
    routing = raw.get('routing', {})
    requested_policy = routing.get('policy', 'single' if count == 1 else 'address_interleave')
    expected_policy = 'single' if count == 1 else 'address_interleave'
    if requested_policy != expected_policy:
        raise ValueError(f'{count}-module topology requires routing policy {expected_policy}')
    stripe = args.topology_stripe_bytes or routing.get('stripe_bytes', 4096)
    if stripe < 32 or stripe & (stripe - 1):
        raise ValueError('topology stripe must be a power of two and at least 32 bytes')
    if stripe < args.axi_data_width // 8:
        raise ValueError('topology stripe cannot be smaller than one AXI beat')

    def from_modules(key, default):
        values = []
        for item in modules_raw:
            values.append(item.get('ucie', {}).get(key, default))
        return values or [default]

    lanes = _csv(args.ucie_lanes, int) if args.ucie_lanes else from_modules('lanes', 16)
    rates = _csv(args.ucie_rate_gtps, float) if args.ucie_rate_gtps else from_modules('rate_gtps', 24.0)
    mods = _csv(args.ucie_modulation, lambda x: x.upper()) if args.ucie_modulation else from_modules('modulation', 'NRZ')
    lanes = _broadcast(lanes, count, 'ucie lanes')
    rates = _broadcast(rates, count, 'ucie rates')
    mods = _broadcast(mods, count, 'ucie modulation')
    if any(x < 1 for x in lanes) or any(x <= 0 or not math.isfinite(x) for x in rates):
        raise ValueError('UCIe lane counts and rates must be positive')
    if any(x not in ('NRZ', 'PAM4') for x in mods):
        raise ValueError('UCIe modulation must be NRZ or PAM4')
    bits = [1 if x == 'NRZ' else 2 for x in mods]
    compiled_width = int(os.environ.get('SS_AXI_DATA_WIDTH', '256'))
    configured_width = raw.get('axi', {}).get('data_width_bits', args.axi_data_width)
    if configured_width != args.axi_data_width:
        raise ValueError('topology AXI width does not match --axi-data-width')
    if args.axi_data_width != compiled_width:
        raise ValueError(f'--axi-data-width={args.axi_data_width} does not match '
                         f'compiled SS_AXI_DATA_WIDTH={compiled_width}; rebuild first')
    resolved = {
        'schema': 'storagestacked.topology.v1',
        'source': source,
        'axi': {'data_width_bits': args.axi_data_width},
        'routing': {'policy': expected_policy,
                    'stripe_bytes': stripe},
        'modules': [
            {'id': i, 'name': (modules_raw[i].get('name', f'module{i}')
                               if i < len(modules_raw) else f'module{i}'),
             'ucie': {'lanes': lanes[i], 'rate_gtps': rates[i],
                      'modulation': mods[i],
                      'raw_bandwidth_GBps': lanes[i] * rates[i] * bits[i] / 8.0},
             'memory_node': i,
             'memory': {
                 **(modules_raw[i].get('memory', {}) if i < len(modules_raw) else {}),
                 **({'config': str((source_dir / modules_raw[i]['memory']['config']).resolve())}
                    if i < len(modules_raw) and modules_raw[i].get('memory',{}).get('config') else {})}}
            for i in range(count)
        ],
    }
    return resolved


def simobject_params(topology):
    modules = topology['modules']
    return dict(
        topology_modules=len(modules),
        topology_policy=topology['routing']['policy'],
        topology_stripe_bytes=topology['routing']['stripe_bytes'],
        ucie_lanes=[m['ucie']['lanes'] for m in modules],
        ucie_rates=[m['ucie']['rate_gtps'] for m in modules],
        ucie_bits_per_symbol=[1 if m['ucie']['modulation'] == 'NRZ' else 2
                              for m in modules],
    )


def write_resolved(topology, directory):
    """Persist reproducible input without embedding raw JSON in config.dot."""
    path = Path(directory) / 'topology_resolved.json'
    path.write_text(json.dumps(topology, indent=2, sort_keys=True) + '\n')
    return path


def interleaved_ranges(AddrRange, ranges, topology):
    """Return one list of non-overlapping gem5 ranges for every module."""
    count = len(topology['modules'])
    if count == 1:
        return [list(ranges)]
    bits = int(math.log2(count))
    low = int(math.log2(topology['routing']['stripe_bytes']))
    return [[AddrRange(int(r.start), end=int(r.end), intlvHighBit=low + bits - 1,
                       intlvBits=bits, intlvMatch=i) for r in ranges]
            for i in range(count)]
