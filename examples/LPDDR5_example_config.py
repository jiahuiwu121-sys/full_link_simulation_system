"""Configurable LPDDR5-6400 BG/BL16 example with matching DRAMPower input.

Public sources and electrical-model limitations: examples/LPDDR_POWER.md.
Each controller models one x16 channel, not an HBM controller.
"""

from pathlib import Path

from ramulator.power import LPDDRPowerModel
from ramulator.reporting import print_memory_performance_report

import ramulator

ROOT = Path(__file__).resolve().parents[1]
ORG_PRESET = "LPDDR5_16Gb_x16"
TIMING_PRESET = "LPDDR5_6400"
PHYSICAL_CHANNELS = 2
NUM_CONTROLLERS = PHYSICAL_CHANNELS
DRAM_OVERRIDES = {}  # e.g. rank=2; use a complete timing preset for a new rate
READ_QUEUE_DEPTH = 32
WRITE_QUEUE_DEPTH = 32
WR_LOW_WATERMARK = 0.2
WR_HIGH_WATERMARK = 0.8
FRONTEND_CLOCK_RATIO = 8
MEMORY_CLOCK_RATIO = 1
TRACE_FILES = [ROOT / "examples/traces/read7_write3_32ch_x10.trace"]
NUM_EXPECTED_INSTS = 50000  # SimpleO3 cyclically replays traces until this target
INST_WINDOW_DEPTH = 128
MSHR_PER_CORE = 16
SCHEDULER = "FRFCFSRowHit"  # FRFCFSRowHit or FRFCFS
ROW_POLICY = "Open"  # Open or ClosedCAP
ROW_CAP = 4
REFRESH_POLICY = "AllBank"  # AllBank, PerBank (LPDDR5 only), or diagnostic NoRefresh
WCK_SYNC_MODE = "need_sync"  # need_sync or always_on; shared with the power model
READ_TOGGLE_RATE = 0.5  # assumed bit activity; address-only traces do not provide data
WRITE_TOGGLE_RATE = 0.5
POWER_OVERRIDES = {}  # optional measured IDD/voltage values (A/V), not generated JSON edits
IMPEDANCE_OVERRIDES = {}  # optional measured interface impedances/transition energies


def make_dram():
    return ramulator.dram.LPDDR5(
        org_preset=ORG_PRESET,
        timing_preset=TIMING_PRESET,
        **DRAM_OVERRIDES,
    )


POWER_MODEL = LPDDRPowerModel(
    make_dram(),
    ROOT / "examples/power_specs/LPDDR5_example_config.generated.json",
    reference_memspec_path=ROOT / "DRAMPower/examples/lpddr5/lpddr5_16gb_x16_6400_estimated.json",
    wck_sync_mode=WCK_SYNC_MODE,
    power_overrides=POWER_OVERRIDES,
    impedance_overrides=IMPEDANCE_OVERRIDES,
)
NOMINAL_RATE_MBPS = POWER_MODEL.nominal_rate_mbps
RUNTIME_TICK_PS = POWER_MODEL.tick_ps
CONTROLLER_WIDTH_BITS = POWER_MODEL.controller_width_bits
TRANSACTION_BYTES = POWER_MODEL.transaction_bytes
MEMORY_CAPACITY_BYTES = NUM_CONTROLLERS * POWER_MODEL.controller_capacity_bytes


def make_controller():
    return ramulator.controller.LPDDR5(
        dram=make_dram(),
        read_buffer_size=READ_QUEUE_DEPTH,
        write_buffer_size=WRITE_QUEUE_DEPTH,
        wr_low_watermark=WR_LOW_WATERMARK,
        wr_high_watermark=WR_HIGH_WATERMARK,
        wck_sync_mode=WCK_SYNC_MODE,
        scheduler={
            "FRFCFS": ramulator.scheduler.FRFCFS,
            "FRFCFSRowHit": ramulator.scheduler.FRFCFSRowHit,
        }[SCHEDULER](),
        refresh_manager={
            "AllBank": ramulator.refresh_manager.AllBank,
            "PerBank": ramulator.refresh_manager.PerBank,
            "NoRefresh": ramulator.refresh_manager.NoRefresh,
        }[REFRESH_POLICY](),
        row_policy={
            "Open": lambda: ramulator.row_policy.Open(),
            "ClosedCAP": lambda: ramulator.row_policy.ClosedCAP(cap=ROW_CAP),
        }[ROW_POLICY](),
        addr_mapper=ramulator.addr_mapper.RoBaRaCoCh(),
        controller_plugins=[
            POWER_MODEL.plugin(
                read_toggle_rate=READ_TOGGLE_RATE,
                write_toggle_rate=WRITE_TOGGLE_RATE,
            )
        ],
    )


frontend = ramulator.frontend.SimpleO3(
    clock_ratio=FRONTEND_CLOCK_RATIO,
    traces=[str(path) for path in TRACE_FILES],
    num_expected_insts=NUM_EXPECTED_INSTS,
    inst_window_depth=INST_WINDOW_DEPTH,
    llc_num_mshr_per_core=MSHR_PER_CORE,
    llc_linesize=TRANSACTION_BYTES,
    translation=ramulator.translation.NoTranslation(max_addr=MEMORY_CAPACITY_BYTES),
)
mem = ramulator.memory_system.GenericDRAM(
    clock_ratio=MEMORY_CLOCK_RATIO,
    controllers=[make_controller() for _ in range(NUM_CONTROLLERS)],
    channel_mapper=ramulator.channel_mapper.CacheLineInterleave(),
)
sim = ramulator.Simulation(frontend, mem)
sim.run()
if sim.stats:  # Preserve configuration-only `ramulator export` behavior.
    sim.finalize()
    print("Traces:                        " + ", ".join(str(path) for path in TRACE_FILES))
    print(f"Memory capacity:               {MEMORY_CAPACITY_BYTES / 1024**3:g} GiB")
    print(f"Controller/scheduler:          LPDDR5 / {SCHEDULER}")
    print(f"Row/refresh/WCK policy:        {ROW_POLICY} / {REFRESH_POLICY} / {WCK_SYNC_MODE}")
    print_memory_performance_report(
        sim.stats,
        nominal_rate_mbps=NOMINAL_RATE_MBPS,
        total_dq_bits=NUM_CONTROLLERS * CONTROLLER_WIDTH_BITS,
        tick_ps=RUNTIME_TICK_PS,
        frontend_ticks_per_memory_tick=FRONTEND_CLOCK_RATIO / MEMORY_CLOCK_RATIO,
        transaction_bytes=TRANSACTION_BYTES,
        read_queue_depth=READ_QUEUE_DEPTH,
        write_queue_depth=WRITE_QUEUE_DEPTH,
        product="LPDDR5 x16 BL16 configurable system",
        org_preset=ORG_PRESET,
        timing_preset=TIMING_PRESET,
        physical_channels=PHYSICAL_CHANNELS,
        power_model_metadata=POWER_MODEL.memspec["modelMetadata"],
        payload_fraction=POWER_MODEL.payload_fraction,
    )
