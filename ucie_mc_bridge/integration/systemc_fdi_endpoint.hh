#pragma once
// Representation-only adapter. Compile against gem5's native SystemC headers;
// never link a second SystemC. No Ramulator or storage_bridge dependency.
#include <systemc>
#include <memory>
#include <optional>
#include <fstream>
#include <iomanip>
#include <string>
#include "ucie_fdi.h"
#ifndef VM_SC
#define VM_SC 0
#endif
#ifndef VL_TIME_CONTEXT
#define VL_TIME_CONTEXT
#endif
#include "Vucie_mc_bridge_top.h"
#include "verilated.h"
#include "verilated_vcd_c.h"
namespace ucie_mc_bridge {
class SystemCFdiEndpoint : public sc_core::sc_module {
 public:
  sc_core::sc_in<bool> clk{"clk"},rst_n{"rst_n"};
  sc_core::sc_fifo_in<FdiFlit> link_rx{"link_rx"};
  sc_core::sc_fifo_out<FdiFlit> link_tx{"link_tx"};
  sc_core::sc_in<bool> hif_cmd_stall{"hif_cmd_stall"};
  sc_core::sc_in<bool> hif_lpr_credit{"hif_lpr_credit"};
  sc_core::sc_in<bool> hif_hpr_credit{"hif_hpr_credit"};
  sc_core::sc_in<bool> hif_wr_credit{"hif_wr_credit"};
  sc_core::sc_in<sc_dt::sc_uint<2>> hif_wrecc_credit{"hif_wrecc_credit"};
  sc_core::sc_in<bool> hif_rdata_valid{"hif_rdata_valid"};
  sc_core::sc_in<bool> hif_rdata_end{"hif_rdata_end"};
  sc_core::sc_in<sc_dt::sc_uint<53>> hif_rdata_token{"hif_rdata_token"};
  sc_core::sc_in<sc_dt::sc_biguint<256>> hif_rdata{"hif_rdata"};
  sc_core::sc_in<bool> hif_rdata_uncorr_ecc_err{"hif_rdata_uncorr_ecc_err"};
  sc_core::sc_in<bool> hif_rdata_addr_err{"hif_rdata_addr_err"};
  sc_core::sc_in<bool> hif_rdata_crc_err{"hif_rdata_crc_err"};
  sc_core::sc_in<bool> hif_wdata_stall{"hif_wdata_stall"};
  sc_core::sc_in<bool> hif_wdata_ptr_valid{"hif_wdata_ptr_valid"};
  sc_core::sc_in<sc_dt::sc_uint<19>> hif_wdata_ptr{"hif_wdata_ptr"};
  sc_core::sc_in<bool> hif_wdata_ptr_addr_err{"hif_wdata_ptr_addr_err"};
  sc_core::sc_out<bool> hif_cmd_valid{"hif_cmd_valid"};
  sc_core::sc_out<sc_dt::sc_uint<2>> hif_cmd_type{"hif_cmd_type"};
  sc_core::sc_out<sc_dt::sc_uint<2>> hif_cmd_pri{"hif_cmd_pri"};
  sc_core::sc_out<sc_dt::sc_uint<40>> hif_cmd_addr{"hif_cmd_addr"};
  sc_core::sc_out<sc_dt::sc_uint<53>> hif_cmd_token{"hif_cmd_token"};
  sc_core::sc_out<bool> hif_cmd_length{"hif_cmd_length"};
  sc_core::sc_out<sc_dt::sc_uint<19>> hif_cmd_wdata_ptr{"hif_cmd_wdata_ptr"};
  sc_core::sc_out<bool> hif_cmd_autopre{"hif_cmd_autopre"};
  sc_core::sc_out<sc_dt::sc_uint<11>> hif_cmd_latency{"hif_cmd_latency"};
  sc_core::sc_out<bool> hif_wdata_valid{"hif_wdata_valid"};
  sc_core::sc_out<sc_dt::sc_biguint<256>> hif_wdata{"hif_wdata"};
  sc_core::sc_out<sc_dt::sc_uint<32>> hif_wdata_mask{"hif_wdata_mask"};
  sc_core::sc_out<bool> hif_wdata_end{"hif_wdata_end"};
  sc_core::sc_out<bool> hif_go2critical_lpr{"hif_go2critical_lpr"};
  sc_core::sc_out<bool> hif_go2critical_hpr{"hif_go2critical_hpr"};
  sc_core::sc_out<bool> hif_go2critical_wr{"hif_go2critical_wr"};
  SC_HAS_PROCESS(SystemCFdiEndpoint);
  SystemCFdiEndpoint(sc_core::sc_module_name name,const std::string& directory,bool trace_enabled=false)
    : sc_core::sc_module(name),context(std::make_unique<VerilatedContext>()),
      rtl(std::make_unique<Vucie_mc_bridge_top>(context.get())),
      rx_log(directory+"/fdi_rx.csv"),tx_log(directory+"/fdi_tx.csv") {
    if(sc_core::sc_get_time_resolution()!=sc_core::sc_time(1,sc_core::SC_FS))
      SC_REPORT_FATAL("McFdiEndpoint","requires native SystemC 1fs time resolution");
    if(!rx_log || !tx_log) SC_REPORT_FATAL("McFdiEndpoint","cannot create FDI logs");
    rx_log<<"time_fs,frame_hex_byte249_to_byte0\n";tx_log<<"time_fs,frame_hex_byte249_to_byte0\n";
    rtl->clk=0;rtl->rst_n=0;rtl->fdi_rx_valid=0;rtl->fdi_tx_ready=0;
    rtl->hif_cmd_stall=0;
    rtl->hif_lpr_credit=0;
    rtl->hif_hpr_credit=0;
    rtl->hif_wr_credit=0;
    rtl->hif_wrecc_credit=0;
    rtl->hif_rdata_valid=0;
    rtl->hif_rdata_end=0;
    rtl->hif_rdata_token=0;
    for(unsigned i=0;i<8;i++) rtl->hif_rdata[i]=0;
    rtl->hif_rdata_uncorr_ecc_err=0;
    rtl->hif_rdata_addr_err=0;
    rtl->hif_rdata_crc_err=0;
    rtl->hif_wdata_stall=0;
    rtl->hif_wdata_ptr_valid=0;
    rtl->hif_wdata_ptr=0;
    rtl->hif_wdata_ptr_addr_err=0;
    rtl->eval();
    if(trace_enabled) {
      context->traceEverOn(true);trace=std::make_unique<VerilatedVcdC>();
      rtl->trace(trace.get(),3);trace->set_time_unit("1fs");trace->set_time_resolution("1fs");
      trace->open((directory+"/ucie_mc_bridge.vcd").c_str());
    }
    SC_THREAD(run);sensitive<<clk;
  }
  ~SystemCFdiEndpoint() override {rtl->final();if(trace) trace->close();}
  bool idle() const {return rtl->business_idle && !incoming;}
  const Vucie_mc_bridge_top& model() const {return *rtl;}
 private:
  std::unique_ptr<VerilatedContext> context;
  std::unique_ptr<Vucie_mc_bridge_top> rtl;
  std::unique_ptr<VerilatedVcdC> trace;
  std::optional<FdiFlit> incoming;
  std::ofstream rx_log,tx_log;
  uint64_t next_frame=0;
  void evaluate() {
    context->time(sc_core::sc_time_stamp().value());rtl->eval();
    if(rtl->protocol_error) SC_REPORT_FATAL("McFdiEndpoint","RTL protocol_error; inspect error_code/VCD");
  }
  static void log_frame(std::ofstream& out,const FdiFlit& frame) {
    out<<sc_core::sc_time_stamp().value()<<','<<std::hex<<std::setfill('0');
    for(auto it=frame.payload.rbegin();it!=frame.payload.rend();++it) out<<std::setw(2)<<unsigned(*it);
    out<<std::dec<<'\n';
  }
  void inputs() {
    rtl->hif_cmd_stall=hif_cmd_stall.read();
    rtl->hif_lpr_credit=hif_lpr_credit.read();
    rtl->hif_hpr_credit=hif_hpr_credit.read();
    rtl->hif_wr_credit=hif_wr_credit.read();
    rtl->hif_wrecc_credit=hif_wrecc_credit.read().to_uint64();
    rtl->hif_rdata_valid=hif_rdata_valid.read();
    rtl->hif_rdata_end=hif_rdata_end.read();
    rtl->hif_rdata_token=hif_rdata_token.read().to_uint64();
    for(unsigned i=0;i<8;i++) rtl->hif_rdata[i]=hif_rdata.read().range(i*32+31,i*32).to_uint();
    rtl->hif_rdata_uncorr_ecc_err=hif_rdata_uncorr_ecc_err.read();
    rtl->hif_rdata_addr_err=hif_rdata_addr_err.read();
    rtl->hif_rdata_crc_err=hif_rdata_crc_err.read();
    rtl->hif_wdata_stall=hif_wdata_stall.read();
    rtl->hif_wdata_ptr_valid=hif_wdata_ptr_valid.read();
    rtl->hif_wdata_ptr=hif_wdata_ptr.read().to_uint64();
    rtl->hif_wdata_ptr_addr_err=hif_wdata_ptr_addr_err.read();
    if(!incoming) {FdiFlit f;if(link_rx.nb_read(f)) {
      if(f.valid_bytes!=250 || f.payload.size()!=250) SC_REPORT_FATAL("McFdiEndpoint","FDI requires exactly 250 bytes");
      incoming=std::move(f);
    }}
    for(unsigned i=0;i<63;i++) rtl->fdi_rx_data[i]=0;
    if(incoming) for(unsigned i=0;i<250;i++) rtl->fdi_rx_data[i/4]|=uint32_t(incoming->payload[i])<<(8*(i%4));
    rtl->fdi_rx_valid=incoming.has_value();rtl->fdi_tx_ready=link_tx.num_free()!=0;
  }
  void outputs() {
    hif_cmd_valid.write(rtl->hif_cmd_valid);
    hif_cmd_type.write(rtl->hif_cmd_type);
    hif_cmd_pri.write(rtl->hif_cmd_pri);
    hif_cmd_addr.write(rtl->hif_cmd_addr);
    hif_cmd_token.write(rtl->hif_cmd_token);
    hif_cmd_length.write(rtl->hif_cmd_length);
    hif_cmd_wdata_ptr.write(rtl->hif_cmd_wdata_ptr);
    hif_cmd_autopre.write(rtl->hif_cmd_autopre);
    hif_cmd_latency.write(rtl->hif_cmd_latency);
    hif_wdata_valid.write(rtl->hif_wdata_valid);
    sc_dt::sc_biguint<256> hif_wdata_value=0;
    for(unsigned i=0;i<8;i++) hif_wdata_value.range(i*32+31,i*32)=rtl->hif_wdata[i];
    hif_wdata.write(hif_wdata_value);
    hif_wdata_mask.write(rtl->hif_wdata_mask);
    hif_wdata_end.write(rtl->hif_wdata_end);
    hif_go2critical_lpr.write(rtl->hif_go2critical_lpr);
    hif_go2critical_hpr.write(rtl->hif_go2critical_hpr);
    hif_go2critical_wr.write(rtl->hif_go2critical_wr);
  }
  void run() {
    bool started=false;
    while(true) {
      wait();
      if(!rst_n.read()) {
        if(started) SC_REPORT_FATAL("McFdiEndpoint","hot reset requires both endpoint/link and MC reconstruction");
        rtl->rst_n=0;rtl->clk=clk.read();evaluate();outputs();
      } else {
        started=true;rtl->rst_n=1;rtl->clk=0;inputs();evaluate();
        if(clk.read()) {
          const bool rx=rtl->fdi_rx_valid && rtl->fdi_rx_ready;
          const bool tx=rtl->fdi_tx_valid && rtl->fdi_tx_ready;
          FdiFlit outgoing;
          if(tx) {
            outgoing.payload.resize(250);outgoing.valid_bytes=250;outgoing.transaction_id=next_frame++;
            outgoing.kind=BusinessKind::Response;outgoing.vc=0;
            outgoing.transaction_start=outgoing.fdi_time=sc_core::sc_time_stamp();
            for(unsigned i=0;i<250;i++) outgoing.payload[i]=uint8_t(rtl->fdi_tx_data[i/4]>>(8*(i%4)));
          }
          rtl->clk=1;evaluate();
          if(rx) {log_frame(rx_log,*incoming);incoming.reset();}
          if(tx) {if(!link_tx.nb_write(outgoing)) SC_REPORT_FATAL("McFdiEndpoint","reserved link FIFO rejected frame");log_frame(tx_log,outgoing);}
        }
        outputs();
      }
      if(trace) trace->dump(static_cast<uint64_t>(sc_core::sc_time_stamp().value()));
    }
  }
};
} // namespace ucie_mc_bridge
