#include "axi_mux.hh"
#include "sim/cur_tick.hh"
#include <algorithm>
#include <fstream>
#include <limits>
#include <stdexcept>

namespace storage_axi {
using namespace sc_core;

AxiMux::AxiMux(sc_module_name n, std::vector<Signals*> inputs, Signals& output,
               std::vector<unsigned> global_port_ids, unsigned clock_divider,
               std::vector<unsigned> clock_phases, const std::string& trace_dir)
    : sc_module(n), in(std::move(inputs)), out(output),
      portIds(std::move(global_port_ids)), clockDivider(clock_divider),
      clockPhases(std::move(clock_phases)), directory(trace_dir),
      awQueues(in.size()), arQueues(in.size()), wQueues(in.size()),
      bQueues(in.size()), rQueues(in.size()), counts(in.size()) {
    if (in.empty() || in.size() != portIds.size() || in.size() != clockPhases.size() ||
        in.size() > 1023 || !clockDivider)
        throw std::invalid_argument("AXI mux requires 1..1023 named input ports");
    for (auto phase : clockPhases)
        if (phase >= clockDivider) throw std::invalid_argument("AXI mux phase outside divider");
    localMax = 1023 / in.size();
    if (!localMax) throw std::invalid_argument("AXI mux has no encodable local IDs");
    SC_METHOD(comb);
    sensitive << resetn << changed;
    for (auto* p : in) {
#define INPUT_SENSITIVE(T, field) sensitive << p->field;
        AXI_M2S(INPUT_SENSITIVE)
#undef INPUT_SENSITIVE
    }
#define OUTPUT_SENSITIVE(T, field) sensitive << out.field;
    AXI_S2M(OUTPUT_SENSITIVE)
#undef OUTPUT_SENSITIVE
    SC_METHOD(tick); sensitive << clk.pos(); dont_initialize();
}

unsigned AxiMux::encode(unsigned port, unsigned id) const {
    if (port >= in.size() || id < 1 || id > localMax)
        throw std::out_of_range("AXI mux local ID outside assigned range");
    return port * localMax + id;
}

unsigned AxiMux::decodePort(unsigned id) const {
    if (id < 1 || id > localMax * in.size())
        throw std::out_of_range("AXI mux response ID outside assigned ranges");
    return (id - 1) / localMax;
}

unsigned AxiMux::decodeLocal(unsigned id) const {
    return (id - 1) % localMax + 1;
}

bool AxiMux::completeWrite(unsigned port) const {
    if (port >= in.size() || awQueues[port].empty()) return false;
    const unsigned beats = awQueues[port].front().len + 1;
    return wQueues[port].size() >= beats;
}

int AxiMux::chooseWrite() const {
    for (unsigned n = 0; n < in.size(); ++n) {
        const unsigned p = (rrWrite + n) % in.size();
        if (completeWrite(p)) return int(p);
    }
    return -1;
}

int AxiMux::chooseRead() const {
    for (unsigned n = 0; n < in.size(); ++n) {
        const unsigned p = (rrRead + n) % in.size();
        if (!arQueues[p].empty()) return int(p);
    }
    return -1;
}

bool AxiMux::active(unsigned port) const {
    return port < in.size() && clockPhases[port] == fabricCycle % clockDivider;
}

void AxiMux::comb() {
    const bool on = resetn.read();
    for (auto* p : in) {
        p->awready = false; p->wready = false; p->arready = false;
        p->bvalid = false; p->bid = 0; p->bresp = 0;
        p->rvalid = false; p->rid = 0; p->rdata = 0; p->rresp = 0; p->rlast = false;
    }
    out.awvalid = false; out.awaddr = 0; out.awid = 0; out.awlen = 0;
    out.awsize = 0; out.awburst = 0;
    out.wvalid = false; out.wdata = 0; out.wstrb = 0; out.wlast = false;
    out.arvalid = false; out.araddr = 0; out.arid = 0; out.arlen = 0;
    out.arsize = 0; out.arburst = 0;
    out.bready = false; out.rready = false;
    if (!on) return;

    // Each input is sampled once per logical 1 GHz port cycle.  The queues are
    // the actual 4:1 gearbox: they decouple those edges from the 4 GHz shared
    // AXI link and keep every output payload stable under backpressure.
    for (unsigned p = 0; p < in.size(); ++p) if (active(p)) {
        in[p]->awready = awQueues[p].size() < AddrDepth;
        in[p]->wready = wQueues[p].size() < DataDepth;
        in[p]->arready = arQueues[p].size() < AddrDepth;
    }

    if (writePort >= 0 && !writeAwSent) {
        const auto& a = awQueues[writePort].front();
        out.awaddr = a.address; out.awid = a.id; out.awlen = a.len;
        out.awsize = a.size; out.awburst = a.burst; out.awvalid = true;
    }
    if (writePort >= 0 && writeAwSent) {
        const auto& w = wQueues[writePort].front();
        out.wdata = w.data; out.wstrb = w.strb;
        out.wlast = w.last; out.wvalid = true;
    }
    if (readPort >= 0) {
        const auto& a = arQueues[readPort].front();
        out.araddr = a.address; out.arid = a.id; out.arlen = a.len;
        out.arsize = a.size; out.arburst = a.burst; out.arvalid = true;
    }
    if (out.bvalid.read()) {
        try {
            const unsigned bp = decodePort(out.bid.read().to_uint());
            out.bready = bQueues[bp].size() < ResponseDepth;
        } catch (const std::exception& e) { SC_REPORT_FATAL("AxiMux", e.what()); }
    }
    if (out.rvalid.read()) {
        try {
            const unsigned rp = decodePort(out.rid.read().to_uint());
            out.rready = rQueues[rp].size() < ResponseDepth;
        } catch (const std::exception& e) { SC_REPORT_FATAL("AxiMux", e.what()); }
    }
    for (unsigned p = 0; p < in.size(); ++p) if (active(p)) {
        if (!bQueues[p].empty()) {
            const auto& b = bQueues[p].front();
            in[p]->bid = b.id; in[p]->bresp = b.resp; in[p]->bvalid = true;
        }
        if (!rQueues[p].empty()) {
            const auto& r = rQueues[p].front();
            in[p]->rid = r.id; in[p]->rdata = r.data;
            in[p]->rresp = r.resp; in[p]->rlast = r.last; in[p]->rvalid = true;
        }
    }
}

void AxiMux::tick() {
    if (!resetn.read()) {
        for (auto& q : awQueues) q.clear();
        for (auto& q : arQueues) q.clear();
        for (auto& q : wQueues) q.clear();
        for (auto& q : bQueues) q.clear();
        for (auto& q : rQueues) q.clear();
        rrWrite = rrRead = 0; writePort = readPort = -1;
        writeAwSent = false; writeBeatsRemaining = 0;
        ++fabricCycle;
        changed.notify(SC_ZERO_TIME); return;
    }
    ++cycles;

    // Capture all logical input handshakes into independent gearbox FIFOs.
    for (unsigned p = 0; p < in.size(); ++p) if (active(p)) {
        if (in[p]->awvalid.read() && in[p]->awready.read()) {
            awQueues[p].push_back({in[p]->awaddr.read().to_uint64(),
                encode(p, in[p]->awid.read().to_uint()), in[p]->awlen.read().to_uint(),
                in[p]->awsize.read().to_uint(), in[p]->awburst.read().to_uint()});
            counts[p].max_aw_buffer = std::max<uint64_t>(counts[p].max_aw_buffer,
                                                         awQueues[p].size());
        }
        else if (in[p]->awvalid.read()) ++counts[p].aw_wait;
        if (in[p]->wvalid.read() && in[p]->wready.read()) {
            wQueues[p].push_back({in[p]->wdata.read(), in[p]->wstrb.read(),
                                  in[p]->wlast.read()});
            counts[p].max_w_buffer = std::max<uint64_t>(counts[p].max_w_buffer,
                                                        wQueues[p].size());
        }
        else if (in[p]->wvalid.read()) ++counts[p].w_wait;
        if (in[p]->arvalid.read() && in[p]->arready.read()) {
            arQueues[p].push_back({in[p]->araddr.read().to_uint64(),
                encode(p, in[p]->arid.read().to_uint()), in[p]->arlen.read().to_uint(),
                in[p]->arsize.read().to_uint(), in[p]->arburst.read().to_uint()});
            counts[p].max_ar_buffer = std::max<uint64_t>(counts[p].max_ar_buffer,
                                                         arQueues[p].size());
        }
        else if (in[p]->arvalid.read()) ++counts[p].ar_wait;
    }

    if (writePort >= 0 && !writeAwSent && out.awvalid.read() && out.awready.read()) {
        writeBeatsRemaining = awQueues[writePort].front().len + 1;
        awQueues[writePort].pop_front(); writeAwSent = true;
        ++counts[writePort].aw;
    }
    if (writePort >= 0 && writeAwSent && out.wvalid.read() && out.wready.read()) {
        const bool expectedLast = writeBeatsRemaining == 1;
        if (wQueues[writePort].front().last != expectedLast)
            SC_REPORT_FATAL("AxiMux", "buffered WLAST does not match AWLEN");
        wQueues[writePort].pop_front(); ++counts[writePort].w;
        if (!--writeBeatsRemaining) {
            rrWrite = (unsigned(writePort) + 1) % in.size();
            writePort = -1; writeAwSent = false;
        }
    }
    if (readPort >= 0 && out.arvalid.read() && out.arready.read()) {
        arQueues[readPort].pop_front(); ++counts[readPort].ar;
        rrRead = (unsigned(readPort) + 1) % in.size(); readPort = -1;
    }

    if (out.bvalid.read() && out.bready.read()) {
        const unsigned p = decodePort(out.bid.read().to_uint());
        bQueues[p].push_back({decodeLocal(out.bid.read().to_uint()),
                              out.bresp.read().to_uint()});
        counts[p].max_b_buffer = std::max<uint64_t>(counts[p].max_b_buffer,
                                                    bQueues[p].size());
    }
    if (out.rvalid.read() && out.rready.read()) {
        const unsigned p = decodePort(out.rid.read().to_uint());
        rQueues[p].push_back({decodeLocal(out.rid.read().to_uint()),
            out.rresp.read().to_uint(), out.rdata.read(), out.rlast.read()});
        counts[p].max_r_buffer = std::max<uint64_t>(counts[p].max_r_buffer,
                                                    rQueues[p].size());
    }
    for (unsigned p = 0; p < in.size(); ++p) if (active(p)) {
        if (!bQueues[p].empty() && in[p]->bvalid.read() && in[p]->bready.read()) {
            bQueues[p].pop_front(); ++counts[p].b;
        }
        if (!rQueues[p].empty() && in[p]->rvalid.read() && in[p]->rready.read()) {
            rQueues[p].pop_front(); ++counts[p].r;
        }
    }

    if (writePort < 0) writePort = chooseWrite();
    if (readPort < 0) readPort = chooseRead();
    ++fabricCycle;
    changed.notify(SC_ZERO_TIME);
}

bool AxiMux::idle() const {
    if (writePort >= 0 || readPort >= 0) return false;
    auto nonempty = [](const auto& queues) {
        return std::any_of(queues.begin(), queues.end(),
                           [](const auto& q) { return !q.empty(); });
    };
    return !nonempty(awQueues) && !nonempty(arQueues) && !nonempty(wQueues) &&
           !nonempty(bQueues) && !nonempty(rQueues);
}

void AxiMux::finish() {
    std::ofstream f(directory + "/axi_aggregator.json");
    f << "{\"schema\":\"storagestacked.axi-aggregator.v1\",\"ports\":" << in.size()
      << ",\"local_id_max\":" << localMax << ",\"cycles\":" << cycles
      << ",\"clock_divider\":" << clockDivider
      << ",\"drained\":" << (idle() ? "true" : "false") << ",\"per_port\":[";
    for (unsigned i = 0; i < counts.size(); ++i) {
        if (i) f << ',';
        const auto& c = counts[i];
        f << "{\"port\":" << portIds[i] << ",\"id_base\":" << i * localMax + 1
          << ",\"id_limit\":" << (i + 1) * localMax
          << ",\"aw\":" << c.aw << ",\"w\":" << c.w << ",\"b\":" << c.b
          << ",\"ar\":" << c.ar << ",\"r\":" << c.r
          << ",\"aw_wait_cycles\":" << c.aw_wait
          << ",\"ar_wait_cycles\":" << c.ar_wait
          << ",\"w_wait_cycles\":" << c.w_wait
          << ",\"max_aw_buffer\":" << c.max_aw_buffer
          << ",\"max_w_buffer\":" << c.max_w_buffer
          << ",\"max_ar_buffer\":" << c.max_ar_buffer
          << ",\"max_b_buffer\":" << c.max_b_buffer
          << ",\"max_r_buffer\":" << c.max_r_buffer << '}';
    }
    f << "]}\n";
}

}
