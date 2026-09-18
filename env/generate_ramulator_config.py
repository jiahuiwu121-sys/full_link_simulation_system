#!/usr/bin/env python3
"""Generate an expanded External HBM4 config and its matching power memspec."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ramulator2/python'))


def generate_config(directory, channels=2, queue=8, clock_scale=1, power=True, sample_cycles=1000):
    from ramulator import addr_mapper, channel_mapper, controller, dram, frontend
    from ramulator import memory_system, refresh_manager, row_policy, scheduler
    from ramulator.power import HBM34PowerModel
    if channels < 1 or channels & (channels - 1) or queue < 1 or clock_scale < 1 or sample_cycles < 1:
        raise ValueError('channels must be power of two; queue/scale must be positive')
    if 8000 % clock_scale:
        raise ValueError('clock scale must divide the reference rate 8000')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)

    def make_dram():
        # Controlled clock sensitivity experiment: all CK timings retained,
        # refresh CK count retained. This is not a new validated JEDEC preset.
        return dram.HBM4(org_preset='HBM4_32Gb_8Hi', timing_preset='HBM4_8000Mbps',
                         rate=8000 // clock_scale, tCK_ps=500 * clock_scale)

    model = HBM34PowerModel(make_dram(), directory / 'hbm4_memspec.json')
    config = {
        'integration_statistics': {'sample_cycles': sample_cycles},
        'frontend': frontend.External(clock_ratio=1).to_config(),
        'memory_system': memory_system.GenericDRAM(
            clock_ratio=1, channel_mapper=channel_mapper.CacheLineInterleave(),
            controllers=[controller.HBM34(
                dram=make_dram(), read_buffer_size=queue, write_buffer_size=queue,
                scheduler=scheduler.FRFCFSRowHit(),
                refresh_manager=refresh_manager.HBM34PerBankRefresh(),
                row_policy=row_policy.Open(), addr_mapper=addr_mapper.RoBaRaCoCh(),
                controller_plugins=[model.plugin()] if power else [],
            ) for _ in range(channels)],
        ).to_config(),
    }
    # JSON is accepted by the native YAML parser and handles arbitrary path quoting.
    path = directory / 'hbm4_external.yaml'
    path.write_text(json.dumps(config, indent=2) + '\n')
    metadata = {
        'channels': channels, 'queue': queue, 'clock_scale': clock_scale, 'power': power,
        'metrics_sample_cycles': sample_cycles,
        'config_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'memspec_sha256': hashlib.sha256(model.memspec_path.read_bytes()).hexdigest(),
        'model_metadata': model.memspec['modelMetadata'],
        'experiment': 'controlled clock scaling; not an independently calibrated JEDEC preset',
    }
    (directory / 'ramulator_config_metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    return str(path)


def add_options(parser, default_backend='ramulator2'):
    parser.add_argument('--memory-backend', choices=['simple', 'memsim', 'ramulator2'], default=default_backend)
    parser.add_argument('--ramulator-config', default='', help='Expanded External config; otherwise generate HBM4')
    parser.add_argument('--ramulator-channels', type=int, default=None)
    parser.add_argument('--ramulator-queue', type=int, default=8)
    parser.add_argument('--ramulator-slots', type=int, default=8)
    parser.add_argument('--ramulator-children', type=int, default=32)
    parser.add_argument('--ramulator-response-hold', type=int, default=0)
    parser.add_argument('--ramulator-scale', type=int, default=1, help='Generate matching slow timing/memspec experiment')
    parser.add_argument('--ramulator-no-power', action='store_true')
    parser.add_argument('--metrics-sample-cycles', type=int, default=1000,
                        help='Native queue/power sampling interval; exact final snapshot is always written')


def runtime_config(args, directory, default_channels=2):
    if min(args.ramulator_queue, args.ramulator_slots, args.ramulator_children, args.ramulator_scale, args.metrics_sample_cycles) < 1 or args.ramulator_response_hold < 0:
        raise ValueError('invalid ramulator capacity/scale/hold')
    if args.memory_backend != 'ramulator2':
        return ''
    if args.ramulator_config:
        if args.ramulator_scale != 1 or args.ramulator_no_power or args.ramulator_channels is not None:
            raise ValueError('custom config already determines timing, power and channels')
        path = Path(args.ramulator_config).resolve()
        if not path.is_file():
            raise ValueError('missing Ramulator config: ' + str(path))
        return str(path)
    return generate_config(directory, default_channels if args.ramulator_channels is None else args.ramulator_channels,
                           args.ramulator_queue, args.ramulator_scale, not args.ramulator_no_power, args.metrics_sample_cycles)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--channels', type=int, default=2)
    parser.add_argument('--queue', type=int, default=8)
    parser.add_argument('--clock-scale', type=int, default=1)
    parser.add_argument('--no-power', action='store_true')
    args = parser.parse_args()
    print(generate_config(args.directory, args.channels, args.queue, args.clock_scale, not args.no_power))
