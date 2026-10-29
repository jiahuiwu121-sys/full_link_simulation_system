`timescale 1ns/1fs
module tx_span_tb;
  import umcb_pkg::*;
  logic clk=0,rst_n=0;
  always #5 clk=~clk;
  logic message_valid=0,message_ready,completes=0,valid,ready,grant_take,idle;
  logic [319:0] message=0;
  logic [3:0] granules=0;
  logic [5:0] tag=0;
  logic [1999:0] frame;
  logic [63:0] retire,frames_sent,packed_granules,spanning_messages;
  integer cycle=0,frame_index=0,seen=0,have=0,need=0,finished=0;
  logic [319:0] expected[8],partial=0;
  logic [63:0] retired=0;
  string outdir;
  integer fd;
  assign ready=cycle%9>=4;
  umcb_fdi_tx #(.FLUSH_CYCLES(8)) dut(.clk,.rst_n,.message_valid,.message_ready,.message,.granules,
    .completes,.tag,.grant_valid(1'b0),.grant(16'b0),.grant_take,.valid,.ready,.frame,.retire,.idle,
    .frames_sent,.packed_granules,.spanning_messages);
  task automatic compare_message(input logic [319:0] m);
    if(seen>=8 || m!==expected[seen]) $fatal(1,"TX span byte/order mismatch %0d",seen);
    seen=seen+1;
  endtask
  always @(posedge clk) if(rst_n) begin : monitor
    integer g,n;
    logic [47:0] starts;
    logic [319:0] m;
    cycle<=cycle+1;
    if(retire!=0) begin
      if((retired & retire)!=0) $fatal(1,"duplicate tag retirement");
      retired=retired|retire;
    end
    if(valid && ready) begin
      starts=frame_starts(frame);g=0;frame_index=frame_index+1;
      while(g<48) begin
        if(have!=0) begin
          if(starts[g]) $fatal(1,"continuation has MsgStart");
          partial[have*40+:40]=frame[(10+g*5)*8+:40];have=have+1;g=g+1;
          if(have==need) begin compare_message(partial);have=0;need=0;end
        end else if(starts[g]) begin
          n=frame[(10+g*5)*8+4+:4]==M_B?1:8;m=0;
          if(g+n<=48) begin
            for(int k=0;k<n;k++) m[k*40+:40]=frame[(10+(g+k)*5)*8+:40];
            compare_message(m);g=g+n;
          end else begin
            partial=0;have=48-g;need=n;
            for(int k=0;k<have;k++) partial[k*40+:40]=frame[(10+(g+k)*5)*8+:40];
            g=48;
          end
        end else g=g+1;
      end
      if(retire[2] && seen!=8) $fatal(1,"retired before final message fragment");
    end
    if(cycle>1000) $fatal(1,"TX span timeout");
  end
  assert property(@(posedge clk) disable iff(!rst_n) valid && !ready |=> valid && $stable(frame));
  initial begin
    if(!$value$plusargs("OUT=%s",outdir)) outdir=".";
    $dumpfile({outdir,"/bridge.vcd"});$dumpvars(0,tx_span_tb);
    for(int n=0;n<8;n++) begin
      expected[n]=0;expected[n][0+:8]=n==0?8'h50:8'h40;
      for(int b=1;b<(n==0?5:40);b++) expected[n][b*8+:8]=8'(n*19+b);
    end
    repeat(3) @(negedge clk);rst_n=1;
    for(int n=0;n<8;n++) begin
      @(negedge clk);message_valid=1;message=expected[n];granules=n==0?1:8;
      completes=n==0 || n==7;tag=n==0?1:2;
      do @(posedge clk);while(!message_ready);
      @(negedge clk);message_valid=0;
    end
    while(seen!=8 || !idle) @(negedge clk);
    if(spanning_messages==0 || retired!=64'h6 || packed_granules!=57) $fatal(1,"TX span counters/retire mismatch");
    fd=$fopen({outdir,"/summary.json"},"w");
    $fwrite(fd,"{\"status\":\"unit_verified\",\"real_mc_verified\":false,\"messages\":8,\"tx_frames\":%0d,\"packed_granules\":%0d,\"spanning_messages\":%0d}\n",frames_sent,packed_granules,spanning_messages);
    $fclose(fd);$display("TEST_PASS tx spanning and retirement");$finish;
  end
endmodule
