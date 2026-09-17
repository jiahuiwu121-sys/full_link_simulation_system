#!/usr/bin/env python3
"""Check project-owned source directories and pinned external submodules."""
import argparse
import os
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LOCAL_SOURCES = {
    "gem5": ("SConstruct", "src/systemc/tlm_bridge/gem5_to_tlm.cc"),
    "coralnpu": ("MODULE.bazel", "hw_sim/core_mini_axi_wrapper.h"),
    "gem5_new": ("gem5int/src/dev/coralnpu/coralnpu_dev.cc",),
    "axi2flit": ("systemc/include/axi2flit.h",),
    "ucie-model": ("src/ucie_link.h",),
    "gem5_axi": ("SConscript",),
    "protocol": ("include/aou_format6.h",),
    "ramulator2": ("CMakeLists.txt",),
    "mem_sim": ("CMakeLists.txt", "integration/online.h"),
}


def git(directory, *args):
    return subprocess.check_output(
        ["git", "-C", str(directory), *args], text=True,
        stderr=subprocess.PIPE,
    )


def check_local(name):
    directory = ROOT / name
    if not directory.is_dir():
        raise ValueError(f"{name}: 项目源码目录缺失；请取得与当前项目匹配的源码")
    if (directory / ".git").exists() or (directory / ".git").is_symlink():
        raise ValueError(f"{name}: 应为主仓库普通目录，不应包含内部 .git")
    if Path(git(directory, "rev-parse", "--show-toplevel").strip()).resolve() != ROOT:
        raise ValueError(f"{name}: 源码不属于当前主仓库")
    entries = git(ROOT, "ls-files", "--stage", "--", name).splitlines()
    if any(entry.startswith("160000 ") for entry in entries):
        raise ValueError(f"{name}: 索引仍包含 Git 子模块链接，应导入普通源码文件")
    if not entries:
        raise ValueError(f"{name}: 源码尚未纳入主仓库索引")
    for relative in LOCAL_SOURCES[name]:
        if not (directory / relative).is_file():
            raise ValueError(f"{name}: 缺少 {relative}，请检查是否多嵌套了一层目录")
    print(f"{name}: monorepo source")


def check_external(name, revision):
    directory = ROOT / name
    if not (directory / ".git").exists():
        raise ValueError(f"{name}: 子模块未初始化，请执行 git submodule update --init --recursive")
    if Path(git(directory, "rev-parse", "--show-toplevel").strip()).resolve() != directory:
        raise ValueError(f"{name}: 应为独立外部子模块")
    actual = git(directory, "rev-parse", "HEAD").strip()
    if actual != revision:
        raise ValueError(f"{name}: expected {revision}, found {actual}; no checkout performed")
    states = git(ROOT, "submodule", "status", "--recursive", "--", name)
    for state in states.splitlines():
        if state and state[0] != " ":
            raise ValueError("子模块未初始化、版本不匹配或存在冲突：" + state)
    print(f"{name}: {actual}")


def main():
    expected = json.loads((ROOT / "env/sources.lock.json").read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", choices=tuple(LOCAL_SOURCES) + tuple(expected),
                        help="仅检查指定模块；默认检查完整链路所需源码")
    parser.add_argument('--memory-backend', choices=['ramulator2','memsim'],
                        default=os.environ.get('SS_MEMORY_BACKEND','ramulator2'))
    parser.add_argument('--xpu', action='store_true', help='Also require the locked Vortex submodules')
    args = parser.parse_args()
    common = ['gem5','gem5_new','gem5_axi','axi2flit','ucie-model','protocol','ramulator2']
    selected = args.only or common + (['mem_sim'] if args.memory_backend == 'memsim' else [])
    if args.xpu and not args.only:
        selected += ['coralnpu'] + list(expected)
    errors = []
    for name in dict.fromkeys(selected):
        try:
            if name in LOCAL_SOURCES:
                check_local(name)
            else:
                check_external(name, expected[name])
        except (ValueError, subprocess.CalledProcessError) as error:
            errors.append(str(error))
    if errors:
        raise SystemExit("\n".join(errors))


if __name__ == "__main__":
    main()
