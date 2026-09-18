#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"
export SS_RUN_XPU=1
export LD_LIBRARY_PATH="$SS_DEPS_ROOT/xpu-native/lib:$VORTEX_HOME/third_party/ramulator:$LD_LIBRARY_PATH"
destination=${1:-"$SS_ROOT/results/xpu-$(date -u +%Y%m%dT%H%M%SZ)"}
[[ ! -e "$destination" ]] || { echo "结果目录已存在：$destination" >&2; exit 1; }
mkdir -p "$destination"
destination=$(cd "$destination" && pwd)
"$AXI_PYTHON" "$AXI_PROJECT_DIR/tests/metrics_contract_test.py" > "$destination/metrics-contract.log" 2>&1
"$AXI_PYTHON" "$SS_ROOT/env/check_sources.py" --xpu
"$AXI_PYTHON" "$SS_ROOT/env/record.py" "$destination/environment"
"$AXI_PYTHON" "$SS_ROOT/env/record_xpu.py" "$destination/environment"
if [[ $SS_MEMORY_BACKEND == ramulator2 ]]; then
    native_build="$RAMULATOR_BUILD"
    native_api="$RAMULATOR_HOME/integration/check_online.py"
    native_library="$RAMULATOR_BUILD/lib/libstoragestacked_ramulator2.so"
    memory_checks=(check_ramulator ramulator_view)
    memory_flags=(--memory-backend ramulator2)
    slow_flags=(--ramulator-scale 4)
else
    native_build="$MEMSIM_BUILD"
    native_api="$MEMSIM_HOME/integration/check_online.py"
    native_library="$MEMSIM_BUILD/libstoragestacked_memsim.so"
    memory_checks=(check_memsim memsim_view)
    memory_flags=(--memory-backend memsim)
    slow_flags=(--memsim-scale 4)
fi
ctest --test-dir "$native_build" --show-only=json-v1 > "$destination/native-test-plan.json"
ctest --test-dir "$native_build" --output-on-failure > "$destination/native-tests.log" 2>&1
"$AXI_PYTHON" "$native_api" "$native_library" "$destination/api"
if [[ $SS_MEMORY_BACKEND == ramulator2 ]]; then
    "$AXI_PYTHON" "$RAMULATOR_HOME/integration/check_metrics_sampling.py" "$native_library" "$destination/metrics_sampling"
fi
gpu=(--vortex-library "$VORTEX_BUILD/sim/simx/libvortex-gem5.so" --vortex-host-rt-dir "$VORTEX_BUILD/sw/runtime")
npu=(--npu-library "$CORALNPU_HOME/bazel-bin/gem5int/libcoralnpu-gem5.so" --npu-kernel "$SS_ROOT/build/xpu/ddr_touch.elf")
run_case() {
    local name=$1
    shift
    local dir="$destination/$name"
    mkdir -p "$dir"
    echo "运行 $name"
    # Acceptance runs need no debugger; stray connections can stop simulation.
    "$AXI_GEM5_BIN" --listener-mode=off -d "$dir" "$AXI_PROJECT_DIR/configs/run_xpu.py" "${memory_flags[@]}" "$@" > "$dir/run.log" 2>&1
    echo "$name 仿真结束，开始数据与链路校验"
    for checker in check check_aou inspect_link check_metrics trace_view "${memory_checks[@]}"; do
        "$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/$checker.py" "$dir" >> "$dir/verification.log" 2>&1
    done
    "$AXI_PYTHON" -m hettrace validate "$dir/hettrace" --ticks-per-second 1000000000000000 > "$dir/hettrace/validation.txt"
    echo "$name 计算与链路校验通过"
}
run_case npu --cmd "$HET_PROJECT_ROOT/workloads/shared_buffer/build/host_main" --options=npu "${npu[@]}"
run_case gpu --cmd "$VORTEX_BUILD/tests/regression/vecadd/vecadd" --options="-n 4 -k $VORTEX_BUILD/tests/regression/vecadd/kernel.vxbin" "${gpu[@]}"
run_case three --cmd "$HET_PROJECT_ROOT/workloads/three_source/build/host_main" --options="-k $VORTEX_BUILD/tests/regression/vecadd/kernel.vxbin" "${gpu[@]}" "${npu[@]}"
run_case three_slow --cmd "$HET_PROJECT_ROOT/workloads/three_source/build/host_main" --options="-k $VORTEX_BUILD/tests/regression/vecadd/kernel.vxbin" "${gpu[@]}" "${npu[@]}" "${slow_flags[@]}"
"$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/audit_wave.py" "$destination/npu" "$destination/gpu" "$destination/three" "$destination/three_slow" --output "$destination/wave_audit"
"$AXI_PYTHON" "$SS_ROOT/env/verify_xpu.py" "$destination"
"$AXI_PYTHON" "$SS_ROOT/env/summarize_metrics.py" "$destination"
echo "三源全链路验收通过：$destination/summary.json"
