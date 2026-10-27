#pragma once

#include <memory>
#include <string>
#include <systemc>

#include "aou_target.h"
#include "params/AxiDemo.hh"
#include "ramulator_backend.hh"
#include "simple_burst_memory.h"

#ifdef SS_STORAGE_BRIDGE_RTL
#include "rtl_aou_target.hh"
#endif

#ifdef SS_HAVE_MEMSIM
#include "memsim_backend.hh"
#endif

namespace storage_axi {

// Storage-side protocol bridge boundary.  The public contract is FDI in both
// directions; the AoU endpoint, bounded request/response FIFOs and selected
// timing/data backend remain independently testable children.
class StorageBridge : public sc_core::sc_module {
  public:
    struct EndpointCounters {
        uint64_t reads = 0, writes = 0, read_beats = 0, write_beats = 0;
    };
    sc_core::sc_in<bool> clk{"clk"};
    sc_core::sc_in<bool> resetn{"resetn"};
    sc_core::sc_fifo_in<FdiFlit> link_rx{"link_rx"};
    sc_core::sc_fifo_out<FdiFlit> link_tx{"link_tx"};

    SC_HAS_PROCESS(StorageBridge);
    StorageBridge(sc_core::sc_module_name, const Config&,
                  const gem5::AxiDemoParams&, const std::string& ramulator_config,
                  const std::string& trace_dir);
    ~StorageBridge() override;

    bool idle() const;
    void finish();
    uint64_t completed() const;
    uint64_t errors() const;
    unsigned requestAvailable() const { return requests.num_available(); }
    unsigned requestFree() const { return requests.num_free(); }
    unsigned responseAvailable() const { return responses.num_available(); }
    unsigned responseFree() const { return responses.num_free(); }

    EndpointCounters endpoint() const;
    const std::string& implementation() const { return implementation_; }

  private:
    sc_core::sc_fifo<SimpleMemRequest> requests;
    sc_core::sc_fifo<SimpleMemResponse> responses;
    std::string implementation_;
    std::unique_ptr<AouTarget> target;
#ifdef SS_STORAGE_BRIDGE_RTL
    std::unique_ptr<RtlAouTarget> rtl_target;
#endif
    std::unique_ptr<RamulatorBackend> ramulator;
    std::unique_ptr<SimpleBurstMemory> simple;
#ifdef SS_HAVE_MEMSIM
    std::unique_ptr<MemSimBackend> memory;
#endif
};

} // namespace storage_axi
