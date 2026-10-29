module umcb_aou_credit_manager #(
  parameter int RP=1,REQUEST_SLOTS=4,WDATA_GRANULES=64
)(
  input logic clk,rst_n,header_valid,input logic [15:0] header_credit,
  input logic misc_valid,input logic [319:0] misc_message,
  input logic [15:0] released[RP][3],
  input logic response_valid,response_write,input logic [1:0] response_rp,
  output logic response_allowed,input logic response_take,
  output logic grant_valid,output logic [15:0] grant,input logic grant_take,
  output logic fault
);
  import umcb_pkg::*;
  integer available[RP][2],pending[RP][3],turn,chosen;
  logic [2:0] codes[3];
  always_comb begin
    response_allowed=response_rp<RP && available[response_rp][response_write?1:0]>=(response_write?1:8);
    grant_valid=0;chosen=turn;
    for(int n=0;n<RP;n++) if(!grant_valid && (pending[(turn+n)%RP][0]!=0 || pending[(turn+n)%RP][1]!=0 || pending[(turn+n)%RP][2]!=0)) begin
      chosen=(turn+n)%RP;grant_valid=1;
    end
    for(int k=0;k<3;k++) codes[k]=credit_code(pending[chosen][k],7);
    grant={2'(chosen),5'b0,codes[2],codes[1],codes[0]};
  end
  always_ff @(posedge clk or negedge rst_n) begin : account
    integer n,idx,capacity;
    logic [63:0] bits;
    if(!rst_n) begin
      fault<=0;turn<=0;
      for(int r=0;r<RP;r++) begin
        available[r][0]<=0;available[r][1]<=0;
        pending[r][0]<=REQUEST_SLOTS*3;pending[r][1]<=REQUEST_SLOTS*3;pending[r][2]<=WDATA_GRANULES;
      end
    end else begin
      if(header_valid && header_credit[15:14]>=RP && header_credit[13:0]!=0) fault<=1;
      if(response_take && (!response_valid || !response_allowed)) fault<=1;
      if(grant_take) turn<=(chosen+1)%RP;
      for(int r=0;r<RP;r++) begin
        for(int k=0;k<2;k++) begin
          n=available[r][k];
          if(header_valid && header_credit[15:14]==r)
            n=n+credit_value(k==0?header_credit[11:9]:{1'b0,header_credit[13:12]});
          if(misc_valid) begin
            idx=k==0?43+r*3:55+r*2;
            bits=field_be(misc_message,idx,k==0?3:2);n=n+credit_value(bits[2:0]);
          end
          if(response_take && response_rp==r && int'(response_write)==k) n=n-(response_write?1:8);
          if(n<0 || n>65535) fault<=1;
          available[r][k]<=n;
        end
        for(int k=0;k<3;k++) begin
          n=pending[r][k]+int'(released[r][k]);
          if(grant_take && chosen==r) n=n-credit_value(codes[k]);
          capacity=k==2?WDATA_GRANULES:REQUEST_SLOTS*3;
          if(n<0 || n>capacity) fault<=1;
          pending[r][k]<=n;
        end
      end
    end
  end
endmodule
