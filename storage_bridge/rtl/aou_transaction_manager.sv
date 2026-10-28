// Bounded hardware ownership of descriptors, write storage and transaction tags.
// HIF emits one command followed by all W beats for a write. Read commands
// have no data phase. Tags remain allocated until the final response fragment
// has entered the outgoing FDI FIFO (retire_mask), not merely HIF acceptance.
module aou_transaction_manager #(
  parameter int AXI_DATA_WIDTH=256,
  parameter int RESOURCE_PLANES=1,
  parameter int REQUEST_SLOTS=4,
  parameter int MAX_OUTSTANDING=8,
  parameter int WDATA_GRANULES=64,
  parameter int MAX_BURST_BYTES=4096
)(
  input logic clk, rst_n,
  input logic cmd_valid, output logic cmd_ready,
  input logic cmd_write,
  input logic [1:0] cmd_rp,
  input logic [9:0] cmd_id,
  input logic [15:0] cmd_user,
  input logic [63:0] cmd_addr,
  input logic [7:0] cmd_len,
  input logic [2:0] cmd_size,cmd_prot,
  input logic cmd_lock,
  input logic [3:0] cmd_cache,cmd_qos,
  input logic [31:0] cmd_origin_cycle,
  input logic w_valid, output logic w_ready,
  input logic [1:0] w_rp,
  input logic [15:0] w_user,
  input logic [AXI_DATA_WIDTH-1:0] w_data,
  input logic [AXI_DATA_WIDTH/8-1:0] w_strb,
  input logic [7:0] w_granules,
  output logic hif_cmd_valid, input logic hif_cmd_ready,
  output logic hif_cmd_write,
  output logic [1:0] hif_cmd_rp,
  output logic [9:0] hif_cmd_id,
  output logic [15:0] hif_cmd_user,
  output logic [63:0] hif_cmd_addr,
  output logic [7:0] hif_cmd_len,
  output logic [2:0] hif_cmd_size,hif_cmd_prot,
  output logic hif_cmd_lock,
  output logic [3:0] hif_cmd_cache,hif_cmd_qos,
  output logic [31:0] hif_cmd_latency_cycles,
  output logic hif_w_valid, input logic hif_w_ready,
  output logic [1:0] hif_w_rp,
  output logic [15:0] hif_w_user,
  output logic [AXI_DATA_WIDTH-1:0] hif_w_data,
  output logic [AXI_DATA_WIDTH/8-1:0] hif_w_strb,
  output logic hif_w_last,
  input logic backend_rsp_valid, output logic backend_rsp_ready,
  input logic backend_rsp_write,
  input logic [1:0] backend_rsp_rp,
  input logic [9:0] backend_rsp_id,
  input logic backend_rsp_last,
  output logic checked_rsp_valid, input logic checked_rsp_ready,
  output logic [5:0] checked_rsp_tag,
  input logic [63:0] retire_mask,
  output logic release_valid,
  output logic [1:0] release_rp,
  output logic [2:0] release_kind,
  output logic [7:0] release_granules,
  output logic data_release_valid,
  output logic [1:0] data_release_rp,
  output logic [7:0] data_release_granules,
  output logic business_idle,
  output logic [31:0] descriptor_depth,outstanding_depth,wdata_depth,
  output logic [63:0] stat_cmd_latency_count,stat_cmd_latency_sum,stat_cmd_latency_max,
  output logic [63:0] stat_rsp_latency_count,stat_rsp_latency_sum,stat_rsp_latency_max,
  output logic protocol_error
);
  import storage_bridge_pkg::*;
  localparam int AXI_BYTES=AXI_DATA_WIDTH/8;
  localparam int DESCRIPTORS=2*RESOURCE_PLANES*REQUEST_SLOTS;
  localparam int WDATA_SLOTS=WDATA_GRANULES/data_message_granules(MSG_WRITE_FULL,dlength(AXI_DATA_WIDTH));
  // AW and W are independent upstream channels. Reserve W storage even when
  // no AW descriptor exists, so W cannot block a later AW/credit in FDI RX.
  logic [AXI_DATA_WIDTH-1:0] pending_data[RESOURCE_PLANES][WDATA_SLOTS];
  logic [AXI_BYTES-1:0] pending_strb[RESOURCE_PLANES][WDATA_SLOTS];
  logic [15:0] pending_user[RESOURCE_PLANES][WDATA_SLOTS];
  logic [7:0] pending_granules[RESOURCE_PLANES][WDATA_SLOTS];
  integer w_read[RESOURCE_PLANES],w_write[RESOURCE_PLANES],w_count[RESOURCE_PLANES],w_used[RESOURCE_PLANES];
  logic data_pop;
  logic [1:0] fill_rp;
  logic [AXI_DATA_WIDTH-1:0] fill_data;
  logic [AXI_BYTES-1:0] fill_strb;
  logic [15:0] fill_user;
  typedef struct packed {
    logic write;
    logic [1:0] rp;
    logic [9:0] id;
    logic [15:0] user;
    logic [63:0] addr;
    logic [7:0] len;
    logic [2:0] size,prot;
    logic lock;
    logic [3:0] cache,qos;
    logic [31:0] sequence_number,origin_cycle;
  } descriptor_t;
  descriptor_t descriptors[DESCRIPTORS];
  logic descriptor_valid[DESCRIPTORS];
  logic [8:0] received_beats[DESCRIPTORS];
  // Store only transfer bytes, not all inactive AXI lanes. No RAM reset is
  // required: descriptors and beat counts prevent reads of uninitialized RAM.
  logic [7:0] write_bytes[RESOURCE_PLANES*REQUEST_SLOTS][MAX_BURST_BYTES];
  logic write_masks[RESOURCE_PLANES*REQUEST_SLOTS][MAX_BURST_BYTES];
  logic [15:0] write_users[RESOURCE_PLANES*REQUEST_SLOTS][256];
  logic ticket_valid[MAX_OUTSTANDING],ticket_write[MAX_OUTSTANDING];
  logic ticket_backend_done[MAX_OUTSTANDING],ticket_rsp_seen[MAX_OUTSTANDING];
  logic [1:0] ticket_rp[MAX_OUTSTANDING];
  logic [9:0] ticket_id[MAX_OUTSTANDING];
  logic [8:0] ticket_beats[MAX_OUTSTANDING],ticket_received[MAX_OUTSTANDING];
  logic [31:0] ticket_sequence[MAX_OUTSTANDING],ticket_rsp_cycle[MAX_OUTSTANDING];
  logic [31:0] cycle_q,sequence_q;
  integer next_group_q,dispatch_slot_q,selected_slot_q;
  logic dispatch_write_q;
  logic [8:0] send_beat_q;
  integer allocate_slot,fill_slot,issue_slot,free_ticket,response_ticket;
  logic response_shape_ok;

  always_comb begin : select_and_drive
    int group_index,head,byte_count,lane,offset;
    allocate_slot=-1;fill_slot=-1;issue_slot=-1;free_ticket=-1;response_ticket=-1;
    descriptor_depth=0;outstanding_depth=0;wdata_depth=0;
    for(int r=0;r<RESOURCE_PLANES;r++) wdata_depth=wdata_depth+32'(w_count[r]);
    for(int s=0;s<DESCRIPTORS;s++) begin
      if(descriptor_valid[s]) descriptor_depth=descriptor_depth+1;
      if(!descriptor_valid[s] && allocate_slot<0 &&
          s/REQUEST_SLOTS == (int'(cmd_write)*RESOURCE_PLANES+int'(cmd_rp)))
        allocate_slot=s;
      if(descriptor_valid[s] && descriptors[s].write && w_count[descriptors[s].rp]!=0 &&
          received_beats[s] < int'(descriptors[s].len)+1 &&
          (fill_slot<0 || descriptors[s].sequence_number<descriptors[fill_slot].sequence_number))
        fill_slot=s;
    end
    for(int n=0;n<2*RESOURCE_PLANES;n++) begin
      group_index=(next_group_q+n)%(2*RESOURCE_PLANES);head=-1;
      for(int s=0;s<DESCRIPTORS;s++)
        if(descriptor_valid[s] && s/REQUEST_SLOTS==group_index &&
            (head<0 || descriptors[s].sequence_number<descriptors[head].sequence_number)) head=s;
      if(issue_slot<0 && head>=0 &&
          (!descriptors[head].write || received_beats[head]==int'(descriptors[head].len)+1))
        issue_slot=head;
    end
    if(selected_slot_q>=0) issue_slot=selected_slot_q;
    for(int t=0;t<MAX_OUTSTANDING;t++) begin
      if(ticket_valid[t]) outstanding_depth=outstanding_depth+1;
      if(!ticket_valid[t] && free_ticket<0) free_ticket=t;
      if(ticket_valid[t] && !ticket_backend_done[t] && ticket_write[t]==backend_rsp_write &&
          ticket_rp[t]==backend_rsp_rp && ticket_id[t]==backend_rsp_id &&
          (response_ticket<0 || ticket_sequence[t]<ticket_sequence[response_ticket])) response_ticket=t;
    end
    cmd_ready=cmd_rp<RESOURCE_PLANES && allocate_slot>=0;
    w_ready=w_rp<RESOURCE_PLANES && w_count[w_rp]<WDATA_SLOTS &&
      w_used[w_rp]+int'(w_granules)<=WDATA_GRANULES;
    data_pop=fill_slot>=0;
    fill_rp=0;
    if(fill_slot>=0) fill_rp=descriptors[fill_slot].rp;
    fill_data=pending_data[fill_rp][w_read[fill_rp]];
    fill_strb=pending_strb[fill_rp][w_read[fill_rp]];
    fill_user=pending_user[fill_rp][w_read[fill_rp]];
    hif_cmd_valid=!dispatch_write_q && issue_slot>=0 && free_ticket>=0;
    hif_cmd_write=0;hif_cmd_rp=0;hif_cmd_id=0;hif_cmd_user=0;hif_cmd_addr=0;
    hif_cmd_len=0;hif_cmd_size=0;hif_cmd_prot=0;hif_cmd_lock=0;hif_cmd_cache=0;hif_cmd_qos=0;
    hif_cmd_latency_cycles=0;
    if(issue_slot>=0) begin
      hif_cmd_write=descriptors[issue_slot].write;hif_cmd_rp=descriptors[issue_slot].rp;
      hif_cmd_id=descriptors[issue_slot].id;hif_cmd_user=descriptors[issue_slot].user;
      hif_cmd_addr=descriptors[issue_slot].addr;hif_cmd_len=descriptors[issue_slot].len;
      hif_cmd_size=descriptors[issue_slot].size;hif_cmd_prot=descriptors[issue_slot].prot;
      hif_cmd_lock=descriptors[issue_slot].lock;hif_cmd_cache=descriptors[issue_slot].cache;
      hif_cmd_qos=descriptors[issue_slot].qos;
      hif_cmd_latency_cycles=cycle_q-descriptors[issue_slot].origin_cycle;
    end
    hif_w_valid=dispatch_write_q;hif_w_rp=0;hif_w_user=0;
    hif_w_data='0;hif_w_strb='0;hif_w_last=0;
    byte_count=0;lane=0;offset=0;
    if(dispatch_write_q) begin
      hif_w_rp=descriptors[dispatch_slot_q].rp;
      hif_w_user=write_users[dispatch_slot_q-RESOURCE_PLANES*REQUEST_SLOTS][send_beat_q];
      hif_w_last=send_beat_q=={1'b0,descriptors[dispatch_slot_q].len};
      byte_count=1<<descriptors[dispatch_slot_q].size;
      offset=int'(send_beat_q)*byte_count;
      lane=(descriptors[dispatch_slot_q].addr+offset)%AXI_BYTES;
      for(int b=0;b<AXI_BYTES;b++) if(b<byte_count) begin
        hif_w_data[(lane+b)*8 +:8]=write_bytes[dispatch_slot_q-RESOURCE_PLANES*REQUEST_SLOTS][offset+b];
        hif_w_strb[lane+b]=write_masks[dispatch_slot_q-RESOURCE_PLANES*REQUEST_SLOTS][offset+b];
      end
    end
    response_shape_ok=0;
    if(response_ticket>=0)
      response_shape_ok=!ticket_backend_done[response_ticket] &&
        (backend_rsp_write || backend_rsp_last ==
          (ticket_received[response_ticket]+1==ticket_beats[response_ticket]));
    checked_rsp_valid=backend_rsp_valid && response_ticket>=0 && response_shape_ok;
    checked_rsp_tag=6'(response_ticket);

    business_idle=descriptor_depth==0 && outstanding_depth==0 && wdata_depth==0 && !dispatch_write_q;
  end

  assign backend_rsp_ready=checked_rsp_ready && response_ticket>=0 && response_shape_ok;

  always_ff @(posedge clk or negedge rst_n) begin : update_state
    int offset,lane,byte_count;
    logic [31:0] latency;
    if(!rst_n) begin
      cycle_q<=0;sequence_q<=0;next_group_q<=0;dispatch_slot_q<=0;selected_slot_q<=-1;
      dispatch_write_q<=0;send_beat_q<=0;release_valid<=0;release_rp<=0;
      release_kind<=0;release_granules<=0;protocol_error<=0;
      data_release_valid<=0;data_release_rp<=0;data_release_granules<=0;
      for(int r=0;r<RESOURCE_PLANES;r++) begin
        w_read[r]<=0;w_write[r]<=0;w_count[r]<=0;w_used[r]<=0;
      end
      stat_cmd_latency_count<=0;stat_cmd_latency_sum<=0;stat_cmd_latency_max<=0;
      stat_rsp_latency_count<=0;stat_rsp_latency_sum<=0;stat_rsp_latency_max<=0;
      for(int s=0;s<DESCRIPTORS;s++) begin
        descriptor_valid[s]<=0;received_beats[s]<=0;descriptors[s]<='0;
      end
      for(int t=0;t<MAX_OUTSTANDING;t++) begin
        ticket_valid[t]<=0;ticket_backend_done[t]<=0;ticket_rsp_seen[t]<=0;
        ticket_write[t]<=0;ticket_rp[t]<=0;ticket_id[t]<=0;ticket_beats[t]<=0;
        ticket_received[t]<=0;ticket_sequence[t]<=0;ticket_rsp_cycle[t]<=0;
      end
    end else begin
      cycle_q<=cycle_q+1;release_valid<=0;data_release_valid<=0;
      for(int r=0;r<RESOURCE_PLANES;r++) begin
        case({w_valid && w_ready && w_rp==r,data_pop && fill_rp==r})
          2'b10:w_count[r]<=w_count[r]+1;
          2'b01:w_count[r]<=w_count[r]-1;
          default:;
        endcase
        begin
          int next_used;
          next_used=w_used[r];
          if(w_valid && w_ready && w_rp==r) next_used=next_used+int'(w_granules);
          if(data_pop && fill_rp==r) next_used=next_used-int'(pending_granules[r][w_read[r]]);
          w_used[r]<=next_used;
          if(next_used<0 || next_used>WDATA_GRANULES) protocol_error<=1;
        end
      end
      if(w_valid && w_ready) begin
        pending_data[w_rp][w_write[w_rp]]<=w_data;
        pending_strb[w_rp][w_write[w_rp]]<=w_strb;
        pending_user[w_rp][w_write[w_rp]]<=w_user;
        pending_granules[w_rp][w_write[w_rp]]<=w_granules;
        w_write[w_rp]<=(w_write[w_rp]+1)%WDATA_SLOTS;
        if(w_granules!=data_message_granules(MSG_WRITE_FULL,dlength(AXI_DATA_WIDTH)) &&
            w_granules!=data_message_granules(MSG_WRITE_DATA,dlength(AXI_DATA_WIDTH))) protocol_error<=1;
      end
      if(cmd_valid && cmd_ready) begin
        descriptors[allocate_slot]<='{cmd_write,cmd_rp,cmd_id,cmd_user,cmd_addr,cmd_len,
          cmd_size,cmd_prot,cmd_lock,cmd_cache,cmd_qos,sequence_q,cmd_origin_cycle};
        descriptor_valid[allocate_slot]<=1;received_beats[allocate_slot]<=0;
        sequence_q<=sequence_q+1;
      end
      if(data_pop) begin
        byte_count=1<<descriptors[fill_slot].size;
        offset=int'(received_beats[fill_slot])*byte_count;
        lane=(descriptors[fill_slot].addr+offset)%AXI_BYTES;
        for(int b=0;b<AXI_BYTES;b++) begin
          if(b<byte_count && offset+b<MAX_BURST_BYTES) begin
            write_bytes[fill_slot-RESOURCE_PLANES*REQUEST_SLOTS][offset+b]<=fill_data[(lane+b)*8 +:8];
            write_masks[fill_slot-RESOURCE_PLANES*REQUEST_SLOTS][offset+b]<=fill_strb[lane+b];
          end
          if(fill_strb[b] && (b<lane || b>=lane+byte_count)) protocol_error<=1;
        end
        write_users[fill_slot-RESOURCE_PLANES*REQUEST_SLOTS][received_beats[fill_slot]]<=fill_user;
        received_beats[fill_slot]<=received_beats[fill_slot]+1;
        data_release_valid<=1;data_release_rp<=descriptors[fill_slot].rp;
        data_release_granules<=pending_granules[descriptors[fill_slot].rp][w_read[descriptors[fill_slot].rp]];
        w_read[descriptors[fill_slot].rp]<=(w_read[descriptors[fill_slot].rp]+1)%WDATA_SLOTS;
      end
      if(hif_cmd_valid && !hif_cmd_ready && selected_slot_q<0) selected_slot_q<=issue_slot;
      if(hif_cmd_valid && hif_cmd_ready) begin
        selected_slot_q<=-1;
        ticket_valid[free_ticket]<=1;ticket_backend_done[free_ticket]<=0;
        ticket_rsp_seen[free_ticket]<=0;ticket_received[free_ticket]<=0;
        ticket_write[free_ticket]<=descriptors[issue_slot].write;
        ticket_rp[free_ticket]<=descriptors[issue_slot].rp;ticket_id[free_ticket]<=descriptors[issue_slot].id;
        ticket_beats[free_ticket]<={1'b0,descriptors[issue_slot].len}+1;
        ticket_sequence[free_ticket]<=descriptors[issue_slot].sequence_number;
        stat_cmd_latency_count<=stat_cmd_latency_count+1;
        stat_cmd_latency_sum<=stat_cmd_latency_sum+hif_cmd_latency_cycles;
        if(hif_cmd_latency_cycles>stat_cmd_latency_max) stat_cmd_latency_max<=hif_cmd_latency_cycles;
        next_group_q<=(issue_slot/REQUEST_SLOTS+1)%(2*RESOURCE_PLANES);
        if(descriptors[issue_slot].write) begin
          dispatch_write_q<=1;dispatch_slot_q<=issue_slot;send_beat_q<=0;
        end else begin
          descriptor_valid[issue_slot]<=0;
          release_valid<=1;release_rp<=descriptors[issue_slot].rp;
          release_kind<=CREDIT_RREQ;release_granules<=3;
        end
      end
      if(hif_w_valid && hif_w_ready) begin
        if(hif_w_last) begin
          dispatch_write_q<=0;descriptor_valid[dispatch_slot_q]<=0;
          release_valid<=1;release_rp<=descriptors[dispatch_slot_q].rp;
          release_kind<=CREDIT_WREQ;release_granules<=3;
        end else send_beat_q<=send_beat_q+1;
      end
      if(backend_rsp_valid) begin
        if(response_ticket<0 || !response_shape_ok) protocol_error<=1;
        else if(!ticket_rsp_seen[response_ticket]) begin
          ticket_rsp_seen[response_ticket]<=1;ticket_rsp_cycle[response_ticket]<=cycle_q;
        end
      end
      if(checked_rsp_valid && checked_rsp_ready) begin
        ticket_received[response_ticket]<=ticket_received[response_ticket]+1;
        if(backend_rsp_write || backend_rsp_last) ticket_backend_done[response_ticket]<=1;
      end
      // At most one latency accumulator update per cycle: TX can retire many
      // one-granule responses in one frame, so accumulate via temporaries.
      begin
        logic [63:0] count_next,sum_next,max_next;
        count_next=stat_rsp_latency_count;sum_next=stat_rsp_latency_sum;max_next=stat_rsp_latency_max;
        for(int t=0;t<MAX_OUTSTANDING;t++) if(retire_mask[t]) begin
          if(!ticket_valid[t] || !ticket_backend_done[t] || !ticket_rsp_seen[t]) protocol_error<=1;
          latency=cycle_q-ticket_rsp_cycle[t];
          count_next=count_next+1;sum_next=sum_next+latency;
          if(latency>max_next) max_next=latency;
          ticket_valid[t]<=0;
        end
        stat_rsp_latency_count<=count_next;stat_rsp_latency_sum<=sum_next;stat_rsp_latency_max<=max_next;
      end
      if((retire_mask >> MAX_OUTSTANDING)!=0) protocol_error<=1;
    end
  end
  initial begin
    if(REQUEST_SLOTS<1 || REQUEST_SLOTS>16 || MAX_OUTSTANDING<1 || MAX_OUTSTANDING>64 || WDATA_GRANULES<30 || WDATA_GRANULES>4096)
      $error("invalid bridge descriptor/ticket capacity");
  end
endmodule
