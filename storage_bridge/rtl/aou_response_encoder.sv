module aou_response_encoder #(
  parameter int AXI_DATA_WIDTH = 256
) (
  input logic clk,
  input logic rst_n,
  input logic rsp_valid,
  output logic rsp_ready,
  input logic rsp_write,
  input logic [1:0] rsp_rp,
  input logic [9:0] rsp_id,
  input logic [15:0] rsp_user,
  input logic [1:0] rsp_status,
  input logic rsp_last,
  input logic [AXI_DATA_WIDTH-1:0] rsp_data,
  input logic credit_ok,
  output logic credit_consume,
  output logic [1:0] credit_rp,
  output logic [2:0] credit_kind,
  output logic [7:0] credit_granules,
  output logic msg_valid,
  input logic msg_ready,
  output logic [3:0] msg_type,
  output logic [1:0] msg_rp,
  output logic [5:0] msg_granules,
  output logic [storage_bridge_pkg::MAX_MESSAGE_BITS-1:0] msg_data
);
  import storage_bridge_pkg::*;
  localparam int AXI_BYTES = AXI_DATA_WIDTH / 8;
  localparam int R_GRANULES = data_message_granules(MSG_READ_DATA, dlength(AXI_DATA_WIDTH));

  assign msg_valid = rsp_valid && credit_ok;
  assign rsp_ready = msg_ready && credit_ok;
  assign msg_type = rsp_write ? MSG_WRITE_RESP : MSG_READ_DATA;
  assign msg_rp = rsp_rp;
  assign msg_granules = rsp_write ? 1 : R_GRANULES;
  assign credit_consume = rsp_valid && rsp_ready;
  assign credit_rp = rsp_rp;
  assign credit_kind = rsp_write ? CREDIT_WRESP : CREDIT_RDATA;
  assign credit_granules = rsp_write ? 1 : R_GRANULES;

  always_comb begin
    msg_data = '0;
    msg_data[0*8 +: 8] = {msg_type, rsp_rp, rsp_write ? 2'b00 : dlength(AXI_DATA_WIDTH)};
    msg_data[1*8 +: 8] = rsp_user[15:8];
    msg_data[2*8 +: 8] = rsp_user[7:0];
    msg_data[3*8 +: 8] = rsp_id[9:2];
    msg_data[4*8 +: 8] = {rsp_id[1:0], rsp_status, rsp_write ? 1'b0 : rsp_last, 3'b000};
    if (!rsp_write)
      for (int unsigned i = 0; i < AXI_BYTES; i++)
        msg_data[(5+AXI_BYTES-1-i)*8 +: 8] = rsp_data[i*8 +: 8];
  end

  logic unused;
  assign unused = clk ^ rst_n;
endmodule
