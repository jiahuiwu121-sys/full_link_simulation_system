"""Example Ramulator2 configuration and simulation script using 64 HBM4 controllers."""

import ramulator


NUM_CONTROLLERS = 64


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
    # Controller stats are under memory_system -> controller.
    ctrl_stats = stats["memory_system"]["controller"]
    controllers = ctrl_stats if isinstance(ctrl_stats, list) else [ctrl_stats]

    total_reads = sum(ctrl["num_read_reqs"] for ctrl in controllers)
    total_writes = sum(ctrl["num_write_reqs"] for ctrl in controllers)
    total_row_hits = sum(ctrl["row_hits"] for ctrl in controllers)
    total_row_misses = sum(ctrl["row_misses"] for ctrl in controllers)
    total_row_conflicts = sum(ctrl["row_conflicts"] for ctrl in controllers)
    active_controllers = sum(
        1
        for ctrl in controllers
        if ctrl["num_read_reqs"] > 0 or ctrl["num_write_reqs"] > 0
    )

    print(f"Controllers:           {len(controllers)}")
    print(f"Total modeled DQ bits: {len(controllers) * 32}")
    print(f"Active controllers:    {active_controllers}")
    print(f"Total read requests:   {total_reads}")
    print(f"Total write requests:  {total_writes}")
    print(f"Total row hits:        {total_row_hits}")
    print(f"Total row misses:      {total_row_misses}")
    print(f"Total row conflicts:   {total_row_conflicts}")

    for index, ctrl in enumerate(controllers):
        print(f"Controller {index} cycles:       {ctrl['cycles']}")
        print(f"Controller {index} read latency: {ctrl['avg_read_latency']:.1f} cycles")
