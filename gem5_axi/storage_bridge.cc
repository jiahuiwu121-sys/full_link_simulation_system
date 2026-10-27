#include "storage_bridge.hh"

#include <stdexcept>

namespace storage_axi {

StorageBridge::StorageBridge(sc_core::sc_module_name name, const Config& cfg,
                             const gem5::AxiDemoParams& p,
                             const std::string& ramulator_config,
                             const std::string& trace_dir)
    : sc_module(name),
      requests("requests", p.memory_fifo_depth),
      responses("responses", p.memory_fifo_depth),
      implementation_(p.storage_bridge_implementation)
{
    if (implementation_ == "systemc") {
        target = std::make_unique<AouTarget>("target", cfg, p.planes);
        target->clk(clk); target->rst_n(resetn);
        target->link_rx(link_rx); target->link_tx(link_tx);
        target->mem_req(requests); target->mem_rsp(responses);
#ifdef SS_STORAGE_BRIDGE_RTL
    } else if (implementation_ == "rtl") {
        rtl_target = std::make_unique<RtlAouTarget>("rtl_target", p.planes);
        rtl_target->clk(clk); rtl_target->rst_n(resetn);
        rtl_target->link_rx(link_rx); rtl_target->link_tx(link_tx);
        rtl_target->mem_req(requests); rtl_target->mem_rsp(responses);
#endif
    } else {
        throw std::invalid_argument("storage bridge implementation is unavailable in this build");
    }

    if (p.memory_backend == "ramulator2") {
        ramulator = std::make_unique<RamulatorBackend>(
            "memory", p.base, p.size, p.ramulator_slots,
            p.ramulator_children, p.ramulator_submit_width,
            p.ramulator_response_hold, ramulator_config, trace_dir);
        ramulator->request(requests);
        ramulator->response(responses);
#ifdef SS_HAVE_MEMSIM
    } else if (p.memory_backend == "memsim") {
        memory = std::make_unique<MemSimBackend>(
            "memory", p.base, p.size, p.memsim_slots, p.memsim_channels,
            p.memsim_scale, p.memsim_queue, p.memsim_response_hold,
            trace_dir);
        memory->request(requests);
        memory->response(responses);
#endif
    } else if (p.memory_backend == "simple") {
        simple = std::make_unique<SimpleBurstMemory>(
            "memory", p.base, p.size,
            sc_core::sc_time::from_value(p.period * p.latency),
            sc_core::sc_time::from_value(p.period));
        simple->request(requests);
        simple->response(responses);
    } else {
        throw std::invalid_argument("unknown storage bridge memory backend");
    }
}

StorageBridge::~StorageBridge() = default;

bool StorageBridge::idle() const
{
    bool endpoint_idle = target && target->idle();
#ifdef SS_STORAGE_BRIDGE_RTL
    if (rtl_target)
        endpoint_idle = rtl_target->idle();
#endif
    return endpoint_idle && requests.num_available() == 0 &&
           responses.num_available() == 0;
}

StorageBridge::EndpointCounters StorageBridge::endpoint() const
{
    if (target)
        return {target->reads, target->writes, target->read_beats, target->write_beats};
#ifdef SS_STORAGE_BRIDGE_RTL
    return {rtl_target->reads, rtl_target->writes,
            rtl_target->read_beats, rtl_target->write_beats};
#else
    return {};
#endif
}

uint64_t StorageBridge::completed() const
{
    if (ramulator)
        return ramulator->completed;
#ifdef SS_HAVE_MEMSIM
    if (memory)
        return memory->completed;
#endif
    return simple->completed;
}

uint64_t StorageBridge::errors() const
{
    if (ramulator)
        return ramulator->error_responses;
#ifdef SS_HAVE_MEMSIM
    if (memory)
        return memory->error_responses;
#endif
    return simple->error_responses;
}

void StorageBridge::finish()
{
    sc_assert(idle());
    if (ramulator)
        ramulator->finish();
#ifdef SS_HAVE_MEMSIM
    if (memory)
        memory->finish();
#endif
}

} // namespace storage_axi
