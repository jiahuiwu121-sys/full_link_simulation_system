// Independent bounded parent/child engine. Metadata, RAM ownership, token and
// pointer scheduling are hardware state. The external MC is never synthesized here.
module umcb_transaction_core #(
  parameter int RP=1,REQUEST_SLOTS=4,CHILD_SLOTS=32,MAX_BYTES=4096,
  parameter int WDATA_GRANULES=64,
  parameter bit POSTED_WRITE_ACK=0,TWO_WORD_COMMANDS=1,
  parameter logic LENGTH_ONE=0,LENGTH_TWO=1,MASK_ONE_WRITES=1,
  parameter logic [1:0] HPR_CODE=2,
  parameter logic [10:0] COMMAND_LATENCY=0,
  parameter bit AUTO_PRECHARGE=0
)(
  input logic clk,rst_n,
  input logic request_valid,output logic request_ready,input umcb_pkg::request_t request,
  input logic write_valid,output logic write_ready,input umcb_pkg::write_t write_data,
  output logic response_valid,input logic response_ready,output umcb_pkg::response_t response,
  input logic [63:0] retire,output logic [15:0] released[RP][3],
  output logic hif_cmd_valid,input logic hif_cmd_stall,
  output logic [1:0] hif_cmd_type,hif_cmd_pri,
  output logic [39:0] hif_cmd_addr,output logic [52:0] hif_cmd_token,
  output logic hif_cmd_length,output logic [18:0] hif_cmd_wdata_ptr,
  output logic hif_cmd_autopre,output logic [10:0] hif_cmd_latency,
  output logic credit_query_valid,output logic [1:0] credit_query_type,credit_query_pri,
  input logic credit_allowed,
  input logic hif_rdata_valid,hif_rdata_end,input logic [52:0] hif_rdata_token,
  input logic [255:0] hif_rdata,
  input logic hif_rdata_uncorr_ecc_err,hif_rdata_addr_err,hif_rdata_crc_err,
  output logic hif_wdata_valid,input logic hif_wdata_stall,
  output logic [255:0] hif_wdata,output logic [31:0] hif_wdata_mask,output logic hif_wdata_end,
  input logic hif_wdata_ptr_valid,input logic [18:0] hif_wdata_ptr,input logic hif_wdata_ptr_addr_err,
  output logic idle,output logic [31:0] error_code,
  output logic [31:0] parents_used,children_used,
  output logic [63:0] stat_commands,stat_reads,stat_writes,stat_rmw,
  output logic [63:0] stat_cmd_stall,stat_wdata_stall,stat_pointer_requests,stat_read_words,
  output logic [63:0] stat_effective_write_bytes,stat_mc_write_words,stat_response_count
);
  import umcb_pkg::*;
  localparam int P=2*RP*REQUEST_SLOTS,WQ=WDATA_GRANULES/7;
  request_t descriptors[P];
  logic present[P],rejected[P],response_sent[P];
  logic [1:0] status[P];
  logic [31:0] sequence_id[P],sequence_next;
  integer received[P],next_word[P],finished[P],response_beat[P];
  logic [7:0] bytes_ram[P][MAX_BYTES];
  logic [MAX_BYTES-1:0] masks[P];
  write_t early[RP][WQ];
  integer qhead[RP],qtail[RP],qcount[RP],qused[RP];
  typedef struct packed {
    logic valid,accepted,write,requested;
    logic [52:0] token;
    logic [18:0] pointer;
    logic [5:0] parent;
    logic [7:0] word_index;
    logic [1:0] words,received;
    logic [1:0] operation,priority_code;
  } child_t;
  child_t children[CHILD_SLOTS];
  logic [52:0] serial;
  integer command_slot,write_queue[CHILD_SLOTS],write_head,write_tail,write_count,write_word;
  integer rsp_hold;
  integer allocation,fill,issue,free_child,response_parent,return_child,pointer_child;
  integer issue_words,issue_kind,words_total,needed,pop_rp;
  logic issue_blocked,pointer_collision,data_pop,cmd_fire,w_fire,push_pointer,pop_pointer;
  logic [1:0] issue_priority;
  integer completion_delta[P];
  function automatic integer length_bytes(input request_t d);
    return (int'(d.len)+1)<<d.size;
  endfunction
  function automatic integer word_count(input request_t d);
    return (int'(d.addr[4:0])+length_bytes(d)+31)/32;
  endfunction
  function automatic logic overlap(input request_t a,input request_t b);
    return a.addr < b.addr+64'(length_bytes(b)) && b.addr < a.addr+64'(length_bytes(a));
  endfunction
  function automatic logic input_done(input integer p);
    return !descriptors[p].write || received[p]==int'(descriptors[p].len)+1;
  endfunction
  function automatic logic memory_done(input integer p);
    return rejected[p]?input_done(p):finished[p]==word_count(descriptors[p]);
  endfunction

  always_comb begin : drive
    integer total,end_byte,need_beats,p,word_offset,lane,width,offset;
    logic blocked;
    total=0;end_byte=0;need_beats=0;p=0;word_offset=0;lane=0;width=0;offset=0;blocked=0;
    allocation=-1;fill=-1;issue=-1;free_child=-1;response_parent=-1;return_child=-1;pointer_child=-1;
    parents_used=0;children_used=0;issue_words=0;issue_kind=0;issue_priority=0;pointer_collision=0;
    for(int c=0;c<CHILD_SLOTS;c++) begin
      if(!children[c].valid && free_child<0) free_child=c;
      if(children[c].valid) begin
        children_used=children_used+1;
        if(children[c].pointer==serial[18:0]) pointer_collision=1;
        if(children[c].accepted && !children[c].write && children[c].token==hif_rdata_token) return_child=c;
        if(children[c].accepted && children[c].write && children[c].pointer==hif_wdata_ptr) pointer_child=c;
      end
    end
    for(int n=0;n<P;n++) begin
      if(!present[n] && allocation<0 && n/REQUEST_SLOTS==int'(request.write)*RP+int'(request.rp)) allocation=n;
      if(present[n]) begin
        parents_used=parents_used+1;
        if(descriptors[n].write && !input_done(n) && qcount[descriptors[n].rp]>0 &&
           (fill<0 || sequence_id[n]<sequence_id[fill])) fill=n;
        blocked=0;
        for(int older=0;older<P;older++) if(present[older] && sequence_id[older]<sequence_id[n]) begin
          if(!memory_done(older) && (descriptors[n].write || descriptors[older].write) && overlap(descriptors[n],descriptors[older])) blocked=1;
        end
        total=word_count(descriptors[n]);
        end_byte=(next_word[n]+1)*32;
        if(end_byte>int'(descriptors[n].addr[4:0])+length_bytes(descriptors[n])) end_byte=int'(descriptors[n].addr[4:0])+length_bytes(descriptors[n]);
        need_beats=(end_byte-int'(descriptors[n].addr[4:0]))/(1<<descriptors[n].size);
        if(!rejected[n] && next_word[n]<total && !blocked &&
           (!descriptors[n].write || received[n]>=need_beats) &&
           (issue<0 || sequence_id[n]<sequence_id[issue])) issue=n;
        blocked=0;
        for(int older=0;older<P;older++)
          if(present[older] && sequence_id[older]<sequence_id[n] && descriptors[older].write==descriptors[n].write &&
             descriptors[older].rp==descriptors[n].rp && descriptors[older].id==descriptors[n].id) blocked=1;
        if(memory_done(n) && input_done(n) && !response_sent[n] && !blocked &&
           (response_parent<0 || sequence_id[n]<sequence_id[response_parent])) response_parent=n;
      end
    end
    if(issue>=0) begin
      issue_words=1;
      if(TWO_WORD_COMMANDS && next_word[issue]+1<word_count(descriptors[issue])) begin
        end_byte=(next_word[issue]+2)*32;
        if(end_byte>int'(descriptors[issue].addr[4:0])+length_bytes(descriptors[issue])) end_byte=int'(descriptors[issue].addr[4:0])+length_bytes(descriptors[issue]);
        need_beats=(end_byte-int'(descriptors[issue].addr[4:0]))/(1<<descriptors[issue].size);
        if(!descriptors[issue].write || received[issue]>=need_beats) issue_words=2;
      end
      issue_kind=descriptors[issue].write?0:1;
      if(descriptors[issue].write) for(int w=0;w<2;w++)
        if(w<issue_words && masks[issue][(next_word[issue]+w)*32+:32]!=32'hffffffff) issue_kind=2;
      issue_priority=issue_kind==1 && descriptors[issue].qos>=8?HPR_CODE:2'b0;
    end
    request_ready=request.rp<RP && allocation>=0;
    write_ready=write_data.rp<RP && qcount[write_data.rp]<WQ && qused[write_data.rp]+int'(write_data.granules)<=WDATA_GRANULES;
    data_pop=fill>=0;pop_rp=fill>=0?int'(descriptors[fill].rp):0;
    credit_query_valid=command_slot>=0 || issue>=0;
    credit_query_type=command_slot>=0?children[command_slot].operation:2'(issue_kind);
    credit_query_pri=command_slot>=0?children[command_slot].priority_code:issue_priority;
    hif_cmd_valid=command_slot>=0;
    hif_cmd_type=0;hif_cmd_pri=0;hif_cmd_addr=0;hif_cmd_token=0;hif_cmd_wdata_ptr=0;hif_cmd_length=LENGTH_ONE;
    if(command_slot>=0) begin
      p=int'(children[command_slot].parent);
      hif_cmd_type=children[command_slot].operation;hif_cmd_pri=children[command_slot].priority_code;
      hif_cmd_addr=40'((descriptors[p].addr & ~64'd31)+64'(children[command_slot].word_index)*32);
      hif_cmd_token=children[command_slot].token;hif_cmd_wdata_ptr=children[command_slot].pointer;
      hif_cmd_length=children[command_slot].words==2?LENGTH_TWO:LENGTH_ONE;
    end
    hif_cmd_autopre=AUTO_PRECHARGE;hif_cmd_latency=COMMAND_LATENCY;
    cmd_fire=hif_cmd_valid && !hif_cmd_stall;
    hif_wdata_valid=write_count!=0;hif_wdata=0;hif_wdata_mask=0;hif_wdata_end=0;
    if(write_count!=0) begin
      p=int'(children[write_queue[write_head]].parent);
      word_offset=(int'(children[write_queue[write_head]].word_index)+write_word)*32;
      for(int b=0;b<32;b++) begin
        if(masks[p][word_offset+b]) hif_wdata[b*8+:8]=bytes_ram[p][word_offset+b];
        hif_wdata_mask[b]=masks[p][word_offset+b];
      end
      hif_wdata_end=write_word+1==int'(children[write_queue[write_head]].words);
    end
    if(!MASK_ONE_WRITES) hif_wdata_mask=~hif_wdata_mask;
    w_fire=hif_wdata_valid && !hif_wdata_stall;
    push_pointer=hif_wdata_ptr_valid && pointer_child>=0 && !children[pointer_child].requested && !hif_wdata_ptr_addr_err;
    pop_pointer=w_fire && hif_wdata_end;
    if(rsp_hold>=0) response_parent=rsp_hold;
    response='0;response_valid=response_parent>=0;
    if(response_parent>=0) begin
      p=response_parent;response.write=descriptors[p].write;response.rp=descriptors[p].rp;
      response.id=descriptors[p].id;response.user=descriptors[p].user;response.status=status[p];response.tag=6'(p);
      response.last=descriptors[p].write || response_beat[p]==int'(descriptors[p].len);
      width=1<<descriptors[p].size;offset=int'(descriptors[p].addr[4:0])+response_beat[p]*width;
      lane=offset%32;
      if(!descriptors[p].write && !rejected[p]) for(int b=0;b<32;b++) if(b<width)
        response.data[(lane+b)*8+:8]=bytes_ram[p][offset+b];
    end
    for(int r=0;r<RP;r++) for(int k=0;k<3;k++) released[r][k]=0;
    for(int n=0;n<P;n++) if(retire[n] && present[n])
      released[descriptors[n].rp][descriptors[n].write?0:1]=released[descriptors[n].rp][descriptors[n].write?0:1]+3;
    if(data_pop) released[pop_rp][2]=16'(early[pop_rp][qhead[pop_rp]].granules);
    idle=parents_used==0 && children_used==0 && command_slot<0 && write_count==0;
    for(int r=0;r<RP;r++) if(qcount[r]!=0) idle=0;
  end

  // Pointer error and the final data beat of another child can coincide.
  // Accumulate all completions before the single parent counter assignment.
  always_comb begin
    for(int n=0;n<P;n++) completion_delta[n]=0;
    if(hif_wdata_ptr_valid && pointer_child>=0 && !children[pointer_child].requested && hif_wdata_ptr_addr_err)
      completion_delta[children[pointer_child].parent]=completion_delta[children[pointer_child].parent]+int'(children[pointer_child].words);
    if(pop_pointer)
      completion_delta[children[write_queue[write_head]].parent]=completion_delta[children[write_queue[write_head]].parent]+int'(children[write_queue[write_head]].words);
    if(hif_rdata_valid && return_child>=0 && hif_rdata_end)
      completion_delta[children[return_child].parent]=completion_delta[children[return_child].parent]+int'(children[return_child].words);
  end

  always_ff @(posedge clk or negedge rst_n) begin : state
    integer p,width,base,lane,c,offset,valid_bytes;
    if(!rst_n) begin
      sequence_next<=0;serial<=1;command_slot<=-1;write_head<=0;write_tail<=0;write_count<=0;write_word<=0;rsp_hold<=-1;error_code<=0;
      stat_commands<=0;stat_reads<=0;stat_writes<=0;stat_rmw<=0;stat_cmd_stall<=0;stat_wdata_stall<=0;
      stat_pointer_requests<=0;stat_read_words<=0;stat_effective_write_bytes<=0;stat_mc_write_words<=0;stat_response_count<=0;
      for(int n=0;n<P;n++) begin
        descriptors[n]<='0;present[n]<=0;rejected[n]<=0;response_sent[n]<=0;status[n]<=0;sequence_id[n]<=0;
        received[n]<=0;next_word[n]<=0;finished[n]<=0;response_beat[n]<=0;masks[n]<=0;
      end
      for(int r=0;r<RP;r++) begin qhead[r]<=0;qtail[r]<=0;qcount[r]<=0;qused[r]<=0;end
      for(int n=0;n<CHILD_SLOTS;n++) children[n]<='0;
    end else begin
      for(int n=0;n<P;n++) if(completion_delta[n]!=0) finished[n]<=finished[n]+completion_delta[n];
      if(hif_cmd_valid && hif_cmd_stall) stat_cmd_stall<=stat_cmd_stall+1;
      if(hif_wdata_valid && hif_wdata_stall) stat_wdata_stall<=stat_wdata_stall+1;
      for(int r=0;r<RP;r++) begin
        case({write_valid && write_ready && write_data.rp==r,data_pop && pop_rp==r})
          2'b10:qcount[r]<=qcount[r]+1;
          2'b01:qcount[r]<=qcount[r]-1;
          default:;
        endcase
        qused[r]<=qused[r]+((write_valid && write_ready && write_data.rp==r)?int'(write_data.granules):0)-
          ((data_pop && pop_rp==r)?int'(early[r][qhead[r]].granules):0);
      end
      if(write_valid && write_ready) begin
        early[write_data.rp][qtail[write_data.rp]]<=write_data;qtail[write_data.rp]<=(qtail[write_data.rp]+1)%WQ;
      end
      if(request_valid && request_ready) begin
        descriptors[allocation]<=request;present[allocation]<=1;response_sent[allocation]<=0;
        sequence_id[allocation]<=sequence_next;sequence_next<=sequence_next+1;
        received[allocation]<=0;next_word[allocation]<=0;finished[allocation]<=0;response_beat[allocation]<=0;masks[allocation]<=0;
        rejected[allocation]<=request.lock || request.addr>=64'h10000000000 ||
          request.addr+64'(length_bytes(request))>64'h10000000000 ||
          int'(request.addr[4:0])+length_bytes(request)>MAX_BYTES || (request.write && !POSTED_WRITE_ACK);
        status[allocation]<=request.addr>=64'h10000000000 || request.addr+64'(length_bytes(request))>64'h10000000000 ? 2'd3:
          ((request.lock || (request.write && !POSTED_WRITE_ACK) || int'(request.addr[4:0])+length_bytes(request)>MAX_BYTES)?2'd2:2'd0);
      end
      if(data_pop) begin
        p=fill;width=1<<descriptors[p].size;base=int'(descriptors[p].addr[4:0])+received[p]*width;lane=base%32;
        for(int b=0;b<32;b++) begin
          if(b<width && base+b<MAX_BYTES) begin
            bytes_ram[p][base+b]<=early[pop_rp][qhead[pop_rp]].data[(lane+b)*8+:8];
            masks[p][base+b]<=early[pop_rp][qhead[pop_rp]].mask[lane+b];
          end
          if(early[pop_rp][qhead[pop_rp]].mask[b] && (b<lane || b>=lane+width)) error_code[0]<=1;
        end
        received[p]<=received[p]+1;qhead[pop_rp]<=(qhead[pop_rp]+1)%WQ;
      end
      if(command_slot<0 && issue>=0 && free_child>=0 && !pointer_collision && credit_allowed && error_code==0) begin
        children[free_child]<='{valid:1'b1,accepted:1'b0,write:descriptors[issue].write,requested:1'b0,
          token:serial,pointer:serial[18:0],parent:6'(issue),word_index:8'(next_word[issue]),words:2'(issue_words),received:2'b0,
          operation:2'(issue_kind),priority_code:issue_priority};
        serial<=serial+1;command_slot<=free_child;
      end
      if(cmd_fire) begin
        c=command_slot;p=int'(children[c].parent);children[c].accepted<=1;
        next_word[p]<=next_word[p]+int'(children[c].words);command_slot<=-1;stat_commands<=stat_commands+1;
        if(children[c].operation==1) stat_reads<=stat_reads+1;
        else if(children[c].operation==2) stat_rmw<=stat_rmw+1;
        else stat_writes<=stat_writes+1;
        if(!credit_allowed) error_code[1]<=1;
      end
      case({push_pointer,pop_pointer})
        2'b10:write_count<=write_count+1;
        2'b01:write_count<=write_count-1;
        default:;
      endcase
      if(hif_wdata_ptr_valid) begin
        stat_pointer_requests<=stat_pointer_requests+1;
        if(pointer_child<0 || children[pointer_child].requested) error_code[2]<=1;
        else begin
          children[pointer_child].requested<=1;
          if(hif_wdata_ptr_addr_err) begin
            p=int'(children[pointer_child].parent);status[p]<=3;
            children[pointer_child].valid<=0;
          end else if(write_count==CHILD_SLOTS && !pop_pointer) error_code[3]<=1;
          else begin write_queue[write_tail]<=pointer_child;write_tail<=(write_tail+1)%CHILD_SLOTS;end
        end
      end
      if(w_fire) begin
        c=write_queue[write_head];p=int'(children[c].parent);valid_bytes=0;
        offset=(int'(children[c].word_index)+write_word)*32;
        for(int b=0;b<32;b++) if(masks[p][offset+b]) valid_bytes=valid_bytes+1;
        stat_effective_write_bytes<=stat_effective_write_bytes+64'(valid_bytes);stat_mc_write_words<=stat_mc_write_words+1;
        if(hif_wdata_end) begin
          children[c].valid<=0;
          write_head<=(write_head+1)%CHILD_SLOTS;write_word<=0;
        end else write_word<=write_word+1;
      end
      if(hif_rdata_valid) begin
        stat_read_words<=stat_read_words+1;
        if(return_child<0) error_code[4]<=1;
        else begin
          c=return_child;p=int'(children[c].parent);offset=(int'(children[c].word_index)+int'(children[c].received))*32;
          if(hif_rdata_end!=(children[c].received+1==children[c].words)) error_code[5]<=1;
          for(int b=0;b<32;b++) if(offset+b<MAX_BYTES) bytes_ram[p][offset+b]<=hif_rdata[b*8+:8];
          children[c].received<=children[c].received+1;
          if(hif_rdata_addr_err) status[p]<=3;
          else if(hif_rdata_uncorr_ecc_err || hif_rdata_crc_err) if(status[p]!=3) status[p]<=2;
          if(hif_rdata_end) begin
            children[c].valid<=0;
          end
        end
      end
      if(response_valid && !response_ready && rsp_hold<0) rsp_hold<=response_parent;
      if(response_valid && response_ready) begin
        rsp_hold<=-1;
        if(response.last) begin response_sent[response_parent]<=1;stat_response_count<=stat_response_count+1;end
        else response_beat[response_parent]<=response_beat[response_parent]+1;
      end
      for(int n=0;n<P;n++) if(retire[n]) begin
        if(!present[n] || !response_sent[n]) error_code[6]<=1;
        present[n]<=0;
      end
      if((retire>>P)!=0) error_code[7]<=1;
    end
  end
  initial begin
    if(RP<1 || RP>4 || REQUEST_SLOTS<1 || P>64 || CHILD_SLOTS<1 || CHILD_SLOTS>256 ||
       MAX_BYTES<32 || MAX_BYTES>4096 || MAX_BYTES%32!=0 || WDATA_GRANULES<8 || WDATA_GRANULES>4096 || LENGTH_ONE==LENGTH_TWO)
      $error("unsupported MC bridge geometry/length contract");
  end
endmodule
