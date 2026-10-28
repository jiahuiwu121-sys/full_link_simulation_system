module aou_fdi_tx #(
  parameter int FRAME_FIFO_DEPTH=2,
  parameter int TX_FLUSH_CYCLES=2,
  parameter int CREDIT_RETURN_CYCLES=8
)(
  input logic clk,rst_n,
  input logic msg_valid,output logic msg_ready,
  input logic [5:0] msg_granules,
  input logic [storage_bridge_pkg::MAX_MESSAGE_BITS-1:0] msg_data,
  input logic msg_complete,input logic [5:0] msg_tag,
  input logic grant_valid,input logic [15:0] grant_field,output logic grant_take,
  output logic fdi_valid,input logic fdi_ready,
  output logic [storage_bridge_pkg::FDI_BITS-1:0] fdi_data,
  output logic [63:0] retire_mask,
  output logic business_idle,
  output logic [31:0] queue_depth,
  output logic [63:0] stat_packed_granules,stat_spanning_messages,stat_credit_only_frames,
  output logic protocol_error
);
  import storage_bridge_pkg::*;
  logic [PAYLOAD_BYTES*8-1:0] payload_q,payload_d;
  logic [47:0] starts_q,starts_d;
  integer used_q,used_d;
  logic [63:0] complete_q,complete_d;
  logic [MAX_MESSAGE_BITS-1:0] spill_q,spill_d;
  integer spill_offset_q,spill_offset_d,spill_total_q,spill_total_d;
  logic spill_complete_q,spill_complete_d;
  logic [5:0] spill_tag_q,spill_tag_d;
  logic [FDI_BITS-1:0] frames[FRAME_FIFO_DEPTH];
  logic [63:0] frame_completions[FRAME_FIFO_DEPTH];
  logic frame_business[FRAME_FIFO_DEPTH];
  integer read_pointer,write_pointer,frame_count,idle_age_q,credit_age_q;
  logic pop_frame,push_frame,append_message,space_available;
  integer sealed_granules;
  function automatic logic [FDI_BITS-1:0] format_frame(
      input logic [PAYLOAD_BYTES*8-1:0] payload,
      input logic [47:0] starts_in,
      input logic [15:0] credit);
    logic [FDI_BITS-1:0] frame;
    logic [47:0] starts;
    starts = starts_in; frame = '0;
    frame[0*8 +: 8] = {starts[3:0], 2'b00, 2'b00};
    frame[1*8 +: 8] = starts[11:4];
    frame[2*8 +: 8] = {starts[15:12], 4'b0000};
    frame[3*8 +: 8] = starts[23:16];
    frame[4*8 +: 8] = credit[7:0];
    frame[5*8 +: 8] = credit[15:8];
    frame[6*8 +: 8] = {starts[27:24], 4'b0000};
    frame[7*8 +: 8] = starts[35:28];
    frame[8*8 +: 8] = {starts[39:36], 4'b0000};
    frame[9*8 +: 8] = starts[47:40];
    for (int i = 0; i < PAYLOAD_BYTES; i++)
      frame[(PROTOCOL_HEADER_BYTES+i)*8 +: 8] = payload[i*8 +: 8];
    return frame;
  endfunction


  always_comb begin : pack_and_seal
    int take,offset,total;
    logic last_piece,completes;
    logic [5:0] tag;
    logic [MAX_MESSAGE_BITS-1:0] source_data;
    payload_d=payload_q;starts_d=starts_q;used_d=used_q;complete_d=complete_q;
    spill_d=spill_q;spill_offset_d=spill_offset_q;spill_total_d=spill_total_q;
    spill_complete_d=spill_complete_q;spill_tag_d=spill_tag_q;

    append_message=0;push_frame=0;sealed_granules=0;
    take=0;offset=0;total=0;last_piece=0;completes=0;tag=0;source_data=0;
    if(space_available && spill_total_q!=0) begin
      source_data=spill_q;offset=spill_offset_q;total=spill_total_q;
      completes=spill_complete_q;tag=spill_tag_q;append_message=1;
    end else if(msg_valid && msg_ready) begin
      source_data=msg_data;total=int'(msg_granules);completes=msg_complete;tag=msg_tag;
      starts_d[used_q]=1;append_message=1;
    end
    if(append_message) begin
      take=total-offset;
      if(take>GRANULES_PER_FLIT-used_q) take=GRANULES_PER_FLIT-used_q;
      for(int g=0;g<30;g++) if(g<take)
        payload_d[(used_q+g)*40 +:40]=source_data[(offset+g)*40 +:40];
      used_d=used_q+take;last_piece=offset+take==total;
      if(last_piece) begin
        spill_total_d=0;spill_offset_d=0;
        if(completes) complete_d[tag]=1;
      end else begin
        spill_d=source_data;spill_total_d=total;spill_offset_d=offset+take;
        spill_complete_d=completes;spill_tag_d=tag;
      end
    end
    if(space_available && (used_d==GRANULES_PER_FLIT ||
        (used_d!=0 && !append_message && idle_age_q+1>=TX_FLUSH_CYCLES) ||
        (grant_valid && credit_age_q+1>=CREDIT_RETURN_CYCLES))) begin
      push_frame=1;sealed_granules=used_d;
    end
    // This is an atomic, same-edge reservation. The credit manager subtracts
    // exactly the grant_field that format_frame captures on this edge.
    grant_take=push_frame && grant_valid;
    business_idle=used_q==0 && spill_total_q==0;
    for(int n=0;n<FRAME_FIFO_DEPTH;n++)
      if(n<frame_count && frame_business[(read_pointer+n)%FRAME_FIFO_DEPTH]) business_idle=0;
  end

  assign fdi_valid=frame_count!=0;
  assign fdi_data=frames[read_pointer];
  assign pop_frame=fdi_valid && fdi_ready;
  assign retire_mask=pop_frame?frame_completions[read_pointer]:64'b0;
  assign queue_depth=32'(frame_count);
  assign space_available=frame_count<FRAME_FIFO_DEPTH || pop_frame;
  assign msg_ready=space_available && spill_total_q==0 && msg_granules>0 && msg_granules<=30;

  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      payload_q<=0;starts_q<=0;used_q<=0;complete_q<=0;spill_q<=0;
      spill_offset_q<=0;spill_total_q<=0;spill_complete_q<=0;spill_tag_q<=0;
      read_pointer<=0;write_pointer<=0;frame_count<=0;idle_age_q<=0;credit_age_q<=0;
      protocol_error<=0;stat_packed_granules<=0;stat_spanning_messages<=0;stat_credit_only_frames<=0;
    end else begin
      payload_q<=payload_d;starts_q<=starts_d;used_q<=used_d;complete_q<=complete_d;
      spill_q<=spill_d;spill_offset_q<=spill_offset_d;spill_total_q<=spill_total_d;
      spill_complete_q<=spill_complete_d;spill_tag_q<=spill_tag_d;
      if(append_message || push_frame || used_q==0) idle_age_q<=0;
      else if(idle_age_q<TX_FLUSH_CYCLES) idle_age_q<=idle_age_q+1;
      if(!grant_valid || grant_take) credit_age_q<=0;
      else if(credit_age_q<CREDIT_RETURN_CYCLES) credit_age_q<=credit_age_q+1;
      case({push_frame,pop_frame})
        2'b10:frame_count<=frame_count+1;
        2'b01:frame_count<=frame_count-1;
        default:;
      endcase
      if(pop_frame) read_pointer<=(read_pointer+1)%FRAME_FIFO_DEPTH;
      if(push_frame) begin
        frames[write_pointer]<=format_frame(payload_d,starts_d,grant_valid?grant_field:16'b0);
        frame_completions[write_pointer]<=complete_d;frame_business[write_pointer]<=used_d!=0;
        write_pointer<=(write_pointer+1)%FRAME_FIFO_DEPTH;
        payload_q<=0;starts_q<=0;used_q<=0;complete_q<=0;
        stat_packed_granules<=stat_packed_granules+64'(sealed_granules);
        if(sealed_granules==0) stat_credit_only_frames<=stat_credit_only_frames+1;
      end
      if(msg_valid && msg_ready && spill_total_q==0 && spill_total_d!=0)
        stat_spanning_messages<=stat_spanning_messages+1;
      if(msg_valid && (msg_granules==0 || msg_granules>30)) protocol_error<=1;
    end
  end
  initial begin
    if(FRAME_FIFO_DEPTH<1 || FRAME_FIFO_DEPTH>16 || TX_FLUSH_CYCLES<1 || CREDIT_RETURN_CYCLES<1)
      $error("invalid TX frame FIFO/flush configuration");
  end
endmodule
