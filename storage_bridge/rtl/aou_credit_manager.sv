module aou_credit_manager #(
  parameter int RESOURCE_PLANES = 1,
  parameter int REQUEST_SLOTS = 4,
  parameter int WDATA_GRANULES = 64
) (
  input logic clk,
  input logic rst_n,
  input logic header_valid,
  input logic [15:0] header_field,
  input logic misc_valid,
  output logic misc_ready,
  input logic [storage_bridge_pkg::MAX_MESSAGE_BITS-1:0] misc_data,
  input logic return_valid,
  input logic [1:0] return_rp,
  input logic [2:0] return_kind,
  input logic [7:0] return_granules,
  input logic query_write,
  input logic [1:0] query_rp,
  input logic [7:0] query_granules,
  output logic query_ok,
  input logic consume_valid,
  input logic [1:0] consume_rp,
  input logic [2:0] consume_kind,
  input logic [7:0] consume_granules,
  output logic grant_valid,
  output logic [15:0] grant_field,
  input logic grant_take,
  output logic protocol_error
);
  import storage_bridge_pkg::*;
  integer tx_credit [0:3][0:4];
  integer pending [0:3][0:4];
  logic [1:0] grant_rp;
  logic [2:0] grant_code [0:4];
  integer next_rp;

  function automatic int capacity(input int rp, input int kind);
    if (rp >= RESOURCE_PLANES) return 0;
    case (kind)
      CREDIT_WREQ, CREDIT_RREQ: return REQUEST_SLOTS * 3;
      CREDIT_WDATA: return WDATA_GRANULES;
      default: return 0;
    endcase
  endfunction

  function automatic logic [2:0] misc_code(input int kind, input int rp,
      input logic [MAX_MESSAGE_BITS-1:0] data);
    int start;
    logic [63:0] bits;
    if (kind < CREDIT_WRESP) begin
      start = 7 + kind * 12 + rp * 3;
      bits = get_be_bits(data, start, 3);
      return bits[2:0];
    end
    start = 55 + rp * 2;
    bits = get_be_bits(data, start, 2);
    return {1'b0, bits[1:0]};
  endfunction

  function automatic logic [2:0] header_code(input int kind, input logic [15:0] field);
    case (kind)
      0: return field[2:0];
      1: return field[5:3];
      2: return field[8:6];
      3: return field[11:9];
      default: return {1'b0, field[13:12]};
    endcase
  endfunction

  assign misc_ready = 1'b1;
  always_comb begin
    query_ok = query_rp < RESOURCE_PLANES &&
      tx_credit[query_rp][query_write ? CREDIT_WRESP : CREDIT_RDATA] >= query_granules;
    grant_valid = 1'b0; grant_field = '0; grant_rp = next_rp[1:0];
    for (int scan = 0; scan < RESOURCE_PLANES; scan++) begin
      int rp;
      rp = (next_rp + scan) % RESOURCE_PLANES;
      if (!grant_valid && (pending[rp][CREDIT_WREQ] != 0 ||
          pending[rp][CREDIT_RREQ] != 0 || pending[rp][CREDIT_WDATA] != 0)) begin
        grant_valid = 1'b1; grant_rp = rp[1:0];
      end
    end
    grant_code[CREDIT_WREQ] = encode_credit(pending[grant_rp][CREDIT_WREQ], 7);
    grant_code[CREDIT_RREQ] = encode_credit(pending[grant_rp][CREDIT_RREQ], 7);
    grant_code[CREDIT_WDATA] = encode_credit(pending[grant_rp][CREDIT_WDATA], 7);
    grant_code[CREDIT_RDATA] = 0; grant_code[CREDIT_WRESP] = 0;
    grant_field = {grant_rp, grant_code[CREDIT_WRESP][1:0], grant_code[CREDIT_RDATA],
                   grant_code[CREDIT_WDATA], grant_code[CREDIT_RREQ], grant_code[CREDIT_WREQ]};
  end

  always_ff @(posedge clk or negedge rst_n) begin : update_credits
    if (!rst_n) begin
      next_rp <= 0; protocol_error <= 1'b0;
      for (int r = 0; r < 4; r++)
        for (int k = 0; k < 5; k++) begin
          tx_credit[r][k] <= 0;
          pending[r][k] <= capacity(r, k);
        end
    end else begin
      if (misc_valid && misc_ready &&
          (misc_data[7:4] != MSG_MISC || misc_data[3:1] != 3'b100))
        protocol_error <= 1'b1;
      if (consume_valid && (consume_rp >= RESOURCE_PLANES ||
          consume_kind > CREDIT_WRESP ||
          tx_credit[consume_rp][consume_kind] < consume_granules))
        protocol_error <= 1'b1;
      if (return_valid &&
          (return_rp >= RESOURCE_PLANES || return_kind > CREDIT_WDATA))
        protocol_error <= 1'b1;

      // Calculate one assignment per counter so simultaneous header/Misc
      // grants, response consumption, credit return and header emission add up.
      for (int r = 0; r < 4; r++) begin
        for (int k = 0; k < 5; k++) begin
          int tx_next, pending_next;
          tx_next = tx_credit[r][k];
          if (header_valid && header_field[15:14] == r && r < RESOURCE_PLANES)
            tx_next = tx_next + decode_credit(header_code(k, header_field));
          if (misc_valid && misc_ready && misc_data[7:4] == MSG_MISC &&
              misc_data[3:1] == 3'b100 && r < RESOURCE_PLANES)
            tx_next = tx_next + decode_credit(misc_code(k, r, misc_data));
          if (consume_valid && consume_rp == r && consume_kind == k &&
              consume_rp < RESOURCE_PLANES && consume_kind <= CREDIT_WRESP &&
              tx_credit[r][k] >= consume_granules)
            tx_next = tx_next - consume_granules;
          tx_credit[r][k] <= tx_next > 4095 ? 4095 : tx_next;

          pending_next = pending[r][k];
          if (return_valid && return_rp == r && return_kind == k &&
              return_rp < RESOURCE_PLANES && return_kind <= CREDIT_WDATA) begin
            pending_next = pending_next + return_granules;
            if (pending_next > capacity(r, k)) pending_next = capacity(r, k);
          end
          if (grant_valid && grant_take && grant_rp == r)
            pending_next = pending_next - decode_credit(grant_code[k]);
          pending[r][k] <= pending_next;
        end
      end
      if (grant_valid && grant_take)
        next_rp <= (grant_rp + 1) % RESOURCE_PLANES;
    end
  end

  initial begin
    if (RESOURCE_PLANES < 1 || RESOURCE_PLANES > 4) $error("RESOURCE_PLANES must be 1..4");
  end
endmodule
