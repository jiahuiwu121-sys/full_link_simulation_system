module aou_fdi_rx (
  input  logic clk,
  input  logic rst_n,
  input  logic                         fdi_valid,
  output logic                         fdi_ready,
  input  logic [storage_bridge_pkg::FDI_BITS-1:0] fdi_data,
  output logic                         header_credit_valid,
  output logic [15:0]                  header_credit,
  output logic                         msg_valid,
  input  logic                         msg_ready,
  output logic [3:0]                   msg_type,
  output logic [1:0]                   msg_rp,
  output logic [5:0]                   msg_granules,
  output logic [7:0]                   msg_bytes,
  output logic [storage_bridge_pkg::MAX_MESSAGE_BITS-1:0] msg_data,
  output logic                         protocol_error
);
  import storage_bridge_pkg::*;
  logic [FDI_BITS-1:0] frame_q;
  logic [47:0] starts_q;
  logic [5:0] granule_q;
  logic busy_q;
  logic [MAX_MESSAGE_BITS-1:0] carry_data_q;
  logic [5:0] carry_have_q, carry_total_q;
  logic [3:0] carry_type_q;
  logic [1:0] carry_rp_q;

  function automatic logic [47:0] decode_starts(input logic [FDI_BITS-1:0] frame);
    logic [47:0] starts;
    starts = '0;
    starts[3:0]   = frame[0*8 + 4 +: 4];
    starts[11:4]  = frame[1*8 +: 8];
    starts[15:12] = frame[2*8 + 4 +: 4];
    starts[23:16] = frame[3*8 +: 8];
    starts[27:24] = frame[6*8 + 4 +: 4];
    starts[35:28] = frame[7*8 +: 8];
    starts[39:36] = frame[8*8 + 4 +: 4];
    starts[47:40] = frame[9*8 +: 8];
    return starts;
  endfunction

  assign fdi_ready = !busy_q && !msg_valid;

  always_ff @(posedge clk or negedge rst_n) begin : receive
    int unsigned total, take;
    logic [7:0] first_byte;
    if (!rst_n) begin
      frame_q <= '0; starts_q <= '0; granule_q <= '0; busy_q <= 1'b0;
      carry_data_q <= '0; carry_have_q <= '0; carry_total_q <= '0;
      carry_type_q <= '0; carry_rp_q <= '0;
      header_credit_valid <= 1'b0; header_credit <= '0;
      msg_valid <= 1'b0; msg_type <= '0; msg_rp <= '0;
      msg_granules <= '0; msg_bytes <= '0; msg_data <= '0;
      protocol_error <= 1'b0;
    end else begin
      header_credit_valid <= 1'b0;
      if (msg_valid && msg_ready) msg_valid <= 1'b0;
      if (fdi_valid && fdi_ready) begin
        frame_q <= fdi_data;
        starts_q <= decode_starts(fdi_data);
        granule_q <= 0;
        busy_q <= 1'b1;
        header_credit <= {fdi_data[5*8 +: 8], fdi_data[4*8 +: 8]};
        header_credit_valid <= 1'b1;
        if (fdi_data[0 +: 2] != 2'b00 || fdi_data[0*8+2 +: 2] != 0 ||
            fdi_data[2*8 +: 4] != 0 || fdi_data[6*8 +: 4] != 0 ||
            fdi_data[8*8 +: 4] != 0)
          protocol_error <= 1'b1;
      end else if (busy_q && !msg_valid) begin
        if (granule_q >= GRANULES_PER_FLIT) begin
          busy_q <= 1'b0;
        end else if (carry_have_q != 0) begin
          take = carry_total_q - carry_have_q;
          if (take > GRANULES_PER_FLIT - granule_q)
            take = GRANULES_PER_FLIT - granule_q;
          for (int unsigned i = 0; i < take; i++) begin
            if (starts_q[granule_q+i]) protocol_error <= 1'b1;
            for (int unsigned b = 0; b < GRANULE_BYTES; b++)
              carry_data_q[(carry_have_q+i)*40+b*8 +: 8] <=
                frame_q[(PROTOCOL_HEADER_BYTES+(granule_q+i)*GRANULE_BYTES+b)*8 +: 8];
          end
          granule_q <= granule_q + take;
          if (carry_have_q + take == carry_total_q) begin
            msg_data <= carry_data_q;
            for (int unsigned i = 0; i < take; i++)
              for (int unsigned b = 0; b < GRANULE_BYTES; b++)
                msg_data[(carry_have_q+i)*40+b*8 +: 8] <=
                  frame_q[(PROTOCOL_HEADER_BYTES+(granule_q+i)*GRANULE_BYTES+b)*8 +: 8];
            msg_type <= carry_type_q; msg_rp <= carry_rp_q;
            msg_granules <= carry_total_q; msg_bytes <= carry_total_q * GRANULE_BYTES;
            msg_valid <= 1'b1; carry_have_q <= 0; carry_total_q <= 0;
          end else carry_have_q <= carry_have_q + take;
        end else if (!starts_q[granule_q]) begin
          granule_q <= granule_q + 1;
        end else begin
          first_byte = frame_q[(PROTOCOL_HEADER_BYTES+granule_q*GRANULE_BYTES)*8 +: 8];
          total = message_granules(first_byte);
          if (total == 0 || total > 30) begin
            protocol_error <= 1'b1;
            granule_q <= granule_q + 1;
          end else begin
            take = total;
            if (take > GRANULES_PER_FLIT - granule_q)
              take = GRANULES_PER_FLIT - granule_q;
            for (int unsigned i = 1; i < take; i++)
              if (starts_q[granule_q+i]) protocol_error <= 1'b1;
            if (take == total) begin
              msg_data <= '0;
              for (int unsigned i = 0; i < take; i++)
                for (int unsigned b = 0; b < GRANULE_BYTES; b++)
                  msg_data[i*40+b*8 +: 8] <=
                    frame_q[(PROTOCOL_HEADER_BYTES+(granule_q+i)*GRANULE_BYTES+b)*8 +: 8];
              msg_type <= first_byte[7:4]; msg_rp <= first_byte[3:2];
              msg_granules <= total; msg_bytes <= total * GRANULE_BYTES;
              msg_valid <= 1'b1;
            end else begin
              carry_data_q <= '0;
              for (int unsigned i = 0; i < take; i++)
                for (int unsigned b = 0; b < GRANULE_BYTES; b++)
                  carry_data_q[i*40+b*8 +: 8] <=
                    frame_q[(PROTOCOL_HEADER_BYTES+(granule_q+i)*GRANULE_BYTES+b)*8 +: 8];
              carry_have_q <= take; carry_total_q <= total;
              carry_type_q <= first_byte[7:4]; carry_rp_q <= first_byte[3:2];
            end
            granule_q <= granule_q + take;
          end
        end
      end
    end
  end
endmodule
