module storage_bridge_top #(
  parameter int AXI_DATA_WIDTH = 256,
  parameter int RESOURCE_PLANES = 1,
  parameter int REQUEST_SLOTS = 4,
  parameter int WDATA_GRANULES = 64
) (
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

  output logic protocol_error
);
  import storage_bridge_pkg::*;
  logic rx_header_valid, rx_msg_valid, rx_msg_ready;
  logic [15:0] rx_header;
  logic [3:0] rx_type;
  logic [1:0] rx_rp;
  logic [5:0] rx_granules;
  logic [7:0] rx_bytes;
  logic [MAX_MESSAGE_BITS-1:0] rx_data;
  logic rx_error, request_error, credit_error, tx_error;
  logic request_ready;
  logic return_valid;
  logic [1:0] return_rp;
  logic [2:0] return_kind;
  logic [7:0] return_granules;
  logic credit_ok, consume;
  logic [1:0] consume_rp;
  logic [2:0] consume_kind;
  logic [7:0] consume_granules;
  logic grant_valid, grant_take;
  logic [15:0] grant_field;
  logic encoded_valid, encoded_ready;
  logic [3:0] encoded_type;
  logic [1:0] encoded_rp;
  logic [5:0] encoded_granules;
  logic [MAX_MESSAGE_BITS-1:0] encoded_data;

  aou_fdi_rx rx (
    .clk, .rst_n, .fdi_valid(fdi_rx_valid), .fdi_ready(fdi_rx_ready), .fdi_data(fdi_rx_data),
    .header_credit_valid(rx_header_valid), .header_credit(rx_header),
    .msg_valid(rx_msg_valid), .msg_ready(rx_msg_ready), .msg_type(rx_type), .msg_rp(rx_rp),
    .msg_granules(rx_granules), .msg_bytes(rx_bytes), .msg_data(rx_data),
    .protocol_error(rx_error));

  assign rx_msg_ready = rx_type == MSG_MISC ? 1'b1 : request_ready;

  aou_request_decoder #(.AXI_DATA_WIDTH(AXI_DATA_WIDTH)) request_decoder (
    .clk, .rst_n, .msg_valid(rx_msg_valid && rx_type != MSG_MISC), .msg_ready(request_ready),
    .msg_type(rx_type), .msg_rp(rx_rp), .msg_granules(rx_granules), .msg_data(rx_data),
    .cmd_valid(hif_cmd_valid), .cmd_ready(hif_cmd_ready), .cmd_write(hif_cmd_write),
    .cmd_rp(hif_cmd_rp), .cmd_id(hif_cmd_id), .cmd_user(hif_cmd_user), .cmd_addr(hif_cmd_addr),
    .cmd_len(hif_cmd_len), .cmd_size(hif_cmd_size), .cmd_lock(hif_cmd_lock),
    .cmd_prot(hif_cmd_prot), .cmd_cache(hif_cmd_cache), .cmd_qos(hif_cmd_qos),
    .w_valid(hif_w_valid), .w_ready(hif_w_ready), .w_rp(hif_w_rp), .w_user(hif_w_user),
    .w_data(hif_w_data), .w_strb(hif_w_strb),
    .credit_return_valid(return_valid), .credit_return_rp(return_rp),
    .credit_return_kind(return_kind), .credit_return_granules(return_granules),
    .protocol_error(request_error));

  aou_credit_manager #(.RESOURCE_PLANES(RESOURCE_PLANES), .REQUEST_SLOTS(REQUEST_SLOTS),
      .WDATA_GRANULES(WDATA_GRANULES)) credits (
    .clk, .rst_n, .header_valid(rx_header_valid), .header_field(rx_header),
    .misc_valid(rx_msg_valid && rx_type == MSG_MISC), .misc_ready(), .misc_data(rx_data),
    .return_valid(return_valid), .return_rp(return_rp), .return_kind(return_kind),
    .return_granules(return_granules), .query_write(hif_rsp_write), .query_rp(hif_rsp_rp),
    .query_granules(hif_rsp_write ? 8'd1 : encoded_granules), .query_ok(credit_ok),
    .consume_valid(consume), .consume_rp(consume_rp), .consume_kind(consume_kind),
    .consume_granules(consume_granules), .grant_valid, .grant_field, .grant_take,
    .protocol_error(credit_error));

  aou_response_encoder #(.AXI_DATA_WIDTH(AXI_DATA_WIDTH)) response_encoder (
    .clk, .rst_n, .rsp_valid(hif_rsp_valid), .rsp_ready(hif_rsp_ready),
    .rsp_write(hif_rsp_write), .rsp_rp(hif_rsp_rp), .rsp_id(hif_rsp_id),
    .rsp_user(hif_rsp_user), .rsp_status(hif_rsp_status), .rsp_last(hif_rsp_last),
    .rsp_data(hif_rsp_data), .credit_ok, .credit_consume(consume), .credit_rp(consume_rp),
    .credit_kind(consume_kind), .credit_granules(consume_granules),
    .msg_valid(encoded_valid), .msg_ready(encoded_ready), .msg_type(encoded_type),
    .msg_rp(encoded_rp), .msg_granules(encoded_granules), .msg_data(encoded_data));

  aou_fdi_tx tx (
    .clk, .rst_n, .msg_valid(encoded_valid), .msg_ready(encoded_ready),
    .msg_granules(encoded_granules), .msg_data(encoded_data), .grant_valid, .grant_field,
    .grant_take, .fdi_valid(fdi_tx_valid), .fdi_ready(fdi_tx_ready), .fdi_data(fdi_tx_data),
    .protocol_error(tx_error));

  assign protocol_error = rx_error || request_error || credit_error || tx_error ||
    (rx_msg_valid && !(rx_type inside {MSG_MISC, MSG_WRITE_REQ, MSG_READ_REQ,
                                       MSG_WRITE_DATA, MSG_WRITE_FULL}));
  logic unused;
  assign unused = ^{rx_bytes, encoded_type, encoded_rp};
endmodule
