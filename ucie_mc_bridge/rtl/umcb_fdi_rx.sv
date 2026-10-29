module umcb_fdi_rx(
  input logic clk,rst_n,
  input logic valid,output logic ready,input logic [1999:0] frame,
  output logic header_valid,output logic [15:0] header_credit,
  output logic message_valid,input logic message_ready,
  output logic [319:0] message,output logic idle,output logic fault
);
  import umcb_pkg::*;
  logic occupied;
  logic [1999:0] stored;
  logic [47:0] starts;
  logic [319:0] partial;
  integer cursor,have,wanted;
  integer first,amount,position;
  logic [319:0] assembled;
  assign ready=!occupied;
  assign idle=!occupied && !message_valid && have==0;
  always_comb begin
    first=-1;
    for(int g=0;g<48;g++) if(g>=cursor && starts[g] && first<0) first=g;
    position=have!=0?cursor:first;
    amount=have!=0?wanted-have:(first<0?0:message_size(stored[(10+first*5)*8+:8]));
    if(position>=0 && amount>48-position) amount=48-position;
    assembled=have!=0?partial:'0;
    for(int g=0;g<8;g++) if(g<amount && position>=0)
      assembled[(have+g)*40+:40]=stored[(10+(position+g)*5)*8+:40];
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      occupied<=0;stored<=0;starts<=0;cursor<=0;have<=0;wanted<=0;partial<=0;
      message_valid<=0;message<=0;header_valid<=0;header_credit<=0;fault<=0;
    end else begin
      header_valid<=0;
      if(message_valid && message_ready) message_valid<=0;
      if(valid && ready) begin
        stored<=frame;starts<=frame_starts(frame);cursor<=0;occupied<=1;
        header_valid<=1;header_credit<=frame[32+:16];
        if(frame[0+:4]!=0 || frame[16+:4]!=0 || frame[48+:4]!=0 || frame[64+:4]!=0) fault<=1;
      end
      if(occupied && (!message_valid || message_ready)) begin
        if(position<0) occupied<=0;
        else if(amount<=0 || (have==0 && message_size(stored[(10+position*5)*8+:8])>8)) begin
          fault<=1;occupied<=0;
        end else begin
          for(int g=0;g<8;g++) if(g<amount && (have!=0 || g!=0) && starts[position+g]) fault<=1;
          cursor<=position+amount;
          if(position+amount==48) occupied<=0;
          if(have+amount==(have!=0?wanted:message_size(stored[(10+position*5)*8+:8]))) begin
            message<=assembled;message_valid<=1;have<=0;wanted<=0;
          end else begin
            partial<=assembled;have<=have+amount;
            if(have==0) wanted<=message_size(stored[(10+position*5)*8+:8]);
          end
        end
      end
    end
  end
endmodule
