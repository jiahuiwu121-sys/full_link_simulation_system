#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"
export SS_MEMORY_BACKEND=ramulator2
export SS_VISUALIZATION_BATCH=1
[[ -x "$AXI_GEM5_BIN" ]] || { echo '请先执行 bash env/build.sh' >&2; exit 1; }
destination=$("$AXI_PYTHON" "$SS_ROOT/env/create_result_dir.py" "$SS_ROOT/results" \
    ${1:+"$1"} --label "${SS_EXPERIMENT_LABEL:-bandwidth-sweep}")
echo "结果目录：$destination"
"$AXI_PYTHON" "$SS_ROOT/env/check_sources.py"
"$AXI_PYTHON" "$SS_ROOT/env/record.py" "$destination/environment"

run_case() {
    local load=$1
    local name
    printf -v name 'load_%03d' "$load"
    local dir="$destination/$name"
    mkdir -p "$dir"
    echo "运行 $name（AXI理论载荷的 $load%）"
    "$AXI_GEM5_BIN" --listener-mode=off -d "$dir" "$AXI_PROJECT_DIR/configs/run.py" \
        --backend aou --memory-backend ramulator2 --het-trace --mode traffic --no-stalls \
        --period 666667fs --target-size 0x100000 --traffic-working-set 0x100000 \
        --traffic-size 256 --traffic-write-percent 50 --traffic-max-inflight 64 \
        --traffic-warmup 128 --traffic-measure 1024 --traffic-cooldown 128 \
        --traffic-load-percent "$load" --slots 64 --ramulator-slots 64 \
        --ramulator-children 512 --ramulator-submit-width 8 --ramulator-queue 64 \
        > "$dir/run.log" 2>&1
    "$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/check.py" "$dir"
    "$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/check_aou.py" "$dir"
    for checker in inspect_link check_ramulator check_metrics trace_view ramulator_view; do
        "$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/$checker.py" "$dir"
    done
}

for load in 10 25 50 75 100 125; do
    run_case "$load"
done
"$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/audit_wave.py" \
    "$destination/load_010" "$destination/load_025" "$destination/load_050" \
    "$destination/load_075" "$destination/load_100" "$destination/load_125" \
    --output "$destination/wave_audit"
"$AXI_PYTHON" "$SS_ROOT/env/verify_bandwidth_sweep.py" "$destination"
"$AXI_PYTHON" "$SS_ROOT/env/summarize_metrics.py" "$destination"
"$AXI_PYTHON" "$SS_ROOT/env/publish_results.py" "$destination" --skip-views --no-open --no-serve
echo "带宽—延迟压力扫描通过：$destination/index.html"
