#!/usr/bin/env bash
# Functional/stress regression; this short matrix does NOT certify saturation.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"
export SS_STORAGE_BRIDGE_IMPL=rtl SS_AXI_DATA_WIDTH=256 SS_RESOURCE_PLANES=1
export SS_VISUALIZATION_BATCH=1 SS_VISUALIZATION_OPEN=0 SS_VISUALIZATION_SERVE=0
root=$("$AXI_PYTHON" "$SS_ROOT/env/create_result_dir.py" "$SS_ROOT/results" \
    ${1:+"$1"} --label storage-bridge-validation)
echo "Bridge验收结果目录：$root"
bash "$SS_ROOT/env/build.sh" > "$root/build.log" 2>&1
topology="$SS_ROOT/configs/topology/single-hbm4.json"

mkdir "$root/directed"
"$AXI_PYTHON" "$SS_ROOT/env/record.py" "$root/directed/environment"
SS_STORAGE_BRIDGE_TRACE=1 "$AXI_GEM5_BIN" --listener-mode=off -d "$root/directed" \
    "$AXI_PROJECT_DIR/configs/run.py" --mode tester --backend aou --memory-backend ramulator2 \
    --planes 1 --axi-data-width 256 > "$root/directed/run.log" 2>&1
"$AXI_PYTHON" "$SS_ROOT/env/publish_results.py" "$root/directed" --no-open --no-serve
"$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/check_metrics_negative.py" "$root/directed" > "$root/metrics-negative.log"

echo '{}' > "$root/process_environment.json"
SS_EXECUTION_MODE=cpu SS_HOST_BINARY="$AXI_PROJECT_DIR/build/ramulator_check" \
SS_PROCESS_ENV_JSON="$root/process_environment.json" SS_AXI_NO_STALLS=1 \
bash "$SS_ROOT/env/run_topology.sh" "$root/cpu" "$topology"

export SS_EXECUTION_MODE=traffic SS_TLM_SLOTS=64 SS_AXI_NO_STALLS=1
export SS_TRAFFIC_WARMUP=16 SS_TRAFFIC_MEASURE=256 SS_TRAFFIC_COOLDOWN=16
export SS_TRAFFIC_MAX_INFLIGHT=64 SS_TRAFFIC_WORKING_SET=1048576
for size in 256 1024 4096; do
    for writes in 0 50 100; do
        SS_TRAFFIC_SIZE="$size" SS_TRAFFIC_WRITE_PERCENT="$writes" \
        bash "$SS_ROOT/env/run_topology.sh" "$root/rtl-size${size}-write${writes}" "$topology"
    done
done
# The RTL-enabled binary contains both endpoints; select the reference at
# runtime, keeping the exact same workload, topology and backend settings.
SS_STORAGE_BRIDGE_IMPL=systemc SS_TRAFFIC_SIZE=1024 SS_TRAFFIC_WRITE_PERCENT=50 \
bash "$SS_ROOT/env/run_topology.sh" "$root/systemc-size1024-write50" "$topology"
"$AXI_PYTHON" "$SS_ROOT/env/compare_storage_bridge.py" \
    "$root/rtl-size1024-write50" "$root/systemc-size1024-write50" \
    --output "$root/differential_check.json"
"$AXI_PYTHON" "$SS_ROOT/env/publish_results.py" "$root" --skip-views --no-open --no-serve
echo "Bridge定向/CPU/9组压力/参考差分验收通过：$root"
