// Verification ONLY. Implements the provisional waveform-demo contract, not
// DRAM timing, ECC algorithms, PHY, power, or a substitute production MC.
module mc_hif_model(
  input logic clk,rst_n,
  input logic hif_cmd_valid,output logic hif_cmd_stall,
  input logic [1:0] hif_cmd_type,hif_cmd_pri,
  input logic [39:0] hif_cmd_addr,input logic [52:0] hif_cmd_token,
  input logic hif_cmd_length,input logic [18:0] hif_cmd_wdata_ptr,
  output logic hif_lpr_credit,hif_hpr_credit,hif_wr_credit,
  output logic hif_rdata_valid,hif_rdata_end,output logic [52:0] hif_rdata_token,
  output logic [255:0] hif_rdata,
  output logic hif_rdata_uncorr_ecc_err,hif_rdata_addr_err,hif_rdata_crc_err,
  input logic hif_wdata_valid,output logic hif_wdata_stall,
  input logic [255:0] hif_wdata,input logic [31:0] hif_wdata_mask,input logic hif_wdata_end,
  output logic hif_wdata_ptr_valid,output logic [18:0] hif_wdata_ptr,output logic hif_wdata_ptr_addr_err,
  input logic inject_crc,inject_addr,inject_unknown,inject_ecc,inject_pointer_error,inject_read_token,
  output integer out_of_order_returns
);
  typedef struct packed {
    logic valid,requested,credit_returned;
    logic [1:0] op,pri;
    logic [39:0] addr;
    logic [52:0] token;
    logic [18:0] pointer;
    integer words,received,arrival;
  } entry_t;
  entry_t table_q[64];
  logic [7:0] memory[65536];
  integer cycle,free_slot,read_slot,ptr_slot,credit_slot,oldest_read;
  integer data_queue[64],head,tail,count,word_index;
  integer write_returns;
  logic push,pop;
  initial for(int b=0;b<65536;b++) memory[b]=8'(b*13+7);
  always_comb begin
    free_slot=-1;read_slot=-1;ptr_slot=-1;credit_slot=-1;oldest_read=-1;
    for(int k=0;k<64;k++) begin
      if(!table_q[k].valid && free_slot<0) free_slot=k;
      if(table_q[k].valid) begin
        if(table_q[k].op==1) begin
          if(oldest_read<0 || table_q[k].arrival<table_q[oldest_read].arrival) oldest_read=k;
          if(cycle-table_q[k].arrival>=24 && (read_slot<0 || table_q[k].token>table_q[read_slot].token)) read_slot=k;
        end else if(!table_q[k].requested && cycle-table_q[k].arrival>=3 &&
                    (ptr_slot<0 || table_q[k].arrival<table_q[ptr_slot].arrival)) ptr_slot=k;
        if(table_q[k].op!=0 && !table_q[k].credit_returned && cycle-table_q[k].arrival>=2 && credit_slot<0) credit_slot=k;
      end
    end
    hif_cmd_stall=free_slot<0 || (cycle%11>=3 && cycle%11<=6);
    hif_wdata_stall=cycle%7==1 || cycle%7==2;
    hif_lpr_credit=credit_slot>=0 && !(table_q[credit_slot].op==1 && table_q[credit_slot].pri==2);
    hif_hpr_credit=credit_slot>=0 && table_q[credit_slot].op==1 && table_q[credit_slot].pri==2;
    hif_wdata_ptr_valid=ptr_slot>=0 && cycle%4!=0;
    hif_wdata_ptr=hif_wdata_ptr_valid?table_q[ptr_slot].pointer:19'b0;
    if(inject_unknown) begin hif_wdata_ptr_valid=1;hif_wdata_ptr=19'h7ffff;end
    hif_wdata_ptr_addr_err=inject_pointer_error && ptr_slot>=0 && table_q[ptr_slot].token%3==0;
    hif_rdata_valid=read_slot>=0 && cycle%3!=1;
    hif_rdata_end=0;hif_rdata_token=0;hif_rdata=0;
    if(hif_rdata_valid) begin
      hif_rdata_token=table_q[read_slot].token;
      hif_rdata_end=table_q[read_slot].received+1==table_q[read_slot].words;
      for(int b=0;b<32;b++) hif_rdata[b*8+:8]=memory[(int'(table_q[read_slot].addr)+table_q[read_slot].received*32+b)%65536];
    end
    if(inject_read_token) begin hif_rdata_valid=1;hif_rdata_token=53'h1fffffffffffff;hif_rdata_end=1;end
    hif_rdata_uncorr_ecc_err=inject_ecc && hif_rdata_valid;hif_rdata_addr_err=inject_addr && hif_rdata_valid;
    hif_rdata_crc_err=inject_crc && hif_rdata_valid;
    push=hif_wdata_ptr_valid && !inject_unknown && !hif_wdata_ptr_addr_err;
  end
  assign hif_wr_credit=write_returns>0;
  assign pop=hif_wdata_valid && !hif_wdata_stall && hif_wdata_end;
  always_ff @(posedge clk or negedge rst_n) begin : model
    integer c,address;
    if(!rst_n) begin
      cycle<=0;head<=0;tail<=0;count<=0;word_index<=0;out_of_order_returns<=0;write_returns<=0;
      for(int k=0;k<64;k++) table_q[k]<='0;
    end else begin
      cycle<=cycle+1;
      write_returns<=write_returns+int'(pop)+int'(hif_wdata_ptr_valid && hif_wdata_ptr_addr_err)-int'(hif_wr_credit);
      if(hif_wdata_ptr_valid && hif_wdata_ptr_addr_err) begin table_q[ptr_slot].valid<=0;table_q[ptr_slot].requested<=1;end
      if(hif_cmd_valid && !hif_cmd_stall) begin
        table_q[free_slot]<='{valid:1'b1,requested:1'b0,credit_returned:1'b0,
          op:hif_cmd_type,pri:hif_cmd_pri,addr:hif_cmd_addr,token:hif_cmd_token,
          pointer:hif_cmd_wdata_ptr,words:hif_cmd_length?32'd2:32'd1,received:32'd0,arrival:cycle};
        if(hif_cmd_addr[4:0]!=0 || hif_cmd_type==3) $fatal(1,"invalid provisional MC command");
      end
      if(credit_slot>=0) table_q[credit_slot].credit_returned<=1;
      case({push,pop})
        2'b10:count<=count+1;
        2'b01:count<=count-1;
        default:;
      endcase
      if(push) begin
        table_q[ptr_slot].requested<=1;data_queue[tail]<=ptr_slot;tail<=(tail+1)%64;
        if(count==64 && !pop) $fatal(1,"MC model data request overflow");
      end
      if(hif_wdata_valid && !hif_wdata_stall) begin
        if(count==0) $fatal(1,"data supplied before pointer request");
        c=data_queue[head];address=int'(table_q[c].addr)+word_index*32;
        if(hif_wdata_end!=(word_index+1==table_q[c].words)) $fatal(1,"MC END mismatch");
        if(table_q[c].op==0 && hif_wdata_mask!=32'hffffffff) $fatal(1,"partial mask on block write");
        for(int b=0;b<32;b++) if(hif_wdata_mask[b]) memory[(address+b)%65536]<=hif_wdata[b*8+:8];
        if(hif_wdata_end) begin table_q[c].valid<=0;head<=(head+1)%64;word_index<=0;end
        else word_index<=word_index+1;
      end
      if(hif_rdata_valid && !inject_read_token) begin
        if(read_slot!=oldest_read) out_of_order_returns<=out_of_order_returns+1;
        table_q[read_slot].received<=table_q[read_slot].received+1;
        if(hif_rdata_end) table_q[read_slot].valid<=0;
      end
    end
  end
endmodule
