#!/usr/bin/env bash
# Unified user entry for traffic, CPU, Vortex and CoralNPU configurations.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"
exec "$AXI_PYTHON" "$SS_ROOT/env/run_system_profile.py" "$@"
