module storage_bridge_top #(
  parameter int AXI_DATA_WIDTH=256,
  parameter int RESOURCE_PLANES=1,
  parameter int REQUEST_SLOTS=4,
  parameter int WDATA_GRANULES=64,
  parameter int MAX_OUTSTANDING=8,
  parameter int FRAME_FIFO_DEPTH=2,
  parameter int TX_FLUSH_CYCLES=2
)(
  input logic clk,
  input logic rst_n,

  input logic fdi_rx_valid,
  output logic fdi_rx_ready,
  input logic [storage_bridge_pkg::FDI_BITS-1:0] fdi_rx_data,
  output logic fdi_tx_valid,
  input logic fdi_tx_ready,
  output logic [storage_bridge_pkg::FDI_BITS-1:0] fdi_tx_data,

  output logic hif_cmd_valid,
  input logic hif_cmd_ready,
  output logic hif_cmd_write,
  output logic [1:0] hif_cmd_rp,
  output logic [9:0] hif_cmd_id,
  output logic [15:0] hif_cmd_user,
  output logic [63:0] hif_cmd_addr,
  output logic [7:0] hif_cmd_len,
  output logic [2:0] hif_cmd_size,
  output logic hif_cmd_lock,
  output logic [2:0] hif_cmd_prot,
  output logic [3:0] hif_cmd_cache,
  output logic [3:0] hif_cmd_qos,

  output logic hif_w_valid,
  input logic hif_w_ready,
  output logic [1:0] hif_w_rp,
  output logic [15:0] hif_w_user,
  output logic [AXI_DATA_WIDTH-1:0] hif_w_data,
  output logic [AXI_DATA_WIDTH/8-1:0] hif_w_strb,

  input logic hif_rsp_valid,
  output logic hif_rsp_ready,
  input logic hif_rsp_write,
  input logic [1:0] hif_rsp_rp,
  input logic [9:0] hif_rsp_id,
  input logic [15:0] hif_rsp_user,
  input logic [1:0] hif_rsp_status,
  input logic hif_rsp_last,
  input logic [AXI_DATA_WIDTH-1:0] hif_rsp_data,

  output logic hif_w_last,
  output logic [5:0] response_tag,
  output logic response_known,
  output logic [63:0] response_retire_mask,
  output logic [31:0] hif_cmd_latency_cycles,
  output logic business_idle,link_idle,
  output logic [31:0] error_code,
  output logic [31:0] config_axi_width,config_resource_planes,config_request_slots,
  output logic [31:0] config_max_outstanding,config_wdata_granules,config_frame_fifo_depth,
  output logic [31:0] config_tx_flush_cycles,
  output logic [63:0] stat_cycles,stat_rx_frames,stat_rx_messages,stat_tx_frames,
  output logic [63:0] stat_credit_wait_cycles,stat_cmd_stall_cycles,stat_w_stall_cycles,
  output logic [63:0] stat_tx_stall_cycles,stat_descriptor_depth_sum,stat_outstanding_depth_sum,
  output logic [63:0] stat_wdata_depth_sum,
  output logic [31:0] stat_wdata_peak,
  output logic [31:0] stat_descriptor_peak,stat_outstanding_peak,stat_rx_queue_peak,stat_tx_queue_peak,
  output logic [63:0] stat_packed_granules,stat_spanning_messages,stat_credit_only_frames,
  output logic [63:0] stat_cmd_latency_count,stat_cmd_latency_sum,stat_cmd_latency_max,
  output logic [63:0] stat_rsp_latency_count,stat_rsp_latency_sum,stat_rsp_latency_max,
  output logic protocol_error
);

  import storage_bridge_pkg::*;
  logic rx_header_valid,rx_msg_valid,rx_msg_ready;
  logic [15:0] rx_header;
  logic [3:0] rx_type;
  logic [1:0] rx_rp;
  logic [5:0] rx_granules;
  logic [7:0] rx_bytes;
  logic [31:0] rx_origin_cycle;
  logic [MAX_MESSAGE_BITS-1:0] rx_data;
  logic rx_error,request_error,credit_error,transaction_error,tx_error;
  logic rx_idle,rx_link_idle,transaction_idle,tx_idle;
  logic [31:0] rx_queue,tx_queue,descriptor_depth,outstanding_depth,wdata_depth;
  logic request_ready,return_valid;
  logic [1:0] return_rp,release_rp;
  logic [2:0] return_kind,release_kind;
  logic [7:0] return_granules,release_granules;
  logic release_valid;
  logic credit_ok,consume;
  logic [1:0] consume_rp;
  logic [2:0] consume_kind;
  logic [7:0] consume_granules;
  logic grant_valid,grant_take;
  logic [15:0] grant_field;
  logic encoded_valid,encoded_ready;
  logic [3:0] encoded_type;
  logic [1:0] encoded_rp;
  logic [5:0] encoded_granules,checked_rsp_tag;
  logic [MAX_MESSAGE_BITS-1:0] encoded_data;
  logic checked_rsp_valid,checked_rsp_ready;
  logic [63:0] retire_mask;
  logic cmd_valid,cmd_ready,cmd_write,cmd_lock,w_valid,w_ready;
  logic [1:0] cmd_rp,w_rp;
  logic [9:0] cmd_id;
  logic [15:0] cmd_user,w_user;
  logic [63:0] cmd_addr;
  logic [7:0] cmd_len;
  logic [2:0] cmd_size,cmd_prot;
  logic [3:0] cmd_cache,cmd_qos;
  logic [AXI_DATA_WIDTH-1:0] w_data;
  logic [AXI_DATA_WIDTH/8-1:0] w_strb;
  logic [7:0] w_granules;

  aou_fdi_rx #(.FRAME_FIFO_DEPTH(FRAME_FIFO_DEPTH)) rx (
    .clk,.rst_n,.fdi_valid(fdi_rx_valid),.fdi_ready(fdi_rx_ready),.fdi_data(fdi_rx_data),
    .header_credit_valid(rx_header_valid),.header_credit(rx_header),
    .msg_valid(rx_msg_valid),.msg_ready(rx_msg_ready),.msg_type(rx_type),.msg_rp(rx_rp),
    .msg_granules(rx_granules),.msg_bytes(rx_bytes),.msg_data(rx_data),
    .msg_origin_cycle(rx_origin_cycle),.business_idle(rx_idle),.link_idle(rx_link_idle),.queue_depth(rx_queue),.protocol_error(rx_error));
  assign rx_msg_ready=rx_type==MSG_MISC ? 1'b1:request_ready;
  aou_request_decoder #(.AXI_DATA_WIDTH(AXI_DATA_WIDTH),.RESOURCE_PLANES(RESOURCE_PLANES)) decoder (
    .clk,.rst_n,.msg_valid(rx_msg_valid && rx_type!=MSG_MISC),.msg_ready(request_ready),
    .msg_type(rx_type),.msg_rp(rx_rp),.msg_granules(rx_granules),.msg_data(rx_data),
    .cmd_valid,.cmd_ready,.cmd_write,.cmd_rp,.cmd_id,.cmd_user,.cmd_addr,.cmd_len,.cmd_size,
    .cmd_lock,.cmd_prot,.cmd_cache,.cmd_qos,.w_valid,.w_ready,.w_rp,.w_user,.w_data,.w_strb,.w_granules,
    .protocol_error(request_error));
  assign return_kind=CREDIT_WDATA;
  aou_transaction_manager #(.AXI_DATA_WIDTH(AXI_DATA_WIDTH),.RESOURCE_PLANES(RESOURCE_PLANES),
    .REQUEST_SLOTS(REQUEST_SLOTS),.MAX_OUTSTANDING(MAX_OUTSTANDING),.WDATA_GRANULES(WDATA_GRANULES)) transactions (
    .clk,.rst_n,.cmd_valid,.cmd_ready,.cmd_write,.cmd_rp,.cmd_id,.cmd_user,.cmd_addr,.cmd_len,
    .cmd_size,.cmd_prot,.cmd_lock,.cmd_cache,.cmd_qos,.cmd_origin_cycle(rx_origin_cycle),
    .w_valid,.w_ready,.w_rp,.w_user,.w_data,.w_strb,.w_granules,
    .hif_cmd_valid,.hif_cmd_ready,.hif_cmd_write,.hif_cmd_rp,.hif_cmd_id,.hif_cmd_user,
    .hif_cmd_addr,.hif_cmd_len,.hif_cmd_size,.hif_cmd_prot,.hif_cmd_lock,.hif_cmd_cache,.hif_cmd_qos,
    .hif_cmd_latency_cycles,.hif_w_valid,.hif_w_ready,.hif_w_rp,.hif_w_user,.hif_w_data,.hif_w_strb,.hif_w_last,
    .backend_rsp_valid(hif_rsp_valid),.backend_rsp_ready(hif_rsp_ready),.backend_rsp_write(hif_rsp_write),
    .backend_rsp_rp(hif_rsp_rp),.backend_rsp_id(hif_rsp_id),.backend_rsp_last(hif_rsp_last),
    .checked_rsp_valid,.checked_rsp_ready,.checked_rsp_tag,.retire_mask,
    .release_valid,.release_rp,.release_kind,.release_granules,.business_idle(transaction_idle),
    .data_release_valid(return_valid),.data_release_rp(return_rp),.data_release_granules(return_granules),
    .descriptor_depth,.outstanding_depth,.wdata_depth,.stat_cmd_latency_count,.stat_cmd_latency_sum,.stat_cmd_latency_max,
    .stat_rsp_latency_count,.stat_rsp_latency_sum,.stat_rsp_latency_max,.protocol_error(transaction_error));
  aou_credit_manager #(.RESOURCE_PLANES(RESOURCE_PLANES),.REQUEST_SLOTS(REQUEST_SLOTS),
    .WDATA_GRANULES(WDATA_GRANULES)) credits (
    .clk,.rst_n,.header_valid(rx_header_valid),.header_field(rx_header),
    .misc_valid(rx_msg_valid && rx_type==MSG_MISC),.misc_ready(),.misc_data(rx_data),
    .return_valid,.return_rp,.return_kind,.return_granules,
    .release_valid,.release_rp,.release_kind,.release_granules,
    .query_write(hif_rsp_write),.query_rp(hif_rsp_rp),
    .query_granules(hif_rsp_write?8'd1:{2'b0,encoded_granules}),.query_ok(credit_ok),
    .consume_valid(consume),.consume_rp,.consume_kind,.consume_granules,
    .grant_valid,.grant_field,.grant_take,.protocol_error(credit_error));
  aou_response_encoder #(.AXI_DATA_WIDTH(AXI_DATA_WIDTH)) encoder (
    .clk,.rst_n,.rsp_valid(checked_rsp_valid),.rsp_ready(checked_rsp_ready),
    .rsp_write(hif_rsp_write),.rsp_rp(hif_rsp_rp),.rsp_id(hif_rsp_id),.rsp_user(hif_rsp_user),
    .rsp_status(hif_rsp_status),.rsp_last(hif_rsp_last),.rsp_data(hif_rsp_data),
    .credit_ok,.credit_consume(consume),.credit_rp(consume_rp),.credit_kind(consume_kind),
    .credit_granules(consume_granules),.msg_valid(encoded_valid),.msg_ready(encoded_ready),
    .msg_type(encoded_type),.msg_rp(encoded_rp),.msg_granules(encoded_granules),.msg_data(encoded_data));
  aou_fdi_tx #(.FRAME_FIFO_DEPTH(FRAME_FIFO_DEPTH),.TX_FLUSH_CYCLES(TX_FLUSH_CYCLES)) tx (
    .clk,.rst_n,.msg_valid(encoded_valid),.msg_ready(encoded_ready),.msg_granules(encoded_granules),
    .msg_data(encoded_data),.msg_complete(hif_rsp_write||hif_rsp_last),.msg_tag(checked_rsp_tag),
    .grant_valid,.grant_field,.grant_take,.fdi_valid(fdi_tx_valid),.fdi_ready(fdi_tx_ready),.fdi_data(fdi_tx_data),
    .retire_mask,.business_idle(tx_idle),.queue_depth(tx_queue),
    .stat_packed_granules,.stat_spanning_messages,.stat_credit_only_frames,.protocol_error(tx_error));

  assign response_tag=checked_rsp_tag;
  assign response_known=checked_rsp_valid;
  assign response_retire_mask=retire_mask;
  assign business_idle=rx_idle && transaction_idle && tx_idle;
  assign link_idle=business_idle && rx_link_idle && rx_queue==0 && tx_queue==0 && !grant_valid && !fdi_rx_valid;
  assign error_code={26'b0,
    rx_msg_valid && !(rx_type inside {MSG_MISC,MSG_WRITE_REQ,MSG_READ_REQ,MSG_WRITE_DATA,MSG_WRITE_FULL}),
    tx_error,transaction_error,credit_error,request_error,rx_error};
  assign protocol_error=|error_code;
  assign config_axi_width=AXI_DATA_WIDTH;
  assign config_resource_planes=RESOURCE_PLANES;
  assign config_request_slots=REQUEST_SLOTS;
  assign config_max_outstanding=MAX_OUTSTANDING;
  assign config_wdata_granules=WDATA_GRANULES;
  assign config_frame_fifo_depth=FRAME_FIFO_DEPTH;
  assign config_tx_flush_cycles=TX_FLUSH_CYCLES;
  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      stat_cycles<=0;stat_rx_frames<=0;stat_rx_messages<=0;stat_tx_frames<=0;
      stat_credit_wait_cycles<=0;stat_cmd_stall_cycles<=0;stat_w_stall_cycles<=0;stat_tx_stall_cycles<=0;
      stat_descriptor_depth_sum<=0;stat_outstanding_depth_sum<=0;
      stat_wdata_depth_sum<=0;stat_wdata_peak<=0;
      stat_descriptor_peak<=0;stat_outstanding_peak<=0;stat_rx_queue_peak<=0;stat_tx_queue_peak<=0;
    end else begin
      stat_cycles<=stat_cycles+1;
      if(fdi_rx_valid && fdi_rx_ready) stat_rx_frames<=stat_rx_frames+1;
      if(rx_msg_valid && rx_msg_ready) stat_rx_messages<=stat_rx_messages+1;
      if(fdi_tx_valid && fdi_tx_ready) stat_tx_frames<=stat_tx_frames+1;
      if(checked_rsp_valid && !credit_ok) stat_credit_wait_cycles<=stat_credit_wait_cycles+1;
      if(hif_cmd_valid && !hif_cmd_ready) stat_cmd_stall_cycles<=stat_cmd_stall_cycles+1;
      if(hif_w_valid && !hif_w_ready) stat_w_stall_cycles<=stat_w_stall_cycles+1;
      if(fdi_tx_valid && !fdi_tx_ready) stat_tx_stall_cycles<=stat_tx_stall_cycles+1;
      stat_descriptor_depth_sum<=stat_descriptor_depth_sum+descriptor_depth;
      stat_outstanding_depth_sum<=stat_outstanding_depth_sum+outstanding_depth;
      stat_wdata_depth_sum<=stat_wdata_depth_sum+wdata_depth;
      if(wdata_depth>stat_wdata_peak) stat_wdata_peak<=wdata_depth;
      if(descriptor_depth>stat_descriptor_peak) stat_descriptor_peak<=descriptor_depth;
      if(outstanding_depth>stat_outstanding_peak) stat_outstanding_peak<=outstanding_depth;
      if(rx_queue>stat_rx_queue_peak) stat_rx_queue_peak<=rx_queue;
      if(tx_queue>stat_tx_queue_peak) stat_tx_queue_peak<=tx_queue;
    end
  end
endmodule
