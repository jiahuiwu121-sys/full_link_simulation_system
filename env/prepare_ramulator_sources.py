#!/usr/bin/env python3
"""Prepare hash-pinned native dependencies without nested source repositories."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--check', action='store_true', help='Require existing cache; never download')
args = parser.parse_args()
deps = Path(os.environ['SS_DEPS_ROOT'])
cache = deps/'downloads/ramulator2'; sources = deps/'ramulator2-sources'
cache.mkdir(parents=True, exist_ok=True); sources.mkdir(parents=True, exist_ok=True)
lock = json.loads((Path(__file__).parent/'ramulator-artifacts.lock.json').read_text())
for item in lock['dependencies']:
    archive = cache/f"{item['name']}-{item['version']}.archive"
    if not archive.exists():
        if args.check or os.environ.get('SS_OFFLINE') == '1':
            raise RuntimeError('Ramulator2 缓存缺失，请运行 env/bootstrap.sh：' + str(archive))
        env = dict(os.environ); env.pop('LD_LIBRARY_PATH', None)
        temporary = archive.with_suffix('.download')
        subprocess.run(['curl','-fsSL','--retry','3','--max-time','180',item['url'],'-o',str(temporary)],check=True,env=env)
        temporary.rename(archive)
    if hashlib.file_digest(archive.open('rb'),'sha256').hexdigest() != item['sha256']:
        raise RuntimeError('Ramulator2 archive checksum differs from lock: ' + str(archive))
    target = sources/item['name']; marker = target/'.storagestacked-source.sha256'
    if target.exists():
        if not marker.is_file() or marker.read_text().strip() != item['sha256']:
            raise RuntimeError('Ramulator2 source cache differs from lock: ' + str(target))
        continue
    if args.check:
        raise RuntimeError('Ramulator2 source cache missing; run env/bootstrap.sh: ' + str(target))
    with tempfile.TemporaryDirectory(dir=sources) as temporary:
        temporary = Path(temporary)
        with tarfile.open(archive) as source:
            source.extractall(temporary, filter='data')
        roots = list(temporary.iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            raise RuntimeError('Expected one source archive root: ' + str(archive))
        roots[0].rename(target)
    marker.write_text(item['sha256']+'\n')
    print('Prepared Ramulator2 dependency:',item['name'],item['version'])
