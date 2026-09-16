"""Tests for DRAM-derived HBM3/HBM4 DRAMPower memspecs."""

import json

import pytest
from ramulator.power import HBM34PowerModel

import ramulator


def test_hbm3_power_model_follows_resolved_organization_and_timing(tmp_path):
    path = tmp_path / "hbm3.json"
    dram = ramulator.dram.HBM3(
        org_preset="HBM3_16Gb_8hi",
        timing_preset="HBM3_6400Mbps",
        pseudochannel=1,
    )

    model = HBM34PowerModel(dram, path)
    spec = json.loads(path.read_text())

    assert model.nominal_rate_mbps == 6400
    assert model.tick_ps == pytest.approx(312.5)
    assert model.controller_width_bits == 32
    assert model.transaction_bytes == 32
    assert spec["memoryType"] == "HBM3"
    assert spec["memarchitecturespec"]["nbrOfPseudoChannels"] == 1
    assert spec["memarchitecturespec"]["nbrOfSIDs"] == 2
    assert spec["memarchitecturespec"]["width"] == 32
    assert spec["memarchitecturespec"]["burstLength"] == 8
    assert spec["memarchitecturespec"]["dataRate"] == 4
    assert spec["memtimingspec"]["tCK"] == pytest.approx(625e-12)
    assert spec["memtimingspec"]["ticksPerCK"] == 2
    assert spec["memtimingspec"]["RCDRD"] == 31
    assert model.plugin().memspec_path == str(path.resolve())


def test_hbm4_11gbps_power_model_marks_unvalidated_extrapolation(tmp_path):
    path = tmp_path / "hbm4.json"
    dram = ramulator.dram.HBM4(
        org_preset="HBM4_24Gb_8Hi",
        timing_preset="HBM4_11000Mbps",
        pseudochannel=1,
    )

    model = HBM34PowerModel(dram, path)
    spec = model.memspec

    assert model.tick_ps == pytest.approx(182)
    assert spec["memarchitecturespec"]["nbrOfRows"] == 3 << 12
    assert spec["memtimingspec"]["tCK"] == pytest.approx(364e-12)
    assert spec["memtimingspec"]["RCDRD"] == 54
    assert spec["modelMetadata"]["modelKind"] == "out_of_range_extrapolated"
    assert spec["modelMetadata"]["absoluteAccuracyValidated"] is False
    expected_idd4r = 0.0346 + 11000 / 6400 * (0.6304 - 0.0346)
    assert spec["mempowerspec"]["idd4r"] == pytest.approx(expected_idd4r)


def test_existing_path_is_regenerated_when_dram_configuration_changes(tmp_path):
    path = tmp_path / "selected.json"
    first = ramulator.dram.HBM4(
        org_preset="HBM4_32Gb_8Hi",
        timing_preset="HBM4_8000Mbps",
        pseudochannel=1,
    )
    second = ramulator.dram.HBM4(
        org_preset="HBM4_32Gb_8Hi",
        timing_preset="HBM4_8000Mbps",
    )

    HBM34PowerModel(first, path)
    assert json.loads(path.read_text())["memarchitecturespec"]["nbrOfPseudoChannels"] == 1

    HBM34PowerModel(second, path)
    assert json.loads(path.read_text())["memarchitecturespec"]["nbrOfPseudoChannels"] == 2
