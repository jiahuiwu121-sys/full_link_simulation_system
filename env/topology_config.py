#!/usr/bin/env python3
"""Load and validate legacy and graph-based AXI/UCIe/memory topologies.

``storagestacked.topology.v1`` keeps the original one AXI port per UCIe link
contract.  ``storagestacked.system.v2`` separates AXI ports from physical
links, allowing several equal-width AXI ports to share one UCIe/AoU/memory
path.  The returned object is normalized so existing reporting code can keep
using ``modules`` for physical links while new code uses ``axi_ports``.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

from generate_ramulator_config import SUPPORTED_STANDARDS


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
    schema = raw.get('schema', 'storagestacked.topology.v1') if raw else 'storagestacked.topology.v1'
    if schema not in ('storagestacked.topology.v1', 'storagestacked.system.v2'):
        raise ValueError('topology schema must be storagestacked.topology.v1 or storagestacked.system.v2')
    if schema == 'storagestacked.system.v2':
        return _load_v2(args, raw, source, source_dir)
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
    memories = []
    for item in modules_raw:
        memory = dict(item.get('memory', {}))
        if 'standard' in memory:
            memory['standard'] = str(memory['standard']).upper()
            if memory['standard'] not in SUPPORTED_STANDARDS:
                raise ValueError('memory standard must be one of ' +
                                 ', '.join(SUPPORTED_STANDARDS))
        if 'channels' in memory:
            channels = memory['channels']
            if not isinstance(channels, int) or channels < 1 or channels & (channels - 1):
                raise ValueError('memory channels must be a positive power of two')
        if memory.get('config'):
            memory['config'] = str((source_dir / memory['config']).resolve())
        memories.append(memory)
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
             'memory': memories[i] if i < len(memories) else {}}
            for i in range(count)
        ],
    }
    resolved['axi_ports'] = [
        {'id': i, 'name': f'axi{i}', 'link': i, 'sources': []}
        for i in range(count)
    ]
    resolved['memory_nodes'] = [
        {'id': i, 'name': f'memory{i}', **resolved['modules'][i]['memory']}
        for i in range(count)
    ]
    resolved['mapping'] = {'axi_port_to_link': list(range(count)),
                           'link_to_memory_node': list(range(count))}
    resolved['bridge'] = {'fabric_clock_ratio': 1}
    return resolved


def _load_v2(args, raw, source, source_dir):
    """Normalize the system graph while enforcing currently modeled edges.

    Multiple AXI ports may share a link.  Each physical link currently owns
    exactly one memory node; the explicit mapping is retained so a later
    multi-link memory arbiter can extend the graph without another schema
    change.
    """
    axi_raw = raw.get('axi_ports', [])
    links_raw = raw.get('ucie_links', [])
    memory_raw = raw.get('memory_nodes', [])
    if not axi_raw or not links_raw or not memory_raw:
        raise ValueError('system.v2 requires non-empty axi_ports, ucie_links and memory_nodes')
    if len(axi_raw) > 64 or len(links_raw) > 64 or len(memory_raw) > 64:
        raise ValueError('system.v2 supports at most 64 AXI ports, links and memory nodes')

    def unique(items, kind):
        names = [str(x.get('name', '')) for x in items]
        if any(not x for x in names) or len(names) != len(set(names)):
            raise ValueError(f'{kind} names must be non-empty and unique')
        return {name: i for i, name in enumerate(names)}

    link_ids = unique(links_raw, 'UCIe link')
    memory_ids = unique(memory_raw, 'memory node')
    unique(axi_raw, 'AXI port')
    configured_width = raw.get('axi', {}).get('data_width_bits', args.axi_data_width)
    if configured_width not in (256, 512, 1024):
        raise ValueError('system.v2 AXI width must be 256, 512 or 1024')
    if configured_width != args.axi_data_width:
        raise ValueError('topology AXI width does not match --axi-data-width')
    compiled_width = int(os.environ.get('SS_AXI_DATA_WIDTH', '256'))
    if configured_width != compiled_width:
        raise ValueError(f'--axi-data-width={configured_width} does not match '
                         f'compiled SS_AXI_DATA_WIDTH={compiled_width}; rebuild first')

    memories = []
    for i, item in enumerate(memory_raw):
        memory = dict(item)
        memory.pop('name', None)
        standard = str(memory.get('standard', '')).upper()
        if standard not in SUPPORTED_STANDARDS:
            raise ValueError('memory standard must be one of ' + ', '.join(SUPPORTED_STANDARDS))
        memory['standard'] = standard
        channels = memory.get('channels', 2)
        if not isinstance(channels, int) or channels < 1 or channels & (channels - 1):
            raise ValueError('memory channels must be a positive power of two')
        memory['channels'] = channels
        if memory.get('config'):
            memory['config'] = str((source_dir / memory['config']).resolve())
        memories.append({'id': i, 'name': memory_raw[i]['name'], **memory})

    modules = []
    link_to_memory = []
    for i, item in enumerate(links_raw):
        lanes = int(item.get('lanes', 16))
        rate = float(item.get('rate_gtps', 24.0))
        modulation = str(item.get('modulation', 'NRZ')).upper()
        if lanes < 1 or rate <= 0 or not math.isfinite(rate):
            raise ValueError('UCIe lane counts and rates must be positive')
        if modulation not in ('NRZ', 'PAM4'):
            raise ValueError('UCIe modulation must be NRZ or PAM4')
        memory_name = item.get('memory_node')
        if memory_name not in memory_ids:
            raise ValueError(f'UCIe link {item["name"]} references unknown memory node')
        memory_id = memory_ids[memory_name]
        link_to_memory.append(memory_id)
        bits = 1 if modulation == 'NRZ' else 2
        modules.append({
            'id': i, 'name': item['name'],
            'ucie': {'lanes': lanes, 'rate_gtps': rate, 'modulation': modulation,
                     'raw_bandwidth_GBps': lanes * rate * bits / 8.0},
            'memory_node': memory_id,
            'memory': {k: v for k, v in memories[memory_id].items()
                       if k not in ('id', 'name')},
        })
    if len(set(link_to_memory)) != len(link_to_memory):
        raise ValueError('shared memory nodes across multiple UCIe links are not yet enabled; '
                         'aggregate AXI ports onto one link or use distinct memory nodes')
    unused_memories = sorted(set(range(len(memories))) - set(link_to_memory))
    if unused_memories:
        raise ValueError('every memory node must be connected to one UCIe link')

    ports = []
    port_to_link = []
    for i, item in enumerate(axi_raw):
        link_name = item.get('link')
        if link_name not in link_ids:
            raise ValueError(f'AXI port {item["name"]} references unknown UCIe link')
        link = link_ids[link_name]
        port_to_link.append(link)
        sources = item.get('sources', [])
        if isinstance(sources, str):
            sources = [sources]
        if not isinstance(sources, list) or any(not isinstance(x, str) for x in sources):
            raise ValueError('AXI port sources must be a string list')
        ports.append({'id': i, 'name': item['name'], 'link': link, 'sources': sources})
    missing_links = sorted(set(range(len(modules))) - set(port_to_link))
    if missing_links:
        raise ValueError('every UCIe link must have at least one AXI port')

    routing = raw.get('routing', {})
    expected_policy = 'single' if len(ports) == 1 else 'address_interleave'
    policy = routing.get('policy', expected_policy)
    if policy != expected_policy:
        raise ValueError(f'{len(ports)} AXI ports require routing policy {expected_policy}')
    stripe = args.topology_stripe_bytes or routing.get('stripe_bytes', 4096)
    if stripe < configured_width // 8 or stripe & (stripe - 1):
        raise ValueError('topology stripe must be a power of two and cover one AXI beat')
    if len(ports) > 1 and len(ports) & (len(ports) - 1):
        raise ValueError('address-interleaved AXI port count must be a power of two')
    fanin = [port_to_link.count(link) for link in range(len(modules))]
    fabric_ratio = int(raw.get('bridge', {}).get('fabric_clock_ratio', 1))
    if fabric_ratio < 1 or fabric_ratio & (fabric_ratio - 1):
        raise ValueError('bridge.fabric_clock_ratio must be a positive power of two')
    if any(count != fabric_ratio for count in fanin):
        raise ValueError('every UCIe link must have exactly fabric_clock_ratio AXI ports; '
                         'this models a deterministic multi-port gearbox')

    sources = raw.get('sources', [])
    if not isinstance(sources, list) or any(not isinstance(x, dict) for x in sources):
        raise ValueError('sources must be an object list')
    source_list = [str(x.get('name', '')) for x in sources]
    if any(not x for x in source_list) or len(source_list) != len(set(source_list)):
        raise ValueError('source names must be non-empty and unique')
    source_names = set(source_list)
    referenced_sources = {x for port in ports for x in port['sources']}
    if not referenced_sources <= source_names:
        raise ValueError('AXI port references an unknown source')
    resolved = {
        'schema': 'storagestacked.system.v2', 'source': source,
        'name': raw.get('name', Path(source).stem if source != 'command-line defaults' else 'system'),
        'axi': {'data_width_bits': configured_width,
                'clock_period': raw.get('axi', {}).get('clock_period', '666667fs')},
        'routing': {'policy': policy, 'stripe_bytes': stripe},
        'sources': sources, 'axi_ports': ports, 'modules': modules,
        'memory_nodes': memories,
        'bridge': {'fabric_clock_ratio': fabric_ratio},
        'mapping': {'axi_port_to_link': port_to_link,
                    'link_to_memory_node': link_to_memory},
        'requirements': raw.get('requirements', {}),
    }
    return resolved


def simobject_params(topology):
    modules = topology['modules']
    ports = topology.get('axi_ports') or [
        {'id': i, 'link': i} for i in range(len(modules))]
    return dict(
        topology_modules=len(modules),
        topology_ports=len(ports),
        axi_port_to_link=[p['link'] for p in ports],
        axi_port_dividers=[topology.get('bridge', {}).get('fabric_clock_ratio', 1)] * len(ports),
        axi_port_phases=[sum(1 for prior in ports[:i] if prior['link'] == port['link'])
                         for i, port in enumerate(ports)],
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
    """Return one list of non-overlapping gem5 ranges for every AXI port."""
    count = len(topology.get('axi_ports') or topology['modules'])
    if count == 1:
        return [list(ranges)]
    bits = int(math.log2(count))
    low = int(math.log2(topology['routing']['stripe_bytes']))
    return [[AddrRange(int(r.start), end=int(r.end), intlvHighBit=low + bits - 1,
                       intlvBits=bits, intlvMatch=i) for r in ranges]
            for i in range(count)]
