package storage_bridge_pkg;
  parameter int FDI_BYTES = 250;
  parameter int FDI_BITS = FDI_BYTES * 8;
  parameter int PROTOCOL_HEADER_BYTES = 10;
  parameter int PAYLOAD_BYTES = 240;
  parameter int GRANULE_BYTES = 5;
  parameter int GRANULES_PER_FLIT = 48;
  parameter int MAX_MESSAGE_BYTES = 150;
  parameter int MAX_MESSAGE_BITS = MAX_MESSAGE_BYTES * 8;

  typedef enum logic [3:0] {
    MSG_MISC       = 4'h0,
    MSG_WRITE_REQ  = 4'h1,
    MSG_READ_REQ   = 4'h2,
    MSG_WRITE_DATA = 4'h3,
    MSG_READ_DATA  = 4'h4,
    MSG_WRITE_RESP = 4'h5,
    MSG_WRITE_FULL = 4'h6
  } msg_type_e;

  typedef enum logic [2:0] {
    CREDIT_WREQ  = 3'd0,
    CREDIT_RREQ  = 3'd1,
    CREDIT_WDATA = 3'd2,
    CREDIT_RDATA = 3'd3,
    CREDIT_WRESP = 3'd4
  } credit_kind_e;

  function automatic int unsigned data_bytes(input int unsigned axi_data_width);
    return axi_data_width / 8;
  endfunction

  function automatic logic [1:0] dlength(input int unsigned axi_data_width);
    case (axi_data_width)
      256: return 2'd0;
      512: return 2'd1;
      default: return 2'd2;
    endcase
  endfunction

  function automatic int unsigned data_message_granules(
      input logic [3:0] msg_type, input logic [1:0] dl);
    case (msg_type)
      MSG_WRITE_DATA: case (dl) 0: return 8; 1: return 15; 2: return 30; default: return 0; endcase
      MSG_WRITE_FULL: case (dl) 0: return 7; 1: return 14; 2: return 27; default: return 0; endcase
      MSG_READ_DATA:  case (dl) 0: return 8; 1: return 14; 2: return 27; default: return 0; endcase
      default: return 0;
    endcase
  endfunction

  function automatic int unsigned message_granules(input logic [7:0] first_byte);
    logic [3:0] kind;
    logic [2:0] misc_op;
    kind = first_byte[7:4];
    misc_op = first_byte[3:1];
    case (kind)
      MSG_WRITE_REQ, MSG_READ_REQ: return 3;
      MSG_WRITE_RESP: return 1;
      MSG_WRITE_DATA, MSG_WRITE_FULL, MSG_READ_DATA:
        return data_message_granules(kind, first_byte[1:0]);
      MSG_MISC: case (misc_op) 3'b100: return 2; 3'b000: return 1; default: return 0; endcase
      default: return 0;
    endcase
  endfunction

  function automatic int unsigned decode_credit(input logic [2:0] encoding);
    case (encoding)
      3'd0: return 0;   3'd1: return 1;   3'd2: return 4;   3'd3: return 8;
      3'd4: return 16;  3'd5: return 32;  3'd6: return 64;  default: return 128;
    endcase
  endfunction

  function automatic logic [2:0] encode_credit(input int unsigned amount,
                                                 input int unsigned max_code);
    if (max_code >= 7 && amount >= 128) return 3'd7;
    if (max_code >= 6 && amount >= 64)  return 3'd6;
    if (max_code >= 5 && amount >= 32)  return 3'd5;
    if (max_code >= 4 && amount >= 16)  return 3'd4;
    if (max_code >= 3 && amount >= 8)   return 3'd3;
    if (max_code >= 2 && amount >= 4)   return 3'd2;
    if (max_code >= 1 && amount >= 1)   return 3'd1;
    return 3'd0;
  endfunction

  // AoU fields are bit-serialized MSB first. This helper matches BitReader.
  function automatic logic [63:0] get_be_bits(
      input logic [MAX_MESSAGE_BITS-1:0] bytes,
      input int unsigned start, input int unsigned width);
    logic [63:0] value;
    int unsigned byte_index, bit_index;
    value = '0;
    for (int unsigned i = 0; i < width; i++) begin
      byte_index = (start + i) / 8;
      bit_index = 7 - ((start + i) % 8);
      value = (value << 1) | bytes[byte_index * 8 + bit_index];
    end
    return value;
  endfunction
endpackage
