#!/usr/bin/env bash
# Compile, build when necessary, and run one user system profile.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"

profile=${1:?用法: bash env/run_profile.sh <system-profile.json> [result-directory]}
result=${2:-}
[[ -f $profile ]] || { echo "系统配置不存在：$profile" >&2; exit 1; }
name=$(basename -- "$profile" .json)
compiled="$SS_ROOT/build/system_profiles/$name"
"$AXI_PYTHON" "$SS_ROOT/env/system_profile.py" "$profile" --output "$compiled"
# shellcheck disable=SC1090
source "$compiled/build.env"
# shellcheck disable=SC1090
source "$compiled/run.env"

active="$SS_ROOT/build/active_profile_signature.json"
if [[ ! -f $AXI_GEM5_BIN ]] || ! cmp -s "$compiled/build_signature.json" "$active"; then
    echo "当前二进制与配置的构建参数不匹配，自动重新构建。"
    bash "$SS_ROOT/env/build.sh"
fi
cp "$compiled/build_signature.json" "$active"
cp "$compiled/topology_resolved.json" "$SS_ROOT/build/active_system_profile.json"

export SS_TOPOLOGY_CONFIG="$compiled/runtime_topology.json"
export SS_PROFILE_ARTIFACT_DIR="$compiled"
export SS_EXPERIMENT_LABEL="${SS_EXPERIMENT_LABEL:-$name}"
export SS_TRAFFIC_LOAD_PERCENT="${SS_TRAFFIC_LOAD_PERCENT:-100}"
export SS_TRAFFIC_WARMUP="${SS_TRAFFIC_WARMUP:-128}"
export SS_TRAFFIC_MEASURE="${SS_TRAFFIC_MEASURE:-1024}"
export SS_TRAFFIC_COOLDOWN="${SS_TRAFFIC_COOLDOWN:-128}"
export SS_TRAFFIC_SIZE="${SS_TRAFFIC_SIZE:-256}"
export SS_TRAFFIC_WORKING_SET="${SS_TRAFFIC_WORKING_SET:-1048576}"
export SS_TRAFFIC_MAX_INFLIGHT="${SS_TRAFFIC_MAX_INFLIGHT:-256}"
if [[ -n $result ]]; then
    bash "$SS_ROOT/env/run_topology.sh" "$result"
else
    bash "$SS_ROOT/env/run_topology.sh"
fi
