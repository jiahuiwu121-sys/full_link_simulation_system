#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"
export SS_MEMORY_BACKEND=ramulator2
[[ -x "$AXI_GEM5_BIN" ]] || { echo '请先执行 bash env/build.sh' >&2; exit 1; }
destination=${1:-"$SS_ROOT/results/ramulator2-$(date -u +%Y%m%dT%H%M%SZ)"}
[[ ! -e "$destination" ]] || { echo "结果目录已存在：$destination" >&2; exit 1; }
mkdir -p "$destination" "$AXI_PROJECT_DIR/build"
destination=$(cd "$destination" && pwd)
"$AXI_PYTHON" "$SS_ROOT/env/check_sources.py"
"$AXI_PYTHON" "$SS_ROOT/env/record.py" "$destination/environment"
ctest --test-dir "$RAMULATOR_BUILD" --show-only=json-v1 > "$destination/native-test-plan.json"
ctest --test-dir "$RAMULATOR_BUILD" --output-on-failure > "$destination/native-tests.log" 2>&1
"$AXI_PYTHON" "$RAMULATOR_HOME/integration/check_online.py" \
    "$RAMULATOR_BUILD/lib/libstoragestacked_ramulator2.so" "$destination/api"
"$AXI_CC" -O2 -static -nostdlib -ffreestanding -fno-stack-protector -fno-pie -no-pie -Wl,-e,_start \
    "$AXI_PROJECT_DIR/workloads/ramulator_check.c" -o "$AXI_PROJECT_DIR/build/ramulator_check"
run_case() {
    local name=$1; shift
    local dir="$destination/$name"
    mkdir -p "$dir"
    echo "运行 $name"
    "$AXI_GEM5_BIN" --listener-mode=off -d "$dir" "$AXI_PROJECT_DIR/configs/run.py" \
        --backend aou --memory-backend ramulator2 --het-trace "$@" > "$dir/run.log" 2>&1
    local flags=()
    [[ $name == cpu* ]] || flags+=(--directed)
    "$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/check.py" "$dir" "${flags[@]}"
    flags=(); [[ $name != replay ]] || flags+=(--replay)
    "$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/check_aou.py" "$dir" "${flags[@]}"
    for checker in inspect_link check_ramulator trace_view ramulator_view; do
        "$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/$checker.py" "$dir"
    done
}
run_case directed --mode tester
run_case replay --mode tester --planes 2 --replay
run_case shallow --mode tester --ramulator-queue 1
run_case held --mode tester --ramulator-queue 1 --ramulator-slots 1 --ramulator-response-hold 200
run_case period_3ns --mode tester --period 3ns
run_case power_off --mode tester --ramulator-no-power
run_case cpu --mode cpu --no-stalls --binary "$AXI_PROJECT_DIR/build/ramulator_check"
run_case cpu_slow --mode cpu --no-stalls --binary "$AXI_PROJECT_DIR/build/ramulator_check" --ramulator-scale 4
"$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/audit_wave.py" \
    "$destination/directed" "$destination/replay" "$destination/shallow" "$destination/held" \
    "$destination/period_3ns" "$destination/power_off" "$destination/cpu" "$destination/cpu_slow" \
    --output "$destination/wave_audit"
"$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/check_ramulator_negative.py" "$destination/directed"
"$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/check_aou_negative.py" "$destination/directed"
"$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/check_link_negative.py" "$destination/directed"
"$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/check_axi256.py" "$destination/directed"
"$AXI_PYTHON" "$SS_ROOT/env/verify_ramulator.py" "$destination"
echo "Ramulator2 全链路验收通过：$destination/summary.json"
