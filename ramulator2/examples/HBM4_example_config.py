"""Four-channel HBM4 simulation with the in-process DRAMPower backend."""

from pathlib import Path

from ramulator.power import HBM34PowerModel
from ramulator.reporting import print_memory_performance_report

import ramulator

ROOT = Path(__file__).resolve().parents[1]
ORG_PRESET = "HBM4_32Gb_8Hi"
TIMING_PRESET = "HBM4_8000Mbps"
NUM_CONTROLLERS = 4
READ_QUEUE_DEPTH = 32
WRITE_QUEUE_DEPTH = 32
FRONTEND_CLOCK_RATIO = 8
MEMORY_CLOCK_RATIO = 1


def make_dram():
    """Return the shared Ramulator/DRAMPower organization and timing source."""
    return ramulator.dram.HBM4(
        org_preset=ORG_PRESET,
        timing_preset=TIMING_PRESET,
    )


POWER_MODEL = HBM34PowerModel(
    make_dram(), ROOT / "examples/power_specs/HBM4_example_config.generated.json"
)
NOMINAL_RATE_MBPS = POWER_MODEL.nominal_rate_mbps
RUNTIME_TICK_PS = POWER_MODEL.tick_ps
CONTROLLER_WIDTH_BITS = POWER_MODEL.controller_width_bits
TRANSACTION_BYTES = POWER_MODEL.transaction_bytes


def make_hbm4_controller():
    """Create one HBM4 channel controlled by the HBM3/HBM4 controller."""
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


# Configure the simulation frontend that sends memory requests
frontend = ramulator.frontend.SimpleO3(
    clock_ratio=FRONTEND_CLOCK_RATIO,
    traces=["./examples/traces/read7_write3_32ch_x10.trace"],
    num_expected_insts=500000,
    llc_linesize=32,
    translation=ramulator.translation.NoTranslation(max_addr=2147483648),
)

# Create a memory system with four HBM4 controllers
mem = ramulator.memory_system.GenericDRAM(
    clock_ratio=MEMORY_CLOCK_RATIO,
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
        frontend_ticks_per_memory_tick=FRONTEND_CLOCK_RATIO / MEMORY_CLOCK_RATIO,
        transaction_bytes=TRANSACTION_BYTES,
        read_queue_depth=READ_QUEUE_DEPTH,
        write_queue_depth=WRITE_QUEUE_DEPTH,
        product="HBM4 4-controller configuration with DRAMPower",
        org_preset=ORG_PRESET,
        timing_preset=TIMING_PRESET,
        physical_channels=NUM_CONTROLLERS,
        power_model_metadata=POWER_MODEL.memspec["modelMetadata"],
    )
