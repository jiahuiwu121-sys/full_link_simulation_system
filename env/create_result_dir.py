#!/usr/bin/env python3
"""Reserve a fresh result directory without replacing previous experiments."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('destination', nargs='?', type=Path)
    parser.add_argument('--label', default='baseline')
    args = parser.parse_args()
    if args.destination is not None:
        destination = args.destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            destination.mkdir()
        except FileExistsError:
            parser.error('结果目录已存在：' + str(destination))
    else:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.label):
            parser.error('实验名只能包含英文字母、数字、连字符和下划线，且须以字母或数字开头')
        args.root.mkdir(parents=True, exist_ok=True)
        prefix = datetime.now(timezone.utc).strftime('%Y%m%d') + '-' + args.label + '-r'
        indices = [int(p.name[len(prefix):]) for p in args.root.iterdir()
                   if p.name.startswith(prefix) and p.name[len(prefix):].isdigit()]
        index = max(indices, default=0) + 1
        while True:
            destination = args.root / (prefix + f'{index:02d}')
            try:
                destination.mkdir()
                break
            except FileExistsError:
                index += 1
    print(destination.resolve())


if __name__ == '__main__':
    main()
