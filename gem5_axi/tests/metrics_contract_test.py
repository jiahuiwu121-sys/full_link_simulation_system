#!/usr/bin/env python3
"""Metric definitions: reused AXI IDs, masked bytes, empty latency and failed runs."""
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from collect_metrics import collect, distribution


def write_csv(d,name,records):
    with (d/name).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=records[0]);w.writeheader();w.writerows(records)


class MetricsContract(unittest.TestCase):
    def fixture(self,d):
        (d/'metrics_run.json').write_text(json.dumps(dict(completed=True,end_tick_fs=100,arguments={})))
        (d/'protocol_summary.json').write_text(json.dumps(dict(completed=2,drained=True,axi_data_bits=256,
            period_ticks=2,measured_cycles=50,channels={ch:dict(handshakes=1,stall_cycles=0) for ch in ('AW','W','B','AR','R')})))
        write_csv(d,'transactions.csv',[
            dict(id=1,command='W',address=0,bytes=4,begin_tick=10,accepted_tick=12,axi_done_tick=20,end_resp_tick=22,segments=1,requestor=1,stream=0,substream=0,status=1),
            dict(id=1,command='R',address=4,bytes=4,begin_tick=30,accepted_tick=32,axi_done_tick=46,end_resp_tick=46,segments=1,requestor=2,stream=0,substream=0,status=1)])
        write_csv(d,'request_metadata.csv',[
            dict(uid=1,id=1,begin_tick=10,source_name='cpu.data',enabled_bytes=2,packet_id=101),
            dict(uid=2,id=1,begin_tick=30,source_name='vortex',enabled_bytes=4,packet_id=102)])

    def test_id_reuse_masks_and_source_conservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);self.fixture(d);r=collect(d)
            self.assertEqual(r['status'],'complete')
            self.assertEqual(r['overall']['effective_bytes'],6)
            self.assertEqual(r['overall']['sources']['cpu']['successful_enabled_bytes'],2)
            self.assertEqual(r['overall']['sources']['gpu']['successful_enabled_bytes'],4)
            self.assertEqual(r['overall']['latency']['p99_fs'],16)
            self.assertIsNone(r['overall']['dram_energy_j'])
            self.assertIsNone(r['overall']['system_total_energy_j'])
            self.assertEqual(len(list((d/'metrics').glob('*.json'))),14)

    def test_missing_source_is_invalid_not_successful(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);self.fixture(d);(d/'request_metadata.csv').unlink()
            self.assertEqual(collect(d)['status'],'invalid')

    def test_unfinished_simulation_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);self.fixture(d)
            (d/'metrics_run.json').write_text(json.dumps(dict(completed=False,end_tick_fs=100)))
            self.assertEqual(collect(d)['status'],'incomplete')

    def test_unclosed_host_roi_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);self.fixture(d)
            write_csv(d,'application_markers.csv',[dict(tick_fs=5,marker=1)])
            result=collect(d)
            self.assertEqual(result['status'],'invalid')
            self.assertFalse(result['overall']['metric_consistency_checks']['application_markers_balanced'])

    def test_empty_distribution_has_nulls(self):
        d=distribution([])
        self.assertEqual(d['count'],0)
        self.assertIsNone(d['mean_fs']);self.assertIsNone(d['p99_fs'])


if __name__=='__main__':unittest.main()
