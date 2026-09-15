"""Example Ramulator2 configuration and simulation script using HBM4."""

from ramulator.reporting import print_memory_performance_report

import ramulator

NUM_CONTROLLERS = 1
CONTROLLER_WIDTH_BITS = 32
NOMINAL_RATE_MBPS = 8000
RUNTIME_TICK_PS = 500 // 2  # HBM4 uses two simulator ticks per CK.

# Configure the simulation frontend that sends memory requests
frontend = ramulator.frontend.SimpleO3(
    clock_ratio=8,
    traces=["./examples/traces/example_inst.trace"],
    num_expected_insts=500000,
    llc_linesize=32,
    translation=ramulator.translation.NoTranslation(max_addr=2147483648),
)

# Create HBM4 DRAM configuration
hbm4 = ramulator.dram.HBM4(
    org_preset="HBM4_32Gb_8Hi",
    timing_preset="HBM4_8000Mbps",
)

# Instantiate the HBM3/HBM4 memory controller with the HBM4 DRAM configuration
ctrl = ramulator.controller.HBM34(
    dram=hbm4,
    scheduler=ramulator.scheduler.FRFCFSRowHit(),
    refresh_manager=ramulator.refresh_manager.HBM34PerBankRefresh(),
    row_policy=ramulator.row_policy.Open(),
    addr_mapper=ramulator.addr_mapper.RoBaRaCoCh(),
)

# Create a memory system with the controller
mem = ramulator.memory_system.GenericDRAM(
    clock_ratio=1,
    controllers=[ctrl],
    channel_mapper=ramulator.channel_mapper.CacheLineInterleave(),
)

# Run the simulation
sim = ramulator.Simulation(frontend, mem)
sim.run()

# sim.stats returns a nested Python dict of all simulation statistics
stats = sim.stats

# Guard here for `ramulator export`, which does not run the simulation
# but only exports the config for pure C++ Ramulator library
if stats:
    print_memory_performance_report(
        stats,
        nominal_rate_mbps=NOMINAL_RATE_MBPS,
        total_dq_bits=NUM_CONTROLLERS * CONTROLLER_WIDTH_BITS,
        tick_ps=RUNTIME_TICK_PS,
    )
