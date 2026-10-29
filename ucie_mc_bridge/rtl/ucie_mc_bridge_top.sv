module ucie_mc_bridge_top #(
  parameter int RESOURCE_PLANES=1,REQUEST_SLOTS=4,CHILD_SLOTS=32,MAX_BURST_BYTES=4096,
  parameter int WDATA_GRANULES=64,TX_FLUSH_CYCLES=2,
  parameter int INITIAL_LPR=24,INITIAL_HPR=8,INITIAL_WR=32,
  parameter bit POSTED_WRITE_ACK=0,TWO_WORD_COMMANDS=1,
  parameter logic LENGTH_ONE=0,LENGTH_TWO=1,MASK_ONE_WRITES=1,
  parameter logic [1:0] HPR_CODE=2,
  parameter logic [10:0] COMMAND_LATENCY=0,
  parameter bit AUTO_PRECHARGE=0
)(
  input logic clk,rst_n,
  input logic fdi_rx_valid,output logic fdi_rx_ready,input logic [1999:0] fdi_rx_data,
  output logic fdi_tx_valid,input logic fdi_tx_ready,output logic [1999:0] fdi_tx_data,
  output logic hif_cmd_valid,input logic hif_cmd_stall,
  output logic [1:0] hif_cmd_type,hif_cmd_pri,
  output logic [39:0] hif_cmd_addr,output logic [52:0] hif_cmd_token,
  output logic hif_cmd_length,output logic [18:0] hif_cmd_wdata_ptr,
  output logic hif_cmd_autopre,output logic [10:0] hif_cmd_latency,
  input logic hif_lpr_credit,hif_hpr_credit,hif_wr_credit,input logic [1:0] hif_wrecc_credit,
  input logic hif_rdata_valid,hif_rdata_end,input logic [52:0] hif_rdata_token,
  input logic [255:0] hif_rdata,
  input logic hif_rdata_uncorr_ecc_err,hif_rdata_addr_err,hif_rdata_crc_err,
  output logic hif_wdata_valid,input logic hif_wdata_stall,
  output logic [255:0] hif_wdata,output logic [31:0] hif_wdata_mask,output logic hif_wdata_end,
  input logic hif_wdata_ptr_valid,input logic [18:0] hif_wdata_ptr,input logic hif_wdata_ptr_addr_err,
  output logic hif_go2critical_lpr,hif_go2critical_hpr,hif_go2critical_wr,
  output logic business_idle,link_idle,protocol_error,output logic [31:0] error_code,
  output logic [15:0] lpr_available,hpr_available,wr_available,
  output logic [31:0] parents_used,children_used,
  output logic [63:0] stat_cycles,stat_rx_frames,stat_rx_messages,stat_tx_frames,
  output logic [63:0] stat_commands,stat_reads,stat_writes,stat_rmw,
  output logic [63:0] stat_cmd_stall,stat_wdata_stall,stat_pointer_requests,stat_read_words,
  output logic [63:0] stat_effective_write_bytes,stat_mc_write_words,stat_response_count,
  output logic [63:0] stat_packed_granules,stat_spanning_messages,stat_aou_credit_wait
);
  import umcb_pkg::*;
  logic rx_valid,rx_ready,header_valid,request_valid,request_ready,write_valid,write_ready,misc_valid;
  logic [319:0] rx_message,tx_message;
  logic [15:0] header_credit,grant;
  request_t request;
  write_t write_data;
  response_t response;
  logic response_valid,response_ready,response_allowed,tx_ready;
  logic grant_valid,grant_take,rx_idle,tx_idle,core_idle;
  logic rx_fault,decode_fault,aou_fault,mc_fault;
  logic [31:0] core_error;
  logic [3:0] granules;
  logic [15:0] released[RESOURCE_PLANES][3];
  logic [63:0] retire;
  logic query_valid,credit_allowed;
  logic [1:0] query_type,query_pri;
  umcb_fdi_rx rx(.clk,.rst_n,.valid(fdi_rx_valid),.ready(fdi_rx_ready),.frame(fdi_rx_data),
    .header_valid,.header_credit,.message_valid(rx_valid),.message_ready(rx_ready),.message(rx_message),.idle(rx_idle),.fault(rx_fault));
  umcb_aou_decoder #(.RP(RESOURCE_PLANES)) decoder(.clk,.rst_n,.valid(rx_valid),.ready(rx_ready),.message(rx_message),
    .request_valid,.request_ready,.request,.write_valid,.write_ready,.write_data,.misc_valid,.fault(decode_fault));
  umcb_aou_credit_manager #(.RP(RESOURCE_PLANES),.REQUEST_SLOTS(REQUEST_SLOTS),.WDATA_GRANULES(WDATA_GRANULES)) aou_credits(
    .clk,.rst_n,.header_valid,.header_credit,.misc_valid,.misc_message(rx_message),.released,
    .response_valid,.response_write(response.write),.response_rp(response.rp),.response_allowed,
    .response_take(response_valid && response_ready),.grant_valid,.grant,.grant_take,.fault(aou_fault));
  umcb_mc_credit_manager #(.INITIAL_LPR(INITIAL_LPR),.INITIAL_HPR(INITIAL_HPR),.INITIAL_WR(INITIAL_WR),.HPR_CODE(HPR_CODE)) mc_credits(
    .clk,.rst_n,.lpr_return(hif_lpr_credit),.hpr_return(hif_hpr_credit),.wr_return(hif_wr_credit),
    .accepted(hif_cmd_valid && !hif_cmd_stall),.command_type(query_type),.priority_code(query_pri),.allowed(credit_allowed),
    .lpr_count(lpr_available),.hpr_count(hpr_available),.wr_count(wr_available),.fault(mc_fault));
  umcb_transaction_core #(.RP(RESOURCE_PLANES),.REQUEST_SLOTS(REQUEST_SLOTS),.CHILD_SLOTS(CHILD_SLOTS),
    .MAX_BYTES(MAX_BURST_BYTES),.WDATA_GRANULES(WDATA_GRANULES),.POSTED_WRITE_ACK(POSTED_WRITE_ACK),
    .TWO_WORD_COMMANDS(TWO_WORD_COMMANDS),.LENGTH_ONE(LENGTH_ONE),.LENGTH_TWO(LENGTH_TWO),
    .MASK_ONE_WRITES(MASK_ONE_WRITES),.HPR_CODE(HPR_CODE),.COMMAND_LATENCY(COMMAND_LATENCY),.AUTO_PRECHARGE(AUTO_PRECHARGE)) core(
    .clk,.rst_n,.request_valid,.request_ready,.request,.write_valid,.write_ready,.write_data,
    .response_valid,.response_ready,.response,.retire,.released,
    .hif_cmd_valid,.hif_cmd_stall,.hif_cmd_type,.hif_cmd_pri,.hif_cmd_addr,.hif_cmd_token,.hif_cmd_length,
    .hif_cmd_wdata_ptr,.hif_cmd_autopre,.hif_cmd_latency,
    .credit_query_valid(query_valid),.credit_query_type(query_type),.credit_query_pri(query_pri),.credit_allowed,
    .hif_rdata_valid,.hif_rdata_end,.hif_rdata_token,.hif_rdata,
    .hif_rdata_uncorr_ecc_err,.hif_rdata_addr_err,.hif_rdata_crc_err,
    .hif_wdata_valid,.hif_wdata_stall,.hif_wdata,.hif_wdata_mask,.hif_wdata_end,
    .hif_wdata_ptr_valid,.hif_wdata_ptr,.hif_wdata_ptr_addr_err,
    .idle(core_idle),.error_code(core_error),.parents_used,.children_used,
    .stat_commands,.stat_reads,.stat_writes,.stat_rmw,.stat_cmd_stall,.stat_wdata_stall,
    .stat_pointer_requests,.stat_read_words,.stat_effective_write_bytes,.stat_mc_write_words,.stat_response_count);
  umcb_aou_encoder encoder(.response,.message(tx_message),.granules);
  assign response_ready=tx_ready && response_allowed;
  umcb_fdi_tx #(.FLUSH_CYCLES(TX_FLUSH_CYCLES)) tx(.clk,.rst_n,
    .message_valid(response_valid && response_allowed),.message_ready(tx_ready),.message(tx_message),.granules,
    .completes(response.write || response.last),.tag(response.tag),.grant_valid,.grant,.grant_take,
    .valid(fdi_tx_valid),.ready(fdi_tx_ready),.frame(fdi_tx_data),.retire,.idle(tx_idle),
    .frames_sent(stat_tx_frames),.packed_granules(stat_packed_granules),.spanning_messages(stat_spanning_messages));
  assign business_idle=rx_idle && core_idle && tx_idle;
  assign link_idle=business_idle && !grant_valid && !fdi_tx_valid && !fdi_rx_valid;
  assign error_code=core_error | (32'(rx_fault)<<16) | (32'(decode_fault)<<17) | (32'(aou_fault)<<18) | (32'(mc_fault)<<19);
  assign protocol_error=error_code!=0;
  // Criticality and WRECC semantics are unspecified by the supplied waveforms.
  // No operation uses WRECC credits, and escalation is disabled in this profile.
  assign hif_go2critical_lpr=0;
  assign hif_go2critical_hpr=0;
  assign hif_go2critical_wr=0;
  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin stat_cycles<=0;stat_rx_frames<=0;stat_rx_messages<=0;stat_aou_credit_wait<=0;end
    else begin
      stat_cycles<=stat_cycles+1;
      if(fdi_rx_valid && fdi_rx_ready) stat_rx_frames<=stat_rx_frames+1;
      if(rx_valid && rx_ready) stat_rx_messages<=stat_rx_messages+1;
      if(response_valid && !response_allowed) stat_aou_credit_wait<=stat_aou_credit_wait+1;
    end
  end
endmodule
