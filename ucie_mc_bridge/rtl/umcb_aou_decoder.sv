module umcb_aou_decoder # (parameter int RP=1)(
  input logic clk,rst_n,valid,output logic ready,input logic [319:0] message,
  output logic request_valid,input logic request_ready,output umcb_pkg::request_t request,
  output logic write_valid,input logic write_ready,output umcb_pkg::write_t write_data,
  output logic misc_valid,output logic fault
);
  import umcb_pkg::*;
  logic is_request,is_write,legal;
  logic [63:0] value;
  always_comb begin
    is_request=message[7:4]==M_AW || message[7:4]==M_AR;
    is_write=message[7:4]==M_W || message[7:4]==M_FULL;
    request='0;request.write=message[7:4]==M_AW;request.rp=message[3:2];
    value=field_be(message,8,16);request.user=value[15:0];
    value=field_be(message,24,10);request.id=value[9:0];
    value=field_be(message,34,3);request.size=value[2:0];
    value=field_be(message,37,3);request.prot=value[2:0];
    value=field_be(message,40,8);request.len=value[7:0];
    value=field_be(message,48,4);request.cache=value[3:0];
    value=field_be(message,52,4);request.qos=value[3:0];
    request.addr=field_be(message,56,64);request.lock=message[0];
    write_data='0;write_data.rp=message[3:2];
    value=field_be(message,8,16);write_data.user=value[15:0];
    write_data.granules=message[7:4]==M_FULL?7:8;
    for(int b=0;b<32;b++) begin
      write_data.data[b*8+:8]=message[(34-b)*8+:8];
      write_data.mask[b]=message[7:4]==M_FULL?1'b1:message[(38-b/8)*8+b%8];
    end
    legal=request.rp<RP;
    if(is_request) legal=legal && request.size<=5 &&
      (request.addr & ((64'd1<<request.size)-1))==0 &&
      ({1'b0,request.addr[11:0]}+((int'(request.len)+1)<<request.size))<=4096;
    if(is_write) legal=legal && message[1:0]==0;
    misc_valid=valid && message[7:4]==M_MISC && message[3:1]==4;
    request_valid=valid && is_request && legal;
    write_valid=valid && is_write && legal;
  end
  assign ready=misc_valid || (is_request && legal && request_ready) || (is_write && legal && write_ready);
  always_ff @(posedge clk or negedge rst_n)
    if(!rst_n) fault<=0;
    else if(valid && !(misc_valid || (legal && (is_request || is_write)))) fault<=1;
endmodule
