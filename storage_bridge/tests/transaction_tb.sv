`timescale 1ns/1ps
module transaction_tb #(
 parameter int WIDTH=256,
 parameter int PLANES=1
);
 import storage_bridge_pkg::*;
 localparam int BYTES=WIDTH/8;
 localparam int RP=PLANES-1;
 localparam int WGRAN=data_message_granules(MSG_WRITE_DATA,dlength(WIDTH));
 logic clk=0,rst_n=0;always #5 clk=~clk;
 logic fdi_rx_valid=0,fdi_rx_ready,fdi_tx_valid,fdi_tx_ready=1;
 logic [FDI_BITS-1:0] fdi_rx_data=0,fdi_tx_data;
 logic sink_enabled=0,hif_cmd_valid,hif_cmd_ready,hif_cmd_write;
 logic [1:0] hif_cmd_rp,hif_w_rp;
 logic [9:0] hif_cmd_id,hif_rsp_id;
 logic [63:0] hif_cmd_addr;
 logic [7:0] hif_cmd_len;
 logic [2:0] hif_cmd_size;
 logic hif_w_valid,hif_w_ready,hif_w_last;
 logic [15:0] hif_w_user;
 integer test_cycle=0;
 always @(posedge clk) test_cycle<=test_cycle+1;
 assign hif_w_ready=(test_cycle%5)!=0;
 logic [WIDTH-1:0] hif_w_data;
 logic [BYTES-1:0] hif_w_strb;
 logic hif_rsp_valid,hif_rsp_ready,protocol_error,business_idle;
 logic [63:0] rsp_count;
 integer grants=0,wcredits=0,commands=0,beats=0,current_id=0,current_beat=0;
 integer response_head=0,response_tail=0,response_count=0;
 logic [9:0] response_ids[8];
 assign hif_cmd_ready=sink_enabled;
 assign hif_rsp_valid=response_count!=0;
 assign hif_rsp_id=response_ids[response_head];
 storage_bridge_top #(.AXI_DATA_WIDTH(WIDTH),.RESOURCE_PLANES(PLANES)) dut(
   .clk,.rst_n,.fdi_rx_valid,.fdi_rx_ready,.fdi_rx_data,.fdi_tx_valid,.fdi_tx_ready,.fdi_tx_data,
   .hif_cmd_valid,.hif_cmd_ready,.hif_cmd_write,.hif_cmd_rp,.hif_cmd_id,.hif_cmd_addr,.hif_cmd_len,.hif_cmd_size,
   .hif_w_valid,.hif_w_ready,.hif_w_rp,.hif_w_user,.hif_w_data,.hif_w_strb,.hif_w_last,
   .hif_rsp_valid,.hif_rsp_ready,.hif_rsp_write(1'b1),.hif_rsp_rp(2'(RP)),.hif_rsp_id,
   .hif_rsp_user(16'b0),.hif_rsp_status(2'b0),.hif_rsp_last(1'b0),.hif_rsp_data(WIDTH'(0)),
   .business_idle,.stat_rsp_latency_count(rsp_count),.protocol_error);
 function automatic logic [WIDTH-1:0] expected(input int id,input int beat);
   logic [WIDTH-1:0] v;
   for(int b=0;b<BYTES;b++) v[b*8 +:8]=8'(id*17+beat*3+b);
   return v;
 endfunction
 function automatic logic [BYTES-1:0] expected_mask(input int id,input int beat);
   logic [BYTES-1:0] v;
   for(int b=0;b<BYTES;b++) v[b]=(id+beat+b)%3!=1;
   return v;
 endfunction
 function automatic logic[FDI_BITS-1:0] header(input logic[47:0] bitmap);
   logic [FDI_BITS-1:0] f;f=0;
   f[0*8 +:8]={bitmap[3:0],4'b0};f[1*8 +:8]=bitmap[11:4];
   f[2*8 +:8]={bitmap[15:12],4'b0};f[3*8 +:8]=bitmap[23:16];
   f[6*8 +:8]={bitmap[27:24],4'b0};f[7*8 +:8]=bitmap[35:28];
   f[8*8 +:8]={bitmap[39:36],4'b0};f[9*8 +:8]=bitmap[47:40];
   // Grant 8 B responses to the chosen RP, no address credits in this direction.
   f[4*8 +:16]=16'((RP<<14)|(3<<12));
   return f;
 endfunction
 function automatic logic[FDI_BITS-1:0] addresses();
   logic[FDI_BITS-1:0] f;logic[47:0] bitmap;logic[63:0] address;int start;
   bitmap=0;for(int n=0;n<4;n++) bitmap[n*3]=1;
   f=header(bitmap);
   for(int n=0;n<4;n++) begin
     start=10+n*15;address=64'h90000000+(n+1)*BYTES*2;
     f[start*8 +:8]=8'(8'h10|(RP<<2));
     f[(start+3)*8 +:8]=8'((n+1)>>2);
     f[(start+4)*8 +:8]=8'((((n+1)&3)<<6)|($clog2(BYTES)<<3));
     f[(start+5)*8 +:8]=1;
     for(int b=0;b<8;b++) f[(start+7+b)*8 +:8]=address[(7-b)*8 +:8];
   end
   return f;
 endfunction
 function automatic logic[FDI_BITS-1:0] data_frame(input int id,input int beat);
   logic[FDI_BITS-1:0] f;logic[WIDTH-1:0] v;logic[BYTES-1:0] mask;
   f=header(48'd1);v=expected(id,beat);
   mask=expected_mask(id,beat);
   f[10*8 +:8]=8'(8'h30|(RP<<2)|int'(dlength(WIDTH)));
   f[11*8 +:8]=8'((id*16+beat)>>8);f[12*8 +:8]=8'(id*16+beat);
   for(int b=0;b<BYTES;b++) f[(13+BYTES-1-b)*8 +:8]=v[b*8 +:8];
   for(int b=0;b<BYTES/8;b++) f[(13+BYTES+BYTES/8-1-b)*8 +:8]=mask[b*8 +:8];
   return f;
 endfunction
 task automatic send_frame(input logic[FDI_BITS-1:0] f);
   @(negedge clk);fdi_rx_data=f;fdi_rx_valid=1;
   do @(posedge clk);while(!fdi_rx_ready);
   @(negedge clk);fdi_rx_valid=0;
 endtask
 always @(posedge clk) if(rst_n) begin
   if(protocol_error) $fatal(1,"bridge error mask=%h",dut.error_code);
   if(fdi_tx_valid && fdi_tx_ready && fdi_tx_data[5*8+6 +:2]==RP) begin
     grants=grants+decode_credit(fdi_tx_data[4*8 +:3]);
     wcredits=wcredits+decode_credit(fdi_tx_data[4*8+6 +:3]);
   end
   if(hif_cmd_valid && hif_cmd_ready) begin
     if(!hif_cmd_write || hif_cmd_rp!=RP || hif_cmd_len!=1 || hif_cmd_size!=$clog2(BYTES))
       $fatal(1,"HIF descriptor mismatch");
     current_id=hif_cmd_id;current_beat=0;commands=commands+1;
   end
   if(hif_w_valid && hif_w_ready) begin
     if(hif_w_rp!=RP || hif_w_data!==expected(current_id,current_beat) ||
         hif_w_strb!==expected_mask(current_id,current_beat) ||
         hif_w_user!=16'(current_id*16+current_beat) || hif_w_last!=(current_beat==1))
       $fatal(1,"write RAM/beat mismatch id=%0d beat=%0d",current_id,current_beat);
     current_beat=current_beat+1;beats=beats+1;
   end
   case({hif_w_valid && hif_w_ready && hif_w_last,hif_rsp_valid && hif_rsp_ready})
     2'b10:response_count<=response_count+1;
     2'b01:response_count<=response_count-1;
     default:;
   endcase
   if(hif_w_valid && hif_w_ready && hif_w_last) begin
     response_ids[response_tail]<=10'(current_id);response_tail<=(response_tail+1)%8;
   end
   if(hif_rsp_valid && hif_rsp_ready) response_head<=(response_head+1)%8;
 end
 assert property(@(posedge clk) disable iff(!rst_n)
   hif_cmd_valid && !hif_cmd_ready |=> hif_cmd_valid && $stable({hif_cmd_id,hif_cmd_addr,hif_cmd_len,hif_cmd_size}));
 assert property(@(posedge clk) disable iff(!rst_n)
   hif_w_valid && !hif_w_ready |=> hif_w_valid && $stable({hif_w_rp,hif_w_user,hif_w_data,hif_w_strb,hif_w_last}));
 initial begin
   repeat(4) @(negedge clk);rst_n=1;
   repeat(80) @(negedge clk);
   if(grants!=12) $fatal(1,"initial WREQ credit mismatch %0d",grants);
   // Independent AXI channels permit WDATA to precede its AW on the wire.
   wcredits=wcredits-WGRAN;
   send_frame(data_frame(1,0));
   repeat(8) @(negedge clk);
   if(dut.wdata_depth!=1 || dut.descriptor_depth!=0)
     $fatal(1,"WDATA before AW was not independently buffered");
   send_frame(addresses());
   repeat(60) @(negedge clk);
   if(grants!=12 || commands!=0 || dut.descriptor_depth!=4)
     $fatal(1,"AW credit returned before descriptor release");
   for(int id=1;id<=4;id++) for(int beat=0;beat<2;beat++) begin
     if(id==1 && beat==0) continue;
     // Behave like the upstream endpoint: never inject more WDATA granules
     // than advertised, including in the 1024-bit/30-granule masked case.
     while(wcredits<WGRAN) @(negedge clk);
     wcredits=wcredits-WGRAN;
     send_frame(data_frame(id,beat));
   end
   repeat(30) @(negedge clk);
   if(grants!=12) $fatal(1,"AW credit returned while blocked at HIF");
   sink_enabled=1;
   repeat(300) @(negedge clk);
   if(commands!=4 || beats!=8 || grants!=24 || rsp_count!=4 || !business_idle || protocol_error)
     $fatal(1,"transaction did not drain: commands=%0d beats=%0d grants=%0d rsp=%0d idle=%0d",commands,beats,grants,rsp_count,business_idle);
   $display("PASS RTL descriptor lifecycle, reserved AW credit, write RAM and exact retirement WIDTH=%0d RP=%0d",WIDTH,PLANES);
   $finish;
 end
 initial begin #100000; $fatal(1,"test timeout");end
endmodule
