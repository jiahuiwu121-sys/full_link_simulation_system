module umcb_mc_credit_manager #(
  parameter int INITIAL_LPR=24,INITIAL_HPR=8,INITIAL_WR=32,
  parameter logic [1:0] HPR_CODE=2
)(
  input logic clk,rst_n,lpr_return,hpr_return,wr_return,
  input logic accepted,input logic [1:0] command_type,priority_code,
  output logic allowed,output logic [15:0] lpr_count,hpr_count,wr_count,
  output logic fault
);
  logic needs_read,needs_write,high_priority;
  always_comb begin
    needs_read=command_type==1 || command_type==2;
    needs_write=command_type==0 || command_type==2;
    high_priority=command_type==1 && priority_code==HPR_CODE;
    allowed=(!needs_read || (high_priority?hpr_count!=0:lpr_count!=0)) && (!needs_write || wr_count!=0);
  end
  always_ff @(posedge clk or negedge rst_n) begin : update
    integer l,h,w;
    if(!rst_n) begin
      lpr_count<=16'(INITIAL_LPR);hpr_count<=16'(INITIAL_HPR);wr_count<=16'(INITIAL_WR);fault<=0;
    end else begin
      l=int'(lpr_count)+int'(lpr_return)-int'(accepted && needs_read && !high_priority);
      h=int'(hpr_count)+int'(hpr_return)-int'(accepted && needs_read && high_priority);
      w=int'(wr_count)+int'(wr_return)-int'(accepted && needs_write);
      if(l<0 || h<0 || w<0 || l>INITIAL_LPR || h>INITIAL_HPR || w>INITIAL_WR || (accepted && !allowed)) fault<=1;
      lpr_count<=16'(l);hpr_count<=16'(h);wr_count<=16'(w);
    end
  end
  initial begin
    if(INITIAL_LPR<0 || INITIAL_LPR>65535 || INITIAL_HPR<0 || INITIAL_HPR>65535 || INITIAL_WR<0 || INITIAL_WR>65535)
      $error("MC credit initialization outside counter range");
  end
endmodule
