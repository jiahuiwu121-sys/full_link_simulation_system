#include "ramulator_backend.hh"
#include "axi_contract.h"
#include "sim/cur_tick.hh"
#include <algorithm>
#include <iomanip>
#include <stdexcept>
using namespace sc_core;

RamulatorBackend::RamulatorBackend(sc_module_name name, uint64_t base_, uint64_t size_,
 unsigned slots_, unsigned children_, unsigned hold_, const std::string& config, const std::string& dir_)
 : sc_module(name), base(base_), size(size_), slots(slots_), childLimit(children_), hold(hold_),
   backing(size_), dir(dir_), log(dir + "/ramulator_bridge.csv"), commands(dir + "/ramulator_commands.csv") {
    if (!slots || !childLimit || !size || base > UINT64_MAX - size || config.empty())
        throw std::invalid_argument("invalid ramulator window/capacities/configuration");
    native = ssr_create(config.c_str(), children_, 1, dir.c_str());
    if (!native) throw std::runtime_error(ssr_error());
    try {
        checked(ssr_get_info(native, &info));
        if (info.abi_version != SSR_ABI_VERSION || info.struct_bytes != sizeof(info) ||
            !info.transaction_bytes || !info.period_fs || size > info.capacity_bytes ||
            base % info.transaction_bytes || size % info.transaction_bytes)
            throw std::invalid_argument("Ramulator ABI/geometry does not cover target window");
        period = info.period_fs;
        log << "tick,event,burst,rp,axi_id,command,address,bytes,offset,token,issued_cycle,completion_cycle,status,data,mask\n";
        commands << "tick,cycle,token,command,channel,address,level0,level1,level2,level3,level4,level5,level6,level7\n";
        if (!log || !commands) throw std::runtime_error("cannot open ramulator logs");
    } catch (...) { ssr_destroy(native); native = nullptr; throw; }
    SC_THREAD(run);
}
RamulatorBackend::~RamulatorBackend() { ssr_destroy(native); }
int RamulatorBackend::checked(int n) {
    if (n < 0) SC_REPORT_FATAL("ramulator2", ssr_error());
    return n;
}
void RamulatorBackend::event(const char* what, const Burst& b, unsigned off, unsigned n,
 uint64_t token, uint64_t issue, uint64_t complete, const uint8_t* data, const uint8_t* mask) {
    const auto tick = gem5::curTick(); sc_assert(tick == sc_time_stamp().value());
    log << tick << ',' << what << ',' << b.serial << ',' << unsigned(b.req.rp) << ',' << b.req.address.id
        << ',' << (b.req.write ? 'W' : 'R') << ',' << b.req.address.addr + off << ',' << n << ',' << off
        << ',' << token << ',' << issue << ',' << complete << ',' << unsigned(b.rsp.resp) << ',';
    if (data) for (unsigned j = 0; j < n; ++j)
        log << std::hex << std::setw(2) << std::setfill('0') << unsigned(data[j]);
    log << std::dec << ',';
    if (mask) for (unsigned j = 0; j < n; ++j) log << (mask[j] ? '1' : '0');
    log << '\n';
}
void RamulatorBackend::accept(SimpleMemRequest req) {
    auto b = std::make_shared<Burst>(); b->serial = nextBurst++; b->req = std::move(req);
    const auto& a = b->req.address;
    if (axi_request_error(a) || (b->req.write && b->req.write_beats.size() != b->req.beats()))
        SC_REPORT_FATAL("ramulator2", "invalid AXI burst structure");
    const unsigned width = 1u << a.size;
    b->length = width * b->req.beats(); b->data.resize(b->length); b->mask.resize(b->length, 1);
    b->rsp.write = b->req.write; b->rsp.rp = b->req.rp; b->rsp.id = a.id; b->rsp.user = a.user;
    unsigned status = (a.addr < base || a.addr - base >= size || b->length > size - (a.addr - base)) ? 3 : (a.lock ? 2 : 0);
    if (b->req.write) {
        for (unsigned beat = 0; beat < b->req.beats(); ++beat) {
            const unsigned lane = (a.addr + beat * width) % AXI_DATA_BYTES;
            const auto& w = b->req.write_beats[beat];
            for (unsigned j = 0; j < AXI_DATA_BYTES; ++j)
                if (w.strobe[j] && (j < lane || j >= lane + width)) status = 2;
            for (unsigned j = 0; j < width; ++j) {
                b->data[beat * width + j] = w.data[lane + j]; b->mask[beat * width + j] = w.strobe[lane + j] != 0;
            }
        }
    } else {
        b->rsp.read_beats.resize(b->req.beats());
        for (auto& beat : b->rsp.read_beats) { beat.user = a.user; beat.resp = status; }
    }
    b->rsp.resp = status;
    if (!status) for (unsigned off = 0; off < b->length;) {
        const auto addr = a.addr - base + off;
        const unsigned n = std::min<unsigned>(b->length - off, info.transaction_bytes - addr % info.transaction_bytes);
        Descriptor d; d.token = nextToken++; d.address = addr - addr % info.transaction_bytes; d.offset = off; d.bytes = n;
        // Reserve every child now, including those not submitted: a younger parent
        // must never overtake an earlier unsent access to the same transaction.
        hazards[d.address].push_back(d.token); b->descriptors.push_back(d); ++b->remaining; off += n;
    }
    event("accept", *b, 0, b->length, 0, 0, 0, b->req.write ? b->data.data() : nullptr,
          b->req.write ? b->mask.data() : nullptr);
    bursts.push_back(b);
}
void RamulatorBackend::submit() {
    if (active.size() >= childLimit) { ++submitStalls; ++childLimitCycles; return; }
    bool hazardThisCycle = false;
    for (const auto& b : bursts) for (unsigned i = 0; i < b->descriptors.size(); ++i) {
        auto& d = b->descriptors[i]; if (d.submitted) continue;
        if (hazards.at(d.address).front() != d.token) {
            ++hazardStalls;
            if (!hazardThisCycle) { ++hazardCycles; hazardThisCycle = true; }
            continue;
        }
        const int accepted = checked(ssr_submit(native, d.token, d.address, b->req.write));
        if (accepted) {
            d.submitted = true; active.emplace(d.token, Child{b, i}); ++submitted;
            event("submit", *b, d.offset, d.bytes, d.token, 0, 0,
                  b->req.write ? b->data.data() + d.offset : nullptr,
                  b->req.write ? b->mask.data() + d.offset : nullptr);
        } else { ++submitStalls; ++nativeRejectCycles; event("submit_stall", *b, d.offset, d.bytes, d.token); }
        return; // At most one actual submission per DRAM tick.
    }
}
void RamulatorBackend::process(const ssr_event& e) {
    sc_assert(e.abi_version == SSR_ABI_VERSION && e.struct_bytes == sizeof(e));
    sc_assert(e.cycle * period == gem5::curTick());
    if (e.kind == 1) {
        commands << gem5::curTick() << ',' << e.cycle << ',' << e.token << ',' << e.command_name
                 << ',' << e.channel << ',' << e.address;
        for (auto coordinate : e.coordinates) commands << ',' << coordinate;
        commands << '\n';
        if (e.token) {
            auto it = active.find(e.token); sc_assert(it != active.end());
            auto& b = *it->second.burst; const auto& d = b.descriptors[it->second.index];
            event("issue", b, d.offset, d.bytes, d.token, e.cycle);
        }
        return;
    }
    sc_assert(e.kind == 2);
    auto it = active.find(e.token); sc_assert(it != active.end());
    auto& b = *it->second.burst; auto& d = b.descriptors[it->second.index];
    sc_assert(!d.complete && d.address == e.address && bool(e.write) == b.req.write);
    const auto relative = b.req.address.addr - base + d.offset;
    if (b.req.write) backing.write(relative, d.bytes, b.data.data() + d.offset, b.mask.data() + d.offset);
    else {
        backing.read(relative, d.bytes, b.data.data() + d.offset);
        const unsigned width = 1u << b.req.address.size;
        for (unsigned j = 0; j < d.bytes; ++j) {
            const unsigned off = d.offset + j;
            b.rsp.read_beats[off / width].data[(b.req.address.addr + off) % AXI_DATA_BYTES] = b.data[off];
        }
    }
    event("service", b, d.offset, d.bytes, d.token, e.issue_cycle, e.cycle,
          b.data.data() + d.offset, b.req.write ? b.mask.data() + d.offset : nullptr);
    d.complete = true; --b.remaining; ++services;
    auto h = hazards.find(d.address); sc_assert(h != hazards.end() && h->second.front() == d.token);
    h->second.pop_front(); if (h->second.empty()) hazards.erase(h);
    active.erase(it);
}
void RamulatorBackend::run() {
    while (true) {
        wait(sc_time::from_value(period));
        sc_assert((cycle + 1) * period == gem5::curTick());
        checked(ssr_step(native)); ++cycle;
        ssr_event e; while (checked(ssr_poll_event(native, &e))) process(e);
        // Post-service, pre-return/admission sample; no queue or scheduling mutation.
        parentDepthSum += bursts.size(); childDepthSum += active.size();
        parentPeak = std::max<uint64_t>(parentPeak, bursts.size());
        childPeak = std::max<uint64_t>(childPeak, active.size());
        if (bursts.size() >= slots && request.num_available()) ++ingressFullCycles;
        if (!bursts.empty() && bursts.front()->remaining &&
            std::any_of(bursts.begin() + 1, bursts.end(), [](const auto& b) { return !b->remaining; })) ++holCycles;
        if (!bursts.empty()) {
            auto& b = *bursts.front();
            if (!b.remaining) {
                if (!b.ready) b.ready = gem5::curTick() + uint64_t(hold) * period;
                if (gem5::curTick() >= b.ready && response.nb_write(b.rsp)) {
                    event("return", b, 0, b.length, 0, 0, 0, b.req.write ? nullptr : b.data.data());
                    ++completed; if (b.rsp.resp) ++error_responses; bursts.pop_front();
                } else {
                    ++responseStalls;
                    if (gem5::curTick() < b.ready) ++holdCycles;
                    else ++responseFifoCycles;
                }
            }
        }
        SimpleMemRequest req;
        if (bursts.size() < slots && request.nb_read(req)) accept(std::move(req));
        submit();
    }
}
void RamulatorBackend::finish() {
    log.flush(); commands.flush();
    sc_assert(bursts.empty() && active.empty() && hazards.empty() && request.num_available() == 0);
    sc_assert(checked(ssr_is_idle(native)) == 1); checked(ssr_finish(native));
    backing.dump(dir + "/ramulator_final_image.csv", base);
    std::ofstream f(dir + "/ramulator_backend_summary.json");
    f << "{\"passed\":true,\"drained\":true,\"bursts\":" << completed << ",\"errors\":" << error_responses
      << ",\"submitted\":" << submitted << ",\"services\":" << services << ",\"submit_stalls\":" << submitStalls
      << ",\"hazard_stalls\":" << hazardStalls << ",\"response_stalls\":" << responseStalls
      << ",\"period_fs\":" << period << ",\"base\":" << base << ",\"size\":" << size
      << ",\"native_end_tick_fs\":" << cycle * period << ",\"simulation_end_tick_fs\":" << gem5::curTick()
      << ",\"allocated_pages\":" << backing.allocatedPages() << ",\"ordering\":\"transaction serialized; parent FIFO\"}\n";
    std::ofstream m(dir + "/backend_queue_metrics.json");
    m << "{\"cycles\":" << cycle << ",\"period_fs\":" << period
      << ",\"measurement\":\"post-service pre-return/admission cycle samples\""
      << ",\"parent_depth_cycle_sum\":" << parentDepthSum << ",\"child_depth_cycle_sum\":" << childDepthSum
      << ",\"parent_peak\":" << parentPeak << ",\"child_peak\":" << childPeak
      << ",\"parent_capacity\":" << slots << ",\"child_capacity\":" << childLimit
      << ",\"stall_cycles\":{\"ingress_full\":" << ingressFullCycles
      << ",\"child_limit\":" << childLimitCycles << ",\"native_reject\":" << nativeRejectCycles
      << ",\"address_hazard\":" << hazardCycles << ",\"forced_response_hold\":" << holdCycles
      << ",\"response_fifo_full\":" << responseFifoCycles << ",\"parent_fifo_hol\":" << holCycles << "}}\n";
}
