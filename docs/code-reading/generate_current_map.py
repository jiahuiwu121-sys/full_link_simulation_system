#!/usr/bin/env python3
"""Index current files; copy reviewed roles/interfaces from the walkthrough.

Other files receive static classification only, without invented call edges.
The old source-index remains a separately identified initial-scan artifact.
"""
import csv
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUTS = {HERE/'current-file-map.csv', HERE/'current-file-map-summary.json'}
SOURCE_SUFFIXES = {'.c','.cc','.cpp','.cxx','.h','.hh','.hpp','.py','.sh',
                   '.scala','.sv','.v','.S','.s','.isa','.bzl','.js','.ts',
                   '.rs','.go','.java','.proto','.inc','.ll','.cl'}


def git(repo, *args):
    return subprocess.check_output(['git','-C',str(repo),*args])


def discover(repo, include_untracked=False):
    entries = []
    for record in git(repo,'ls-files','--stage','-z').split(b'\0'):
        if not record:
            continue
        info, name = record.split(b'\t',1)
        mode, blob, stage = info.decode().split()
        if stage != '0':
            raise RuntimeError('Resolve Git conflicts before indexing')
        path = repo/name.decode()
        if path in OUTPUTS:
            continue
        status = 'main-indexed' if repo == ROOT else 'external-indexed'
        entries.append((path,mode,blob,status))
        if mode == '160000' and (path/'.git').exists():
            entries.extend(discover(path))
    if include_untracked:
        for name in git(repo,'ls-files','--others','--exclude-standard','-z').split(b'\0'):
            if name:
                path = repo/name.decode()
                if path not in OUTPUTS and path.is_file():
                    entries.append((path,'100644','','main-untracked'))
    return entries


def reviewed_roles():
    reviewed = {}
    for line in (HERE/'09-current-system-walkthrough.md').read_text().splitlines():
        if not line.startswith('| '):
            continue
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if len(cells) not in (2,4):
            continue
        for target in re.findall(r'\]\(([^)]+)\)',cells[0]):
            path = (HERE/target).resolve()
            if path.is_file() and path.is_relative_to(ROOT):
                reviewed[path.relative_to(ROOT).as_posix()] = (
                    cells[1],cells[2] if len(cells)==4 else '',
                    cells[3] if len(cells)==4 else '')
    return reviewed


def main():
    with (HERE/'source-index.csv').open(encoding='utf-8-sig',newline='') as stream:
        previous = {row['path']:row for row in csv.DictReader(stream)}
    reviewed = reviewed_roles()
    records = []
    for path, mode, blob, status in sorted(discover(ROOT,True),key=lambda r:str(r[0])):
        name = path.relative_to(ROOT).as_posix()
        old = previous.get(name,{})
        module = name.split('/')[0] if '/' in name else '(root)'
        default_role = old.get('role_hint',f'{module} 的源码、配置或文档；按所在目录分类')
        role, upstream, downstream = reviewed.get(name,(default_role,'',''))
        if mode == '160000':
            kind, lines, size = 'submodule',0,0
            status = 'initialized-submodule' if (path/'.git').exists() else 'uninitialized-submodule'
            role = '锁定的外部子模块；内部已跟踪文件在初始化后递归列出'
        elif path.is_file():
            content = path.read_bytes()
            size = len(content)
            binary = b'\0' in content[:8192]
            kind = old.get('kind') or (
                'documentation' if path.suffix in ('.md','.rst','.html') else
                'source' if path.suffix in SOURCE_SUFFIXES else
                'build' if path.name in ('SConstruct','SConscript','Makefile','BUILD','BUILD.bazel','CMakeLists.txt') else
                'binary/data' if binary else 'config/text')
            lines = 0 if binary else content.count(b'\n') + int(bool(content) and not content.endswith(b'\n'))
        else:
            kind,lines,size,status = old.get('kind','missing'),0,0,'missing-working-file'
        records.append(dict(path=name,module=module,kind=kind,lines=lines,bytes=size,
                            role_hint=role,upstream=upstream,downstream=downstream,
                            reviewed_role=name in reviewed,reviewed_interface=bool(upstream and downstream),
                            status=status,index_blob=blob))
    with (HERE/'current-file-map.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=list(records[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(records)
    summary = dict(date=datetime.now(timezone.utc).date().isoformat(),
                   base_commit=git(ROOT,'rev-parse','HEAD').decode().strip(),
                   scope='current working files: tracked main repo, nonignored main untracked files, initialized recursive external submodules; generated current-map outputs excluded',
                   total_entries=len(records),module_counts=dict(sorted(Counter(r['module'] for r in records).items())),
                   kind_counts=dict(sorted(Counter(r['kind'] for r in records).items())),
                   reviewed_role_files=sum(r['reviewed_role'] for r in records),
                   reviewed_interface_files=sum(r['reviewed_interface'] for r in records),
                   extraction='manual role/interface table for linked core files; other rows static directory hints with no inferred upstream/downstream; index_blob describes Git index, not working-file hash')
    (HERE/'current-file-map-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
