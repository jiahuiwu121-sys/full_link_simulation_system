"""Generate bounded chart data and online report entries from saved evidence."""
from collections import Counter, defaultdict
import csv
from html import escape
import json
from pathlib import Path
import shutil
import tempfile

ASSETS = Path(__file__).with_name('visualization_assets')


def write_json(path, value):
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False, encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        temporary = Path(stream.name)
    temporary.replace(path)


def read_csv(directory, name):
    path = directory / name
    if not path.exists():
        return []
    with path.open() as stream:
        return list(csv.DictReader(stream))


def thin(points, limit=1000):
    if len(points) <= limit:
        return points
    return [points[i * (len(points)-1) // (limit-1)] for i in range(limit)]


def page(directory, title, kind, links):
    for name in ('dashboard.js', 'dashboard.css'):
        shutil.copyfile(ASSETS / name, directory / name)
    navigation = ' · '.join(f'<a href="{escape(url, quote=True)}">{escape(label)}</a>' for url,label in links)
    source = 'run_index_data.json' if kind=='index' and (directory/'metrics.json').exists() else 'visualization_data.json'
    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>
<link rel="stylesheet" href="dashboard.css"></head><body data-kind="{kind}" data-source="{source}">
<header><h1>{escape(title)}</h1><nav>{navigation}</nav></header>
<p id="status" role="status">正在加载报告…</p><main id="content"></main>
<script src="dashboard.js"></script></body></html>'''
    (directory / ('metrics.html' if kind=='case' else 'index.html')).write_text(html, encoding='utf-8')


def write_dashboard(directory, report=None):
    d = Path(directory)
    if report is None:
        report = json.loads((d/'metrics.json').read_text())
    power = defaultdict(list)
    for row in read_csv(d, 'power_intervals.csv'):
        if row['power_enabled'] == 'True':
            power['channel '+row['channel']].append([int(row['end_tick_fs'])/1e6, float(row['average_power_w'])])
    queues = defaultdict(list)
    fields = ('read_queue','write_queue','priority_queue','active_queue','pending_reads')
    for row in read_csv(d, 'queue_occupancy.csv'):
        for field in fields:
            queues['channel '+row['channel']+' / '+field].append([int(row['tick_fs'])/1e6,int(row[field])])
    latency = read_csv(d, 'latency_summary.csv')
    commands = Counter(row['command'] for row in read_csv(d,'ramulator_commands.csv'))
    check = json.loads((d/'metrics_check.json').read_text()) if (d/'metrics_check.json').exists() else None
    diagnostics = json.loads((d/'link_diagnostics.json').read_text()) if (d/'link_diagnostics.json').exists() else None
    value = dict(schema='storagestacked.visualization.v1',overall=report['overall'],check=check,
                 modules={name:dict(status=v['status'],report='metrics/'+name+'.json') for name,v in report['modules'].items()},
                 power={k:thin(v) for k,v in power.items()},queues={k:thin(v) for k,v in queues.items()},
                 latency=latency,commands=dict(commands),diagnostics=diagnostics,
                 axi=report['modules']['axi'],axi2flit=report['modules']['axi2flit'],
                 sampling_note='图表每条曲线最多保留1000点，均匀抽取并保留首尾；可能遗漏瞬时峰值。功率为采样区间平均值，队列为间隔采样；精确积分及全部数据见JSON/CSV。')
    write_json(d/'visualization_data.json',value)
    candidates=[('index.html','本次运行'),('trace_view.html','AXI/UCIe链路'),('ramulator.html','DRAM命令与数据'),
                ('metrics_summary.md','指标说明'),('metrics.json','完整JSON'),('metrics_manifest.json','口径与证据'),
                ('latency_summary.csv','延迟CSV'),('power_windows.csv','窗口功耗CSV'),('power_intervals.csv','功率CSV'),
                ('queue_occupancy.csv','队列CSV'),('axi_wave.vcd','AXI波形')]
    candidates += [('link_diagnostics.json','带宽与延迟口径'),('bandwidth_timeseries.csv','带宽CSV'),
                   ('request_latency_partition.csv','请求延迟分解CSV'),('protocol_latency_samples.csv','协议延迟CSV'),
                   ('dram_data_bursts.csv','DRAM数据占用CSV')]
    page(d, '全链路实验指标 · '+d.name, 'case', [(n,l) for n,l in candidates if (d/n).exists()])


def write_index(directory, results_root=False):
    d=Path(directory)
    entries=[]
    paths=sorted(d.iterdir(),key=lambda p:p.name,reverse=True) if results_root else [d]
    for run in paths:
        if not run.is_dir() or run.is_symlink():
            continue
        candidates=[run] if (run/'metrics.json').exists() else sorted(run.glob('*/metrics.json'))
        for candidate in candidates:
            case=candidate.parent if candidate.is_file() else candidate
            try:
                report=json.loads((case/'metrics.json').read_text())
                overall=report['overall']
                checked=json.loads((case/'metrics_check.json').read_text()).get('passed') if (case/'metrics_check.json').exists() else None
            except (OSError,ValueError,KeyError):
                continue
            link_resources=overall.get('link_resource_summary',{}).get('resources',{}) if overall.get('link_resource_summary') else {}
            entries.append(dict(run=run.name,case=case.name,status=report['status'],checked=checked,
                url=(case/'metrics.html').relative_to(d).as_posix(),
                duration_seconds=overall['duration_seconds'],requests=overall['traffic']['requests'],
                effective_bytes=overall['effective_bytes'],energy_j=overall['dram_energy_j'],
                power_w=overall['dram_average_power_w'],bandwidth_Bps=overall['full_run_effective_bandwidth_Bps'],
                axi_write_utilization=link_resources.get('AXI W',{}).get('utilization'),
                axi_read_utilization=link_resources.get('AXI R',{}).get('utilization'),
                ucie_forward_utilization=link_resources.get('UCIe FWD',{}).get('utilization'),
                ucie_reverse_utilization=link_resources.get('UCIe REV',{}).get('utilization'),
                p95_latency_ns=overall['latency']['p95_fs']/1e6 if overall['latency']['p95_fs'] is not None else None,
                p99_latency_ns=overall['latency']['p99_fs']/1e6 if overall['latency']['p99_fs'] is not None else None))
    write_json(d/'visualization_data.json' if results_root or not (d/'metrics.json').exists() else d/'run_index_data.json',dict(entries=entries))
    links=[] if results_root else [('../index.html','全部运行')]
    if (d/'metrics_batch.md').exists():
        links.append(('metrics_batch.md','批次指标表'))
    page(d,'仿真实验结果索引' if results_root else '运行结果 · '+d.name,'index',links)


def build_index(directory):
    # Batch entry lists child cases; single-case entry lists its own report.
    d=Path(directory)
    write_index(d)
