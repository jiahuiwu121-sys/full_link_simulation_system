#!/usr/bin/env python3
"""Serve simulation reports and open through VS Code's remote browser bridge."""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, build_opener


def main():
    root = Path(__file__).resolve().parents[1]
    results = root / 'results'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', nargs='?', default=str(results))
    parser.add_argument('--port', type=int, default=int(os.environ.get('SS_VIEW_PORT', '8000')))
    parser.add_argument('--no-open', action='store_true', help='Start/reuse HTTP service without opening a browser')
    args = parser.parse_args()
    path = Path(args.report).resolve()
    if path.is_dir():
        if (path / 'index.html').is_file():
            path /= 'index.html'
        elif (path / 'metrics.html').is_file():
            path /= 'metrics.html'
    if not path.exists():
        parser.error('报告路径不存在：' + str(path))
    try:
        relative = path.relative_to(results.resolve())
    except ValueError:
        parser.error('报告必须位于项目results目录内')
    if not 1 <= args.port <= 65535:
        parser.error('端口须在1至65535之间')
    url = f'http://127.0.0.1:{args.port}/' + quote(relative.as_posix())
    opener = build_opener(ProxyHandler({}))

    def available():
        try:
            with opener.open(url, timeout=2) as response:
                return response.status == 200
        except HTTPError as error:
            parser.error(f'端口已有服务，但报告返回HTTP {error.code}；请用--port指定其他端口')
        except (URLError, TimeoutError):
            return False

    if not available():
        logs = root / 'build' / 'results-view'
        logs.mkdir(parents=True, exist_ok=True)
        logfile = logs / f'http-{args.port}.log'
        with logfile.open('a') as output:
            process = subprocess.Popen(
                [sys.executable, '-u', '-m', 'http.server', str(args.port),
                 '--bind', '127.0.0.1', '--directory', str(results)],
                stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                start_new_session=True)
        for _ in range(30):
            if available():
                break
            if process.poll() is not None:
                parser.error('HTTP服务启动失败，详见：' + str(logfile))
            time.sleep(0.1)
        else:
            parser.error('HTTP服务未就绪，详见：' + str(logfile))
    print('报告服务已就绪：' + url, flush=True)
    browser = os.environ.get('BROWSER')
    if args.no_open:
        return
    if browser:
        subprocess.run(shlex.split(browser) + [url], check=True)
        print('已通过当前环境的浏览器入口打开；VS Code容器环境会处理端口转发。')
    else:
        print('请用浏览器打开上述地址；远程环境需先转发对应端口。')


if __name__ == '__main__':
    main()
