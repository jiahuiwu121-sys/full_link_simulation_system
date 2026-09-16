"""End-to-end checks for the in-process Ramulator/DRAMPower coupling."""

import math
import os
import subprocess
import sys
from pathlib import Path

import pytest
from ramulator.power import HBM34PowerModel, LPDDRPowerModel

import ramulator
from tests.controller_scheduling.harness import ControllerUnderTest

ROOT = Path(__file__).resolve().parents[2]

PROFILES = {
    "HBM3": ROOT / "DRAMPower/examples/hbm34/hbm3_6400_estimated.json",
    "HBM4": ROOT / "DRAMPower/examples/hbm34/hbm4_8000_estimated.json",
    "LPDDR5": ROOT / "DRAMPower/examples/lpddr5/lpddr5_16gb_x16_6400_estimated.json",
    "LPDDR6": ROOT / "DRAMPower/examples/lpddr6/lpddr6_16gb_x12_10667_bl24_estimated.json",
}


def power_plugin(standard):
    return ramulator.controller_plugin.DRAMPower(
        memspec_path=str(PROFILES[standard]), strict_validation=True
    )


def make_dut(standard):
    if standard == "HBM3":
        dram = ramulator.dram.HBM3(org_preset="HBM3_16Gb_8hi", timing_preset="HBM3_6400Mbps")
        dut = ControllerUnderTest.make_hbm34(dram, controller_plugins=[power_plugin(standard)])
        address = dut.addr_vec(
            Channel=0,
            PseudoChannel=0,
            Sid=0,
            BankGroup=0,
            Bank=0,
            Row=1,
            Column=0,
        )
        return dut, address
    if standard == "HBM4":
        dram = ramulator.dram.HBM4(org_preset="HBM4_32Gb_8Hi", timing_preset="HBM4_8000Mbps")
        dut = ControllerUnderTest.make_hbm34(dram, controller_plugins=[power_plugin(standard)])
        address = dut.addr_vec(
            Channel=0,
            PseudoChannel=0,
            Sid=0,
            BankGroup=0,
            Bank=0,
            Row=1,
            Column=0,
        )
        return dut, address
    if standard == "LPDDR5":
        dram = ramulator.dram.LPDDR5(org_preset="LPDDR5_16Gb_x16", timing_preset="LPDDR5_6400")
        dut = ControllerUnderTest.make_lpddr5(dram, controller_plugins=[power_plugin(standard)])
    else:
        dram = ramulator.dram.LPDDR6(
            org_preset="LPDDR6_16Gb_x12", timing_preset="LPDDR6_10667_BL24"
        )
        controller = ramulator.controller.LPDDR6(
            dram=dram,
            scheduler=ramulator.scheduler.FRFCFS(),
            refresh_manager=ramulator.refresh_manager.NoRefresh(),
            row_policy=ramulator.row_policy.Open(),
            addr_mapper=ramulator.addr_mapper.PassThroughAddrMapper(),
            controller_plugins=[power_plugin(standard)],
        )
        dut = ControllerUnderTest(controller)
    return dut, dut.addr_vec(Channel=0, Rank=0, BankGroup=0, Bank=0, Row=1, Column=0)


@pytest.mark.parametrize("standard", ["HBM3", "HBM4", "LPDDR5", "LPDDR6"])
def test_power_backend_tracks_real_issued_commands(standard):
    dut, address = make_dut(standard)
    dut.send_request("Read", address)
    dut.run_until_idle(max_ticks=1000)
    dut.send_request("Write", address)
    dut.run_until_idle(max_ticks=1000)

    plugins = dut.stats()["controller_plugin"]
    if not isinstance(plugins, list):
        plugins = [plugins]
    stats = next(item for item in plugins if item["impl"] == "DRAMPower")

    assert stats["mapped_commands"] >= 2
    assert stats["unsupported_commands"] == 0
    assert stats["duration_seconds"] > 0
    assert stats["core_energy_j"] > 0
    assert stats["read_energy_j"] > 0
    assert stats["write_energy_j"] > 0
    assert stats["total_energy_j"] > 0
    assert stats["total_energy_j"] == pytest.approx(
        sum(
            stats[name]
            for name in (
                "activation_energy_j",
                "precharge_energy_j",
                "read_energy_j",
                "write_energy_j",
                "refresh_energy_j",
                "rfm_energy_j",
                "background_energy_j",
                "interface_energy_j",
            )
        ),
        rel=1e-6,
        abs=1e-18,
    )
    assert math.isfinite(stats["average_power_w"])
    assert stats["average_power_w"] == pytest.approx(
        stats["total_energy_j"] / stats["duration_seconds"]
    )
    if standard.startswith("LPDDR"):
        assert stats["interface_energy_j"] > 0
        assert stats["ignored_interface_commands"] <= 2


def test_strict_validation_rejects_wrong_power_model():
    dram = ramulator.dram.HBM4(org_preset="HBM4_32Gb_8Hi", timing_preset="HBM4_8000Mbps")
    with pytest.raises(RuntimeError, match="memspec mismatch"):
        ControllerUnderTest.make_hbm34(dram, controller_plugins=[power_plugin("HBM3")])


