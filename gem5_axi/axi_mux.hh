#pragma once

#include "axi_signals.hh"
#include <systemc>
#include <cstdint>
#include <deque>
#include <string>
#include <vector>

namespace storage_axi {

// Cycle-accurate AXI4 subset arbiter used when several equal-width AXI ports
// share one AXI2Flit/UCIe path.  IDs are translated into disjoint ranges so a
// response can be routed without relying on non-serialized FDI metadata.
class AxiMux : public sc_core::sc_module {
  public:
    sc_core::sc_in<bool> clk{"clk"}, resetn{"resetn"};
    SC_HAS_PROCESS(AxiMux);
    AxiMux(sc_core::sc_module_name, std::vector<Signals*> inputs, Signals& output,
           std::vector<unsigned> global_port_ids, unsigned clock_divider,
           std::vector<unsigned> clock_phases, const std::string& trace_dir);
    unsigned localMaxId() const { return localMax; }
    unsigned encode(unsigned local_port, unsigned local_id) const;
    unsigned decodePort(unsigned global_id) const;
    unsigned decodeLocal(unsigned global_id) const;
    unsigned clockRatio() const { return clockDivider; }
    bool idle() const;
    void finish();

  private:
    struct AddrBeat {
        uint64_t address = 0;
        unsigned id = 0, len = 0, size = 0, burst = 0;
    };
    struct WriteBeat { Data data = 0; Strb strb = 0; bool last = false; };
    struct BBeat { unsigned id = 0, resp = 0; };
    struct RBeat { unsigned id = 0, resp = 0; Data data = 0; bool last = false; };
    struct Counts {
        uint64_t aw = 0, w = 0, b = 0, ar = 0, r = 0;
        uint64_t aw_wait = 0, ar_wait = 0, w_wait = 0;
        uint64_t max_aw_buffer = 0, max_w_buffer = 0, max_ar_buffer = 0;
        uint64_t max_b_buffer = 0, max_r_buffer = 0;
    };
    std::vector<Signals*> in;
    Signals& out;
    std::vector<unsigned> portIds;
    unsigned clockDivider = 1;
    std::vector<unsigned> clockPhases;
    uint64_t fabricCycle = 0;
    std::string directory;
    unsigned localMax = 0, rrWrite = 0, rrRead = 0;
    int writePort = -1, readPort = -1;
    bool writeAwSent = false;
    unsigned writeBeatsRemaining = 0;
    uint64_t cycles = 0;
    static constexpr unsigned AddrDepth = 1024;
    static constexpr unsigned DataDepth = 4096;
    static constexpr unsigned ResponseDepth = 4096;
    std::vector<std::deque<AddrBeat>> awQueues, arQueues;
    std::vector<std::deque<WriteBeat>> wQueues;
    std::vector<std::deque<BBeat>> bQueues;
    std::vector<std::deque<RBeat>> rQueues;
    std::vector<Counts> counts;
    sc_core::sc_event changed;
    int chooseWrite() const;
    int chooseRead() const;
    bool completeWrite(unsigned port) const;
    bool active(unsigned port) const;
    void comb();
    void tick();
};

}
