#!/usr/bin/env bash
# Compile a user system profile and build the matching AXI width/backend.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"

profile=${1:?用法: bash env/build_profile.sh <system-profile.json> [compiled-directory]}
[[ -f $profile ]] || { echo "系统配置不存在：$profile" >&2; exit 1; }
name=$(basename -- "$profile" .json)
compiled=${2:-"$SS_ROOT/build/system_profiles/$name"}
"$AXI_PYTHON" "$SS_ROOT/env/system_profile.py" "$profile" --output "$compiled"
# shellcheck disable=SC1090
source "$compiled/build.env"
bash "$SS_ROOT/env/build.sh"
mkdir -p "$SS_ROOT/build"
cp "$compiled/build_signature.json" "$SS_ROOT/build/active_profile_signature.json"
cp "$compiled/topology_resolved.json" "$SS_ROOT/build/active_system_profile.json"
echo "配置构建完成：$compiled"
