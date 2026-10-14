#!/usr/bin/env bash
# Rebuild and validate AXI256/512/1024, then restore the selected daily build.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"
restore_width=${SS_RESTORE_AXI_DATA_WIDTH:-256}
case "$restore_width" in 256|512|1024) ;; *) echo 'SS_RESTORE_AXI_DATA_WIDTH只能是256/512/1024' >&2; exit 1;; esac
root=$("$AXI_PYTHON" "$SS_ROOT/env/create_result_dir.py" "$SS_ROOT/results" \
    ${1:+"$1"} --label "${SS_EXPERIMENT_LABEL:-axi-width-matrix}")
echo "AXI位宽矩阵结果目录：$root"
"$AXI_PYTHON" - "$root" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
cases=[{'name':f'axi-{w}', 'axi_data_width':w, 'modules':1, 'resource_planes':1}
       for w in (256,512,1024)]
(root/'matrix_plan.json').write_text(json.dumps({
    'schema':'storagestacked.configuration-matrix.v1',
    'matrix_type':'axi-data-width', 'cases':cases}, indent=2)+'\n')
PY

restored=0
restore_build() {
    if [[ $restored == 0 ]]; then
        restored=1
        echo "恢复AXI${restore_width}构建"
        SS_AXI_DATA_WIDTH="$restore_width" bash "$SS_ROOT/env/build.sh" > "$root/build-restore-axi${restore_width}.log" 2>&1
    fi
}
trap restore_build EXIT
for width in 256 512 1024; do
    topology="$SS_ROOT/configs/topology/single-hbm4.json"
    [[ $width == 512 ]] && topology="$SS_ROOT/configs/topology/single-hbm4-axi512.json"
    [[ $width == 1024 ]] && topology="$SS_ROOT/configs/topology/single-hbm4-axi1024.json"
    echo "构建并运行AXI${width}"
    SS_AXI_DATA_WIDTH="$width" bash "$SS_ROOT/env/build.sh" > "$root/build-axi${width}.log" 2>&1
    SS_AXI_DATA_WIDTH="$width" \
    SS_TRAFFIC_WARMUP="${SS_WIDTH_MATRIX_WARMUP:-4}" \
    SS_TRAFFIC_MEASURE="${SS_WIDTH_MATRIX_MEASURE:-32}" \
    SS_TRAFFIC_COOLDOWN="${SS_WIDTH_MATRIX_COOLDOWN:-4}" \
    SS_TRAFFIC_SIZE="${SS_WIDTH_MATRIX_REQUEST_SIZE:-256}" \
    SS_TRAFFIC_WORKING_SET="${SS_WIDTH_MATRIX_WORKING_SET:-8192}" \
    SS_TRAFFIC_MAX_INFLIGHT="${SS_WIDTH_MATRIX_MAX_INFLIGHT:-8}" \
    SS_VISUALIZATION_OPEN=0 SS_VISUALIZATION_SERVE=0 \
    bash "$SS_ROOT/env/run_topology.sh" "$root/axi-$width" "$topology"
done
"$AXI_PYTHON" "$SS_ROOT/env/verify_configuration_matrix.py" "$root"
"$AXI_PYTHON" "$SS_ROOT/env/publish_results.py" "$root" --skip-views --no-open --no-serve
restore_build
trap - EXIT
echo "AXI256/512/1024完整回归通过且已恢复AXI${restore_width}：$root"
