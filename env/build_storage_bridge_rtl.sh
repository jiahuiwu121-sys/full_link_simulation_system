#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"
width=${SS_AXI_DATA_WIDTH:-256}
planes=${SS_RESOURCE_PLANES:-1}
case "$width" in 256|512|1024) ;; *) echo "无效AXI位宽：$width" >&2; exit 1;; esac
case "$planes" in 1|2|3|4) ;; *) echo "无效Resource Plane数量：$planes" >&2; exit 1;; esac
command -v verilator >/dev/null || { echo "RTL桥接需要Verilator 5.x" >&2; exit 1; }
out=$("$AXI_PYTHON" "$SS_ROOT/env/storage_bridge_config.py" --build-dir)
mapfile -t rtl_parameters < <("$AXI_PYTHON" "$SS_ROOT/env/storage_bridge_config.py" --verilator-args)
mkdir -p "$out"
rtl="$SS_ROOT/storage_bridge/rtl"
verilator --cc --unroll-count 512 --trace --trace-max-array 512 --Mdir "$out" --top-module storage_bridge_top \
  -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM \
  -Wno-PINCONNECTEMPTY -GAXI_DATA_WIDTH="$width" -GRESOURCE_PLANES="$planes" "${rtl_parameters[@]}" \
  "$rtl/storage_bridge_pkg.sv" "$rtl/aou_fdi_rx.sv" "$rtl/aou_request_decoder.sv" \
  "$rtl/aou_credit_manager.sv" "$rtl/aou_transaction_manager.sv" "$rtl/aou_response_encoder.sv" \
  "$rtl/aou_fdi_tx.sv" "$rtl/storage_bridge_top.sv"
make -C "$out" -f Vstorage_bridge_top.mk -j "${AXI_JOBS:-6}" CXX="$AXI_CXX"
"$AXI_PYTHON" - "$out/model_manifest.json" <<'PY_MODEL'
import hashlib,json,os,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(os.environ['SS_ROOT'])/'env'))
from storage_bridge_config import from_environment,source_hash
p=Path(sys.argv[1]);lib=p.parent/'libVstorage_bridge_top.a'
p.write_text(json.dumps({'schema':'storagestacked.rtl-model.v2',
 'axi_data_width':int(os.environ.get('SS_AXI_DATA_WIDTH',256)),
 'resource_planes':int(os.environ.get('SS_RESOURCE_PLANES',1)),
 'parameters':from_environment(),'source_sha256':source_hash(),
 'verilator':subprocess.check_output(['verilator','--version'],text=True).strip(),
 'library_sha256':hashlib.sha256(lib.read_bytes()).hexdigest(),
 'trace_memory_array_limit':512},indent=2)+'\n')
PY_MODEL
