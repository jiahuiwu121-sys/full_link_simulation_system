#!/usr/bin/env bash
# Backward-compatible alias for the unified traffic/CPU/GPU/NPU profile runner.
set -euo pipefail
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/run_system_profile.sh" "$@"
