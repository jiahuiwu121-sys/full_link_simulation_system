#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"

export SS_MEMORY_BACKEND=ramulator2
export SS_VISUALIZATION_BATCH=1
[[ -x "$AXI_GEM5_BIN" ]] || { echo '请先执行 bash env/build.sh' >&2; exit 1; }

topology=${2:-${SS_TOPOLOGY_CONFIG:-$SS_ROOT/configs/topology/dual-ucie-hbm4.json}}
[[ -f "$topology" ]] || { echo "拓扑配置不存在：$topology" >&2; exit 1; }
destination=$("$AXI_PYTHON" "$SS_ROOT/env/create_result_dir.py" "$SS_ROOT/results" \
    ${1:+"$1"} --label "${SS_EXPERIMENT_LABEL:-topology}")
mkdir -p "$destination"
echo "结果目录：$destination"

"$AXI_PYTHON" "$AXI_PROJECT_DIR/tests/topology_config_test.py" \
    > "$destination/topology-config-test.log" 2>&1
"$AXI_PYTHON" "$SS_ROOT/env/record.py" "$destination/environment"

"$AXI_GEM5_BIN" --listener-mode=off -d "$destination" "$AXI_PROJECT_DIR/configs/run.py" \
    --backend aou --memory-backend ramulator2 --mode traffic \
    --topology-config "$topology" --axi-data-width "${SS_AXI_DATA_WIDTH:-256}" \
    --traffic-load-percent "${SS_TRAFFIC_LOAD_PERCENT:-100}" \
    --traffic-warmup "${SS_TRAFFIC_WARMUP:-128}" \
    --traffic-measure "${SS_TRAFFIC_MEASURE:-1024}" \
    --traffic-cooldown "${SS_TRAFFIC_COOLDOWN:-128}" \
    --traffic-size "${SS_TRAFFIC_SIZE:-256}" \
    --traffic-working-set "${SS_TRAFFIC_WORKING_SET:-1048576}" \
    --traffic-write-percent "${SS_TRAFFIC_WRITE_PERCENT:-50}" \
    --traffic-max-inflight "${SS_TRAFFIC_MAX_INFLIGHT:-64}" \
    > "$destination/run.log" 2>&1

publish_flags=()
[[ ${SS_VISUALIZATION_OPEN:-1} == 0 ]] && publish_flags+=(--no-open)
[[ ${SS_VISUALIZATION_SERVE:-1} == 0 ]] && publish_flags+=(--no-serve)
"$AXI_PYTHON" "$SS_ROOT/env/publish_results.py" "$destination" "${publish_flags[@]}"
echo "多模块拓扑仿真与独立验收通过：$destination"
