#pragma once

#ifdef SS_STORAGE_BRIDGE_RTL

#include <array>
#include <deque>
#include <memory>
#include <optional>
#include <systemc>

#ifndef VL_TIME_CONTEXT
#define VL_TIME_CONTEXT
#endif
#ifndef VM_SC
#define VM_SC 0
#endif
#ifndef VM_TRACE
#define VM_TRACE 0
#endif
#include "Vstorage_bridge_top.h"
#include "simple_mem_if.h"
#include "ucie_fdi.h"
#include "verilated.h"

namespace storage_axi {

// gem5-native SystemC transactor around the Verilated synthesizable bridge.
// It performs representation conversion only: protocol state and credits stay
// in RTL; storage data and Ramulator2 completion semantics stay in the backend.
class RtlAouTarget : public sc_core::sc_module {
  public:
    sc_core::sc_in<bool> clk{"clk"};
    sc_core::sc_in<bool> rst_n{"rst_n"};
    sc_core::sc_fifo_in<FdiFlit> link_rx{"link_rx"};
    sc_core::sc_fifo_out<FdiFlit> link_tx{"link_tx"};
    sc_core::sc_fifo_out<SimpleMemRequest> mem_req{"mem_req"};
    sc_core::sc_fifo_in<SimpleMemResponse> mem_rsp{"mem_rsp"};

    uint64_t reads = 0, writes = 0, read_beats = 0, write_beats = 0;
    uint64_t rx_flits = 0, tx_flits = 0;

    SC_HAS_PROCESS(RtlAouTarget);
    RtlAouTarget(sc_core::sc_module_name, unsigned resource_planes);
    ~RtlAouTarget() override;
    bool idle() const;

  private:
    static constexpr unsigned RequestSlots = 4;
    static constexpr unsigned MaxOutstanding = 8;
    struct Reply { SimpleMemResponse rsp; unsigned beat = 0; };

    unsigned planes;
    std::unique_ptr<VerilatedContext> context;
    std::unique_ptr<Vstorage_bridge_top> rtl;
    std::optional<FdiFlit> incoming;
    std::optional<Reply> reply;
    std::array<std::deque<SimpleMemRequest>, 4> write_jobs;
    unsigned outstanding = 0;
    unsigned next_write_submit = 0;
    uint64_t tx_id = 0;

    void run();
    void prepareInputs();
    void acceptCommand();
    void acceptWriteData();
    void acceptResponseBeat();
    void submitAssembledWrite();
    bool writeDataReady(unsigned rp) const;
};

} // namespace storage_axi
#endif
