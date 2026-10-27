#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"
width=${SS_AXI_DATA_WIDTH:-256}
planes=${SS_RESOURCE_PLANES:-4}
case "$width" in 256|512|1024) ;; *) echo "无效AXI位宽：$width" >&2; exit 1;; esac
case "$planes" in 1|2|3|4) ;; *) echo "无效Resource Plane数量：$planes" >&2; exit 1;; esac
command -v verilator >/dev/null || { echo "RTL桥接需要Verilator 5.x" >&2; exit 1; }
out="$SS_ROOT/build/storage_bridge-rtl-${width}-rp${planes}"
mkdir -p "$out"
rtl="$SS_ROOT/storage_bridge/rtl"
verilator --cc --Mdir "$out" --top-module storage_bridge_top \
  -Wno-fatal -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM \
  -Wno-PINCONNECTEMPTY -GAXI_DATA_WIDTH="$width" -GRESOURCE_PLANES="$planes" \
  "$rtl/storage_bridge_pkg.sv" "$rtl/aou_fdi_rx.sv" "$rtl/aou_request_decoder.sv" \
  "$rtl/aou_credit_manager.sv" "$rtl/aou_response_encoder.sv" \
  "$rtl/aou_fdi_tx.sv" "$rtl/storage_bridge_top.sv"
make -C "$out" -f Vstorage_bridge_top.mk -j "${AXI_JOBS:-6}" CXX="$AXI_CXX"
