#!/usr/bin/env bash
# Run reproducible mixed and directional offered-load validation for one profile.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"

profile=${1:?用法: bash env/run_profile_sweep.sh <system-profile.json> [result-directory]}
requested_result=${2:-}
[[ -f $profile ]] || { echo "系统配置不存在：$profile" >&2; exit 1; }
profile=$(realpath -- "$profile")
name=$(basename -- "$profile" .json)

bash "$SS_ROOT/env/build_profile.sh" "$profile"
compiled="$SS_ROOT/build/system_profiles/$name"
profile_mode=$("$AXI_PYTHON" - "$compiled/frontend_plan.json" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))['mode'])
PY
)
[[ $profile_mode == traffic ]] || {
    echo "负载百分比扫描仅适用于execution.mode=traffic，当前为：$profile_mode" >&2
    exit 1
}
# The profile is the source of truth for an explicitly configured sweep.
# Profiles without a sweep section do not emit these variables, preserving
# the historical environment-variable override behavior.
# shellcheck disable=SC1090
source "$compiled/run.env"
destination=$("$AXI_PYTHON" "$SS_ROOT/env/create_result_dir.py" "$SS_ROOT/results" \
    ${requested_result:+"$requested_result"} --label "${SS_EXPERIMENT_LABEL:-$name-sweep}")
mkdir -p "$destination/system_profile"
cp -a "$compiled"/. "$destination/system_profile/"
echo "配置压力扫描结果目录：$destination"

if [[ -n ${SS_PROFILE_SWEEP_LOADS:-} ]]; then
    read -r -a mixed_loads <<<"$SS_PROFILE_SWEEP_LOADS"
else
    mapfile -t mixed_loads < <("$AXI_PYTHON" - "$compiled/validation_plan.json" <<'PY'
import json, sys
for value in json.load(open(sys.argv[1]))['load_sweep_percent']:
    print(value)
PY
)
fi
read -r -a saturation_loads <<<"${SS_PROFILE_SWEEP_SATURATION_LOADS:-100 125}"
read -r -a directions <<<"${SS_PROFILE_SWEEP_DIRECTIONS:-mixed read write}"

run_case() {
    local direction=$1 load=$2 write_percent case_dir
    case "$direction" in
        mixed) write_percent=${SS_PROFILE_SWEEP_MIXED_WRITE_PERCENT:-50} ;;
        read) write_percent=0 ;;
        write) write_percent=100 ;;
        *) echo "未知扫描方向：$direction" >&2; exit 1 ;;
    esac
    printf -v case_dir '%s/%s_load_%03d' "$destination" "$direction" "$load"
    echo "运行 $(basename -- "$case_dir")：写比例 ${write_percent}%，供给负载 ${load}%"
    SS_EXPERIMENT_LABEL="$name-$direction-load-$load" \
    SS_TRAFFIC_LOAD_PERCENT="$load" \
    SS_TRAFFIC_WRITE_PERCENT="$write_percent" \
    SS_VISUALIZATION_OPEN=0 SS_VISUALIZATION_SERVE=0 \
        bash "$SS_ROOT/env/run_profile.sh" "$profile" "$case_dir"
    "$AXI_PYTHON" - "$case_dir/profile_sweep_case.json" "$direction" "$load" "$write_percent" <<'PY'
import json, sys
path, direction, load, writes = sys.argv[1:]
open(path, 'w').write(json.dumps({
    'schema': 'storagestacked.profile-sweep-case.v1',
    'direction': direction,
    'load_percent': float(load),
    'write_percent': int(writes),
}, indent=2) + '\n')
PY
}

for direction in "${directions[@]}"; do
    if [[ $direction == mixed ]]; then loads=("${mixed_loads[@]}");
    else loads=("${saturation_loads[@]}"); fi
    for load in "${loads[@]}"; do run_case "$direction" "$load"; done
done

"$AXI_PYTHON" "$SS_ROOT/env/verify_profile_sweep.py" "$destination"
"$AXI_PYTHON" "$SS_ROOT/env/summarize_metrics.py" "$destination"
"$AXI_PYTHON" "$SS_ROOT/env/publish_results.py" "$destination" \
    --skip-views --no-open --no-serve
echo "配置压力扫描完成：$destination/index.html；判定：$destination/profile_sweep.md"
