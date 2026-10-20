#!/usr/bin/env python3
"""Compile, build and run one unified traffic/CPU/GPU/NPU system profile."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'env'))
from system_profile import compile_profile


def load_json(path):
    return json.loads(Path(path).read_text())


def same_file(left, right):
    return left.is_file() and right.is_file() and left.read_bytes() == right.read_bytes()


def required_frontend_paths(plan):
    files = []
    directories = []
    if plan['mode'] != 'traffic':
        files.append(('host binary', Path(plan['host']['binary'])))
    if plan['gpu']['enabled']:
        files.extend((('Vortex library', Path(plan['gpu']['library'])),
                      ('Vortex kernel', Path(plan['gpu']['kernel']))))
        directories.append(('Vortex runtime', Path(plan['gpu']['runtime_directory'])))
    if plan['npu']['enabled']:
        files.extend((('CoralNPU library', Path(plan['npu']['library'])),
                      ('CoralNPU kernel', Path(plan['npu']['kernel']))))
    return files, directories


def validate_frontend(plan):
    files, directories = required_frontend_paths(plan)
    missing = [f'{kind}: {path}' for kind, path in files if not path.is_file()]
    missing += [f'{kind}: {path}' for kind, path in directories if not path.is_dir()]
    host = Path(plan['host']['binary']) if plan['host']['binary'] else None
    if host is not None and host.is_file() and not os.access(host, os.X_OK):
        missing.append(f'host binary is not executable: {host}')
    if missing:
        raise ValueError('frontend validation failed after build:\n  ' + '\n  '.join(missing))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', type=Path)
    parser.add_argument('result', nargs='?', type=Path)
    parser.add_argument('--build-only', action='store_true')
    args = parser.parse_args()
    if not args.profile.is_file():
        parser.error('system profile does not exist: ' + str(args.profile))

    name = args.profile.stem
    compiled = ROOT / 'build/system_profiles' / name
    compile_profile(args.profile, compiled)
    build_parameters = load_json(compiled / 'build_parameters.json')
    run_parameters = load_json(compiled / 'run_parameters.json')
    frontend = load_json(compiled / 'frontend_plan.json')
    protocol = load_json(compiled / 'protocol_profile.json')
    header = ROOT / protocol['format_header']
    if not header.is_file():
        raise ValueError('protocol profile header is missing: ' + str(header))

    preserved = {key: os.environ[key] for key in run_parameters if key in os.environ}
    environment = os.environ.copy()
    environment.update(build_parameters)
    environment.update(run_parameters)
    environment.update(preserved)
    environment.update({
        'SS_TOPOLOGY_CONFIG': str(compiled / 'runtime_topology.json'),
        'SS_PROFILE_ARTIFACT_DIR': str(compiled),
        'SS_EXPERIMENT_LABEL': environment.get('SS_EXPERIMENT_LABEL', name),
        'SS_HOST_OPTIONS': shlex.join(frontend['host']['arguments']),
        'SS_CPU_COUNT': str(frontend['cpu']['count']),
    })
    for key in ('SS_TARGET_SIZE_BYTES', 'SS_GPU_LIBRARY', 'SS_GPU_RUNTIME_DIR',
                'SS_GPU_KERNEL', 'SS_NPU_LIBRARY', 'SS_NPU_KERNEL'):
        environment.pop(key, None)
    if frontend['host']['binary']:
        environment['SS_HOST_BINARY'] = frontend['host']['binary']
    if frontend['host']['target_size_bytes'] is not None:
        environment['SS_TARGET_SIZE_BYTES'] = str(frontend['host']['target_size_bytes'])
    if frontend['gpu']['enabled']:
        environment.update({
            'SS_GPU_LIBRARY': frontend['gpu']['library'],
            'SS_GPU_RUNTIME_DIR': frontend['gpu']['runtime_directory'],
            'SS_GPU_KERNEL': frontend['gpu']['kernel'],
        })
    if frontend['npu']['enabled']:
        environment.update({
            'SS_NPU_LIBRARY': frontend['npu']['library'],
            'SS_NPU_KERNEL': frontend['npu']['kernel'],
        })

    active = ROOT / 'build/active_profile_signature.json'
    expected = compiled / 'build_signature.json'
    gem5 = ROOT / 'gem5/build/AXI/gem5.opt'
    frontend_files, frontend_directories = required_frontend_paths(frontend)
    host_not_executable = (frontend['host']['binary'] and
                           Path(frontend['host']['binary']).is_file() and
                           not os.access(frontend['host']['binary'], os.X_OK))
    missing_xpu = frontend['requires_xpu'] and any(
        not path.is_file() for _, path in frontend_files)
    missing_xpu |= frontend['requires_xpu'] and any(
        not path.is_dir() for _, path in frontend_directories)
    missing_classic = (frontend['mode'] == 'cpu' and
                       (any(not path.is_file() for _, path in frontend_files) or
                        host_not_executable))
    rebuild = (not gem5.is_file() or not same_file(expected, active) or
               missing_xpu or missing_classic)
    if rebuild:
        build_script = ROOT / ('env/build_xpu.sh' if frontend['requires_xpu'] else 'env/build.sh')
        print('当前二进制与目标系统构建参数不匹配，自动执行：' + str(build_script), flush=True)
        subprocess.run(['bash', str(build_script)], cwd=ROOT, env=environment, check=True)
    active.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(expected, active)
    shutil.copy2(compiled / 'topology_resolved.json', ROOT / 'build/active_system_profile.json')
    validate_frontend(frontend)
    if args.build_only:
        print('目标系统构建完成：' + str(compiled))
        return

    script = ROOT / ('env/run_xpu_profile.sh' if frontend['requires_xpu'] else
                     'env/run_topology.sh')
    command = ['bash', str(script)]
    if args.result is not None:
        command.append(str(args.result))
    subprocess.run(command, cwd=ROOT, env=environment, check=True)


if __name__ == '__main__':
    main()
