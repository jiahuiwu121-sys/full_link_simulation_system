`timescale 1ns/1ps
module credit_snapshot_tb;
  import storage_bridge_pkg::*;
  logic clk=0, rst_n=0;
  always #5 clk=~clk;
  logic return_valid=0;
  logic [7:0] return_granules=0;
  logic grant_valid, grant_take;
  logic [15:0] grant_field;
  logic fdi_valid;
  logic [FDI_BITS-1:0] fdi_data;
  logic credit_error, tx_error;
  integer emitted=0;
  aou_credit_manager credits (
    .clk, .rst_n, .header_valid(1'b0), .header_field(16'b0),
    .misc_valid(1'b0), .misc_ready(), .misc_data('0),
    .release_valid(1'b0), .release_rp(2'b0), .release_kind(3'b0), .release_granules(8'b0),
    .return_valid, .return_rp(2'b0), .return_kind(3'b0), .return_granules,
    .query_write(1'b0), .query_rp(2'b0), .query_granules(8'b0), .query_ok(),
    .consume_valid(1'b0), .consume_rp(2'b0), .consume_kind(3'b0), .consume_granules(8'b0),
    .grant_valid, .grant_field, .grant_take, .protocol_error(credit_error));
  aou_fdi_tx #(.CREDIT_RETURN_CYCLES(1)) tx (
    .clk, .rst_n, .msg_valid(1'b0), .msg_ready(), .msg_granules(6'b0), .msg_data('0),
    .msg_complete(1'b0), .msg_tag(6'b0),
    .grant_valid, .grant_field, .grant_take, .fdi_valid, .fdi_ready(1'b1), .fdi_data,
    .protocol_error(tx_error));
  always @(posedge clk) if (rst_n && fdi_valid)
    emitted = emitted + decode_credit(fdi_data[32 +: 3]);
  initial begin
    repeat(4) @(negedge clk);
    rst_n=1;
    repeat(30) @(negedge clk);
    if (credits.pending[0][0] != 0) $fatal(1,"initial credits not drained");
    emitted=0;
    return_valid=1; return_granules=3;
    @(negedge clk); return_valid=0;
    // Three cycles between returns: compatible with the current RX decoder,
    // which cannot produce a new request on every consecutive cycle.
    repeat(2) @(negedge clk);
    return_valid=1;
    @(negedge clk); return_valid=0;
    repeat(30) @(negedge clk);
    $display("returned_wreq_granules=6 emitted_wreq_granules=%0d pending=%0d protocol_error=%0d", emitted,credits.pending[0][0],credit_error|tx_error);
    if(emitted != 6 || credits.pending[0][0] != 0 || credit_error || tx_error)
      $fatal(1,"credit conservation failed");
    $display("PASS credit snapshot and same-edge conservation");
    $finish;
  end
endmodule
