#!/usr/bin/env bash
# Compile and build the frontend/link/backend selected by one system profile.
set -euo pipefail
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/run_system_profile.sh" "$@" --build-only
