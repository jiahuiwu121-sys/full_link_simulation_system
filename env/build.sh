#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"
mkdir -p "$SS_ROOT/build"
# Serialize native rebuilds, device refreshes and SCons when build_xpu and
# build are requested concurrently.
exec 9>"$SS_ROOT/build/system-build.lock"
flock 9
"$AXI_PYTHON" "$SS_ROOT/env/check_sources.py"
# gem5 兼容适配已随主仓库源码维护，不在构建时修改已有源码。
bash "$HET_PROJECT_ROOT/gem5int/install_devices.sh"
"$AXI_PYTHON" "$SS_ROOT/env/prepare_ramulator_sources.py" --check
ramulator_sources=()
for dependency in yaml-cpp fmt dramutils nlohmann_json; do
    ramulator_sources+=("-DFETCHCONTENT_SOURCE_DIR_${dependency^^}=$SS_DEPS_ROOT/ramulator2-sources/$dependency")
done
backend_args=("SS_HAVE_MEMSIM=0")
case "$SS_MEMORY_BACKEND" in
ramulator2)
    cmake -S "$RAMULATOR_HOME" -B "$RAMULATOR_BUILD" -G Ninja -DCMAKE_BUILD_TYPE=Release \
        "-DCMAKE_CXX_COMPILER=$AXI_CXX" -DRAMULATOR_PYTHON_BINDINGS=OFF \
        -DRAMULATOR_ONLINE_INTEGRATION=ON -DRAMULATOR_ENABLE_DRAMPOWER=ON "${ramulator_sources[@]}"
    cmake --build "$RAMULATOR_BUILD" -j "${AXI_JOBS:-6}"
    ;;
memsim)
    # The legacy backend remains optional and requires matching external delivery.
    cmake -S "$MEMSIM_HOME" -B "$MEMSIM_BUILD" -G Ninja -DCMAKE_BUILD_TYPE=Release "-DCMAKE_CXX_COMPILER=$AXI_CXX"
    cmake --build "$MEMSIM_BUILD" -j "${AXI_JOBS:-6}"
    backend_args=("SS_HAVE_MEMSIM=1")
    # The gem5 binary supports both branches when legacy support is enabled.
    cmake -S "$RAMULATOR_HOME" -B "$RAMULATOR_BUILD" -G Ninja "-DCMAKE_CXX_COMPILER=$AXI_CXX" \
        -DRAMULATOR_PYTHON_BINDINGS=OFF -DRAMULATOR_ONLINE_INTEGRATION=ON "${ramulator_sources[@]}"
    cmake --build "$RAMULATOR_BUILD" -j "${AXI_JOBS:-6}"
    ;;
*) echo "Unknown SS_MEMORY_BACKEND: $SS_MEMORY_BACKEND" >&2; exit 1 ;;
esac
cd "$GEM5_HOME"
build_args=("CXX=$AXI_CXX" "CC=$AXI_CC" "PYTHON_CONFIG=$PYTHON_CONFIG"
    "EXTRAS=$AXI_PROJECT_DIR:$HET_PROJECT_ROOT/gem5int/src/hettrace" "${backend_args[@]}")
if [[ ! -f build/AXI/gem5.build/config ]]; then
    "$SS_PREFIX/bin/scons" defconfig build/AXI build_opts/X86 "${build_args[@]}"
fi
"$SS_PREFIX/bin/scons" setconfig build/AXI RUBY=n USE_KVM=y USE_SYSTEMC=y "${build_args[@]}"
"$SS_PREFIX/bin/scons" build/AXI/gem5.opt "${build_args[@]}" "-j${AXI_JOBS:-6}"
