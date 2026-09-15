"""Tests for aggregate user-facing memory performance metrics."""

import pytest
from ramulator.reporting import build_memory_performance_report


def _controller(**overrides):
    values = {
        "num_read_reqs": 0,
        "num_write_reqs": 0,
        "num_read_reqs_served": 0,
        "num_write_reqs_served": 0,
        "num_read_reqs_forwarded": 0,
        "read_latency": 0,
        "read_throughput_MBps": 0.0,
        "write_throughput_MBps": 0.0,
        "total_throughput_MBps": 0.0,
        "row_hits": 0,
        "row_misses": 0,
        "row_conflicts": 0,
        "read_queue_len_avg": 0.0,
        "write_queue_len_avg": 0.0,
    }
    values.update(overrides)
    return values


def test_build_memory_performance_report_uses_weighted_latency_and_aggregate_bandwidth():
    stats = {
        "memory_system": {
            "controller": [
                _controller(
                    num_read_reqs=2,
                    num_read_reqs_served=1,
                    num_read_reqs_forwarded=1,
                    read_latency=30,
                    read_throughput_MBps=100.0,
                    write_throughput_MBps=25.0,
                    total_throughput_MBps=125.0,
                    row_hits=2,
                    read_queue_len_avg=1.0,
                ),
                _controller(
                    num_read_reqs=3,
                    num_write_reqs=1,
                    num_read_reqs_served=3,
                    num_write_reqs_served=1,
                    read_latency=90,
                    read_throughput_MBps=300.0,
                    write_throughput_MBps=75.0,
                    total_throughput_MBps=375.0,
                    row_misses=1,
                    read_queue_len_avg=2.0,
                    write_queue_len_avg=0.5,
                ),
            ]
        },
        "frontend": {
            "cycles_recorded_core_0": 200,
            "memory_access_cycles_recorded_core_0": 100,
        },
    }

    report = build_memory_performance_report(
        stats,
        nominal_rate_mbps=1000,
        total_dq_bits=64,
        tick_ps=250,
    )

    assert report["total_throughput_MBps"] == 500
    assert report["peak_throughput_MBps"] == 8000
    assert report["total_bandwidth_utilization_pct"] == pytest.approx(6.25)
    assert report["avg_read_latency_ticks"] == pytest.approx(24)
    assert report["avg_read_latency_ns"] == pytest.approx(6)
    assert report["row_hit_rate_pct"] == pytest.approx(200 / 3)
    assert report["memory_access_cycle_share_pct"]["0"] == pytest.approx(50)
