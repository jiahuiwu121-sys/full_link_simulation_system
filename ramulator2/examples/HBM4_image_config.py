"""Image-aligned HBM4 example: 24 GB, 8-Hi, 11 Gb/s, 2048-bit I/O."""

from pathlib import Path

from ramulator.power import HBM34PowerModel
from ramulator.reporting import print_memory_performance_report

import ramulator

ROOT = Path(__file__).resolve().parents[1]
ORG_PRESET = "HBM4_24Gb_8Hi"
TIMING_PRESET = "HBM4_11000Mbps"
PHYSICAL_CHANNELS = 32
PSEUDO_CHANNELS_PER_CHANNEL = 2
NUM_CONTROLLERS = PHYSICAL_CHANNELS * PSEUDO_CHANNELS_PER_CHANNEL
CUBE_CAPACITY_BYTES = 24 * 1024**3
READ_QUEUE_DEPTH = 32
WRITE_QUEUE_DEPTH = 32
FRONTEND_CLOCK_RATIO = 8
MEMORY_CLOCK_RATIO = 1


def make_dram():
    """Return the shared Ramulator/DRAMPower organization and timing source."""
    return ramulator.dram.HBM4(
        org_preset=ORG_PRESET,
        timing_preset=TIMING_PRESET,
        pseudochannel=1,
    )


POWER_MODEL = HBM34PowerModel(
    make_dram(), ROOT / "examples/power_specs/HBM4_image_config.generated.json"
)
NOMINAL_RATE_MBPS = POWER_MODEL.nominal_rate_mbps
RUNTIME_TICK_PS = POWER_MODEL.tick_ps
CONTROLLER_WIDTH_BITS = POWER_MODEL.controller_width_bits
TRANSACTION_BYTES = POWER_MODEL.transaction_bytes


def make_controller():
    """Model one independently scheduled 32-bit HBM4 pseudo-channel."""
    return ramulator.controller.HBM34(
        dram=make_dram(),
        read_buffer_size=READ_QUEUE_DEPTH,
        write_buffer_size=WRITE_QUEUE_DEPTH,
        scheduler=ramulator.scheduler.FRFCFSRowHit(),
        refresh_manager=ramulator.refresh_manager.HBM34PerBankRefresh(),
        row_policy=ramulator.row_policy.Open(),
        addr_mapper=ramulator.addr_mapper.RoBaRaCoCh(),
        controller_plugins=[POWER_MODEL.plugin()],
    )


# A 32-bit pseudo-channel with BL8 transfers 32 bytes per transaction.
frontend = ramulator.frontend.SimpleO3(
    clock_ratio=FRONTEND_CLOCK_RATIO,
    traces=["./examples/traces/read7_write3_32ch_x10.trace"],
    num_expected_insts=500000,
    llc_linesize=32,
    translation=ramulator.translation.NoTranslation(max_addr=CUBE_CAPACITY_BYTES),
)

mem = ramulator.memory_system.GenericDRAM(
    clock_ratio=MEMORY_CLOCK_RATIO,
    controllers=[make_controller() for _ in range(NUM_CONTROLLERS)],
    channel_mapper=ramulator.channel_mapper.CacheLineInterleave(),
)

sim = ramulator.Simulation(frontend, mem)
sim.run()

stats = sim.stats
if stats:
    sim.finalize()
    stats = sim.stats
    print_memory_performance_report(
        stats,
        nominal_rate_mbps=NOMINAL_RATE_MBPS,
        total_dq_bits=NUM_CONTROLLERS * CONTROLLER_WIDTH_BITS,
        tick_ps=RUNTIME_TICK_PS,
        frontend_ticks_per_memory_tick=FRONTEND_CLOCK_RATIO / MEMORY_CLOCK_RATIO,
        transaction_bytes=TRANSACTION_BYTES,
        read_queue_depth=READ_QUEUE_DEPTH,
        write_queue_depth=WRITE_QUEUE_DEPTH,
        product="HBM4 24Gb 8-Hi",
        org_preset=ORG_PRESET,
        timing_preset=TIMING_PRESET,
        physical_channels=PHYSICAL_CHANNELS,
        power_model_metadata=POWER_MODEL.memspec["modelMetadata"],
    )
