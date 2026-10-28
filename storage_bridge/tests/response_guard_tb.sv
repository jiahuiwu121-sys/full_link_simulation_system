`timescale 1ns/1ps
module response_guard_tb;
 logic clk=0,rst_n=0;always #5 clk=~clk;
 logic cmd_valid=0,cmd_ready,hif_cmd_valid,hif_cmd_ready=1;
 logic rsp_valid=0,rsp_ready,rsp_last=0,checked_valid;
 logic [9:0] rsp_id=1;
 logic [63:0] retire_mask=0;
 logic business_idle,protocol_error;
 aou_transaction_manager dut(.clk,.rst_n,.cmd_valid,.cmd_ready,
   .cmd_write(1'b0),.cmd_rp(2'b0),.cmd_id(10'd1),.cmd_user(16'b0),.cmd_addr(64'h90000000),
   .cmd_len(8'd1),.cmd_size(3'd5),.cmd_prot(3'b0),.cmd_lock(1'b0),.cmd_cache(4'b0),.cmd_qos(4'b0),.cmd_origin_cycle(32'b0),
   .w_valid(1'b0),.w_rp(2'b0),.w_user(16'b0),.w_data(256'b0),.w_strb(32'b0),
   .hif_cmd_valid,.hif_cmd_ready,.hif_w_ready(1'b1),
   .backend_rsp_valid(rsp_valid),.backend_rsp_ready(rsp_ready),.backend_rsp_write(1'b0),
   .backend_rsp_rp(2'b0),.backend_rsp_id(rsp_id),.backend_rsp_last(rsp_last),
   .checked_rsp_valid(checked_valid),.checked_rsp_ready(1'b1),.retire_mask,.business_idle,.protocol_error);
 task automatic start_read;
   @(negedge clk);rst_n=0;cmd_valid=0;rsp_valid=0;retire_mask=0;
   repeat(2) @(negedge clk);rst_n=1;
   cmd_valid=1;do @(posedge clk);while(!cmd_ready);
   @(negedge clk);cmd_valid=0;
   repeat(3) @(negedge clk);
 endtask
 initial begin
   start_read();rsp_id=2;rsp_valid=1;
   @(negedge clk);
   if(!protocol_error || rsp_ready) $fatal(1,"unknown response ID was accepted");
   start_read();rsp_id=1;rsp_last=1;rsp_valid=1;
   @(negedge clk);
   if(!protocol_error || rsp_ready) $fatal(1,"short read response LAST was accepted");
   start_read();rsp_id=1;rsp_last=0;rsp_valid=1;
   @(negedge clk);rsp_last=1;
   @(negedge clk);rsp_valid=0;
   if(protocol_error || business_idle) $fatal(1,"tag released before FDI commit");
   retire_mask=1;
   @(negedge clk);retire_mask=0;
   if(protocol_error || !business_idle) $fatal(1,"valid response did not retire");
   $display("PASS unknown-ID rejection, LAST-length validation, tag lifetime through FDI commit");
   $finish;
 end
endmodule
