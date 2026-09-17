#!/usr/bin/env bash
set -euo pipefail
self=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
: "${GEM5_HOME:?请设置 GEM5_HOME}"
# 主仓库 gem5 已包含 DmaPort byte-enable 适配；只刷新设备构建副本。
for component in dev/coralnpu dev/vortex mem/unified_timing; do
    mkdir -p "$GEM5_HOME/src/$component"
    cp "$self/src/$component/"* "$GEM5_HOME/src/$component/"
done
