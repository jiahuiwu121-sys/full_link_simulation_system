#pragma once
#ifdef SS_STORAGE_BRIDGE_RTL
#include <array>
#include <fstream>
#include <memory>
#include <optional>
#include <systemc>
#include <vector>
#ifndef VL_TIME_CONTEXT
#define VL_TIME_CONTEXT
#endif
#ifndef VM_SC
#define VM_SC 0
#endif
#ifndef VM_TRACE
#define VM_TRACE 1
#endif
#include "Vstorage_bridge_top.h"
#include "params/AxiDemo.hh"
#include "simple_mem_if.h"
#include "ucie_fdi.h"
#include "verilated.h"
#include "verilated_vcd_c.h"
namespace storage_axi {
// Representation adapter only. Descriptors, data reservations, arbitration,
// response matching and tag retirement all live in aou_transaction_manager RTL.
class RtlAouTarget : public sc_core::sc_module {
  public:
    sc_core::sc_in<bool> clk{"clk"},rst_n{"rst_n"};
    sc_core::sc_fifo_in<FdiFlit> link_rx{"link_rx"};
    sc_core::sc_fifo_out<FdiFlit> link_tx{"link_tx"};
    sc_core::sc_fifo_out<SimpleMemRequest> mem_req{"mem_req"};
    sc_core::sc_fifo_in<SimpleMemResponse> mem_rsp{"mem_rsp"};
    uint64_t reads=0,writes=0,read_beats=0,write_beats=0,rx_flits=0,tx_flits=0;
    SC_HAS_PROCESS(RtlAouTarget);
    RtlAouTarget(sc_core::sc_module_name,const gem5::AxiDemoParams&,const std::string&);
    ~RtlAouTarget() override;
    bool idle() const;
    void finish();
  private:
    struct Reply { SimpleMemResponse rsp;unsigned beat=0; };
    struct Observation { bool active=false;uint64_t begin=0;unsigned rp=0,id=0; };
    unsigned planes;
    uint64_t period_fs,tx_id=0,ignored_maintenance=0;
    std::string directory;
    std::unique_ptr<VerilatedContext> context;
    std::unique_ptr<Vstorage_bridge_top> rtl;
    std::unique_ptr<VerilatedVcdC> trace;
    std::optional<FdiFlit> incoming;
    std::optional<SimpleMemRequest> assembly;
    std::optional<Reply> reply;
    std::array<Observation,64> observations{};
    std::vector<uint64_t> command_latencies,response_latencies;
    std::ofstream events;
    bool finished=false;
    void run();
    void prepareInputs();
    SimpleMemRequest sampleCommand() const;
    SimpleMemWriteBeat sampleWriteData() const;
    void evaluate();
    void dumpTrace();
    static bool maintenanceOnly(const FdiFlit&);
};
} // namespace storage_axi
#endif
