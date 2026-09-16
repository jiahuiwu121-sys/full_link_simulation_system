"""Organization/timing synchronization for generated LPDDR power specs."""

import json
from pathlib import Path

import pytest
from ramulator.power import LPDDRPowerModel

import ramulator

ROOT = Path(__file__).resolve().parents[2]


def make_model(tmp_path, standard, **overrides):
    dram_cls = getattr(ramulator.dram, standard)
    timing = "LPDDR5_6400" if standard == "LPDDR5" else "LPDDR6_10667_BL24"
    width = 16 if standard == "LPDDR5" else 12
    reference = (
        "lpddr5_16gb_x16_6400_estimated.json"
        if standard == "LPDDR5"
        else "lpddr6_16gb_x12_10667_bl24_estimated.json"
    )
    dram = dram_cls(org_preset=f"{standard}_16Gb_x{width}", timing_preset=timing, **overrides)
    return LPDDRPowerModel(
        dram,
        tmp_path / f"{standard}.json",
        reference_memspec_path=ROOT / "DRAMPower/examples" / standard.lower() / reference,
    )


@pytest.mark.parametrize("standard", ["LPDDR5", "LPDDR6"])
def test_generated_lpddr_geometry_timing_and_payload(tmp_path, standard):
    model = make_model(tmp_path, standard)
    spec = json.loads(model.memspec_path.read_text())
    assert spec["memoryType"] == standard
    assert spec["memarchitecturespec"]["nbrOfRanks"] == 1
    assert spec["memarchitecturespec"]["nbrOfBanks"] == 16
    assert model.controller_capacity_bytes == 2 * 1024**3
    assert model.transaction_bytes == 32
    assert model.payload_fraction == pytest.approx(1 if standard == "LPDDR5" else 8 / 9)
    assert spec["memtimingspec"]["tCK"] == pytest.approx(model.tick_ps * 1e-12)
    assert spec["memtimingspec"]["RFCab"] == model.timing["nRFC"]
    assert spec["modelMetadata"]["absoluteAccuracyValidated"] is False
    assert model.plugin().memspec_path == str(model.memspec_path)
    # Regeneration must not mutate the static reference fixture.
    assert model.reference["memarchitecturespec"]["nbrOfRanks"] == 1


@pytest.mark.parametrize("standard", ["LPDDR5", "LPDDR6"])
def test_lpddr_regeneration_follows_rank_and_latency_override(tmp_path, standard):
    first = make_model(tmp_path, standard)
    original = first.memspec_path.read_text()
    reference_before = first.reference_memspec_path.read_text()
    latency_name = "nCL" if standard == "LPDDR5" else "nRL"
    changed = make_model(tmp_path, standard, rank=2, **{latency_name: 70})
    assert changed.memspec_path.read_text() != original
    assert changed.memspec["memarchitecturespec"]["nbrOfRanks"] == 2
    assert changed.memspec["memtimingspec"]["RL"] == 70
    assert changed.controller_capacity_bytes == 4 * 1024**3
    assert changed.reference_memspec_path.read_text() == reference_before


def test_lpddr5_density_preset_updates_rows_and_refresh(tmp_path):
    model = make_model(tmp_path, "LPDDR5")
    smaller = LPDDRPowerModel(
        ramulator.dram.LPDDR5(org_preset="LPDDR5_8Gb_x16", timing_preset="LPDDR5_6400"),
        model.memspec_path,
        reference_memspec_path=model.reference_memspec_path,
    )
    assert smaller.controller_capacity_bytes == 1024**3
    assert smaller.memspec["memarchitecturespec"]["nbrOfRows"] == 32768
    assert smaller.memspec["memtimingspec"]["RFCab"] == smaller.timing["nRFC"]
    assert smaller.timing["nRFC"] < model.timing["nRFC"]


@pytest.mark.parametrize("standard", ["LPDDR5", "LPDDR6"])
def test_wck_and_electrical_overrides_are_persistent_inputs(tmp_path, standard):
    first = make_model(tmp_path, standard)
    model = LPDDRPowerModel(
        first.dram,
        first.memspec_path,
        reference_memspec_path=first.reference_memspec_path,
        wck_sync_mode="always_on",
        power_overrides={"idd4r1": 0.2},
        impedance_overrides={"rdq_dyn_E": 2e-12},
    )
    assert model.memspec["memarchitecturespec"]["WCKalwaysOn"] is True
    assert model.memspec["mempowerspec"]["idd4r1"] == 0.2
    assert model.memspec["memimpedancespec"]["rdq_dyn_E"] == 2e-12


def test_lpddr_rejects_rate_only_override(tmp_path):
    with pytest.raises(ValueError, match="inconsistent"):
        make_model(tmp_path, "LPDDR5", rate=8000)


def test_lpddr_rejects_overwriting_reference(tmp_path):
    model = make_model(tmp_path, "LPDDR5")
    with pytest.raises(ValueError, match="overwrite"):
        LPDDRPowerModel(
            model.dram,
            model.reference_memspec_path,
            reference_memspec_path=model.reference_memspec_path,
        )


def test_lpddr_rate_change_scales_only_dynamic_current(tmp_path, monkeypatch):
    # Test mechanism with a complete new preset; this is not a validated speed bin.
    presets = dict(ramulator.dram.LPDDR5.timing_presets)
    presets["LPDDR5_test_3200"] = {
        **presets["LPDDR5_6400"],
        "rate": 3200,
        "tCK_ps": 2500,
    }
    monkeypatch.setattr(ramulator.dram.LPDDR5, "timing_presets", presets)
    baseline = make_model(tmp_path, "LPDDR5")
    changed = LPDDRPowerModel(
        ramulator.dram.LPDDR5(org_preset="LPDDR5_16Gb_x16", timing_preset="LPDDR5_test_3200"),
        baseline.memspec_path,
        reference_memspec_path=baseline.reference_memspec_path,
    )
    p = changed.memspec["mempowerspec"]
    assert p["idd4r1"] == pytest.approx(0.035 + (0.1575 - 0.035) / 2)
    assert p["idd01"] == baseline.memspec["mempowerspec"]["idd01"]
    assert changed.memspec["modelMetadata"]["modelKind"] == "rate_scaled_exploratory_profile"
