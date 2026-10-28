module aou_fdi_rx #(parameter int FRAME_FIFO_DEPTH=2) (
  input  logic clk,
  input  logic rst_n,
  input  logic                         fdi_valid,
  output logic                         fdi_ready,
  input  logic [storage_bridge_pkg::FDI_BITS-1:0] fdi_data,
  output logic                         header_credit_valid,
  output logic [15:0]                  header_credit,
  output logic                         msg_valid,
  input  logic                         msg_ready,
  output logic [3:0]                   msg_type,
  output logic [1:0]                   msg_rp,
  output logic [5:0]                   msg_granules,
  output logic [7:0]                   msg_bytes,
  output logic [storage_bridge_pkg::MAX_MESSAGE_BITS-1:0] msg_data,
  output logic [31:0]                  msg_origin_cycle,
  output logic                         business_idle,
  output logic                         link_idle,
  output logic [31:0]                  queue_depth,
  output logic                         protocol_error
);
  import storage_bridge_pkg::*;
  logic [FDI_BITS-1:0] frame_q;
  logic [47:0] starts_q;
  logic [5:0] granule_q;
  logic busy_q;
  logic [MAX_MESSAGE_BITS-1:0] carry_data_q;
  logic [5:0] carry_have_q, carry_total_q;
  logic [3:0] carry_type_q;
  logic [1:0] carry_rp_q;
  logic [FDI_BITS-1:0] frame_fifo[FRAME_FIFO_DEPTH];
  logic [31:0] frame_cycles[FRAME_FIFO_DEPTH];
  integer read_pointer,write_pointer,frame_count;
  logic [31:0] cycle_q,frame_cycle_q,carry_cycle_q;
  logic enqueue_frame,dequeue_frame,bypass_empty;
  integer next_start;
  logic [47:0] input_starts;


  function automatic logic [47:0] decode_starts(input logic [FDI_BITS-1:0] frame);
    logic [47:0] starts;
    starts = '0;
    starts[3:0]   = frame[0*8 + 4 +: 4];
    starts[11:4]  = frame[1*8 +: 8];
    starts[15:12] = frame[2*8 + 4 +: 4];
    starts[23:16] = frame[3*8 +: 8];
    starts[27:24] = frame[6*8 + 4 +: 4];
    starts[35:28] = frame[7*8 +: 8];
    starts[39:36] = frame[8*8 + 4 +: 4];
    starts[47:40] = frame[9*8 +: 8];
    return starts;
  endfunction

  // Exit may ignore fully identified credit maintenance, never an unknown
  // frame or an incomplete continuation. No state is discarded by this flag.
  function automatic logic only_credit(input logic [FDI_BITS-1:0] f,input int from_granule);
    logic [47:0] bitmap;logic [7:0] first;
    bitmap=decode_starts(f);
    for(int g=0;g<GRANULES_PER_FLIT;g++) if(g>=from_granule && bitmap[g]) begin
      first=f[(PROTOCOL_HEADER_BYTES+g*GRANULE_BYTES)*8 +:8];
      if(first[7:4]!=MSG_MISC || first[3:1]!=3'b100 || g+2>GRANULES_PER_FLIT) return 0;
      if(g+1<GRANULES_PER_FLIT && bitmap[g+1]) return 0;
    end
    return 1;
  endfunction
  always_comb begin
    input_starts=decode_starts(fdi_data);
    // Only bypass when no earlier frame can still create a continuation.
    bypass_empty=!busy_q && frame_count==0 && carry_have_q==0 && input_starts==0;
    fdi_ready=frame_count<FRAME_FIFO_DEPTH;
    enqueue_frame=fdi_valid && fdi_ready && !bypass_empty;
    dequeue_frame=!busy_q && frame_count!=0 && (!msg_valid || msg_ready);
    queue_depth=32'(frame_count);
    next_start=-1;
    for(int g=0;g<GRANULES_PER_FLIT;g++)
      if(next_start<0 && g>=int'(granule_q) && starts_q[g]) next_start=g;
    business_idle=carry_have_q==0 &&
      (!msg_valid || (msg_type==MSG_MISC && msg_data[3:1]==3'b100)) &&
      (!busy_q || only_credit(frame_q,int'(granule_q)));
    for(int q=0;q<FRAME_FIFO_DEPTH;q++)
      if(q<frame_count && !only_credit(frame_fifo[(read_pointer+q)%FRAME_FIFO_DEPTH],0)) business_idle=0;
    link_idle=!msg_valid && carry_have_q==0 && !busy_q && frame_count==0;
  end

  always_ff @(posedge clk or negedge rst_n) begin : receive
    int unsigned total,take,start;
    logic [7:0] first_byte;
    if(!rst_n) begin
      frame_q<='0;starts_q<='0;granule_q<=0;busy_q<=0;
      carry_data_q<='0;carry_have_q<=0;carry_total_q<=0;carry_type_q<=0;carry_rp_q<=0;
      header_credit_valid<=0;header_credit<=0;msg_valid<=0;msg_type<=0;msg_rp<=0;
      msg_granules<=0;msg_bytes<=0;msg_data<=0;msg_origin_cycle<=0;
      protocol_error<=0;read_pointer<=0;write_pointer<=0;frame_count<=0;
      cycle_q<=0;frame_cycle_q<=0;carry_cycle_q<=0;
    end else begin
      cycle_q<=cycle_q+1;header_credit_valid<=0;
      if(msg_valid && msg_ready) msg_valid<=0;
      if(fdi_valid && fdi_ready) begin
        header_credit<={fdi_data[5*8 +:8],fdi_data[4*8 +:8]};header_credit_valid<=1;
        if(fdi_data[0 +:4]!=0 || fdi_data[2*8 +:4]!=0 ||
            fdi_data[6*8 +:4]!=0 || fdi_data[8*8 +:4]!=0) protocol_error<=1;
      end
      case({enqueue_frame,dequeue_frame})
        2'b10:frame_count<=frame_count+1;
        2'b01:frame_count<=frame_count-1;
        default:;
      endcase
      if(enqueue_frame) begin
        frame_fifo[write_pointer]<=fdi_data;frame_cycles[write_pointer]<=cycle_q;
        write_pointer<=(write_pointer+1)%FRAME_FIFO_DEPTH;
      end
      if(dequeue_frame) begin
        frame_q<=frame_fifo[read_pointer];starts_q<=decode_starts(frame_fifo[read_pointer]);
        frame_cycle_q<=frame_cycles[read_pointer];granule_q<=0;busy_q<=1;
        read_pointer<=(read_pointer+1)%FRAME_FIFO_DEPTH;
      end else if(busy_q && (!msg_valid || msg_ready)) begin
        if(carry_have_q!=0) begin
          take=int'(carry_total_q)-int'(carry_have_q);
          if(take>GRANULES_PER_FLIT-int'(granule_q)) take=GRANULES_PER_FLIT-int'(granule_q);
          for(int i=0;i<30;i++) if(i<take) begin
            if(starts_q[int'(granule_q)+i]) protocol_error<=1;
            for(int b=0;b<GRANULE_BYTES;b++)
              carry_data_q[(int'(carry_have_q)+i)*40+b*8 +:8]<=
                frame_q[(PROTOCOL_HEADER_BYTES+(int'(granule_q)+i)*GRANULE_BYTES+b)*8 +:8];
          end
          granule_q<=6'(int'(granule_q)+take);
          if(int'(granule_q)+take==GRANULES_PER_FLIT) busy_q<=0;
          if(int'(carry_have_q)+take==int'(carry_total_q)) begin
            msg_data<=carry_data_q;
            for(int i=0;i<30;i++) if(i<take)
              for(int b=0;b<GRANULE_BYTES;b++)
                msg_data[(int'(carry_have_q)+i)*40+b*8 +:8]<=
                  frame_q[(PROTOCOL_HEADER_BYTES+(int'(granule_q)+i)*GRANULE_BYTES+b)*8 +:8];
            msg_type<=carry_type_q;msg_rp<=carry_rp_q;msg_granules<=carry_total_q;
            msg_bytes<=8'(int'(carry_total_q)*GRANULE_BYTES);msg_origin_cycle<=carry_cycle_q;
            msg_valid<=1;carry_have_q<=0;carry_total_q<=0;
          end else carry_have_q<=6'(int'(carry_have_q)+take);
        end else if(next_start<0) begin
          busy_q<=0;starts_q<=0;
        end else begin
          start=next_start;
          first_byte=frame_q[(PROTOCOL_HEADER_BYTES+start*GRANULE_BYTES)*8 +:8];
          total=message_granules(first_byte);
          if(total==0 || total>30) begin
            protocol_error<=1;busy_q<=0;starts_q<=0;
          end else begin
            take=total;
            if(take>GRANULES_PER_FLIT-start) take=GRANULES_PER_FLIT-start;
            for(int i=1;i<30;i++)
              if(i<take && starts_q[start+i]) protocol_error<=1;
            if(take==total) begin
              msg_data<=0;
              for(int i=0;i<30;i++) if(i<take)
                for(int b=0;b<GRANULE_BYTES;b++)
                  msg_data[i*40+b*8 +:8]<=frame_q[(PROTOCOL_HEADER_BYTES+(start+i)*GRANULE_BYTES+b)*8 +:8];
              msg_type<=first_byte[7:4];msg_rp<=first_byte[3:2];
              msg_granules<=6'(total);msg_bytes<=8'(total*GRANULE_BYTES);
              msg_origin_cycle<=frame_cycle_q;msg_valid<=1;
            end else begin
              carry_data_q<=0;
              for(int i=0;i<30;i++) if(i<take)
                for(int b=0;b<GRANULE_BYTES;b++)
                  carry_data_q[i*40+b*8 +:8]<=frame_q[(PROTOCOL_HEADER_BYTES+(start+i)*GRANULE_BYTES+b)*8 +:8];
              carry_have_q<=6'(take);carry_total_q<=6'(total);
              carry_type_q<=first_byte[7:4];carry_rp_q<=first_byte[3:2];carry_cycle_q<=frame_cycle_q;
            end
            granule_q<=6'(start+take);
            if(start+take==GRANULES_PER_FLIT) begin busy_q<=0;starts_q<=0;end
          end
        end
      end
    end
  end
  initial if(FRAME_FIFO_DEPTH<1 || FRAME_FIFO_DEPTH>16) $error("invalid RX frame FIFO depth");
endmodule
