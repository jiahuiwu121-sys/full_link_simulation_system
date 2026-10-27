module aou_request_decoder #(
  parameter int AXI_DATA_WIDTH = 256
) (
  input logic clk,
  input logic rst_n,
  input logic msg_valid,
  output logic msg_ready,
  input logic [3:0] msg_type,
  input logic [1:0] msg_rp,
  input logic [5:0] msg_granules,
  input logic [storage_bridge_pkg::MAX_MESSAGE_BITS-1:0] msg_data,

  output logic cmd_valid,
  input logic cmd_ready,
  output logic cmd_write,
  output logic [1:0] cmd_rp,
  output logic [9:0] cmd_id,
  output logic [15:0] cmd_user,
  output logic [63:0] cmd_addr,
  output logic [7:0] cmd_len,
  output logic [2:0] cmd_size,
  output logic cmd_lock,
  output logic [2:0] cmd_prot,
  output logic [3:0] cmd_cache,
  output logic [3:0] cmd_qos,

  output logic w_valid,
  input logic w_ready,
  output logic [1:0] w_rp,
  output logic [15:0] w_user,
  output logic [AXI_DATA_WIDTH-1:0] w_data,
  output logic [AXI_DATA_WIDTH/8-1:0] w_strb,

  output logic credit_return_valid,
  output logic [1:0] credit_return_rp,
  output logic [2:0] credit_return_kind,
  output logic [7:0] credit_return_granules,
  output logic protocol_error
);
  import storage_bridge_pkg::*;
  localparam int AXI_BYTES = AXI_DATA_WIDTH / 8;
  logic is_cmd, is_wdata, width_ok;
  logic [63:0] field;

  always_comb begin
    is_cmd = msg_type == MSG_WRITE_REQ || msg_type == MSG_READ_REQ;
    is_wdata = msg_type == MSG_WRITE_DATA || msg_type == MSG_WRITE_FULL;
    width_ok = msg_data[1:0] == dlength(AXI_DATA_WIDTH);
    msg_ready = is_cmd ? cmd_ready : (is_wdata ? w_ready : 1'b0);
    cmd_valid = msg_valid && is_cmd;
    cmd_write = msg_type == MSG_WRITE_REQ;
    cmd_rp = msg_rp;
    field = get_be_bits(msg_data, 8, 16); cmd_user = field[15:0];
    field = get_be_bits(msg_data, 24, 10); cmd_id = field[9:0];
    field = get_be_bits(msg_data, 34, 3); cmd_size = field[2:0];
    field = get_be_bits(msg_data, 37, 3); cmd_prot = field[2:0];
    field = get_be_bits(msg_data, 40, 8); cmd_len = field[7:0];
    field = get_be_bits(msg_data, 48, 4); cmd_cache = field[3:0];
    field = get_be_bits(msg_data, 52, 4); cmd_qos = field[3:0];
    cmd_addr = get_be_bits(msg_data, 56, 64);
    cmd_lock = msg_data[0];

    w_valid = msg_valid && is_wdata && width_ok;
    w_rp = msg_rp;
    field = get_be_bits(msg_data, 8, 16); w_user = field[15:0];
    w_data = '0; w_strb = '0;
    for (int unsigned i = 0; i < AXI_BYTES; i++) begin
      w_data[i*8 +: 8] = msg_data[(3+AXI_BYTES-1-i)*8 +: 8];
      if (msg_type == MSG_WRITE_FULL)
        w_strb[i] = 1'b1;
      else
        w_strb[i] = msg_data[(3+AXI_BYTES+(AXI_BYTES/8)-1-(i/8))*8 + (i%8)];
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      credit_return_valid <= 1'b0;
      credit_return_rp <= '0; credit_return_kind <= '0;
      credit_return_granules <= '0; protocol_error <= 1'b0;
    end else begin
      credit_return_valid <= 1'b0;
      if (msg_valid && is_wdata && !width_ok) protocol_error <= 1'b1;
      if (msg_valid && msg_ready) begin
        credit_return_valid <= 1'b1;
        credit_return_rp <= msg_rp;
        credit_return_granules <= msg_granules;
        if (msg_type == MSG_WRITE_REQ) credit_return_kind <= CREDIT_WREQ;
        else if (msg_type == MSG_READ_REQ) credit_return_kind <= CREDIT_RREQ;
        else credit_return_kind <= CREDIT_WDATA;
      end
    end
  end

  initial begin
    if (!(AXI_DATA_WIDTH inside {256, 512, 1024}))
      $error("AXI_DATA_WIDTH must be 256, 512 or 1024");
  end
endmodule
