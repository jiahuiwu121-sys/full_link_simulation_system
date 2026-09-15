"""Four-channel HBM4 simulation with the in-process DRAMPower backend."""

from pathlib import Path

from ramulator.reporting import print_memory_performance_report

import ramulator

ROOT = Path(__file__).resolve().parents[1]
POWER_SPEC = ROOT / "DRAMPower/examples/hbm34/hbm4_8000_estimated.json"
NUM_CONTROLLERS = 4
CONTROLLER_WIDTH_BITS = 32
NOMINAL_RATE_MBPS = 8000
RUNTIME_TICK_PS = 500 // 2  # HBM4 uses two simulator ticks per CK.


def make_hbm4_controller():
    """Create one HBM4 channel controlled by the HBM3/HBM4 controller."""
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
        controller_plugins=[
            ramulator.controller_plugin.DRAMPower(
                memspec_path=str(POWER_SPEC),
                strict_validation=True,
                include_interface=True,
            )
        ],
    )


# Configure the simulation frontend that sends memory requests
frontend = ramulator.frontend.SimpleO3(
    clock_ratio=8,
    traces=["./examples/traces/example_inst.trace"],
    num_expected_insts=500000,
    llc_linesize=32,
    translation=ramulator.translation.NoTranslation(max_addr=2147483648),
)

# Create a memory system with four HBM4 controllers
mem = ramulator.memory_system.GenericDRAM(
    clock_ratio=1,
    controllers=[make_hbm4_controller() for _ in range(NUM_CONTROLLERS)],
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
    sim.finalize()
    stats = sim.stats

    print_memory_performance_report(
        stats,
        nominal_rate_mbps=NOMINAL_RATE_MBPS,
        total_dq_bits=NUM_CONTROLLERS * CONTROLLER_WIDTH_BITS,
        tick_ps=RUNTIME_TICK_PS,
    )
    print(f"DRAM energy:           {stats['memory_system']['dram_total_energy_j']:.6e} J")
    print(f"Average DRAM power:    {stats['memory_system']['dram_average_power_w']:.6f} W")
