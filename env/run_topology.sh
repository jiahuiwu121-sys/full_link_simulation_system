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
if [[ -n ${SS_PROFILE_ARTIFACT_DIR:-} ]]; then
    [[ -d $SS_PROFILE_ARTIFACT_DIR ]] || { echo "配置编译目录不存在：$SS_PROFILE_ARTIFACT_DIR" >&2; exit 1; }
    mkdir -p "$destination/system_profile"
    cp -a "$SS_PROFILE_ARTIFACT_DIR"/. "$destination/system_profile/"
fi

"$AXI_PYTHON" "$AXI_PROJECT_DIR/tests/topology_config_test.py" \
    > "$destination/topology-config-test.log" 2>&1
"$AXI_PYTHON" "$SS_ROOT/env/record.py" "$destination/environment"

ramulator_flags=(
    --ramulator-standard "${SS_RAMULATOR_STANDARD:-HBM4}"
    --ramulator-queue "${SS_RAMULATOR_QUEUE:-8}"
    --ramulator-slots "${SS_RAMULATOR_SLOTS:-8}"
    --ramulator-children "${SS_RAMULATOR_CHILDREN:-32}"
    --ramulator-submit-width "${SS_RAMULATOR_SUBMIT_WIDTH:-8}"
    --ramulator-response-hold "${SS_RAMULATOR_RESPONSE_HOLD:-0}"
    --ramulator-scale "${SS_RAMULATOR_SCALE:-1}"
    --metrics-sample-cycles "${SS_METRICS_SAMPLE_CYCLES:-1000}"
)
[[ -n ${SS_RAMULATOR_CHANNELS:-} ]] && ramulator_flags+=(--ramulator-channels "$SS_RAMULATOR_CHANNELS")
[[ -n ${SS_RAMULATOR_CONFIG:-} ]] && ramulator_flags+=(--ramulator-config "$SS_RAMULATOR_CONFIG")
[[ ${SS_RAMULATOR_NO_POWER:-0} == 1 ]] && ramulator_flags+=(--ramulator-no-power)
link_flags=(--planes "${SS_RESOURCE_PLANES:-1}" --period "${SS_AXI_PERIOD:-666667fs}")
[[ ${SS_AXI_NO_STALLS:-0} == 1 ]] && link_flags+=(--no-stalls)
[[ ${SS_UCIE_REPLAY:-0} == 1 ]] && link_flags+=(--replay)

mode=${SS_EXECUTION_MODE:-traffic}
case "$mode" in
traffic)
    frontend_flags=(--mode traffic
        --traffic-load-percent "${SS_TRAFFIC_LOAD_PERCENT:-100}"
        --traffic-warmup "${SS_TRAFFIC_WARMUP:-128}"
        --traffic-measure "${SS_TRAFFIC_MEASURE:-1024}"
        --traffic-cooldown "${SS_TRAFFIC_COOLDOWN:-128}"
        --traffic-size "${SS_TRAFFIC_SIZE:-256}"
        --traffic-working-set "${SS_TRAFFIC_WORKING_SET:-1048576}"
        --traffic-write-percent "${SS_TRAFFIC_WRITE_PERCENT:-50}"
        --traffic-max-inflight "${SS_TRAFFIC_MAX_INFLIGHT:-64}")
    ;;
cpu)
    [[ -f ${SS_HOST_BINARY:-} ]] || { echo "CPU程序不存在：${SS_HOST_BINARY:-未配置}" >&2; exit 1; }
    frontend_flags=(--mode cpu --binary "$SS_HOST_BINARY"
        --options "${SS_HOST_OPTIONS:-}" --process-env-json "$SS_PROCESS_ENV_JSON")
    [[ -n ${SS_TARGET_SIZE_BYTES:-} ]] && frontend_flags+=(--target-size "$SS_TARGET_SIZE_BYTES")
    ;;
*) echo "run_topology.sh不支持执行模式：$mode" >&2; exit 1 ;;
esac

"$AXI_GEM5_BIN" --listener-mode=off -d "$destination" "$AXI_PROJECT_DIR/configs/run.py" \
    --backend aou --memory-backend ramulator2 \
    --topology-config "$topology" --axi-data-width "${SS_AXI_DATA_WIDTH:-256}" \
    --slots "${SS_TLM_SLOTS:-4}" \
    --fdi-fifo-depth "${SS_FDI_FIFO_DEPTH:-8}" \
    --memory-fifo-depth "${SS_MEMORY_FIFO_DEPTH:-4}" \
    --max-ticks "${SS_MAX_TICKS:-10000000000000}" \
    "${link_flags[@]}" "${ramulator_flags[@]}" \
    "${frontend_flags[@]}" \
    > "$destination/run.log" 2>&1

publish_flags=()
[[ ${SS_VISUALIZATION_OPEN:-1} == 0 ]] && publish_flags+=(--no-open)
[[ ${SS_VISUALIZATION_SERVE:-1} == 0 ]] && publish_flags+=(--no-serve)
"$AXI_PYTHON" "$SS_ROOT/env/publish_results.py" "$destination" "${publish_flags[@]}"
echo "拓扑仿真与独立验收通过：$destination"
