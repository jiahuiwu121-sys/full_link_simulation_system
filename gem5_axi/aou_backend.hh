#pragma once
#include "axi_signals.hh"
#include "params/AxiDemo.hh"
#include <tlm>
#include <memory>

namespace storage_axi {
// Native configurable-width AXI signal binding and the real AoU/UCIe path.
class AouBackend : public sc_core::sc_module {
  public:
    sc_core::sc_in<bool> clk{"clk"}, resetn{"resetn"};
    SlavePorts axi;
    AouBackend(sc_core::sc_module_name, const gem5::AxiDemoParams&,
               unsigned module_index, const std::string& trace_dir,
               const std::string& ramulator_config, unsigned ucie_lanes,
               double ucie_rate_gtps, unsigned ucie_bits_per_symbol);
    ~AouBackend();
    bool ready() const;
    void trace(sc_core::sc_trace_file*);
    void finish(const std::string&);
    unsigned access(tlm::tlm_generic_payload&);
  private:
    struct Fabric;
    std::unique_ptr<Fabric> fabric;
};
}
