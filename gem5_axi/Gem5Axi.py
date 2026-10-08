from m5.objects.SystemC import SystemC_ScModule
from m5.objects.Tlm import VectorTlmTargetSocket
from m5.objects.Device import BasicPioDevice
from m5.SimObject import SimObject, PyBindMethod
from m5.params import *
from m5.proxy import Parent


class AxiDemo(SystemC_ScModule):
    type = 'AxiDemo'
    cxx_class = 'storage_axi::Demo'
    cxx_header = 'gem5_axi/axi_demo.hh'
    cxx_exports = [PyBindMethod('finish')]
    system = Param.System(Parent.any, 'Requestor names for metrics')
    tlm = VectorTlmTargetSocket(64, 'One nonblocking transaction input per AXI/UCIe module')
    topology_modules = Param.Unsigned(1, 'Number of parallel AXI/UCIe modules')
    ucie_lanes = VectorParam.Unsigned([16], 'Physical lanes for every UCIe module')
    ucie_rates = VectorParam.Float([24.0], 'Per-lane transfer rate in GT/s')
    ucie_bits_per_symbol = VectorParam.Unsigned([1], '1=NRZ, 2=PAM4 for every module')
    topology_policy = Param.String('single', 'single, address_interleave or source_ranges')
    topology_stripe_bytes = Param.UInt64(256, 'Address interleave stripe size')
    topology_resolved = Param.String('', 'Resolved topology JSON copied into the result')
    backend = Param.String('ram', 'ram or aou full UCIe path')
    planes = Param.Unsigned(1, 'AoU resource planes (1..4)')
    replay = Param.Bool(False, 'Inject reproducible 2% physical flit errors')
    memory_backend = Param.String('simple', 'simple, ramulator2 or optional memsim after UCIe')
    ramulator_config = Param.String('', 'Fully expanded External Ramulator2 config')
    ramulator_configs = VectorParam.String([], 'One expanded Ramulator2 config per memory node')
    ramulator_slots = Param.Unsigned(8, 'Bounded in-flight AXI bursts')
    ramulator_children = Param.Unsigned(32, 'Bounded native transactions')
    ramulator_submit_width = Param.Unsigned(8, 'Maximum native child submissions per DRAM tick')
    ramulator_response_hold = Param.Unsigned(0, 'Response hold in DRAM ticks')
    memsim_channels = Param.Unsigned(2, 'HBM4 channel count for integration')
    memsim_scale = Param.Unsigned(1, 'Multiply native HBM clock period')
    memsim_queue = Param.Unsigned(4, 'Native ingress/controller/response capacity')
    memsim_slots = Param.Unsigned(8, 'Bounded in-flight AXI bursts')
    memsim_response_hold = Param.Unsigned(0, 'Stress-test response hold in memory ticks')
    # 32 B / 666667 fs = 47.999976 GB/s, matching the default 16 x 24 GT/s
    # NRZ UCIe raw capacity (48 GB/s) to avoid an accidental AXI bottleneck.
    period = Param.Latency('666667fs', 'AXI clock period')
    base = Param.Addr(0x90000000, 'RAM base')
    size = Param.UInt64(8192, 'Target memory window size in bytes')
    outstanding = Param.Unsigned(4, 'Bounded TLM transaction slots')
    latency = Param.Unsigned(3, 'RAM response latency in AXI cycles')
    stalls = Param.Bool(True, 'Deterministic stalls on all five channels')
    trace_dir = Param.String('', 'Directory for CSV/VCD traces')


class AxiPacketTester(SimObject):
    type = 'AxiPacketTester'
    cxx_class = 'gem5::AxiPacketTester'
    cxx_header = 'gem5_axi/packet_tester.hh'
    system = Param.System(Parent.any, 'Parent system')
    port = RequestPort('Timing/functional request source')
    base = Param.Addr(0x90000000, 'Target base')
    trace_dir = Param.String('', 'Result directory')
    response_hold = Param.Latency('7ns', 'Hold each response before retry')
    traffic_mode = Param.String('validation', 'validation or bandwidth')
    traffic_warmup_requests = Param.Unsigned(0, 'Completed requests excluded before measurement')
    traffic_measure_requests = Param.Unsigned(0, 'Requests in the steady measurement window')
    traffic_cooldown_requests = Param.Unsigned(0, 'Requests after measurement that preserve offered load while draining')
    traffic_request_size = Param.Unsigned(256, 'Bytes per bandwidth request')
    traffic_working_set = Param.UInt64(1024 * 1024, 'Bandwidth traffic address working set')
    traffic_write_percent = Param.Percent(50, 'Bandwidth traffic write percentage')
    traffic_max_inflight = Param.Unsigned(64, 'Maximum tester requests in flight')
    traffic_issue_interval = Param.Latency('0ns', 'Minimum interval between generated requests; zero means saturation')
    traffic_offered_load_percent = Param.Float(0.0, 'Requested payload load relative to the AXI data-channel peak')


class MetricsMarker(BasicPioDevice):
    type = 'MetricsMarker'
    cxx_class = 'gem5::MetricsMarker'
    cxx_header = 'gem5_axi/metrics_marker.hh'
    # Override inherited defaults; redeclaring Param would shadow the C++
    # BasicPioDeviceParams fields and leave the base address uninitialized.
    pio_addr = 0x70000000
    pio_latency = '1ns'
    trace_dir = Param.String('', 'Statistics output directory')
