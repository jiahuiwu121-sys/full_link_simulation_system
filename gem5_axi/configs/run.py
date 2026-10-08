"""Bundled gem5 -> nonblocking TLM -> AXI signals -> independent AXI RAM."""
import argparse
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "env"))
from generate_ramulator_config import add_options, runtime_configs
from topology_config import add_options as add_topology_options
from topology_config import load as load_topology, simobject_params, interleaved_ranges, write_resolved
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from collect_metrics import install as install_metrics
import m5
from m5.util.convert import toLatency
from m5.objects import (
    System, SrcClockDomain, VoltageDomain, SimpleMemory, AddrRange, SystemXBar,
    NoncoherentXBar,
    Root, SystemC_Kernel, Gem5ToTlmBridge64, AxiDemo, AxiPacketTester,
    X86TimingSimpleCPU, SEWorkload, Process, MetricsMarker,
)

parser = argparse.ArgumentParser()
parser.add_argument("--mode", choices=["tester", "cpu", "traffic"], default="tester")
parser.add_argument("--binary")
parser.add_argument("--het-trace", action="store_true",
                    help="Observe target packets using gem5_new HetAxiMonitor")
parser.add_argument("--backend", choices=["ram", "aou"], default="ram")
add_options(parser, default_backend="simple")
add_topology_options(parser)
parser.add_argument("--memsim-channels", type=int, default=2)
parser.add_argument("--memsim-scale", type=int, default=1)
parser.add_argument("--memsim-queue", type=int, default=4)
parser.add_argument("--memsim-slots", type=int, default=8)
parser.add_argument("--memsim-response-hold", type=int, default=0)
parser.add_argument("--planes", type=int, choices=[1,2,3,4], default=1)
parser.add_argument("--replay", action="store_true")
parser.add_argument("--latency", type=int, default=3)
parser.add_argument("--slots", type=int, default=4)
parser.add_argument("--period", default="666667fs")
parser.add_argument("--no-stalls", action="store_true")
parser.add_argument("--response-hold", default="7ns")
parser.add_argument("--max-ticks", type=int, default=10**13)
parser.add_argument("--target-size", type=lambda x: int(x, 0), default=None)
parser.add_argument("--traffic-load-percent", type=float, default=100.0)
parser.add_argument("--traffic-warmup", type=int, default=128)
parser.add_argument("--traffic-measure", type=int, default=1024)
parser.add_argument("--traffic-cooldown", type=int, default=128)
parser.add_argument("--traffic-size", type=int, default=256)
parser.add_argument("--traffic-working-set", type=lambda x: int(x, 0), default=1024 * 1024)
parser.add_argument("--traffic-write-percent", type=int, default=50)
parser.add_argument("--traffic-max-inflight", type=int, default=64)
args = parser.parse_args()
topology = load_topology(args)
module_count = len(topology['modules'])
if args.memory_backend in ("memsim", "ramulator2") and args.backend != "aou":
    parser.error("online memory requires --backend aou")
if min(args.memsim_channels, args.memsim_scale, args.memsim_queue, args.memsim_slots) < 1 or args.memsim_response_hold < 0:
    parser.error("invalid memsim capacities/clock scale")
if args.mode == "cpu" and not args.binary:
    parser.error("--binary required for CPU mode")
if args.mode == "traffic":
    if not (0 < args.traffic_load_percent <= 400):
        parser.error("--traffic-load-percent must be in (0, 400]")
    if min(args.traffic_warmup, args.traffic_measure, args.traffic_cooldown,
           args.traffic_size, args.traffic_working_set, args.traffic_max_inflight) < 1:
        parser.error("traffic counts, size, working set and inflight limit must be positive")
    if not (0 <= args.traffic_write_percent <= 100):
        parser.error("--traffic-write-percent must be in [0, 100]")
    if args.traffic_working_set % args.traffic_size or args.traffic_size > 4096:
        parser.error("traffic working set must be a multiple of request size; size must be <= 4096")
    if module_count > 1 and args.traffic_size > topology['routing']['stripe_bytes']:
        parser.error("traffic request size cannot exceed the topology stripe size")
    if module_count > 1 and topology['routing']['stripe_bytes'] % args.traffic_size:
        parser.error("traffic request size must divide the topology stripe to avoid cross-node packets")

# Set before constructing any SystemC time objects or fixing gem5 frequency.
m5.ticks.setGlobalFrequency(10**15)
out = os.path.abspath(m5.options.outdir)
os.makedirs(out, exist_ok=True)
write_resolved(topology, out)
base = 0x90000000
target_size = args.target_size if args.target_size is not None else (args.traffic_working_set if args.mode == "traffic" else 8192)
minimum_target_size = args.traffic_working_set if args.mode == "traffic" else 8192
if target_size < minimum_target_size:
    parser.error("target size does not cover the selected workload")
