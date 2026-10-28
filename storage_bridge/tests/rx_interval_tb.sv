`timescale 1ns/1ps
module rx_interval_tb;
  import storage_bridge_pkg::*;
  logic clk=0,rst_n=0;
  always #5 clk=~clk;
  logic fdi_ready;
  logic header_credit_valid,msg_valid,protocol_error;
  logic [15:0] header_credit;
  logic [3:0] msg_type;
  logic [1:0] msg_rp;
  logic [5:0] msg_granules;
  logic [7:0] msg_bytes;
  logic [MAX_MESSAGE_BITS-1:0] msg_data;
  integer cycles=0,accepted=0,previous=-1,interval=0;
  aou_fdi_rx dut(.clk,.rst_n,.fdi_valid(1'b1),.fdi_ready,.fdi_data('0),
    .header_credit_valid,.header_credit,.msg_valid,.msg_ready(1'b1),
    .msg_type,.msg_rp,.msg_granules,.msg_bytes,.msg_data,.protocol_error);
  always @(posedge clk) if(rst_n) begin
    cycles=cycles+1;
    if(fdi_ready) begin
      if(previous>=0) begin
        interval=cycles-previous;
        $display("empty_frame_accept_interval_cycles=%0d",interval);
      end
      previous=cycles;accepted=accepted+1;
    end
  end
  initial begin
    repeat(4) @(negedge clk);rst_n=1;
    repeat(160) @(negedge clk);
    if(accepted<100 || interval!=1 || protocol_error) $fatal(1,"unexpected RX timing");
    $display("PASS: empty/header-only frames accepted every cycle");
    $finish;
  end
endmodule
