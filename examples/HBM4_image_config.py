"""Image-aligned HBM4 example: 24 GB, 8-Hi, 11 Gb/s, 2048-bit I/O."""

from ramulator.reporting import print_memory_performance_report

import ramulator

PHYSICAL_CHANNELS = 32
PSEUDO_CHANNELS_PER_CHANNEL = 2
NUM_CONTROLLERS = PHYSICAL_CHANNELS * PSEUDO_CHANNELS_PER_CHANNEL
PC_WIDTH_BITS = 32
CUBE_CAPACITY_BYTES = 24 * 1024**3
NOMINAL_RATE_MBPS = 11000
RUNTIME_TICK_PS = 364 // 2  # HBM4 uses two simulator ticks per CK.


def make_controller():
    """Model one independently scheduled 32-bit HBM4 pseudo-channel."""
    dram = ramulator.dram.HBM4(
        org_preset="HBM4_24Gb_8Hi",
        timing_preset="HBM4_11000Mbps",
        pseudochannel=1,
    )
    return ramulator.controller.HBM34(
        dram=dram,
        scheduler=ramulator.scheduler.FRFCFSRowHit(),
        refresh_manager=ramulator.refresh_manager.HBM34PerBankRefresh(),
        row_policy=ramulator.row_policy.Open(),
        addr_mapper=ramulator.addr_mapper.RoBaRaCoCh(),
    )


# A 32-bit pseudo-channel with BL8 transfers 32 bytes per transaction.
frontend = ramulator.frontend.SimpleO3(
    clock_ratio=8,
    traces=["./examples/traces/example_inst.trace"],
    num_expected_insts=500000,
    llc_linesize=32,
    translation=ramulator.translation.NoTranslation(max_addr=CUBE_CAPACITY_BYTES),
)

mem = ramulator.memory_system.GenericDRAM(
    clock_ratio=1,
    controllers=[make_controller() for _ in range(NUM_CONTROLLERS)],
    channel_mapper=ramulator.channel_mapper.CacheLineInterleave(),
)

sim = ramulator.Simulation(frontend, mem)
sim.run()

stats = sim.stats
if stats:
    print("Product:               HBM4 24Gb 8-Hi")
    print(f"Physical channels:     {PHYSICAL_CHANNELS}")
    print_memory_performance_report(
        stats,
        nominal_rate_mbps=NOMINAL_RATE_MBPS,
        total_dq_bits=NUM_CONTROLLERS * PC_WIDTH_BITS,
        tick_ps=RUNTIME_TICK_PS,
    )
