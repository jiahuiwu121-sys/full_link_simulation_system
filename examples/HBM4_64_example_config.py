"""Example Ramulator2 configuration and simulation script using 64 HBM4 controllers."""

from ramulator.reporting import print_memory_performance_report

import ramulator

NUM_CONTROLLERS = 64
CONTROLLER_WIDTH_BITS = 32
NOMINAL_RATE_MBPS = 8000
RUNTIME_TICK_PS = 500 // 2  # HBM4 uses two simulator ticks per CK.


def make_hbm4_controller():
    """Create one 32-bit HBM4 channel controlled by the HBM3/HBM4 controller."""
    hbm4 = ramulator.dram.HBM4(
        org_preset="HBM4_32Gb_8Hi",
        timing_preset="HBM4_8000Mbps",
    )

    return ramulator.controller.HBM34(
        dram=hbm4,
        scheduler=ramulator.scheduler.FRFCFSRowHit(),
        refresh_manager=ramulator.refresh_manager.HBM34PerBankRefresh(),
        row_policy=ramulator.row_policy.Open(),
        addr_mapper=ramulator.addr_mapper.RoBaRaCoCh(),
    )


# Configure the simulation frontend that sends memory requests.
# HBM4 uses 32-byte transactions here: 32-bit channel width * BL8 / 8.
frontend = ramulator.frontend.SimpleO3(
    clock_ratio=8,
    traces=["./examples/traces/example_inst.trace"],
    num_expected_insts=500000,
    llc_linesize=32,
    translation=ramulator.translation.NoTranslation(max_addr=2147483648),
)

# Create a memory system with 64 HBM4 controllers.
# 64 controllers * 32-bit channel width = 2048 total modeled DQ bits.
mem = ramulator.memory_system.GenericDRAM(
    clock_ratio=1,
    controllers=[make_hbm4_controller() for _ in range(NUM_CONTROLLERS)],
    channel_mapper=ramulator.channel_mapper.CacheLineInterleave(),
)

# Run the simulation.
sim = ramulator.Simulation(frontend, mem)
sim.run()

# sim.stats returns a nested Python dict of all simulation statistics.
stats = sim.stats

# Guard here for `ramulator export`, which does not run the simulation
# but only exports the config for pure C++ Ramulator library.
if stats:
    print_memory_performance_report(
        stats,
        nominal_rate_mbps=NOMINAL_RATE_MBPS,
        total_dq_bits=NUM_CONTROLLERS * CONTROLLER_WIDTH_BITS,
        tick_ps=RUNTIME_TICK_PS,
    )
