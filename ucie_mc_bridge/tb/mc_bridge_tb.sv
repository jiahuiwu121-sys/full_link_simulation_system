`timescale 1ns/1fs
module mc_bridge_tb #(parameter int PLANES=1,ACK=1);
  import umcb_pkg::*;
  localparam int TEST_RP=PLANES-1;
  logic clk=0,rst_n=0;
  always #5 clk=~clk;
  logic fdi_rx_valid=0,fdi_rx_ready,fdi_tx_valid,fdi_tx_ready;
  logic [1999:0] fdi_rx_data=0,fdi_tx_data;
  logic hif_cmd_valid,hif_cmd_stall,hif_cmd_length,hif_cmd_autopre;
  logic [1:0] hif_cmd_type,hif_cmd_pri;
  logic [39:0] hif_cmd_addr;
  logic [52:0] hif_cmd_token;
  logic [18:0] hif_cmd_wdata_ptr;
  logic [10:0] hif_cmd_latency;
  logic hif_lpr_credit,hif_hpr_credit,hif_wr_credit;
  logic [1:0] hif_wrecc_credit=0;
  logic hif_rdata_valid,hif_rdata_end;
  logic [52:0] hif_rdata_token;
  logic [255:0] hif_rdata;
  logic hif_rdata_uncorr_ecc_err,hif_rdata_addr_err,hif_rdata_crc_err;
  logic hif_wdata_valid,hif_wdata_stall,hif_wdata_end;
  logic [255:0] hif_wdata;
  logic [31:0] hif_wdata_mask;
  logic hif_wdata_ptr_valid,hif_wdata_ptr_addr_err;
  logic [18:0] hif_wdata_ptr;
  logic hif_go2critical_lpr,hif_go2critical_hpr,hif_go2critical_wr;
  logic business_idle,link_idle,protocol_error;
  logic [31:0] error_code,parents_used,children_used;
  logic [15:0] lpr_available,hpr_available,wr_available;
  logic [63:0] stat_cycles,stat_rx_frames,stat_rx_messages,stat_tx_frames;
  logic [63:0] stat_commands,stat_reads,stat_writes,stat_rmw,stat_cmd_stall,stat_wdata_stall;
  logic [63:0] stat_pointer_requests,stat_read_words,stat_effective_write_bytes,stat_mc_write_words,stat_response_count;
  logic [63:0] stat_packed_granules,stat_spanning_messages,stat_aou_credit_wait;
  logic inject_crc=0,inject_addr=0,inject_unknown=0,allow_errors=0;
  logic inject_ecc=0,inject_pointer_error=0,inject_read_token=0;
  integer out_of_order_returns;
  ucie_mc_bridge_top #(.RESOURCE_PLANES(PLANES),.POSTED_WRITE_ACK(ACK!=0),.TX_FLUSH_CYCLES(8)) dut(.*);
  mc_hif_model mc(.*);

  typedef struct packed {
    logic active,write,done;
    integer addr,beats,size,user,expected_status,received;
  } expected_t;
  expected_t expected[1024];
  integer transactions_left[1024],second_address[1024];
  logic [7:0] reference_memory[65536];
  integer peer_credit[4][3];
  integer case_id,cycle=0,completed=0,sent_messages=0,logfile,summaryfile,rxlog,txlog;
  integer carry_have=0,carry_need=0;
  logic [319:0] carry=0;
  string outdir,tracepath;
  assign fdi_tx_ready=cycle%17>=5; // stalls must not lose credit snapshots/retire masks
  function automatic logic [319:0] put_bits(input logic [319:0] m,input int start,input int width,input logic [63:0] value);
    logic [319:0] result;
    result=m;
    for(int b=0;b<width;b++) result[((start+b)/8)*8+7-(start+b)%8]=value[width-1-b];
    return result;
  endfunction
  function automatic logic [319:0] address_message(input bit wr,input int id,input logic [63:0] addr,input int beats,size,qos,input bit locked);
    logic [319:0] m;
    m=0;m[0+:8]={wr?4'h1:4'h2,2'(TEST_RP),1'b0,locked};
    m=put_bits(m,8,16,64'(id+256));m=put_bits(m,24,10,64'(id));m=put_bits(m,34,3,64'(size));
    m=put_bits(m,40,8,64'(beats-1));m=put_bits(m,52,4,64'(qos));m=put_bits(m,56,64,64'(addr));
    return m;
  endfunction
  function automatic logic [7:0] source_byte(input int id,beat,b);
    return 8'(id*17+beat*3+b);
  endfunction
  task automatic send_frame(input logic [1999:0] f);
    @(negedge clk);fdi_rx_valid=1;fdi_rx_data=f;
    do @(posedge clk);while(!fdi_rx_ready);
    @(negedge clk);fdi_rx_valid=0;
  endtask
  task automatic send_message(input logic [319:0] m,input int granules,input bit split_frame=0);
    logic [1999:0] f;
    logic [1919:0] payload;
    logic [47:0] bitmap;
    logic [15:0] peer_grant;
    integer kind,start,first_part;
    kind=m[7:4]==M_AW?0:(m[7:4]==M_AR?1:2);
    while(peer_credit[TEST_RP][kind]<granules) @(negedge clk);
    peer_credit[TEST_RP][kind]=peer_credit[TEST_RP][kind]-granules;
    // Independent peer grants: RDATA=128 granules, WRESP=8 granules.
    peer_grant=16'((TEST_RP<<14)|(3<<12)|(7<<9));
    start=split_frame?47:0;first_part=granules;if(first_part>48-start) first_part=48-start;
    payload=0;bitmap=0;bitmap[start]=1;
    for(int g=0;g<8;g++) if(g<first_part) payload[(start+g)*40+:40]=m[g*40+:40];
    f=make_frame(payload,bitmap,peer_grant);send_frame(f);
    if(first_part<granules) begin
      payload=0;
      for(int g=0;g<8;g++) if(g<granules-first_part) payload[g*40+:40]=m[(first_part+g)*40+:40];
      send_frame(make_frame(payload,0,peer_grant));
    end
    sent_messages=sent_messages+1;
  endtask
  task automatic prepare_expected(input bit wr,input int id,addr,beats,size,status_code);
    if(expected[id].active && !expected[id].done) $fatal(1,"scoreboard ID still active");
    expected[id]='{active:1'b1,write:wr,done:1'b0,addr:addr,beats:beats,size:size,user:id+256,expected_status:status_code,received:0};
    transactions_left[id]=1;
  endtask
  task automatic issue_read(input int id,addr,beats,size,input int status_code=0,input int qos=0);
    prepare_expected(0,id,addr,beats,size,status_code);
    send_message(address_message(0,id,addr,beats,size,qos,0),3,case_id==5);
  endtask
  task automatic send_write_beat(input int id,addr,beat,size,input bit masked,input bit split_frame=0);
    logic [319:0] m;
    logic [255:0] data;
    logic [31:0] mask;
    integer lane,width;
    m=0;data=0;mask=0;width=1<<size;lane=(addr+beat*width)%32;
    for(int b=0;b<32;b++) if(b>=lane && b<lane+width) begin
      data[b*8+:8]=source_byte(id,beat,b);
      mask[b]=!masked || (beat+b)%3!=1;
      if(mask[b] && ACK) reference_memory[(addr+beat*width+b-lane)%65536]=source_byte(id,beat,b);
    end
    m[0+:8]={mask==32'hffffffff ? M_FULL:M_W,2'(TEST_RP),2'b0};
    m[8+:8]=8'(beat>>8);m[16+:8]=8'(beat);
    for(int b=0;b<32;b++) m[(34-b)*8+:8]=data[b*8+:8];
    for(int b=0;b<4;b++) m[(38-b)*8+:8]=mask[b*8+:8];
    send_message(m,mask==32'hffffffff ? 7:8,split_frame);
  endtask
  task automatic issue_write(input int id,addr,beats,size,input bit masked=0,input bit data_first=0,input int status_override=-1);
    prepare_expected(1,id,addr,beats,size,status_override>=0?status_override:(ACK?0:2));
    if(data_first) begin
      send_write_beat(id,addr,0,size,masked);
      send_write_beat(id,addr,1,size,masked);
    end
    send_message(address_message(1,id,addr,beats,size,0,0),3,case_id==5);
    for(int b=data_first?2:0;b<beats;b++) send_write_beat(id,addr,b,size,masked,case_id==5 && b%7==0);
  endtask
  task automatic await_done(input int id);
    while(!expected[id].done) @(negedge clk);
  endtask
  task automatic check_message(input logic [319:0] m);
    integer id,kind,status_code,width,lane,address;
    logic last;
    kind=int'(m[7:4]);
    if(kind!=4 && kind!=5) $fatal(1,"unexpected outbound message %0d",kind);
    id={m[24+:8],m[38+:2]};status_code=int'(m[36+:2]);last=m[35];
    if(!expected[id].active || expected[id].done || (kind==5)!=expected[id].write || m[3:2]!=TEST_RP)
      $fatal(1,"unexpected/duplicate response id=%0d type=%0d",id,kind);
    if({m[8+:8],m[16+:8]}!=expected[id].user || status_code!=expected[id].expected_status)
      $fatal(1,"response attributes id=%0d status=%0d expected=%0d",id,status_code,expected[id].expected_status);
    if(kind==4) begin
      width=1<<expected[id].size;address=expected[id].addr+expected[id].received*width;lane=address%32;
      if(last!=(expected[id].received+1==expected[id].beats)) $fatal(1,"upstream RLAST mismatch");
      if(status_code==0) for(int b=0;b<32;b++) begin
        if(b>=lane && b<lane+width) begin
          if(m[(36-b)*8+:8]!==reference_memory[(address+b-lane)%65536])
            $fatal(1,"data mismatch id=%0d beat=%0d byte=%0d got=%h expected=%h",id,expected[id].received,b,m[(36-b)*8+:8],reference_memory[(address+b-lane)%65536]);
        end else if(m[(36-b)*8+:8]!=0) $fatal(1,"nonzero inactive read lane");
      end
      expected[id].received=expected[id].received+1;
    end
    if(kind==5 || last) begin
      completed=completed+1;transactions_left[id]=transactions_left[id]-1;
      if(transactions_left[id]==0) expected[id].done=1;
      else begin expected[id].addr=second_address[id];expected[id].received=0;end
    end
  endtask
  // An independent stream parser/scoreboard, not a second instance of DUT RX.
  task automatic inspect_frame(input logic [1999:0] f);
    logic [47:0] bitmap;
    logic [7:0] byte0;
    logic [319:0] m;
    integer g,n,r;
    bitmap=frame_starts(f);r=int'(f[46+:2]);
    if(r<4) begin
      peer_credit[r][0]=peer_credit[r][0]+credit_value(f[32+:3]);
      peer_credit[r][1]=peer_credit[r][1]+credit_value(f[35+:3]);
      peer_credit[r][2]=peer_credit[r][2]+credit_value(f[38+:3]);
    end
    g=0;
    while(g<48) begin
      if(carry_have!=0) begin
        if(bitmap[g]) $fatal(1,"new message inside continuation");
        carry[carry_have*40+:40]=f[(10+g*5)*8+:40];carry_have=carry_have+1;g=g+1;
        if(carry_have==carry_need) begin check_message(carry);carry_have=0;carry_need=0;end
      end else if(bitmap[g]) begin
        byte0=f[(10+g*5)*8+:8];n=byte0[7:4]==4?8:(byte0[7:4]==5?1:0);
        if(n==0) $fatal(1,"unknown output type");
        m=0;
        if(g+n<=48) begin
          for(int k=0;k<n;k++) begin
            if(k>0 && bitmap[g+k]) $fatal(1,"overlapping output starts");
            m[k*40+:40]=f[(10+(g+k)*5)*8+:40];
          end
          check_message(m);g=g+n;
        end else begin
          carry=0;carry_need=n;carry_have=48-g;
          for(int k=0;k<carry_have;k++) carry[k*40+:40]=f[(10+(g+k)*5)*8+:40];
          g=48;
        end
      end else g=g+1;
    end
  endtask
  always @(posedge clk) if(rst_n) begin
    cycle<=cycle+1;
    if(protocol_error && !allow_errors) $fatal(1,"bridge protocol error %h",error_code);
    if(fdi_tx_valid && fdi_tx_ready) inspect_frame(fdi_tx_data);
    if(fdi_rx_valid && fdi_rx_ready) $fwrite(rxlog,"%0t,%0500h\n",$time,fdi_rx_data);
    if(fdi_tx_valid && fdi_tx_ready) $fwrite(txlog,"%0t,%0500h\n",$time,fdi_tx_data);
    if(logfile) begin
      if(fdi_rx_valid && fdi_rx_ready) $fwrite(logfile,"%0t,fdi_rx,0,0,0\n",$time);
      if(fdi_tx_valid && fdi_tx_ready) $fwrite(logfile,"%0t,fdi_tx,0,0,0\n",$time);
      if(hif_cmd_valid && !hif_cmd_stall) $fwrite(logfile,"%0t,command,%0d,%0d,%0h\n",$time,hif_cmd_type,hif_cmd_token,hif_cmd_addr);
      if(hif_wdata_ptr_valid) $fwrite(logfile,"%0t,pointer,0,%0d,0\n",$time,hif_wdata_ptr);
      if(hif_wdata_valid && !hif_wdata_stall) $fwrite(logfile,"%0t,wdata,%0d,0,0\n",$time,hif_wdata_end);
      if(hif_rdata_valid) $fwrite(logfile,"%0t,rdata,%0d,%0d,0\n",$time,hif_rdata_end,hif_rdata_token);
    end
    if(cycle>30000) $fatal(1,"timeout parents=%0d children=%0d cmd=%0d credits=%0d/%0d/%0d",parents_used,children_used,stat_commands,lpr_available,hpr_available,wr_available);
  end
  assert property(@(posedge clk) disable iff(!rst_n)
    hif_cmd_valid && hif_cmd_stall |=> hif_cmd_valid && $stable({hif_cmd_type,hif_cmd_pri,hif_cmd_addr,hif_cmd_token,hif_cmd_length,hif_cmd_wdata_ptr,hif_cmd_autopre,hif_cmd_latency}));
  assert property(@(posedge clk) disable iff(!rst_n)
    hif_wdata_valid && hif_wdata_stall |=> hif_wdata_valid && $stable({hif_wdata,hif_wdata_mask,hif_wdata_end}));
  assert property(@(posedge clk) disable iff(!rst_n)
    fdi_tx_valid && !fdi_tx_ready |=> fdi_tx_valid && $stable(fdi_tx_data));
  initial begin
    if(!$value$plusargs("CASE=%d",case_id)) case_id=0;
    if(!$value$plusargs("OUT=%s",outdir)) outdir=".";
    tracepath={outdir,"/bridge.vcd"};$dumpfile(tracepath);$dumpvars(0,mc_bridge_tb);
    logfile=$fopen({outdir,"/events.csv"},"w");$fwrite(logfile,"time_fs,event,type,token_or_pointer,address\n");
    rxlog=$fopen({outdir,"/fdi_rx.csv"},"w");txlog=$fopen({outdir,"/fdi_tx.csv"},"w");
    $fwrite(rxlog,"time_fs,frame_hex_byte249_to_byte0\n");$fwrite(txlog,"time_fs,frame_hex_byte249_to_byte0\n");
    for(int r=0;r<4;r++) for(int k=0;k<3;k++) peer_credit[r][k]=0;
    for(int n=0;n<1024;n++) expected[n]='0;
    for(int b=0;b<65536;b++) reference_memory[b]=8'(b*13+7);
    repeat(4) @(negedge clk);rst_n=1;repeat(8) @(negedge clk);
    case(case_id)
      0:begin issue_write(1,'h1000,8,5);await_done(1);issue_read(2,'h1000,8,5);await_done(2);end
      1:begin issue_write(3,'h2000,8,5,1);await_done(3);issue_read(4,'h2000,8,5);await_done(4);if(stat_rmw==0) $fatal(1,"no RMW coverage");end
      2:begin issue_write(5,'h3000,8,5,1,1);await_done(5);issue_read(6,'h3000,8,5);await_done(6);end
      3:begin issue_write(7,'h4014,16,2,1);await_done(7);issue_read(8,'h4000,4,5);await_done(8);issue_read(9,'h4014,16,2);await_done(9);end
      4:begin
        issue_read(10,'h5000,8,5,0,0);issue_read(11,'h5200,8,5,0,9);
        issue_read(12,'h5400,8,5,0,0);issue_read(13,'h5600,8,5,0,9);
        await_done(10);await_done(11);await_done(12);await_done(13);
        if(out_of_order_returns==0) $fatal(1,"no out-of-order coverage");
      end
      5:begin issue_write(14,'h6000,128,5,1);await_done(14);issue_read(15,'h6000,128,5);await_done(15);end
      6:begin
        if(!ACK) begin issue_write(16,'h7000,4,5);await_done(16);if(stat_commands!=0) $fatal(1,"unconfirmed posted writes issued");end
        else begin
          prepare_expected(0,16,'h7000,2,5,2);send_message(address_message(0,16,'h7000,2,5,0,1),3);await_done(16);
        end
      end
      7:begin inject_crc=1;issue_read(17,'h7100,4,5,2);await_done(17);inject_crc=0;end
      8:begin inject_addr=1;issue_read(18,'h7200,4,5,3);await_done(18);inject_addr=0;end
      9:begin allow_errors=1;@(negedge clk);inject_unknown=1;repeat(3) @(negedge clk);inject_unknown=0;if(!error_code[2]) $fatal(1,"unknown pointer not detected");end
      10:begin
        issue_read(20,'h8000,8,5);issue_write(21,'h9000,2,5);issue_read(22,'h8200,8,5);
        await_done(20);await_done(21);await_done(22);
      end
      11:begin
        prepare_expected(0,30,'ha000,8,5,0);transactions_left[30]=2;second_address[30]='ha020;
        send_message(address_message(0,30,'ha000,8,5,0,0),3);
        send_message(address_message(0,30,'ha020,8,5,9,0),3);await_done(30);
      end
      12:begin
        issue_write(31,'hb000,8,5,1);issue_read(32,'hb000,8,5);await_done(31);await_done(32);
        issue_write(33,'hb000,8,5);issue_read(34,'hb000,8,5);await_done(33);await_done(34);
      end
      13:begin inject_pointer_error=1;issue_write(35,'hc000,16,5,0,0,3);await_done(35);inject_pointer_error=0;end
      14:begin allow_errors=1;@(negedge clk);inject_read_token=1;repeat(3) @(negedge clk);inject_read_token=0;if(!error_code[4]) $fatal(1,"unknown read token not detected");end
      15:begin
        prepare_expected(0,36,0,2,5,3);send_message(address_message(0,36,64'h10000000000,2,5,0,0),3);await_done(36);
        if(stat_commands!=0) $fatal(1,"40-bit address silently truncated");
      end
      16:begin inject_ecc=1;issue_read(37,'hd000,4,5,2);await_done(37);inject_ecc=0;end
      default:$fatal(1,"unknown case");
    endcase
    if(case_id!=9 && case_id!=14) begin
      while(!business_idle) @(negedge clk);
      repeat(8) @(negedge clk);
      if(carry_have!=0 || parents_used!=0 || children_used!=0) $fatal(1,"undrained transaction");
      if(lpr_available!=24 || hpr_available!=8 || wr_available!=32) $fatal(1,"MC credits not conserved");
      if(stat_response_count!=completed) $fatal(1,"response conservation failure");
    end
    summaryfile=$fopen({outdir,"/summary.json"},"w");
    $fwrite(summaryfile,"{\"status\":\"mock_verified\",\"real_mc_verified\":false,\"completed\":%0d,\"cycles\":%0d,\"commands\":%0d,\"reads\":%0d,\"writes\":%0d,\"rmw\":%0d,\"cmd_stall\":%0d,\"wdata_stall\":%0d,\"out_of_order_words\":%0d,\"effective_write_bytes\":%0d,\"mc_write_words\":%0d,\"rx_frames\":%0d,\"tx_frames\":%0d,\"packed_granules\":%0d,\"spanning_messages\":%0d,\"error_code\":%0d,\"rx_messages\":%0d,\"mc_read_words\":%0d}\n",
      completed,stat_cycles,stat_commands,stat_reads,stat_writes,stat_rmw,stat_cmd_stall,stat_wdata_stall,out_of_order_returns,
      stat_effective_write_bytes,stat_mc_write_words,stat_rx_frames,stat_tx_frames,stat_packed_granules,stat_spanning_messages,error_code,stat_rx_messages,stat_read_words);
    $fclose(summaryfile);$fclose(logfile);$fclose(rxlog);$fclose(txlog);$display("TEST_PASS case=%0d completed=%0d",case_id,completed);$finish;
  end
endmodule
