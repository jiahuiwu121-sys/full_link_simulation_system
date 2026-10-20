#!/usr/bin/env bash
# Run one configured host/Vortex/CoralNPU combination through the common link.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"

export SS_RUN_XPU=1
export SS_MEMORY_BACKEND=ramulator2
export SS_VISUALIZATION_BATCH=1
export LD_LIBRARY_PATH="$SS_DEPS_ROOT/xpu-native/lib:$VORTEX_HOME/third_party/ramulator:$LD_LIBRARY_PATH"
[[ -x "$AXI_GEM5_BIN" ]] || { echo '请先执行 bash env/build_xpu.sh' >&2; exit 1; }
[[ -f ${SS_HOST_BINARY:-} ]] || { echo "宿主程序不存在：${SS_HOST_BINARY:-未配置}" >&2; exit 1; }

topology=${SS_TOPOLOGY_CONFIG:-$SS_ROOT/configs/topology/single-hbm4.json}
[[ -f "$topology" ]] || { echo "拓扑配置不存在：$topology" >&2; exit 1; }
destination=$("$AXI_PYTHON" "$SS_ROOT/env/create_result_dir.py" "$SS_ROOT/results" \
    ${1:+"$1"} --label "${SS_EXPERIMENT_LABEL:-${SS_EXECUTION_MODE:-xpu}}")
mkdir -p "$destination"
echo "结果目录：$destination"
if [[ -n ${SS_PROFILE_ARTIFACT_DIR:-} ]]; then
    mkdir -p "$destination/system_profile"
    cp -a "$SS_PROFILE_ARTIFACT_DIR"/. "$destination/system_profile/"
fi

"$AXI_PYTHON" "$AXI_PROJECT_DIR/tests/topology_config_test.py" \
    > "$destination/topology-config-test.log" 2>&1
"$AXI_PYTHON" "$AXI_PROJECT_DIR/tests/metrics_contract_test.py" \
    > "$destination/metrics-contract.log" 2>&1
"$AXI_PYTHON" "$SS_ROOT/env/check_sources.py" --xpu
"$AXI_PYTHON" "$SS_ROOT/env/record.py" "$destination/environment"
"$AXI_PYTHON" "$SS_ROOT/env/record_xpu.py" "$destination/environment"

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
[[ ${SS_RAMULATOR_NO_POWER:-0} == 1 ]] && ramulator_flags+=(--ramulator-no-power)

device_flags=()
if [[ -n ${SS_GPU_LIBRARY:-} ]]; then
    [[ -f $SS_GPU_LIBRARY ]] || { echo "Vortex库不存在：$SS_GPU_LIBRARY" >&2; exit 1; }
    [[ -d ${SS_GPU_RUNTIME_DIR:-} ]] || { echo "Vortex runtime不存在：${SS_GPU_RUNTIME_DIR:-未配置}" >&2; exit 1; }
    [[ -f ${SS_GPU_KERNEL:-} ]] || { echo "Vortex kernel不存在：${SS_GPU_KERNEL:-未配置}" >&2; exit 1; }
    device_flags+=(--vortex-library "$SS_GPU_LIBRARY" --vortex-host-rt-dir "$SS_GPU_RUNTIME_DIR")
fi
if [[ -n ${SS_NPU_LIBRARY:-} ]]; then
    [[ -f $SS_NPU_LIBRARY ]] || { echo "CoralNPU库不存在：$SS_NPU_LIBRARY" >&2; exit 1; }
    [[ -f ${SS_NPU_KERNEL:-} ]] || { echo "CoralNPU kernel不存在：${SS_NPU_KERNEL:-未配置}" >&2; exit 1; }
    device_flags+=(--npu-library "$SS_NPU_LIBRARY" --npu-kernel "$SS_NPU_KERNEL")
fi

link_flags=(--planes "${SS_RESOURCE_PLANES:-1}" --slots "${SS_TLM_SLOTS:-16}"
    --axi-period "${SS_AXI_PERIOD:-666667fs}"
    --fdi-fifo-depth "${SS_FDI_FIFO_DEPTH:-8}"
    --memory-fifo-depth "${SS_MEMORY_FIFO_DEPTH:-4}")
[[ ${SS_AXI_NO_STALLS:-0} == 1 ]] && link_flags+=(--no-stalls)
[[ ${SS_UCIE_REPLAY:-0} == 1 ]] && link_flags+=(--replay)

"$AXI_GEM5_BIN" --listener-mode=off -d "$destination" "$AXI_PROJECT_DIR/configs/run_xpu.py" \
    --memory-backend ramulator2 --topology-config "$topology" \
    --axi-data-width "${SS_AXI_DATA_WIDTH:-256}" \
    --cmd "$SS_HOST_BINARY" --options "${SS_HOST_OPTIONS:-}" \
    --process-env-json "$SS_PROCESS_ENV_JSON" --num-cpus "${SS_CPU_COUNT:-4}" \
    --max-ticks "${SS_MAX_TICKS:-20000000000000}" \
    "${link_flags[@]}" "${ramulator_flags[@]}" "${device_flags[@]}" \
    > "$destination/run.log" 2>&1

"$AXI_PYTHON" -m hettrace validate "$destination/hettrace" \
    --ticks-per-second 1000000000000000 > "$destination/hettrace/validation.txt"
publish_flags=()
[[ ${SS_VISUALIZATION_OPEN:-1} == 0 ]] && publish_flags+=(--no-open)
[[ ${SS_VISUALIZATION_SERVE:-1} == 0 ]] && publish_flags+=(--no-serve)
"$AXI_PYTHON" "$SS_ROOT/env/publish_results.py" "$destination" "${publish_flags[@]}"
echo "${SS_EXECUTION_MODE:-XPU}全链路仿真与独立验收通过：$destination"
