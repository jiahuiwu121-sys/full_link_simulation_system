#pragma once
#include "axi_master.hh"
#include "axi_ram.hh"
#include "systemc/tlm_port_wrapper.hh"
#include "params/AxiDemo.hh"
#include <fstream>
#include <map>
#include <memory>
#include <vector>

namespace storage_axi {
class AouBackend;
class Demo : public sc_core::sc_module {
  public:
    SC_HAS_PROCESS(Demo);
    explicit Demo(const gem5::AxiDemoParams&);
    gem5::Port& gem5_getPort(const std::string&, int idx = -1) override;
    void finish();
    ~Demo();
  private:
    Demo(sc_core::sc_module_name, const gem5::AxiDemoParams&);
    sc_core::sc_clock clock;
    sc_core::sc_signal<bool> resetn{"resetn"};
    std::vector<std::unique_ptr<Signals>> wires;
    std::vector<std::unique_ptr<Master>> masters;
    std::vector<std::unique_ptr<Ram>> rams;
    std::vector<std::unique_ptr<AouBackend>> aous;
    std::vector<std::unique_ptr<sc_gem5::TlmTargetWrapper<64>>> wrappers;
    std::vector<sc_core::sc_trace_file*> vcds;
    std::vector<std::unique_ptr<std::ofstream>> events;
    std::vector<std::string> linkDirectories;
    std::string directory;
    std::string topologyPolicy;
    uint64_t cycle = 0;
    bool finished = false;
    struct LinkMetrics {
        uint64_t measuredCycles = 0;
        uint64_t firstMeasuredTick = 0, lastMeasuredTick = 0;
        std::map<std::string, std::vector<Data>> held;
        std::map<std::string, uint64_t> handshakes, stalled, readyIdle, blockedIdle;
    };
    std::vector<LinkMetrics> metrics;
    void reset();
    void sample();
    void channel(unsigned link, const std::string&, bool valid, bool ready,
                 const std::vector<Data>& payload);
    void row(unsigned link, const char*, uint64_t id = 0, uint64_t addr = 0,
             unsigned len = 0, unsigned size = 0, Data data = 0,
             const Strb& strb = Strb(0), bool last = false, unsigned resp = 0);
    void writeProtocolSummary(const std::string&, unsigned link);
};
}
