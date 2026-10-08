#!/usr/bin/env python3
"""Finalize saved reports, update online indexes and open the current run."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'gem5_axi' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from visualization import build_index, write_dashboard, write_index, write_json


def publish(directory, skip_views=False, open_browser=True, serve=True, port=8000):
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise ValueError('结果目录不存在：' + str(directory))
    cases = [directory] if (directory/'metrics.json').exists() else [p.parent for p in sorted(directory.glob('*/metrics.json'))]
    if not cases:
        raise ValueError('没有可视化所需的metrics.json：' + str(directory))
    build_index(directory)
    for case in cases:
        try:
            report = json.loads((case/'metrics.json').read_text())
            if not skip_views and report['status']=='complete':
                arguments=json.loads((case/'metrics_run.json').read_text()).get('arguments',{})
                with (case/'visualization.log').open('w') as log:
                    def run(script, *flags):
                        subprocess.run([sys.executable,str(SCRIPTS/(script+'.py')),str(case),*flags],stdout=log,stderr=log,check=True)
                    topology = json.loads((case/'topology_summary.json').read_text()) if (case/'topology_summary.json').exists() else {}
                    multi = topology.get('modules', 1) > 1
                    if multi:
                        run('check_topology')
                        for descriptor in topology['links']:
                            link = case / descriptor['result_dir']
                            scripts = ['trace_view']
                            if (link/'ramulator_commands.csv').exists():
                                scripts.append('ramulator_view')
                            for script in scripts:
                                subprocess.run([sys.executable, str(SCRIPTS/(script+'.py')), str(link)],
                                               stdout=log, stderr=log, check=True)
                    elif report['overall']['traffic']['requests'] and (case/'axi_wave.vcd').exists() and (case/'aou_events.csv').exists():
                        run('check', *(['--directed'] if arguments.get('mode')=='tester' else []))
                        run('check_aou', *(['--replay'] if arguments.get('replay') else []))
                        run('inspect_link')
                        run('trace_view')
                    if not multi and (case/'ramulator_commands.csv').exists():
                        run('check_ramulator')
                        run('ramulator_view')
                    if not multi:
                        run('check_metrics')
            write_dashboard(case, report)
            write_json(case/'visualization_status.json',dict(status='generated',metrics_status=report['status'],entry='metrics.html'))
        except Exception as error:
            write_json(case/'visualization_error.json',dict(error=str(error),log='visualization.log'))
            raise
    build_index(directory)
    try:
        directory.relative_to(ROOT/'results')
    except ValueError:
        print('可视化已生成：'+str(directory/'index.html')+'；自动HTTP查看仅支持项目results目录。')
        return
    write_index(ROOT/'results', results_root=True)
    print('可视化已生成：'+str(directory/'index.html'), flush=True)
    if serve:
        command=[sys.executable,str(ROOT/'env/view_results.py'),str(directory/'index.html'),'--port',str(port)]
        if not open_browser:
            command.append('--no-open')
        result=subprocess.run(command)
        if result.returncode:
            # Browser/port failures must not destroy successful simulation evidence.
            write_json(directory/'visualization_server_error.json',dict(exit_code=result.returncode,port=port))
            print('报告文件已生成；HTTP或浏览器打开失败，详见visualization_server_error.json。',file=sys.stderr)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--skip-views',action='store_true',help='Existing batch pipeline already checked and built trace/DRAM views')
    parser.add_argument('--no-open',action='store_true')
    parser.add_argument('--no-serve',action='store_true')
    parser.add_argument('--port',type=int,default=int(os.environ.get('SS_VIEW_PORT','8000')))
    args=parser.parse_args()
    publish(args.directory,args.skip_views,not args.no_open and os.environ.get('SS_VISUALIZATION_OPEN','1')!='0',
            not args.no_serve,args.port)
