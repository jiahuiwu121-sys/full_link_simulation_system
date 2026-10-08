#include "axi_demo.hh"
#include "aou_backend.hh"
#include "systemc/tlm_bridge/gem5_to_tlm.hh"
#include "systemc/utils/tracefile.hh"
#include "sim/core.hh"
#include "sim/system.hh"
#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <stdexcept>

namespace storage_axi {
using namespace sc_core;
namespace fs = std::filesystem;

namespace {
template<class T>
T vectorValue(const std::vector<T>& values, unsigned i, unsigned count,
              const char* name) {
    if (values.size() == 1) return values.front();
    if (values.size() == count) return values.at(i);
    throw std::invalid_argument(std::string(name) +
        " must contain one value or one value per topology module");
}

void mergeCsv(const std::string& output, const std::vector<std::string>& dirs,
              const std::string& filename) {
    std::ofstream out(output);
    bool header = false;
    for (unsigned i = 0; i < dirs.size(); ++i) {
        std::ifstream in(dirs[i] + "/" + filename);
        std::string line;
        if (!std::getline(in, line)) continue;
        if (!header) { out << "module," << line << '\n'; header = true; }
        while (std::getline(in, line)) out << i << ',' << line << '\n';
    }
}
}

Demo::Demo(const gem5::AxiDemoParams& p)
    : Demo(sc_module_name(p.name.c_str()), p) {}

Demo::Demo(sc_module_name n, const gem5::AxiDemoParams& p)
    : sc_module(n), clock("aclk", sc_time::from_value(p.period)),
      directory(p.trace_dir), topologyPolicy(p.topology_policy) {
    const unsigned count = p.topology_modules;
    if (!count || count > 64) throw std::invalid_argument("topology_modules must be in [1,64]");
    if (p.backend == "ram" && count != 1)
        throw std::invalid_argument("parallel topology requires backend=aou");
    if (p.memory_backend != "memsim" && p.memory_backend != "ramulator2" &&
        p.size > UINT32_MAX)
        throw std::invalid_argument("test RAM size exceeds 32-bit limit");
    if (p.outstanding > 1023 && p.backend == "aou")
        throw std::runtime_error("AoU supports at most 1023 live IDs per module");

    fs::create_directories(directory);
    if (!p.topology_resolved.empty()) {
        std::ofstream topology(directory + "/topology_resolved.json");
        topology << p.topology_resolved << '\n';
    }

    wires.reserve(count); masters.reserve(count); rams.reserve(count);
    aous.reserve(count); wrappers.reserve(count); vcds.reserve(count);
    events.reserve(count); linkDirectories.reserve(count); metrics.resize(count);
    for (unsigned i = 0; i < count; ++i) {
        const std::string suffix = std::to_string(i);
        const std::string linkDir = count == 1 ? directory :
            directory + "/links/link" + suffix;
        fs::create_directories(linkDir);
        linkDirectories.push_back(linkDir);
        wires.push_back(std::make_unique<Signals>("link" + suffix));
        masters.push_back(std::make_unique<Master>(("master" + suffix).c_str(),
            p.outstanding, p.stalls, linkDir, i));
        auto& master = *masters.back();
        master.requestorName = [system = p.system](uint32_t id) {
            return system->getRequestorName(id);
        };
        master.clk(clock); master.resetn(resetn); master.axi.bind(*wires.back());

        if (p.backend == "aou") {
            master.maxId = 1023;
            std::string ramConfig = p.ramulator_config;
            if (!p.ramulator_configs.empty())
                ramConfig = vectorValue<std::string>(p.ramulator_configs, i, count,
                                                      "ramulator_configs");
            aous.push_back(std::make_unique<AouBackend>(("aou" + suffix).c_str(), p,
                i, linkDir, ramConfig,
                vectorValue<unsigned>(p.ucie_lanes, i, count, "ucie_lanes"),
                vectorValue<double>(p.ucie_rates, i, count, "ucie_rates"),
                vectorValue<unsigned>(p.ucie_bits_per_symbol, i, count,
                                      "ucie_bits_per_symbol")));
            rams.push_back(nullptr);
            auto& aou = *aous.back();
            aou.clk(clock); aou.resetn(resetn); aou.axi.bind(*wires.back());
            master.functional = [&aou](tlm::tlm_generic_payload& gp) {
                return aou.access(gp);
            };
        } else if (p.backend == "ram") {
            aous.push_back(nullptr);
            rams.push_back(std::make_unique<Ram>(("ram" + suffix).c_str(), p.base,
                p.size, p.latency, p.stalls));
            auto& ram = *rams.back();
            ram.clk(clock); ram.resetn(resetn); ram.axi.bind(*wires.back());
            master.functional = [&ram](tlm::tlm_generic_payload& gp) {
                return ram.access(gp);
            };
        } else throw std::runtime_error("unknown backend");

        wrappers.push_back(std::make_unique<sc_gem5::TlmTargetWrapper<64>>(
            master.socket, std::string(name()) + ".tlm[" + suffix + "]", i));
        events.push_back(std::make_unique<std::ofstream>(linkDir + "/axi_events.csv"));
        if (!*events.back()) throw std::runtime_error("cannot open AXI trace");
        *events.back() << "tick,cycle,channel,id,address,len,size,data,strb,last,resp\n";
        auto* vcd = sc_create_vcd_trace_file((linkDir + "/axi_wave").c_str());
        vcd->set_time_unit(1, SC_FS);
        sc_trace(vcd, clock, "ACLK"); sc_trace(vcd, resetn, "ARESETn");
        wires.back()->trace(vcd);
        if (aous.back()) aous.back()->trace(vcd);
        vcds.push_back(vcd);
    }

    static bool conversionInstalled = false;
    if (!conversionInstalled) {
        sc_gem5::addPacketToPayloadConversionStep([](gem5::PacketPtr pkt,
                                                     tlm::tlm_generic_payload& gp) {
            auto* a = gp.get_extension<RequestAttributes>();
            if (!a) { a = new RequestAttributes(); gp.set_auto_extension(a); }
            const auto& be = pkt->req->getByteEnable();
            a->enables.assign(pkt->getSize(), 0xff);
            if (!be.empty()) {
                sc_assert(be.size() == pkt->getSize());
                for (unsigned i = 0; i < be.size(); ++i)
                    a->enables[i] = be[i] ? 0xff : 0;
            }
            gp.set_byte_enable_ptr(a->enables.data());
            gp.set_byte_enable_length(a->enables.size());
            a->requestor = pkt->req->requestorId();
            a->hasStream = pkt->req->hasStreamId();
            a->stream = a->hasStream ? pkt->req->streamId() : 0;
            a->hasSubstream = pkt->req->hasSubstreamId();
            a->substream = a->hasSubstream ? pkt->req->substreamId() : 0;
            a->payloadDelay = pkt->payloadDelay;
            a->packetId = pkt->id;
            if (pkt->isAtomicOp() || pkt->isLLSC() || pkt->isLockedRMW() ||
                pkt->req->isSwap() || pkt->req->isCacheMaintenance())
                gp.set_command(tlm::TLM_IGNORE_COMMAND);
        });
        conversionInstalled = true;
    }
    SC_THREAD(reset);
    SC_METHOD(sample); sensitive << clock.posedge_event(); dont_initialize();
}

Demo::~Demo() = default;

void Demo::reset() {
    resetn = false;
    wait(clock.period() * 3 + clock.period() / 2);
    for (;;) {
        bool allReady = true;
        for (const auto& aou : aous) if (aou && !aou->ready()) allReady = false;
        if (allReady) break;
        wait(clock.period());
    }
    resetn = true;
}

gem5::Port& Demo::gem5_getPort(const std::string& n, int idx) {
    if (n != "tlm") throw std::runtime_error("unknown AxiDemo port: " + n);
    if (idx < 0 && wrappers.size() == 1) idx = 0;
    if (idx < 0 || unsigned(idx) >= wrappers.size())
        throw std::runtime_error("AxiDemo TLM port index out of range");
    return *wrappers.at(idx);
}

void Demo::channel(unsigned link, const std::string& n, bool valid, bool ready,
                   const std::vector<Data>& payload) {
    auto& m = metrics.at(link);
    auto it = m.held.find(n);
    if (it != m.held.end() && (!valid || payload != it->second))
        SC_REPORT_FATAL("AXI stability", ("link" + std::to_string(link) + ":" + n).c_str());
    if (valid && !ready) { m.held[n] = payload; ++m.stalled[n]; }
    else m.held.erase(n);
    if (valid && ready) ++m.handshakes[n];
    if (!valid && ready) ++m.readyIdle[n];
    if (!valid && !ready) ++m.blockedIdle[n];
}

void Demo::row(unsigned link, const char* n, uint64_t id, uint64_t a,
               unsigned len, unsigned size, Data d, const Strb& strb,
               bool last, unsigned resp) {
    *events.at(link) << sc_time_stamp().value() << ',' << cycle << ',' << n << ','
        << id << ',' << a << ',' << len << ',' << size << ','
        << d.to_string(sc_dt::SC_DEC, false) << ','
        << strb.to_string(sc_dt::SC_DEC, false) << ',' << last << ',' << resp << '\n';
}

void Demo::sample() {
    ++cycle;
    sc_assert(sc_time_stamp().value() == gem5::curTick());
    if (!resetn.read()) return;
    for (unsigned i = 0; i < wires.size(); ++i) {
        auto& m = metrics[i];
        if (!m.measuredCycles) m.firstMeasuredTick = sc_time_stamp().value();
        ++m.measuredCycles; m.lastMeasuredTick = sc_time_stamp().value();
        auto& w = *wires[i];
        channel(i,"AW",w.awvalid,w.awready,{Data(w.awid.read()),Data(w.awaddr.read()),Data(w.awlen.read()),Data(w.awsize.read()),Data(w.awburst.read())});
        channel(i,"W",w.wvalid,w.wready,{w.wdata.read(),Data(w.wstrb.read()),Data(w.wlast.read())});
        channel(i,"B",w.bvalid,w.bready,{Data(w.bid.read()),Data(w.bresp.read())});
        channel(i,"AR",w.arvalid,w.arready,{Data(w.arid.read()),Data(w.araddr.read()),Data(w.arlen.read()),Data(w.arsize.read()),Data(w.arburst.read())});
        channel(i,"R",w.rvalid,w.rready,{Data(w.rid.read()),w.rdata.read(),Data(w.rresp.read()),Data(w.rlast.read())});
        if (w.awvalid && w.awready) row(i,"AW",w.awid.read(),w.awaddr.read(),w.awlen.read(),w.awsize.read());
        if (w.wvalid && w.wready) row(i,"W",0,0,0,0,w.wdata.read(),w.wstrb.read(),w.wlast.read());
        if (w.bvalid && w.bready) row(i,"B",w.bid.read(),0,0,0,0,Strb(0),false,w.bresp.read());
        if (w.arvalid && w.arready) row(i,"AR",w.arid.read(),w.araddr.read(),w.arlen.read(),w.arsize.read());
        if (w.rvalid && w.rready) row(i,"R",w.rid.read(),0,0,0,w.rdata.read(),Strb(0),w.rlast.read(),w.rresp.read());
        events[i]->flush();
    }
}

void Demo::writeProtocolSummary(const std::string& path, unsigned link) {
    auto& master = *masters.at(link); auto& m = metrics.at(link);
    std::ofstream f(path);
    f << "{\"accepted\":" << master.accepted << ",\"completed\":" << master.completed
      << ",\"max_outstanding\":" << master.maxActive << ",\"drained\":"
      << (master.idle() ? "true" : "false") << ",\"ticks_per_second\":"
      << gem5::sim_clock::Frequency << ",\"period_ticks\":" << clock.period().value()
      << ",\"axi_data_bits\":" << DataBits << ",\"module\":" << link
      << ",\"measured_cycles\":" << m.measuredCycles
      << ",\"first_measured_tick_fs\":" << m.firstMeasuredTick
      << ",\"last_measured_tick_fs\":" << m.lastMeasuredTick
      << ",\"simulation_end_tick_fs\":" << gem5::curTick() << ",\"channels\":{";
    bool first = true;
    for (auto n : {"AW", "W", "B", "AR", "R"}) {
        if (!first) f << ',';
        first = false;
        f << '"' << n << "\":{\"handshakes\":" << m.handshakes[n]
          << ",\"stall_cycles\":" << m.stalled[n]
          << ",\"ready_idle_cycles\":" << m.readyIdle[n]
          << ",\"blocked_idle_cycles\":" << m.blockedIdle[n] << '}';
    }
    f << "}}\n";
}

void Demo::finish() {
    if (finished) return;
    finished = true;
    uint64_t accepted = 0, completed = 0, maxOutstanding = 0;
    for (unsigned i = 0; i < masters.size(); ++i) {
        events[i]->flush();
        if (aous[i]) aous[i]->finish(linkDirectories[i]);
        if (vcds[i]) {
            static_cast<sc_gem5::TraceFile*>(vcds[i])->trace(false);
            sc_close_vcd_trace_file(vcds[i]); vcds[i] = nullptr;
        }
        writeProtocolSummary(linkDirectories[i] + "/protocol_summary.json", i);
        accepted += masters[i]->accepted; completed += masters[i]->completed;
        maxOutstanding += masters[i]->maxActive;
    }
    if (masters.size() > 1) {
        mergeCsv(directory + "/transactions.csv", linkDirectories, "transactions.csv");
        mergeCsv(directory + "/request_segments.csv", linkDirectories, "request_segments.csv");
        mergeCsv(directory + "/request_metadata.csv", linkDirectories, "request_metadata.csv");
        mergeCsv(directory + "/axi_events.csv", linkDirectories, "axi_events.csv");
        std::ofstream p(directory + "/protocol_summary.json");
        uint64_t measuredCycles = 0;
        uint64_t firstMeasured = UINT64_MAX;
        uint64_t lastMeasured = 0;
        for (const auto& metric : metrics) {
            measuredCycles += metric.measuredCycles;
            firstMeasured = std::min(firstMeasured, metric.firstMeasuredTick);
            lastMeasured = std::max(lastMeasured, metric.lastMeasuredTick);
        }
        p << "{\"accepted\":" << accepted << ",\"completed\":" << completed
          << ",\"max_outstanding_sum\":" << maxOutstanding
          << ",\"drained\":" << (accepted == completed ? "true" : "false")
          << ",\"ticks_per_second\":" << gem5::sim_clock::Frequency
          << ",\"period_ticks\":" << clock.period().value()
          << ",\"axi_data_bits\":" << DataBits << ",\"modules\":" << masters.size()
          << ",\"measured_cycles\":" << measuredCycles
          << ",\"first_measured_tick_fs\":" << (firstMeasured == UINT64_MAX ? 0 : firstMeasured)
          << ",\"last_measured_tick_fs\":" << lastMeasured
          << ",\"simulation_end_tick_fs\":" << gem5::curTick() << ",\"channels\":{";
        bool firstChannel = true;
        for (auto name : {"AW", "W", "B", "AR", "R"}) {
            if (!firstChannel) p << ',';
            firstChannel = false;
            uint64_t handshakes = 0, stalled = 0, readyIdle = 0, blockedIdle = 0;
            for (const auto& metric : metrics) {
                handshakes += metric.handshakes.at(name);
                stalled += metric.stalled.at(name);
                readyIdle += metric.readyIdle.at(name);
                blockedIdle += metric.blockedIdle.at(name);
            }
            p << '\"' << name << "\":{\"handshakes\":" << handshakes
              << ",\"stall_cycles\":" << stalled
              << ",\"ready_idle_cycles\":" << readyIdle
              << ",\"blocked_idle_cycles\":" << blockedIdle << '}';
        }
        p << "},\"per_module\":[";
        for (unsigned i = 0; i < masters.size(); ++i) {
            if (i) p << ',';
            p << "{\"module\":" << i << ",\"accepted\":" << masters[i]->accepted
              << ",\"completed\":" << masters[i]->completed << '}';
        }
        p << "]}\n";
    }
    std::ofstream topology(directory + "/topology_summary.json");
    topology << "{\"passed\":true,\"modules\":" << masters.size()
      << ",\"policy\":\"" << topologyPolicy
      << "\",\"axi_data_bits\":" << DataBits << ",\"accepted\":" << accepted
      << ",\"completed\":" << completed << ",\"links\":[";
    for (unsigned i = 0; i < masters.size(); ++i) {
        if (i) topology << ',';
        topology << "{\"id\":" << i << ",\"result_dir\":\""
                 << fs::relative(linkDirectories[i], directory).string() << "\"}";
    }
    topology << "]}\n";
}
}