@pytest.mark.parametrize(
    ("dram", "pseudochannels"),
    [
        (
            ramulator.dram.HBM3(
                org_preset="HBM3_16Gb_8hi",
                timing_preset="HBM3_6400Mbps",
                pseudochannel=1,
            ),
            1,
        ),
        (
            ramulator.dram.HBM4(
                org_preset="HBM4_24Gb_8Hi",
                timing_preset="HBM4_11000Mbps",
                pseudochannel=1,
            ),
            1,
        ),
    ],
)
def test_generated_hbm_power_model_passes_strict_validation(tmp_path, dram, pseudochannels):
    model = HBM34PowerModel(dram, tmp_path / f"{type(dram).name}.json")
    dut = ControllerUnderTest.make_hbm34(
        dram, controller_plugins=[model.plugin(strict_validation=True)]
    )
    address = dut.addr_vec(
        Channel=0,
        PseudoChannel=0,
        Sid=0,
        BankGroup=0,
        Bank=0,
        Row=1,
        Column=0,
    )

    dut.send_request("Read", address)
    dut.run_until_idle(max_ticks=2000)
    stats = dut.stats()["controller_plugin"]
    if isinstance(stats, list):
        stats = next(item for item in stats if item["impl"] == "DRAMPower")

    assert model.org["pseudochannel"] == pseudochannels
    assert stats["mapped_commands"] >= 2
    assert stats["total_energy_j"] > 0


def test_lpddr6_long_burst_is_rejected_instead_of_undercounted():
    dut, address = make_dut("LPDDR6")
    dut.priority_send("RD_L", address)
    with pytest.raises(RuntimeError, match="long-burst command"):
        dut.run_until_idle(max_ticks=1000)


@pytest.mark.parametrize("standard", ["HBM3", "HBM4"])
def test_hbm_refresh_and_rfm_energy_are_accounted(standard):
    dut, _ = make_dut(standard)
    all_banks = dut.addr_vec(Channel=0)

    dut.priority_send("REFab", all_banks)
    dut.run_until_idle(max_ticks=2000)
    dut.priority_send("RFMab", all_banks)
    dut.run_until_idle(max_ticks=2000)

    stats = dut.stats()["controller_plugin"]
    if isinstance(stats, list):
        stats = next(item for item in stats if item["impl"] == "DRAMPower")
    assert stats["refresh_energy_j"] > 0
    assert stats["rfm_energy_j"] > 0
    assert stats["mapped_commands"] == 2


def test_multichannel_power_is_aggregated(tmp_path):
    trace = tmp_path / "power.trace"
    trace.write_text("".join(f"10 {32 * i}\n" for i in range(16)))

    def controller():
        return ramulator.controller.HBM34(
            dram=ramulator.dram.HBM4(org_preset="HBM4_32Gb_8Hi", timing_preset="HBM4_8000Mbps"),
            scheduler=ramulator.scheduler.FRFCFS(),
            refresh_manager=ramulator.refresh_manager.NoRefresh(),
            row_policy=ramulator.row_policy.Open(),
            addr_mapper=ramulator.addr_mapper.RoBaRaCoCh(),
            controller_plugins=[power_plugin("HBM4")],
        )

    frontend = ramulator.frontend.SimpleO3(
        clock_ratio=8,
        traces=[str(trace)],
        num_expected_insts=256,
        llc_linesize=32,
        translation=ramulator.translation.NoTranslation(max_addr=2**31),
    )
    memory = ramulator.memory_system.GenericDRAM(
        clock_ratio=1,
        controllers=[controller(), controller()],
        channel_mapper=ramulator.channel_mapper.CacheLineInterleave(),
    )
    simulation = ramulator.Simulation(frontend, memory)
    simulation.run()
    simulation.finalize()
    stats = simulation.stats["memory_system"]

    per_channel = sum(
        channel["controller_plugin"]["total_energy_j"] for channel in stats["controller"]
    )
    assert stats["powered_channels"] == 2
    assert stats["dram_total_energy_j"] > 0
    assert stats["dram_total_energy_j"] == pytest.approx(per_channel)


