"""Offline wire audit and self-contained HTML for the new MC bridge only."""
from __future__ import annotations
import csv
import html
import json
from collections import Counter
from pathlib import Path

CASE_NAMES = {
    0: '完整写与读回', 1: '掩码写 / RMW', 2: 'W 先于 AW',
    3: '窄访问与未改字节保护', 4: 'LPR/HPR 与乱序返回',
    5: '4 KiB 请求与输入跨帧', 6: 'LOCK 拒绝 / 未确认写策略拒绝',
    7: 'CRC 错误返回', 8: 'MC 地址错误返回', 9: '未知 pointer 检测',
    10: '混合读写响应', 11: '同 ID 的父事务返回顺序',
    12: '同地址写后读排序', 13: 'pointer 地址错误与并发完成',
    14: '未知 token 检测', 15: '40 bit 地址越界拒绝',
    16: '不可纠正 ECC 错误返回', 100: '输出跨帧与最终片段退休',
}

def parse_frames(path: Path):
    messages=[]
    carry=bytearray()
    wanted=0
    frames=0
    with path.open() as stream:
        for row in csv.DictReader(stream):
            encoded=row['frame_hex_byte249_to_byte0']
            if len(encoded)!=500:
                raise ValueError(f'{path}: FDI frame is not exactly 250 bytes')
            data=bytes.fromhex(encoded)[::-1]
            if any(data[b]&15 for b in (0,2,6,8)):
                raise ValueError(f'{path}: unsupported/reserved header bits')
            starts=((data[0]>>4) | data[1]<<4 | (data[2]>>4)<<12 | data[3]<<16 |
                    (data[6]>>4)<<24 | data[7]<<28 | (data[8]>>4)<<36 | data[9]<<40)
            for g in range(48):
                start=bool(starts & (1<<g))
                part=data[10+5*g:15+5*g]
                if carry:
                    if start:
                        raise ValueError(f'{path}: MsgStart inside continuation')
                elif start:
                    kind=part[0]>>4
                    size={1:3,2:3,3:8,4:8,5:1,6:7}.get(kind)
                    if kind==0 and (part[0]>>1)&7==4:
                        size=2
                    if size is None or (kind in (3,4,6) and part[0]&3):
                        raise ValueError(f'{path}: unsupported message type/width')
                    wanted=size*5
                else:
                    continue
                carry.extend(part)
                if len(carry)==wanted:
                    messages.append(bytes(carry));carry.clear();wanted=0
            frames+=1
    if carry:
        raise ValueError(f'{path}: incomplete message at exit')
    return frames,messages

def audit_case(directory: Path, report: dict):
    expected_fault={9:4,14:16}.get(report['case'],0)
    if report.get('error_code',0)!=expected_fault:
        raise ValueError('unexpected bridge protocol fault mask')
    if not (directory/'fdi_rx.csv').exists():
        return {'status':'unit_test', 'note':'Dedicated TX parser and retirement assertions'}
    rx_count,rx=parse_frames(directory/'fdi_rx.csv')
    tx_count,tx=parse_frames(directory/'fdi_tx.csv')
    if rx_count!=report['rx_frames'] or tx_count!=report['tx_frames']:
        raise ValueError('FDI handshake count differs from offline frame log')
    if len(rx)!=report['rx_messages']:
        raise ValueError('RX message count differs from independent parser')
    requests=sum(m[0]>>4 in (1,2) for m in rx)
    terminals=sum(m[0]>>4==5 or (m[0]>>4==4 and bool(m[4]&8)) for m in tx)
    if requests!=report['completed'] or terminals!=report['completed']:
        raise ValueError('parent request/terminal response conservation failed')
    granules=sum(len(m)//5 for m in tx)
    if granules!=report['packed_granules']:
        raise ValueError('TX packed granules differ from output wire data')
    return {'status':'passed','rx_frames':rx_count,'tx_frames':tx_count,
            'requests':requests,'terminal_responses':terminals,
            'rx_message_types':dict(Counter(str(m[0]>>4) for m in rx)),
            'tx_message_types':dict(Counter(str(m[0]>>4) for m in tx))}

def document(title, body):
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>'
            'body{font:16px system-ui;margin:32px auto;padding:0 20px;max-width:1200px;color:#17324d}'
            'table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}'
            'pre{background:#f4f6fa;padding:16px;overflow:auto}a{color:#1264a3}.note{background:#fff4d8;padding:16px}'
            '</style>'+body+'</html>')

def publish_case(directory: Path, report: dict):
    audit=audit_case(directory,report)
    (directory/'offline_audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    report['offline_audit']=audit['status']
    report['name']=CASE_NAMES.get(report['case'],str(report['case']))
    if 'mc_write_words' in report:
        denominator=report['mc_write_words']*32
        report['mc_write_payload_efficiency']=report['effective_write_bytes']/denominator if denominator else None
        report['mc_write_beat_utilization']=report['mc_write_words']/report['cycles']
        report['mc_read_beat_utilization']=report['mc_read_words']/report['cycles']
    links=' · '.join(f'<a href="{p.name}">{p.name}</a>' for p in sorted(directory.iterdir()) if p.is_file())
    body=(f'<h1>{html.escape(report["name"])}</h1><p class="note">MC HIF 行为模型验证；'
          '并非真实 MC 时序、DRAM 功耗或 PPA 结果。测试时钟周期为 10 ns。</p>'
          f'<p>{links}</p><h2>统计</h2><pre>{html.escape(json.dumps(report,ensure_ascii=False,indent=2))}</pre>')
    (directory/'metrics.html').write_text(document(report['name'],body))

def publish_index(output: Path, result: dict):
    rows=[]
    for report in result['cases']:
        n=report['case'];eff=report.get('mc_write_payload_efficiency')
        rows.append(f'<tr><td><a href="case{n:02d}/metrics.html">{n} · {html.escape(report["name"])}</a></td>'
                    f'<td>{report.get("completed","—")}</td><td>{report.get("commands","—")}</td>'
                    f'<td>{report.get("rmw","—")}</td><td>{"—" if eff is None else format(eff,".2%")}</td>'
                    f'<td>{report["offline_audit"]}</td></tr>')
    body=('<h1>独立 UCIe–MC 桥验证</h1><p class="note">状态：mock_verified。'
          '原 storage_bridge / Ramulator 路径未参与此验证。实际 MC 兼容性尚待接入确认。</p>'
          '<p><a href="summary.json">完整统计</a> · <a href="configuration.json">实际测试配置</a></p>'
          '<table><tr><th>用例</th><th>完成请求</th><th>MC 命令</th><th>RMW</th>'
          '<th>写有效字节 / MC 写槽位字节</th><th>离线校验</th></tr>'+''.join(rows)+'</table>')
    (output/'index.html').write_text(document('独立 MC 桥验证',body))
