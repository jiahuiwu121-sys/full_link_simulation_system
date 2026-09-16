"""Tests for aggregate user-facing memory performance metrics."""

import pytest
from ramulator.reporting import build_memory_performance_report, print_memory_performance_report


def _controller(**overrides):
    values = {
        "num_read_reqs": 0,
        "num_write_reqs": 0,
        "num_read_reqs_served": 0,
        "num_write_reqs_served": 0,
        "num_read_reqs_forwarded": 0,
        "read_latency": 0,
        "write_latency": 0,
        "num_write_latency_samples": 0,
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
                    write_latency=40,
                    num_write_latency_samples=1,
                    read_throughput_MBps=300.0,
                    write_throughput_MBps=75.0,
                    total_throughput_MBps=375.0,
                    row_misses=1,
                    read_queue_len_avg=2.0,
                    write_queue_len_avg=0.5,
                ),
                _controller(),
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
        total_dq_bits=96,
        tick_ps=250,
        frontend_ticks_per_memory_tick=2,
    )

    assert report["total_throughput_MBps"] == 500
    assert report["peak_throughput_MBps"] == 8000
    assert report["full_peak_throughput_MBps"] == 12000
    assert report["active_peak_throughput_MBps"] == 8000
    assert report["active_controllers"] == 2
    assert report["active_dq_bits"] == 64
    assert report["total_bandwidth_utilization_pct"] == pytest.approx(6.25)
    assert report["avg_read_latency_ticks"] == pytest.approx(24)
    assert report["avg_read_latency_ns"] == pytest.approx(6)
    assert report["write_latency_available"] is True
    assert report["write_latency_samples"] == 1
    assert report["avg_write_latency_ticks"] == pytest.approx(40)
    assert report["avg_write_latency_ns"] == pytest.approx(10)
    assert report["row_hit_rate_pct"] == pytest.approx(200 / 3)
    assert report["memory_access_cycle_share_pct"]["0"] == pytest.approx(100)
    assert report["power_available"] is False


def test_build_memory_performance_report_aggregates_drampower_breakdown():
    first = _controller()
    first["controller_plugin"] = {
        "impl": "DRAMPower",
        "activation_energy_j": 1.0,
        "read_energy_j": 2.0,
        "mapped_commands": 5,
        "unsupported_commands": 0,
    }
    second = _controller()
    second["controller_plugin"] = [
        {
            "impl": "DRAMPower",
            "activation_energy_j": 3.0,
            "read_energy_j": 4.0,
            "mapped_commands": 7,
            "unsupported_commands": 1,
        }
    ]
    stats = {
        "memory_system": {
            "controller": [first, second],
            "powered_channels": 2,
            "dram_power_duration_seconds": 1e-6,
            "dram_core_energy_j": 10e-6,
            "dram_interface_energy_j": 2e-6,
            "dram_total_energy_j": 12e-6,
            "dram_average_power_w": 12.0,
        }
    }

    report = build_memory_performance_report(
        stats, nominal_rate_mbps=8000, total_dq_bits=128, tick_ps=250
    )

    assert report["power_available"] is True
    assert report["dram_total_energy_j"] == pytest.approx(12e-6)
    assert report["power_categories"]["activation_energy_j"] == pytest.approx(4)
    assert report["power_categories"]["read_energy_j"] == pytest.approx(6)
    assert report["mapped_power_commands"] == 12
    assert report["unsupported_power_commands"] == 1


@pytest.mark.parametrize("total_energy, expected_check", [(10.0, "PASS"), (11.0, "WARNING")])
def test_power_output_includes_all_components_and_checks_energy_sum(
    capsys, total_energy, expected_check
):
    components = {
        "activation_energy_j": 1.0,
        "precharge_energy_j": 1.0,
        "read_energy_j": 1.0,
        "write_energy_j": 1.0,
        "refresh_energy_j": 1.0,
        "rfm_energy_j": 1.0,
        "background_energy_j": 1.0,
    }
    stats = {
        "memory_system": {
            "controller": _controller(
                controller_plugin={
                    "impl": "DRAMPower",
                    **components,
                    "ignored_interface_commands": 2,
                }
            ),
            "powered_channels": 1,
            "dram_power_duration_seconds": 2.0,
            "dram_core_energy_j": 7.0,
            "dram_interface_energy_j": 3.0,
            "dram_total_energy_j": total_energy,
            "dram_average_power_w": total_energy / 2,
        }
    }
    report = print_memory_performance_report(
        stats,
        nominal_rate_mbps=11000,
        total_dq_bits=32,
        tick_ps=250,
        power_model_metadata={
            "modelKind": "out_of_range_extrapolated",
            "absoluteAccuracyValidated": False,
        },
    )
    output = capsys.readouterr().out
    for symbol in (
        "E_ACT",
        "E_PRE",
        "E_RD",
        "E_WR",
        "E_REF",
        "E_RFM",
        "E_background",
        "E_interface",
        "E_total",
        "P_avg",
        "T_simulation",
    ):
        assert symbol in output
    assert "out_of_range_extrapolated" in output
    assert "Absolute accuracy validated:    False" in output
    assert f"Energy sum check:               {expected_check}" in output
    assert report["power_energy_sum_j"] == pytest.approx(10.0)
    assert report["power_energy_sum_matches_total"] is (expected_check == "PASS")
    assert report["ignored_interface_commands"] == 2


def test_power_output_without_backend_is_unavailable_not_zero(capsys):
    print_memory_performance_report(
        {"memory_system": {"controller": _controller()}},
        nominal_rate_mbps=6400,
        total_dq_bits=32,
        tick_ps=312.5,
    )
    output = capsys.readouterr().out
    assert "=== DRAMPower results ===" in output
    assert "N/A (no DRAMPower backend attached)" in output
    assert "Interface energy (E_interface):   N/A" in output
    assert "Total DRAM energy (E_total):      N/A" in output


def test_lpddr6_utilization_uses_payload_peak_not_metadata_bits():
    report = build_memory_performance_report(
        {
            "memory_system": {
                "controller": [
                    _controller(
                        num_read_reqs=1,
                        read_throughput_MBps=8000,
                        total_throughput_MBps=8000,
                    ),
                    _controller(),
                ]
            }
        },
        nominal_rate_mbps=10667,
        total_dq_bits=24,
        tick_ps=375,
        payload_fraction=8 / 9,
    )
    assert report["full_wire_peak_throughput_MBps"] == pytest.approx(32001)
    assert report["active_peak_throughput_MBps"] == pytest.approx(16000.5 * 8 / 9)
    assert report["total_bandwidth_utilization_pct"] == pytest.approx(
        8000 / (16000.5 * 8 / 9) * 100
    )
