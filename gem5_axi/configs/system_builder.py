"""Shared construction of the configured AXI/UCIe/Ramulator2 path."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'env'))

from generate_ramulator_config import runtime_configs
from topology_config import interleaved_ranges, load as load_topology, simobject_params
from m5.objects import AddrRange, AxiDemo, Gem5ToTlmBridge64, NoncoherentXBar


def load(args):
    topology = load_topology(args)
    links = len(topology['modules'])
    ports = len(topology.get('axi_ports') or topology['modules'])
    return topology, links, ports


def create_axi(system, args, out, topology, *, base, size, period,
               default_channels, outstanding, planes, stalls,
               legacy_memory=None):
    legacy_memory = legacy_memory or {}
    link_count = len(topology['modules'])
    system.axi = AxiDemo(
        backend=getattr(args, 'backend', 'aou'), memory_backend=args.memory_backend,
        storage_bridge_implementation=os.environ.get('SS_STORAGE_BRIDGE_IMPL', 'systemc'),
        base=base, size=size,
        period=period, ramulator_config='',
        ramulator_configs=runtime_configs(
            args, out, link_count, default_channels, topology=topology),
        **simobject_params(topology),
        ramulator_slots=args.ramulator_slots,
        ramulator_children=args.ramulator_children,
        ramulator_submit_width=args.ramulator_submit_width,
        ramulator_response_hold=args.ramulator_response_hold,
        fdi_fifo_depth=args.fdi_fifo_depth,
        memory_fifo_depth=args.memory_fifo_depth,
        outstanding=outstanding, planes=planes, stalls=stalls,
        replay=args.replay, trace_dir=str(out), **legacy_memory)
    return system.axi


def connect(system, topology, ranges, axi_data_width):
    module_ranges = interleaved_ranges(AddrRange, ranges, topology)
    system.bridges = [Gem5ToTlmBridge64(addr_ranges=item) for item in module_ranges]
    for index, bridge in enumerate(system.bridges):
        bridge.tlm = system.axi.tlm[index]
    if len(system.bridges) == 1:
        return system.bridges[0].gem5
    system.target_xbar = NoncoherentXBar(
        width=(axi_data_width // 8) * len(system.bridges),
        frontend_latency=0, forward_latency=0, response_latency=0,
        header_latency=0)
    for bridge in system.bridges:
        system.target_xbar.mem_side_ports = bridge.gem5
    return system.target_xbar.cpu_side_ports