@pytest.mark.parametrize("standard", ["LPDDR5", "LPDDR6"])
@pytest.mark.parametrize("wck_mode", ["need_sync", "always_on"])
@pytest.mark.parametrize("row_cap", [None, 1])
def test_generated_lpddr_model_runs_with_native_controller_and_policies(
    tmp_path,
    standard,
    wck_mode,
    row_cap,
):
    width = 16 if standard == "LPDDR5" else 12
    timing = "LPDDR5_6400" if standard == "LPDDR5" else "LPDDR6_10667_BL24"
    dram = getattr(ramulator.dram, standard)(
        org_preset=f"{standard}_16Gb_x{width}",
        timing_preset=timing,
    )
    model = LPDDRPowerModel(
        dram,
        tmp_path / "generated.json",
        reference_memspec_path=PROFILES[standard],
        wck_sync_mode=wck_mode,
    )
    controller = getattr(ramulator.controller, standard)(
        dram=dram,
        scheduler=ramulator.scheduler.FRFCFSRowHit(),
        refresh_manager=ramulator.refresh_manager.NoRefresh(),
        row_policy=(
            ramulator.row_policy.Open()
            if row_cap is None
            else ramulator.row_policy.ClosedCAP(cap=row_cap)
        ),
        addr_mapper=ramulator.addr_mapper.PassThroughAddrMapper(),
        wck_sync_mode=wck_mode,
        controller_plugins=[model.plugin()],
    )
    dut = ControllerUnderTest(controller)
    address = dut.addr_vec(Channel=0, Rank=0, BankGroup=0, Bank=0, Row=1, Column=0)
    dut.send_request("Read", address)
    dut.run_until_idle(max_ticks=2000)
    dut.send_request("Write", address)
    dut.run_until_idle(max_ticks=2000)
    dut.priority_send("REFab", dut.addr_vec(Channel=0, Rank=0))
    dut.run_until_idle(max_ticks=2000)
    stats = dut.stats()
    assert stats["num_write_latency_samples"] == 1
    power = stats["controller_plugin"]
    if isinstance(power, list):
        power = next(item for item in power if item["impl"] == "DRAMPower")
    assert math.isfinite(power["total_energy_j"])
    assert power["read_energy_j"] > 0
    assert power["write_energy_j"] > 0
    assert power["refresh_energy_j"] > 0
    assert power["unsupported_commands"] == 0
    assert power["average_power_w"] == pytest.approx(
        power["total_energy_j"] / power["duration_seconds"]
    )


@pytest.mark.parametrize("standard", ["LPDDR5", "LPDDR6"])
def test_changing_only_lpddr_trace_changes_power_without_manual_memspec_edit(tmp_path, standard):
    from ramulator.reporting import build_memory_performance_report

    width = 16 if standard == "LPDDR5" else 12
    timing = "LPDDR5_6400" if standard == "LPDDR5" else "LPDDR6_10667_BL24"
    reports = []
    specs = []
    for with_writes in (False, True):
        trace = tmp_path / "selected.trace"
        trace.write_text(
            "".join(
                f"10 {32 * i}" + (f" {32 * i}" if with_writes else "") + "\n" for i in range(64)
            )
        )
        dram = getattr(ramulator.dram, standard)(
            org_preset=f"{standard}_16Gb_x{width}",
            timing_preset=timing,
        )
        model = LPDDRPowerModel(
            dram,
            tmp_path / "generated.json",
            reference_memspec_path=PROFILES[standard],
        )
        specs.append(model.memspec_path.read_text())
        controller = getattr(ramulator.controller, standard)(
            dram=dram,
            scheduler=ramulator.scheduler.FRFCFS(),
            refresh_manager=ramulator.refresh_manager.AllBank(),
            row_policy=ramulator.row_policy.Open(),
            addr_mapper=ramulator.addr_mapper.RoBaRaCoCh(),
            controller_plugins=[model.plugin()],
        )
        simulation = ramulator.Simulation(
            ramulator.frontend.SimpleO3(
                clock_ratio=8,
                traces=[str(trace)],
                num_expected_insts=4096,
                llc_linesize=32,
                # Run long enough for dirty evictions to reach write-drain watermarks.
                llc_capacity_per_core="1KB",
                translation=ramulator.translation.NoTranslation(
                    max_addr=model.controller_capacity_bytes
                ),
            ),
            ramulator.memory_system.GenericDRAM(
                clock_ratio=1,
                controllers=[controller],
                channel_mapper=ramulator.channel_mapper.CacheLineInterleave(),
            ),
        )
        simulation.run()
        simulation.finalize()
        reports.append(
            build_memory_performance_report(
                simulation.stats,
                nominal_rate_mbps=model.nominal_rate_mbps,
                total_dq_bits=width,
                tick_ps=model.tick_ps,
                payload_fraction=model.payload_fraction,
            )
        )
    assert specs[0] == specs[1]  # Device parameters are independent of trace R/W ratio.
    assert reports[0]["power_categories"]["write_energy_j"] == 0
    assert reports[1]["power_categories"]["write_energy_j"] > 0
    assert reports[1]["write_latency_available"]
    assert all(report["power_energy_sum_matches_total"] for report in reports)


@pytest.mark.parametrize("standard", ["LPDDR5", "LPDDR6"])
def test_lpddr_example_runs_outside_repository_and_prints_final_power(tmp_path, standard):
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "python"))
    result = subprocess.run(
        [sys.executable, str(ROOT / f"examples/{standard}_example_config.py")],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Controller/scheduler:          {standard}" in result.stdout
    assert "Average write latency:" in result.stdout
    assert "Energy sum check:               PASS" in result.stdout
    assert "Unsupported DRAM commands:      0" in result.stdout
    assert "Absolute accuracy validated:    False" in result.stdout
    assert "nan J" not in result.stdout
    if standard == "LPDDR6":
        assert "Full-interface payload peak:   28.445 GB/s" in result.stdout
