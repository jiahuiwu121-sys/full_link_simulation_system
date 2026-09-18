#!/usr/bin/env python3
"""Inventory physical workspace directories; do not follow directory symlinks.

Copy manual roles from the directory guide. Deeper entries inherit the nearest
documented ancestor, explicitly labelled as inference rather than manual review.
"""
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUTS = {HERE/'directory-inventory.csv', HERE/'directory-inventory-summary.json'}


def roles():
    result = {}
    for line in (HERE/'10-directory-guide.md').read_text().splitlines():
        if not line.startswith('| '):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) != 3:
            continue
        match = re.fullmatch(r'`([^`]+/)`', cells[0])
        if match:
            name = match[1].rstrip('/')
            if not (ROOT/name).is_dir():
                raise ValueError('Documented directory does not exist: '+name)
            result[name] = (cells[1], cells[2])
    return result


def category(name):
    if name.startswith(('results/', 'ucie-model/results/')) or name in ('results','ucie-model/results'):
        return 'simulation-results'
    if name.startswith('integrate_doc'):
        return 'local-handoff'
    if '__pycache__' in name.split('/'):
        return 'generated-cache'
    if name.split('/')[0] == '.vscode':
        return 'local-editor'
    if name.split('/')[0] == 'docs':
        return 'documentation'
    if 'build' in name.split('/') or name.startswith('vortex-gpu/vxbuild/') or name == 'vortex-gpu/vxbuild':
        return 'build-output'
    if name.startswith('vortex-gpu/vortex/') or name == 'vortex-gpu/vortex':
        return 'external-gpu-tree'
    return 'main-source-tree'


def main():
    manual = roles()
    entries = {}
    for current, children, files in os.walk(ROOT, followlinks=False):
        children[:] = sorted(n for n in children if n != '.git')
        directory = Path(current)
        if directory == ROOT:
            # Root is not a subdirectory. Its symlink children are still handled.
            name = ''
        else:
            name = directory.relative_to(ROOT).as_posix()
        local_files = [directory/n for n in files if n != '.git' and directory/n not in OUTPUTS]
        if name:
            entries[name] = dict(path=name, entry_type='directory', symlink_target='',
                                 direct_files=len(local_files), recursive_files=len(local_files))
        for child in list(children):
            path = directory/child
            if path.is_symlink():
                relative = path.relative_to(ROOT).as_posix()
                entries[relative] = dict(path=relative,entry_type='directory-symlink',
                                         symlink_target=os.readlink(path),direct_files='',recursive_files='')
                children.remove(child)
    for name in sorted(entries, key=lambda s:len(s.split('/')), reverse=True):
        row = entries[name]
        parent = name.rpartition('/')[0]
        if parent in entries and row['entry_type'] == 'directory':
            entries[parent]['recursive_files'] += row['recursive_files']
    for name, row in entries.items():
        ancestor = name
        while ancestor not in manual and '/' in ancestor:
            ancestor = ancestor.rpartition('/')[0]
        role, scope = manual.get(ancestor, ('未单独说明；按所在上游目录查阅','未人工审阅'))
        row.update(category=category(name), role=role, scope=scope,
                   role_source=ancestor if ancestor in manual else '',
                   explanation='manual' if name in manual else 'inherited-from-ancestor')
        if row['entry_type'] == 'directory-symlink':
            row['category'] = 'external-build-symlink'
        if '__pycache__' in name.split('/'):
            row.update(role='Python自动生成的bytecode缓存',scope='本地产物，不维护源码、不提交',
                       explanation='directory-type-rule',role_source='__pycache__')
    records = [entries[name] for name in sorted(entries)]
    with (HERE/'directory-inventory.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=list(records[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(records)
    summary = dict(scanned_at=datetime.now(timezone.utc).isoformat(),
                   base_commit=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip(),
                   scope='physical workspace, including ignored build/results/handoff; excludes .git metadata; directory symlinks listed without following; inventory outputs excluded from file counts',
                   entries=len(records),physical_directories=sum(r['entry_type']=='directory' for r in records),
                   directory_symlinks=sum(r['entry_type']=='directory-symlink' for r in records),
                   manually_explained_directories=sum(r['explanation']=='manual' for r in records),
                   top_level={name:row['recursive_files'] for name,row in sorted(entries.items()) if '/' not in name},
                   interpretation='directory roles inherited from documented ancestors are not individual manual code reviews')
    (HERE/'directory-inventory-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
