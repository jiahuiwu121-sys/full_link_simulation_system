// Independent AoU256 wire contract. No dependency on storage_bridge RTL.
package umcb_pkg;
  localparam int FDI_BITS=2000, PAYLOAD_GRANULES=48, MESSAGE_BITS=320;
  localparam logic [3:0] M_MISC=0, M_AW=1, M_AR=2, M_W=3, M_R=4, M_B=5, M_FULL=6;
  localparam int C_AW=0,C_AR=1,C_W=2,C_R=3,C_B=4;
  typedef struct packed {
    logic write;
    logic [1:0] rp;
    logic [9:0] id;
    logic [15:0] user;
    logic [63:0] addr;
    logic [7:0] len;
    logic [2:0] size;
    logic lock;
    logic [2:0] prot;
    logic [3:0] cache,qos;
  } request_t;
  typedef struct packed {
    logic [1:0] rp;
    logic [15:0] user;
    logic [255:0] data;
    logic [31:0] mask;
    logic [3:0] granules;
  } write_t;
  typedef struct packed {
    logic write;
    logic [1:0] rp;
    logic [9:0] id;
    logic [15:0] user;
    logic [1:0] status;
    logic last;
    logic [255:0] data;
    logic [5:0] tag;
  } response_t;
  function automatic int message_size(input logic [7:0] first);
    case(first[7:4])
      M_AW,M_AR:return 3;
      M_W,M_R:return first[1:0]==0?8:0;
      M_FULL:return first[1:0]==0?7:0;
      M_B:return 1;
      M_MISC:return first[3:1]==4?2:0;
      default:return 0;
    endcase
  endfunction
  function automatic logic [63:0] field_be(input logic [MESSAGE_BITS-1:0] m,input int offset,input int width);
    logic [63:0] result;
    result=0;
    for(int i=0;i<width;i++) result=(result<<1)|64'(m[((offset+i)/8)*8+7-(offset+i)%8]);
    return result;
  endfunction
  function automatic int credit_value(input logic [2:0] code);
    case(code)
      0:return 0;1:return 1;2:return 4;3:return 8;4:return 16;5:return 32;6:return 64;7:return 128;
    endcase
  endfunction
  function automatic logic [2:0] credit_code(input int count,input int limit);
    for(int k=7;k>=1;k--) if(k<=limit && credit_value(3'(k))<=count) return 3'(k);
    return 0;
  endfunction
  function automatic logic [47:0] frame_starts(input logic [FDI_BITS-1:0] f);
    return {f[72+:8],f[68+:4],f[56+:8],f[52+:4],f[24+:8],f[20+:4],f[8+:8],f[4+:4]};
  endfunction
  function automatic logic [FDI_BITS-1:0] make_frame(input logic [1919:0] payload,input logic [47:0] starts,input logic [15:0] credit);
    logic [FDI_BITS-1:0] f;
    f=0;f[4+:4]=starts[0+:4];f[8+:8]=starts[4+:8];
    f[20+:4]=starts[12+:4];f[24+:8]=starts[16+:8];
    f[32+:16]=credit;f[52+:4]=starts[24+:4];f[56+:8]=starts[28+:8];
    f[68+:4]=starts[36+:4];f[72+:8]=starts[40+:8];f[80+:1920]=payload;
    return f;
  endfunction
endpackage
