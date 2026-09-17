#!/usr/bin/env python3
"""Build a small summary and paged views of actual DRAM/service evidence."""
import csv
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
data = root/'ramulator_data'; data.mkdir(exist_ok=True)
manifest = {}
for name,file in [('commands','ramulator_commands.csv'),('bridge','ramulator_bridge.csv'),('image','ramulator_final_image.csv')]:
    count = 0; pages = []
    with (root/file).open() as stream:
        reader = csv.DictReader(stream); chunk = []
        fields = reader.fieldnames
        for row in reader:
            chunk.append(row); count += 1
            if len(chunk) == 500:
                path = f'{name}-{len(pages):04d}.json'
                (data/path).write_text(json.dumps(chunk)); pages.append(path); chunk = []
        if chunk:
            path = f'{name}-{len(pages):04d}.json'
            (data/path).write_text(json.dumps(chunk)); pages.append(path)
    manifest[name] = {'count':count,'fields':fields,'pages':pages}
summary = {name:json.loads((root/file).read_text()) for name,file in [
    ('backend','ramulator_backend_summary.json'),('native','ramulator_native_summary.json'),
    ('power','dram_power.json'),('check','ramulator_check.json')]}
(data/'manifest.json').write_text(json.dumps({'tables':manifest,'summary':summary}))
(root/'ramulator.html').write_text('''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>Ramulator2 在线后端</title><style>
body{font:15px system-ui;margin:24px;color:#213047;background:#f7f9fc}pre{white-space:pre-wrap;background:white;padding:16px}
table{border-collapse:collapse;background:white}td,th{border:1px solid #dce2ed;padding:6px;max-width:360px;word-break:break-all}
button,select{padding:8px;margin:8px 4px}th{position:sticky;top:0;background:#eaf0f9}</style>
<h1>Ramulator2 在线后端</h1><p>实际 DRAM 命令、数据服务与内存结果。功耗为 DRAM 估算，范围和参数见报告。</p>
<a href="trace_view.html">AXI / UCIe 链路视图</a>
<pre id="summary"></pre><select id="kind"><option value="commands">DRAM 命令</option><option value="bridge">请求与数据服务</option><option value="image">最终数据</option></select>
<button id="prev">上一页</button><button id="next">下一页</button><span id="status"></span><div id="table"></div>
<script>
let manifest,page=0,sequence=0;
const el=id=>document.getElementById(id);
async function render(){const request=++sequence,kind=el('kind').value,t=manifest.tables[kind];
page=Math.max(0,Math.min(page,t.pages.length-1));const current=page;
const rows=t.pages.length?await (await fetch('ramulator_data/'+t.pages[current])).json():[];
if(request!==sequence)return;
el('status').textContent=`${t.count} 条 · ${current+1}/${Math.max(1,t.pages.length)} 页`;
const table=document.createElement('table'),head=table.createTHead().insertRow();
for(const field of t.fields){const cell=document.createElement('th');cell.textContent=field;head.appendChild(cell);}
const body=table.createTBody();for(const row of rows){const tr=body.insertRow();for(const field of t.fields)tr.insertCell().textContent=row[field];}
el('table').replaceChildren(table);el('prev').disabled=current===0;el('next').disabled=current+1>=t.pages.length;}
el('kind').onchange=()=>{page=0;render();};el('prev').onclick=()=>{--page;render();};el('next').onclick=()=>{++page;render();};
fetch('ramulator_data/manifest.json').then(r=>r.json()).then(m=>{manifest=m;el('summary').textContent=JSON.stringify(m.summary,null,2);render();})
.catch(e=>{el('status').textContent='加载失败，请通过本机 HTTP 服务打开：'+e.message;});
</script></html>''')
print('Generated:',root/'ramulator.html')