system = System()
system.clk_domain = SrcClockDomain(clock="2GHz", voltage_domain=VoltageDomain())
system.mem_mode = "timing"
host_range = AddrRange(0, size="512MiB")
target_range = AddrRange(base, size=max(target_size, 16384 if args.mode == "tester" else target_size))
system.mem_ranges = [host_range, target_range]
system.host_mem = SimpleMemory(range=host_range, latency="10ns")
system.axi = AxiDemo(
    base=base, size=target_size, period=args.period, outstanding=args.slots,
    backend=args.backend, planes=args.planes, replay=args.replay,
    memory_backend=args.memory_backend,
    ramulator_config='',
    ramulator_configs=runtime_configs(args, out, module_count, topology=topology),
    **simobject_params(topology), ramulator_slots=args.ramulator_slots,
    ramulator_children=args.ramulator_children, ramulator_submit_width=args.ramulator_submit_width,
    ramulator_response_hold=args.ramulator_response_hold,
    memsim_channels=args.memsim_channels,
    memsim_scale=args.memsim_scale, memsim_queue=args.memsim_queue,
    memsim_slots=args.memsim_slots, memsim_response_hold=args.memsim_response_hold,
    latency=args.latency, stalls=not args.no_stalls, trace_dir=out,
)
module_ranges = interleaved_ranges(AddrRange, [target_range], topology)
system.bridges = [Gem5ToTlmBridge64(addr_ranges=ranges) for ranges in module_ranges]
for i, bridge in enumerate(system.bridges):
    bridge.tlm = system.axi.tlm[i]
if module_count == 1:
    target_port = system.bridges[0].gem5
else:
    # Pure address demultiplexer: size it for all parallel AXI lanes and add
    # no hidden latency/capacity bottleneck ahead of the modeled links.
    system.target_xbar = NoncoherentXBar(
        width=(args.axi_data_width // 8) * module_count,
        frontend_latency=0, forward_latency=0, response_latency=0,
        header_latency=0)
    for bridge in system.bridges:
        system.target_xbar.mem_side_ports = bridge.gem5
    target_port = system.target_xbar.cpu_side_ports
if args.het_trace:
    from m5.objects import HetAxiMonitor
    trace_path = os.path.join(out, "hettrace")
    os.makedirs(trace_path, exist_ok=True)
    os.environ["HETTRACE_DIR"] = trace_path
    os.environ["HETTRACE_FILTER"] = "all"
    os.environ["HETTRACE_FORMAT"] = "binary"
    system.het_monitor = HetAxiMonitor(unique_packet_ids=True)
    system.het_monitor.mem_side_port = target_port
    target_port = system.het_monitor.cpu_side_port

if args.mode in ("tester", "traffic"):
    period_fs = round(toLatency(args.period) * 1e15)
    # One request occupies request_size/32 ideal AXI data beats. The requested
    # load is defined against that payload capacity, independent of protocol overhead.
    issue_interval_fs = max(1, round((args.traffic_size / (args.axi_data_width // 8)) *
                                     period_fs * 100 / args.traffic_load_percent))
    system.tester = AxiPacketTester(
        base=base, trace_dir=out,
        response_hold=args.response_hold if args.mode == "tester" else "0ns",
        traffic_mode="validation" if args.mode == "tester" else "bandwidth",
        traffic_warmup_requests=args.traffic_warmup,
        traffic_measure_requests=args.traffic_measure,
        traffic_cooldown_requests=args.traffic_cooldown,
        traffic_request_size=args.traffic_size,
        traffic_working_set=args.traffic_working_set,
        traffic_write_percent=args.traffic_write_percent,
        traffic_max_inflight=args.traffic_max_inflight,
        traffic_issue_interval=f"{issue_interval_fs}fs",
        traffic_offered_load_percent=args.traffic_load_percent)
    system.tester.port = target_port
else:
    system.membus = SystemXBar()
    system.metrics_marker = MetricsMarker(trace_dir=out)
    system.metrics_marker.pio = system.membus.mem_side_ports
    system.host_mem.port = system.membus.mem_side_ports
    system.membus.mem_side_ports = target_port
    system.cpu = X86TimingSimpleCPU()
    system.cpu.icache_port = system.membus.cpu_side_ports
    system.cpu.dcache_port = system.membus.cpu_side_ports
    system.cpu.createInterruptController()
    system.cpu.interrupts[0].pio = system.membus.mem_side_ports
    system.cpu.interrupts[0].int_requestor = system.membus.cpu_side_ports
    system.cpu.interrupts[0].int_responder = system.membus.mem_side_ports
    system.system_port = system.membus.cpu_side_ports
    system.workload = SEWorkload.init_compatible(args.binary)
    process = Process(cmd=[os.path.abspath(args.binary)])
    system.cpu.workload = process
    system.cpu.createThreads()

root = Root(full_system=False, systemc_kernel=SystemC_Kernel(system=system))
metrics_context = install_metrics(out, args)
m5.instantiate()
if args.mode == "cpu":
    process.map(base, base, 8192, cacheable=False)
    process.map(0x70000000, 0x70000000, 4096, cacheable=False)
event = m5.simulate(args.max_ticks)  # Default 10 ms simulated, finite watchdog
system.axi.finish()
metrics_context.update(end_tick_fs=m5.curTick(), exit_cause=event.getCause(), exit_code=event.getCode(),
                       completed=event.getCode() == 0 and (
                           event.getCause() == "AXI packet/data/retry tests passed" if args.mode == "tester" else
                           event.getCause() == "AXI bandwidth traffic completed" if args.mode == "traffic" else
                           "exiting with last active thread context" in event.getCause()))
print("EXIT:", event.getCause(), "code", event.getCode(), "tick", m5.curTick())
if args.mode == "tester":
    if event.getCause() != "AXI packet/data/retry tests passed":
        raise RuntimeError("tester did not complete")
elif args.mode == "traffic":
    if event.getCause() != "AXI bandwidth traffic completed" or event.getCode() != 0:
        raise RuntimeError("bandwidth traffic did not complete")
else:
    if "exiting with last active thread context" not in event.getCause() or event.getCode() != 0:
        raise RuntimeError("CPU workload did not pass")
