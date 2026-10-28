`timescale 1ns/1ps
module tx_spanning_tb;
 import storage_bridge_pkg::*;
 logic clk=0,rst_n=0;always #5 clk=~clk;
 logic msg_valid=0,msg_ready;logic [5:0] msg_tag=0;
 logic [MAX_MESSAGE_BITS-1:0] msg_data=0;
 logic fdi_valid,fdi_ready=1,protocol_error,grant_take,business_idle;
 logic [FDI_BITS-1:0] fdi_data;logic [63:0] retire_mask;
 logic [63:0] packed_granules,spanning,credit_only;
 logic [63:0] retired=0;
 integer offset=0,frames=0,cycles=0;
 aou_fdi_tx #(.TX_FLUSH_CYCLES(3)) dut(.clk,.rst_n,.msg_valid,.msg_ready,
   .msg_granules(6'd27),.msg_data,.msg_complete(1'b1),.msg_tag,
   .grant_valid(1'b0),.grant_field(16'b0),.grant_take,.fdi_valid,.fdi_ready,.fdi_data,
   .retire_mask,.business_idle,.queue_depth(),.stat_packed_granules(packed_granules),
   .stat_spanning_messages(spanning),.stat_credit_only_frames(credit_only),.protocol_error);
 function automatic logic [MAX_MESSAGE_BITS-1:0] message(input int n);
   logic [MAX_MESSAGE_BITS-1:0] m;m=0;
   for(int b=0;b<135;b++) m[b*8 +:8]=8'(n*17+b);
   m[7:0]=8'h42;return m;
 endfunction
 function automatic logic [47:0] starts(input logic[FDI_BITS-1:0] f);
   return {f[9*8 +:8],f[8*8+4 +:4],f[7*8 +:8],f[6*8+4 +:4],
           f[3*8 +:8],f[2*8+4 +:4],f[1*8 +:8],f[0*8+4 +:4]};
 endfunction
 always @(negedge clk) if(rst_n) fdi_ready=(cycles%7)>=3;
 assert property (@(posedge clk) disable iff(!rst_n)
   fdi_valid && !fdi_ready |=> fdi_valid && $stable(fdi_data));
 always @(posedge clk) if(rst_n) begin
   cycles=cycles+1;
   if(fdi_valid && fdi_ready) begin
     logic [47:0] bitmap;logic [MAX_MESSAGE_BITS-1:0] expected;
     bitmap=starts(fdi_data);
     for(int g=0;g<48;g++) begin
       if(offset+g<270) begin
         expected=message((offset+g)/27);
         if(fdi_data[(10+g*5)*8 +:40] !== expected[((offset+g)%27)*40 +:40])
           $fatal(1,"cross-frame byte mismatch at granule %0d",offset+g);
         if(bitmap[g] !== ((offset+g)%27==0)) $fatal(1,"bad continuation MsgStart");
       end else if(bitmap[g] || fdi_data[(10+g*5)*8 +:40]!=0) $fatal(1,"nonzero tail padding");
     end
     if((retired & retire_mask)!=0) $fatal(1,"duplicate tag retirement");
     retired=retired|retire_mask;offset=offset+48;frames=frames+1;
   end
   if(cycles>300) $fatal(1,"TX failed to drain");
 end
 initial begin
   repeat(4) @(negedge clk);rst_n=1;
   for(int n=0;n<10;n++) begin
     msg_valid=1;msg_tag=6'(n);msg_data=message(n);
     do @(posedge clk); while(!msg_ready);
     @(negedge clk);
   end
   msg_valid=0;
   repeat(30) @(negedge clk);
   if(protocol_error || !business_idle || frames<6 || spanning==0 || packed_granules!=270 || retired!=1023)
     $fatal(1,"TX accounting/drain failed: frames=%0d granules=%0d retired=%h",frames,packed_granules,retired);
   $display("PASS cross-frame response stream, padding, backpressure, exact retirement: frames=%0d spans=%0d",frames,spanning);
   $finish;
 end
endmodule
