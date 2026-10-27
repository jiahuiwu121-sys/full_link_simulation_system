module aou_fdi_tx (
  input logic clk,
  input logic rst_n,
  input logic msg_valid,
  output logic msg_ready,
  input logic [5:0] msg_granules,
  input logic [storage_bridge_pkg::MAX_MESSAGE_BITS-1:0] msg_data,
  input logic grant_valid,
  input logic [15:0] grant_field,
  output logic grant_take,
  output logic fdi_valid,
  input logic fdi_ready,
  output logic [storage_bridge_pkg::FDI_BITS-1:0] fdi_data,
  output logic protocol_error
);
  import storage_bridge_pkg::*;
  logic [PAYLOAD_BYTES*8-1:0] payload_q;
  logic [47:0] starts_q;
  logic [5:0] used_q;
  logic [FDI_BITS-1:0] fdi_q;
  logic send_now, fits;

  assign fits = msg_granules != 0 && msg_granules <= GRANULES_PER_FLIT &&
                used_q + msg_granules <= GRANULES_PER_FLIT;
  assign msg_ready = !fdi_valid && fits;
  assign send_now = !fdi_valid && used_q != 0 && (!msg_valid || !fits);
  assign fdi_data = fdi_q;

  function automatic logic [FDI_BITS-1:0] format_frame(
      input logic [PAYLOAD_BYTES*8-1:0] payload,
      input logic [47:0] starts_in,
      input logic [15:0] credit);
    logic [FDI_BITS-1:0] frame;
    logic [47:0] starts;
    starts = starts_in; frame = '0;
    frame[0*8 +: 8] = {starts[3:0], 2'b00, 2'b00};
    frame[1*8 +: 8] = starts[11:4];
    frame[2*8 +: 8] = {starts[15:12], 4'b0000};
    frame[3*8 +: 8] = starts[23:16];
    frame[4*8 +: 8] = credit[7:0];
    frame[5*8 +: 8] = credit[15:8];
    frame[6*8 +: 8] = {starts[27:24], 4'b0000};
    frame[7*8 +: 8] = starts[35:28];
    frame[8*8 +: 8] = {starts[39:36], 4'b0000};
    frame[9*8 +: 8] = starts[47:40];
    for (int i = 0; i < PAYLOAD_BYTES; i++)
      frame[(PROTOCOL_HEADER_BYTES+i)*8 +: 8] = payload[i*8 +: 8];
    return frame;
  endfunction

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      payload_q <= '0; starts_q <= '0; used_q <= 0;
      fdi_q <= '0; fdi_valid <= 1'b0; grant_take <= 1'b0;
      protocol_error <= 1'b0;
    end else begin
      grant_take <= 1'b0;
      if (fdi_valid && fdi_ready) fdi_valid <= 1'b0;
      if (msg_valid && msg_ready) begin
        starts_q[used_q] <= 1'b1;
        for (int unsigned i = 0; i < msg_granules*GRANULE_BYTES; i++)
          payload_q[(used_q*GRANULE_BYTES+i)*8 +: 8] <= msg_data[i*8 +: 8];
        used_q <= used_q + msg_granules;
      end else if (send_now || (!fdi_valid && used_q == 0 && grant_valid)) begin
        fdi_q <= format_frame(payload_q, starts_q, grant_valid ? grant_field : 16'b0);
        fdi_valid <= 1'b1;
        if (grant_valid) grant_take <= 1'b1;
        payload_q <= '0; starts_q <= '0; used_q <= 0;
      end
      if (msg_valid && msg_granules > GRANULES_PER_FLIT) protocol_error <= 1'b1;
    end
  end
endmodule
