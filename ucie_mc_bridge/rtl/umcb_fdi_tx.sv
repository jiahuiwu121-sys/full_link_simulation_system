module umcb_fdi_tx # (parameter int FLUSH_CYCLES=2)(
  input logic clk,rst_n,message_valid,output logic message_ready,
  input logic [319:0] message,input logic [3:0] granules,
  input logic completes,input logic [5:0] tag,
  input logic grant_valid,input logic [15:0] grant,output logic grant_take,
  output logic valid,input logic ready,output logic [1999:0] frame,
  output logic [63:0] retire,output logic idle,
  output logic [63:0] frames_sent,packed_granules,spanning_messages
);
  import umcb_pkg::*;
  logic [1919:0] payload;
  logic [47:0] starts;
  logic [63:0] completions,frame_completions;
  logic [319:0] held;
  logic held_complete;
  logic [5:0] held_tag;
  integer used,remaining,offset,age,take;
  logic append,seal;
  assign message_ready=remaining==0;
  assign retire=valid && ready?frame_completions:64'b0;
  assign idle=used==0 && remaining==0 && !(valid && frame_completions!=0);
  always_comb begin
    take=remaining;if(take>48-used) take=48-used;
    append=remaining!=0 && used<48;
    seal=(!valid || ready) && (used==48 ||
      (used!=0 && remaining==0 && age>=FLUSH_CYCLES) ||
      (used==0 && remaining==0 && grant_valid));
    grant_take=seal && grant_valid;
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      payload<=0;starts<=0;completions<=0;frame_completions<=0;
      held<=0;held_complete<=0;held_tag<=0;used<=0;remaining<=0;offset<=0;age<=0;
      valid<=0;frame<=0;frames_sent<=0;packed_granules<=0;spanning_messages<=0;
    end else begin
      if(valid && ready) begin valid<=0;frames_sent<=frames_sent+1;end
      if(message_valid && message_ready) begin
        held<=message;remaining<=int'(granules);offset<=0;held_complete<=completes;held_tag<=tag;
      end
      if(append) begin
        if(offset==0) starts[used]<=1;
        for(int g=0;g<8;g++) if(g<take) payload[(used+g)*40+:40]<=held[(offset+g)*40+:40];
        used<=used+take;offset<=offset+take;remaining<=remaining-take;age<=0;
        if(take==remaining && held_complete) completions[held_tag]<=1;
        if(take<remaining) spanning_messages<=spanning_messages+1;
      end else if(used!=0 && age<FLUSH_CYCLES) age<=age+1;
      if(seal) begin
        valid<=1;frame<=make_frame(payload,starts,grant_valid?grant:16'b0);
        frame_completions<=completions;packed_granules<=packed_granules+64'(used);
        used<=0;starts<=0;payload<=0;completions<=0;age<=0;
      end
    end
  end
  initial if(FLUSH_CYCLES<1 || FLUSH_CYCLES>64) $error("invalid FDI flush interval");
endmodule
