#!/usr/bin/env bash
# Full 4 module-count x 3 Resource-Plane acceptance matrix at the active AXI width.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"
[[ ${SS_AXI_DATA_WIDTH:-256} == 256 ]] || {
    echo '1/2/4/8模块模板要求默认AXI256构建；请设置SS_AXI_DATA_WIDTH=256并重新构建。' >&2
    exit 1
}
root=$("$AXI_PYTHON" "$SS_ROOT/env/create_result_dir.py" "$SS_ROOT/results" \
    ${1:+"$1"} --label "${SS_EXPERIMENT_LABEL:-configuration-matrix}")
echo "矩阵结果目录：$root"
"$AXI_PYTHON" - "$root" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
cases=[]
for modules in (1,2,4,8):
    for planes in (1,2,4):
        cases.append({'name':f'modules-{modules}-rp-{planes}', 'axi_data_width':256,
                      'modules':modules, 'resource_planes':planes})
(root/'matrix_plan.json').write_text(json.dumps({
    'schema':'storagestacked.configuration-matrix.v1',
    'matrix_type':'module-count-resource-plane', 'cases':cases}, indent=2)+'\n')
PY

declare -A topology=(
    [1]="$SS_ROOT/configs/topology/single-hbm4.json"
    [2]="$SS_ROOT/configs/topology/dual-ucie-hbm4.json"
    [4]="$SS_ROOT/configs/topology/quad-ucie-hbm4.json"
    [8]="$SS_ROOT/configs/topology/octal-ucie-hbm4.json"
)
for planes in 1 2 4; do
    if [[ ${SS_STORAGE_BRIDGE_IMPL:-systemc} == rtl ]]; then
        SS_RESOURCE_PLANES="$planes" bash "$SS_ROOT/env/build.sh" > "$root/build-rp${planes}.log" 2>&1
    fi
    for modules in 1 2 4 8; do
        name="modules-$modules-rp-$planes"
        echo "运行 $name"
        SS_RESOURCE_PLANES="$planes" \
        SS_TRAFFIC_WARMUP="${SS_MATRIX_WARMUP:-4}" \
        SS_TRAFFIC_MEASURE="${SS_MATRIX_MEASURE:-32}" \
        SS_TRAFFIC_COOLDOWN="${SS_MATRIX_COOLDOWN:-4}" \
        SS_TRAFFIC_SIZE="${SS_MATRIX_REQUEST_SIZE:-256}" \
        SS_TRAFFIC_WORKING_SET="${SS_MATRIX_WORKING_SET:-8192}" \
        SS_TRAFFIC_MAX_INFLIGHT="${SS_MATRIX_MAX_INFLIGHT:-8}" \
        SS_VISUALIZATION_OPEN=0 SS_VISUALIZATION_SERVE=0 \
        bash "$SS_ROOT/env/run_topology.sh" "$root/$name" "${topology[$modules]}"
    done
done
"$AXI_PYTHON" "$SS_ROOT/env/verify_configuration_matrix.py" "$root"
"$AXI_PYTHON" "$SS_ROOT/env/publish_results.py" "$root" --skip-views --no-open --no-serve
echo "12项模块/RP自动化验收通过：$root"
