module umcb_aou_encoder(
  input umcb_pkg::response_t response,output logic [319:0] message,output logic [3:0] granules
);
  import umcb_pkg::*;
  always_comb begin
    message=0;granules=response.write?1:8;
    message[0+:8]={response.write?M_B:M_R,response.rp,2'b0};
    message[8+:8]=response.user[15:8];message[16+:8]=response.user[7:0];
    message[24+:8]=response.id[9:2];
    message[32+:8]={response.id[1:0],response.status,response.write?1'b0:response.last,3'b0};
    if(!response.write) for(int i=0;i<32;i++) message[(36-i)*8+:8]=response.data[i*8+:8];
  end
endmodule
