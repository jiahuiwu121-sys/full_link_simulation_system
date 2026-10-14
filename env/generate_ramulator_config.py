#!/usr/bin/env python3
"""Generate expanded Ramulator2 External configs with matching power inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ramulator2/python'))

SUPPORTED_STANDARDS = ('HBM4', 'LPDDR5', 'LPDDR6')


def normalize_standard(value):
    standard = str(value).upper()
    if standard not in SUPPORTED_STANDARDS:
        raise ValueError('Ramulator standard must be one of ' + ', '.join(SUPPORTED_STANDARDS))
    return standard


def generate_config(directory, channels=2, queue=8, clock_scale=1, power=True,
                    sample_cycles=1000, standard='HBM4'):
    from ramulator import addr_mapper, channel_mapper, controller, dram, frontend
    from ramulator import memory_system, refresh_manager, row_policy, scheduler
    from ramulator.power import HBM34PowerModel, LPDDRPowerModel

    standard = normalize_standard(standard)
    if channels < 1 or channels & (channels - 1) or queue < 1 or clock_scale < 1 or sample_cycles < 1:
        raise ValueError('channels must be power of two; queue/scale/sample cycles must be positive')
    if standard != 'HBM4' and clock_scale != 1:
        raise ValueError('clock scaling is only defined for the controlled HBM4 experiment')
    if standard == 'HBM4' and 8000 % clock_scale:
        raise ValueError('clock scale must divide the HBM4 reference rate 8000')

    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)

    if standard == 'HBM4':
        org_preset = 'HBM4_32Gb_8Hi'
        timing_preset = 'HBM4_8000Mbps'

        def make_dram():
            # Controlled clock sensitivity experiment: all CK timings and the
            # refresh CK count are retained. This is not a new JEDEC preset.
            return dram.HBM4(org_preset=org_preset, timing_preset=timing_preset,
                             rate=8000 // clock_scale, tCK_ps=500 * clock_scale)

        model = HBM34PowerModel(make_dram(), directory / 'hbm4_memspec.json')

        def make_controller():
            return controller.HBM34(
                dram=make_dram(), read_buffer_size=queue, write_buffer_size=queue,
                scheduler=scheduler.FRFCFSRowHit(),
                refresh_manager=refresh_manager.HBM34PerBankRefresh(),
                row_policy=row_policy.Open(), addr_mapper=addr_mapper.RoBaRaCoCh(),
                controller_plugins=[model.plugin()] if power else [],
            )

        experiment = 'controlled clock scaling; not an independently calibrated JEDEC preset'
    elif standard == 'LPDDR5':
        org_preset = 'LPDDR5_16Gb_x16'
        timing_preset = 'LPDDR5_6400'
        wck_sync_mode = 'need_sync'

        def make_dram():
            return dram.LPDDR5(org_preset=org_preset, timing_preset=timing_preset)

        model = LPDDRPowerModel(
            make_dram(), directory / 'lpddr5_memspec.json',
            reference_memspec_path=ROOT / 'ramulator2/DRAMPower/examples/lpddr5/lpddr5_16gb_x16_6400_estimated.json',
            wck_sync_mode=wck_sync_mode,
        )

        def make_controller():
            return controller.LPDDR5(
                dram=make_dram(), read_buffer_size=queue, write_buffer_size=queue,
                wr_low_watermark=0.2, wr_high_watermark=0.8,
                wck_sync_mode=wck_sync_mode,
                scheduler=scheduler.FRFCFSRowHit(),
                refresh_manager=refresh_manager.PerBank(),
                row_policy=row_policy.Open(), addr_mapper=addr_mapper.RoBaRaCoCh(),
                controller_plugins=[model.plugin(read_toggle_rate=0.5,
                                                  write_toggle_rate=0.5)] if power else [],
            )

        experiment = 'LPDDR5 x16 BL16 External frontend with estimated public power parameters'
    else:
        org_preset = 'LPDDR6_16Gb_x12'
        timing_preset = 'LPDDR6_10667_BL24'
        wck_sync_mode = 'need_sync'

        def make_dram():
            return dram.LPDDR6(org_preset=org_preset, timing_preset=timing_preset)

        model = LPDDRPowerModel(
            make_dram(), directory / 'lpddr6_memspec.json',
            reference_memspec_path=ROOT / 'ramulator2/DRAMPower/examples/lpddr6/lpddr6_16gb_x12_10667_bl24_estimated.json',
            wck_sync_mode=wck_sync_mode,
        )

        def make_controller():
            return controller.LPDDR6(
                dram=make_dram(), read_buffer_size=queue, write_buffer_size=queue,
                wr_low_watermark=0.2, wr_high_watermark=0.8,
                wck_sync_mode=wck_sync_mode,
                scheduler=scheduler.FRFCFSRowHit(),
                refresh_manager=refresh_manager.AllBank(),
                row_policy=row_policy.Open(), addr_mapper=addr_mapper.RoBaRaCoCh(),
                controller_plugins=[model.plugin(read_toggle_rate=0.5,
                                                  write_toggle_rate=0.5)] if power else [],
            )

        experiment = ('LPDDR6 x12 BL24 External frontend; two controllers represent '
                      'the two subchannels of one physical x24 channel')

    config = {
        'integration_statistics': {'sample_cycles': sample_cycles},
        'frontend': frontend.External(clock_ratio=1).to_config(),
        'memory_system': memory_system.GenericDRAM(
            clock_ratio=1,
            channel_mapper=channel_mapper.CacheLineInterleave(),
            controllers=[make_controller() for _ in range(channels)],
        ).to_config(),
    }
    # JSON is valid YAML and safely quotes absolute paths consumed by native Ramulator2.
    path = directory / f'{standard.lower()}_external.yaml'
    path.write_text(json.dumps(config, indent=2) + '\n')
    metadata = {
        'standard': standard,
        'organization_preset': org_preset,
        'timing_preset': timing_preset,
        'channels': channels,
        'queue': queue,
        'clock_scale': clock_scale,
        'power': power,
        'metrics_sample_cycles': sample_cycles,
        'config_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'memspec_sha256': hashlib.sha256(model.memspec_path.read_bytes()).hexdigest(),
        'model_metadata': model.memspec['modelMetadata'],
        'transaction_bytes': getattr(model, 'transaction_bytes', 32),
        'experiment': experiment,
    }
    (directory / 'ramulator_config_metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    return str(path)


def add_options(parser, default_backend='ramulator2'):
    parser.add_argument('--memory-backend', choices=['simple', 'memsim', 'ramulator2'], default=default_backend)
    parser.add_argument('--ramulator-config', default='',
                        help='Expanded External config; otherwise generate the selected standard')
    parser.add_argument('--ramulator-standard', type=str.upper, choices=SUPPORTED_STANDARDS,
                        default='HBM4', help='Generated External memory standard')
    parser.add_argument('--ramulator-channels', type=int, default=None)
    parser.add_argument('--ramulator-queue', type=int, default=8)
    parser.add_argument('--ramulator-slots', type=int, default=8)
    parser.add_argument('--ramulator-children', type=int, default=32)
    parser.add_argument('--ramulator-submit-width', type=int, default=8,
                        help='Maximum native child submission attempts per DRAM tick')
    parser.add_argument('--ramulator-response-hold', type=int, default=0)
    parser.add_argument('--ramulator-scale', type=int, default=1,
                        help='Generate matching slow HBM4 timing/memspec experiment')
    parser.add_argument('--ramulator-no-power', action='store_true')
    parser.add_argument('--metrics-sample-cycles', type=int, default=1000,
                        help='Native queue/power sampling interval; exact final snapshot is always written')


def runtime_config(args, directory, default_channels=2, standard=None):
    if min(args.ramulator_queue, args.ramulator_slots, args.ramulator_children,
           args.ramulator_submit_width, args.ramulator_scale, args.metrics_sample_cycles) < 1 or args.ramulator_response_hold < 0:
        raise ValueError('invalid ramulator capacity/scale/hold')
    if args.ramulator_submit_width > args.ramulator_children:
        raise ValueError('ramulator submit width cannot exceed the child limit')
    if args.memory_backend != 'ramulator2':
        return ''
    if args.ramulator_config:
        if args.ramulator_scale != 1 or args.ramulator_no_power or args.ramulator_channels is not None:
            raise ValueError('custom config already determines timing, power and channels')
        path = Path(args.ramulator_config).resolve()
        if not path.is_file():
            raise ValueError('missing Ramulator config: ' + str(path))
        return str(path)
    selected = normalize_standard(standard or args.ramulator_standard)
    return generate_config(
        directory,
        default_channels if args.ramulator_channels is None else args.ramulator_channels,
        args.ramulator_queue, args.ramulator_scale, not args.ramulator_no_power,
        args.metrics_sample_cycles, selected,
    )


def runtime_configs(args, directory, count, default_channels=2, topology=None):
    """Build one independently traced native memory system per topology module."""
    modules = (topology or {}).get('modules', [])
    explicit = [m.get('memory', {}).get('config', '') for m in modules]
    if any(explicit):
        if len(explicit) != count or not all(explicit):
            raise ValueError('every topology memory node must provide a config when one does')
        missing = [p for p in explicit if not Path(p).is_file()]
        if missing:
            raise ValueError('missing topology Ramulator config: ' + missing[0])
        return explicit
    if args.memory_backend != 'ramulator2':
        return [''] * count
    if args.ramulator_config:
        # A custom immutable input may be instantiated more than once; every
        # native instance still writes to a distinct result directory.
        return [runtime_config(args, directory, default_channels)] * count
    channels = [m.get('memory', {}).get('channels', default_channels) for m in modules]
    standards = [m.get('memory', {}).get('standard', args.ramulator_standard) for m in modules]
    if len(channels) != count:
        channels = [default_channels] * count
        standards = [args.ramulator_standard] * count
    if count == 1:
        return [runtime_config(args, directory, channels[0], standards[0])]
    root = Path(directory) / 'links'
    return [runtime_config(args, root / f'link{i}', channels[i], standards[i])
            for i in range(count)]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--standard', type=str.upper, choices=SUPPORTED_STANDARDS, default='HBM4')
    parser.add_argument('--channels', type=int, default=2)
    parser.add_argument('--queue', type=int, default=8)
    parser.add_argument('--clock-scale', type=int, default=1)
    parser.add_argument('--sample-cycles', type=int, default=1000)
    parser.add_argument('--no-power', action='store_true')
    args = parser.parse_args()
    print(generate_config(args.directory, args.channels, args.queue, args.clock_scale,
                          not args.no_power, args.sample_cycles, args.standard))
