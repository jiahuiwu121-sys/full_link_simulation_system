"""Generate matching HBM3/HBM4 and LPDDR5/LPDDR6 DRAMPower memspecs.

The Ramulator DRAM object is the single source of truth for organization and
timing.  Electrical parameters remain an explicitly documented estimate based
on the public HBM-Power profiles bundled with this repository.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path

from ramulator.controller_plugin import DRAMPower

_BASE_RATE_MBPS = 6400
_BASE_IDD3N = 0.0346
_BASE_IDD4R = 0.6304
_BASE_IDD4W = 0.5051


class HBM34PowerModel:
    """Materialize a matching DRAMPower memspec for one Ramulator controller.

    Organization, full-CK timing, width, burst length, rate, and timestamp unit
    are resolved directly from ``dram``.  Calling :meth:`plugin` creates a fresh
    controller plugin, so one model instance can be attached to every matching
    controller in a multi-controller memory system.
    """

    def __init__(self, dram, memspec_path):
        self.dram = dram
        self.memspec_path = Path(memspec_path).resolve()
        self.org, self.timing = dram.resolve()
        self.standard = type(dram).name
        if self.standard not in {"HBM3", "HBM4"}:
            raise ValueError(
                f"HBM34PowerModel requires an HBM3 or HBM4 DRAM object, got {self.standard}"
            )

        self.memspec = self._build_memspec()
        self._write_if_changed()

    @property
    def nominal_rate_mbps(self):
        return self.timing["rate"]

    @property
    def tick_ps(self):
        return self.timing["tCK_ps"] / type(self.dram).tick_multiplier

    @property
    def channel_width_bits(self):
        """DQ width of one pseudo-channel."""
        return self.org["channel_width"]

    @property
    def controller_width_bits(self):
        """Total DQ width represented by the configured controller."""
        return self.channel_width_bits * self.org["pseudochannel"]

    @property
    def transaction_bytes(self):
        return self.channel_width_bits * type(self.dram).internal_prefetch_size // 8

    def plugin(self, *, strict_validation=True, include_interface=True):
        """Return a new DRAMPower plugin bound to the generated memspec."""
        return DRAMPower(
            memspec_path=str(self.memspec_path),
            strict_validation=strict_validation,
            include_interface=include_interface,
        )

    def _build_memspec(self):
        burst_length = type(self.dram).internal_prefetch_size
        nbl = self.timing["nBL"]
        if burst_length % nbl:
            raise ValueError(f"HBM burst length {burst_length} is not divisible by nBL={nbl}")

        power, pattern, metadata = self._electrical_profile()
        return {
            "memoryType": self.standard,
            "memoryId": (
                f"{self.dram.org_preset}_{self.dram.timing_preset}_"
                f"PC{self.org['pseudochannel']}_generated"
            ),
            "memarchitecturespec": {
                "nbrOfChannels": 1,
                "nbrOfPseudoChannels": self.org["pseudochannel"],
                "nbrOfSIDs": self.org["sid"],
                "nbrOfBankGroups": self.org["bankgroup"],
                "nbrOfBanksPerGroup": self.org["bank"],
                "nbrOfRows": self.org["row"],
                "nbrOfColumns": self.org["column"],
                "nbrOfDevices": 1,
                "burstLength": burst_length,
                "dataRate": burst_length // nbl,
                "width": self.org["channel_width"],
            },
            "memtimingspec": {
                "tCK": self.timing["tCK_ps"] * 1e-12,
                "ticksPerCK": type(self.dram).tick_multiplier,
                "RAS": self.timing["nRAS"],
                "RTP": self.timing["nRTP"],
                "WL": self.timing["nCWL"],
                "WR": self.timing["nWR"],
                "RP": self.timing["nRP"],
                "RCDRD": self.timing["nRCDRD"],
                "RCDWR": self.timing["nRCDWR"],
                "RFC": self.timing["nRFC"],
                "RFCPB": self.timing["nRFCpb"],
                "RFMAB": self.timing["nRFMab"],
                "RFMPB": self.timing["nRFMpb"],
            },
            "mempowerspec": power,
            "datapattern": pattern,
            # IDD4 is treated as calibrated total read/write current.  Keep the
            # external link disabled to avoid counting the same activity twice.
            "interfacepowerspec": {
                "readEnergyPerBit": 0.0,
                "writeEnergyPerBit": 0.0,
            },
            "modelMetadata": metadata,
            "generatedFrom": {
                "orgPreset": self.dram.org_preset,
                "timingPreset": self.dram.timing_preset,
                "generator": "ramulator.power.HBM34PowerModel",
            },
        }

    def _electrical_profile(self):
        rate_scale = self.nominal_rate_mbps / _BASE_RATE_MBPS
        idd4r = round(_BASE_IDD3N + rate_scale * (_BASE_IDD4R - _BASE_IDD3N), 12)
        idd4w = round(_BASE_IDD3N + rate_scale * (_BASE_IDD4W - _BASE_IDD3N), 12)

        is_hbm4 = self.standard == "HBM4"
        voltage = 1.05 if is_hbm4 else 1.1
        vddq = 0.9 if is_hbm4 else 1.1
        bg_rate = 0.5 if is_hbm4 else 0.0

        if is_hbm4:
            model_kind = (
                "extrapolated" if self.nominal_rate_mbps <= 8000 else "out_of_range_extrapolated"
            )
            source = (
                "CMU-SAFARI/HBM-Power linear HBM4 prediction method, based on "
                "its HBM3E 6.4-Gbps current profile; organization and timing "
                "are generated from the paired Ramulator2 HBM4 object"
            )
            reference = (
                "https://github.com/CMU-SAFARI/HBM-Power/blob/artifact/"
                "sources/drampower/docs/hbm4_power_prediction.md"
            )
        else:
            model_kind = (
                "estimated_from_public_HBM3E_data"
                if self.nominal_rate_mbps == _BASE_RATE_MBPS
                else "rate_scaled_from_public_HBM3E_data"
            )
            source = (
                "CMU-SAFARI/HBM-Power HBM3E 6.4-Gbps all-zero current profile "
                "and data-pattern equation; read/write dynamic current is scaled "
                "linearly with the configured rate when it differs from 6.4 Gbps"
            )
            reference = "https://github.com/CMU-SAFARI/HBM-Power/tree/artifact"

        power = {
            "vdd": voltage,
            "vddq": vddq,
            "idd0": 0.0446,
            "idd2n": 0.0383,
            "idd3n": _BASE_IDD3N,
            "idd4r": idd4r,
            "idd4w": idd4w,
            # Public IDD5/RFM values are unavailable.  These explicit estimates
            # match the bundled exploratory profiles and remain replaceable.
            "idd5ab": 0.0446,
            "idd5pb": 0.0446,
            "idd6n": 0.0,
            "idd2p": 0.0,
            "idd3p": 0.0,
            "iddBeta": 0.0446,
            "vpp": 1.8,
            "ipp0": 0.0,
            "ipp2n": 0.0,
            "ipp3n": 0.0,
            "ipp4r": 0.0,
            "ipp4w": 0.0,
            "ipp5ab": 0.0,
            "ipp5pb": 0.0,
            "ippBeta": 0.0,
            "bankWiseRho": 1.0,
            "rfmAbPowerRatio": 1.0,
            "rfmPbPowerRatio": 1.0,
        }
        pattern = {
            "enabled": True,
            "floorPjPerBit": 2.759,
            "coefficientDQ": 1.192,
            "coefficientTSV": 1.331,
            "coefficientBG": 0.720,
            "dqRate": 0.5,
            "tsvRate": 0.5,
            "bgRate": bg_rate,
            "referenceDQRate": 0.0,
            "referenceTSVRate": 0.0,
            "referenceBGRate": 0.0,
            "applyToWrites": True,
        }
        metadata = {
            "modelKind": model_kind,
            "parameterSource": source,
            "reference": reference,
            "scope": (
                f"one Ramulator2 controller containing "
                f"{self.org['pseudochannel']} "
                f"{self.channel_width_bits}-bit pseudo-channel(s)"
            ),
            "notes": (
                "Generated organization/timing exactly follows the paired Ramulator2 "
                "DRAM object. IDD5 and RFM use IDD0-based estimates; external-link "
                "energy is disabled because IDD4 is treated as total read/write current."
            ),
            "absoluteAccuracyValidated": False,
        }
        return power, pattern, metadata

    def _write_if_changed(self):
        payload = json.dumps(self.memspec, indent=2) + "\n"
        self.memspec_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.memspec_path.exists() or self.memspec_path.read_text() != payload:
            self.memspec_path.write_text(payload)


class LPDDRPowerModel:
    """Generate one LPDDR controller's memspec from resolved DRAM parameters.

    ``reference_memspec_path`` supplies electrical/impedance parameters, not
    organization or timing. The bundled LPDDR profiles are exploratory fixtures,
    NOT vendor-measured currents. They remain replaceable with calibrated input.
    Changing a trace changes issued commands, not device electrical parameters.
    """

    def __init__(
        self,
        dram,
        memspec_path,
        *,
        reference_memspec_path,
        wck_sync_mode="need_sync",
        power_overrides=None,
        impedance_overrides=None,
    ):
        self.dram = dram
        self.standard = type(dram).name
        if self.standard not in {"LPDDR5", "LPDDR6"}:
            raise ValueError("LPDDRPowerModel requires an LPDDR5 or LPDDR6 DRAM object")
        if wck_sync_mode not in {"need_sync", "always_on"}:
            raise ValueError("wck_sync_mode must be 'need_sync' or 'always_on'")
        self.org, self.timing = dram.resolve()
        expected_width = 16 if self.standard == "LPDDR5" else 12
        if self.org["channel_width"] != expected_width:
            raise ValueError(
                f"{self.standard} power generation currently requires x{expected_width}"
            )
        if (self.org["bankgroup"], self.org["bank"]) != (4, 4):
            raise ValueError("LPDDR power generation currently supports 4 bank groups x 4 banks")
        self.memspec_path = Path(memspec_path).resolve()
        self.reference_memspec_path = Path(reference_memspec_path).resolve()
        if self.memspec_path == self.reference_memspec_path:
            raise ValueError("Generated output must not overwrite the reference electrical profile")
        reference = json.loads(self.reference_memspec_path.read_text())
        self.reference = reference.get("memspec", reference)
        if self.reference["memoryType"] != self.standard:
            raise ValueError("Reference electrical profile memoryType does not match DRAM")
        self.wck_sync_mode = wck_sync_mode
        self.memspec = self._build_memspec(power_overrides or {}, impedance_overrides or {})
        payload = json.dumps(self.memspec, indent=2) + "\n"
        self.memspec_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.memspec_path.exists() or self.memspec_path.read_text() != payload:
            self.memspec_path.write_text(payload)

    @property
    def nominal_rate_mbps(self):
        return self.timing["rate"]

    @property
    def tick_ps(self):
        return self.timing["tCK_ps"]

    @property
    def controller_width_bits(self):
        return self.org["channel_width"]

    @property
    def burst_length(self):
        return 16 if self.standard == "LPDDR5" else 24

    @property
    def transaction_bytes(self):
        return type(self.dram).data_payload_bytes or (
            self.controller_width_bits * self.burst_length // 8
        )

    @property
    def payload_fraction(self):
        return self.transaction_bytes * 8 / (self.controller_width_bits * self.burst_length)

    @property
    def controller_capacity_bytes(self):
        # The LPDDR6 DSL uses 16-column granularity for 32-byte payloads;
        # multiplying its 12-bit wire width into the geometry loses capacity.
        return (
            self.org["rank"]
            * self.org["bankgroup"]
            * self.org["bank"]
            * self.org["row"]
            * self.org["column"]
            // type(self.dram).internal_prefetch_size
            * self.transaction_bytes
        )

    def plugin(self, *, strict_validation=True, include_interface=True, **toggle_parameters):
        return DRAMPower(
            memspec_path=str(self.memspec_path),
            strict_validation=strict_validation,
            include_interface=include_interface,
            **toggle_parameters,
        )

    def _build_memspec(self, power_overrides, impedance_overrides):
        spec = deepcopy(self.reference)
        org, t = self.org, self.timing
        arch = spec["memarchitecturespec"]
        arch.update(
            {
                "nbrOfChannels": 1,
                "nbrOfColumns": org["column"],
                "nbrOfRows": org["row"],
                "width": self.controller_width_bits,
                "burstLength": self.burst_length,
                # BL48 exists in the LPDDR6 protocol but the coupling rejects it.
                "maxBurstLength": 16 if self.standard == "LPDDR5" else 48,
                "dataRate": 2,
                "nbrOfBankGroups": org["bankgroup"],
                "nbrOfBanks": org["bankgroup"] * org["bank"],
                "nbrOfRanks": org["rank"],
                "nbrOfDevices": 1,
                "WCKalwaysOn": self.wck_sync_mode == "always_on",
            }
        )
        # DDR WCK transfers two beats/cycle. Derive its ratio from the actual
        # burst duration rather than assuming HBM's clock/transfer relationship.
        wck_ratio = self.burst_length / (2 * t["nBL_min"])
        if not wck_ratio.is_integer():
            raise ValueError("Burst duration does not imply an integral WCK:CK ratio")
        implied_rate = 2 * wck_ratio * 1e6 / self.tick_ps
        if not math.isclose(implied_rate, self.nominal_rate_mbps, rel_tol=0.005):
            raise ValueError("LPDDR rate, tCK_ps and nBL_min are inconsistent")
        ref_t = self.reference["memtimingspec"]
        base_rate = round(2 * ref_t["WCK2CK"] / ref_t["tCK"] / 1e6)
        tm = spec["memtimingspec"]
        tm.update(
            {
                "tCK": self.tick_ps * 1e-12,
                "REFI": t["nREFI"],
                "RFCab": t["nRFC"],
                "RAS": t["nRAS"],
                "RPab": t["nRPab"],
                "RPpb": t["nRP"],
                "RCpb": t["nRC"],
                "RCab": t["nRAS"] + t["nRPab"],
                "PPD": t["nPPD"],
                "FAW": t["nFAW"],
                "RBTP": t["nRTP"],
                "RTRS": t["nCS"],
                "WCK2CK": int(wck_ratio),
            }
        )
        if self.standard == "LPDDR5":
            tm.update(
                {
                    "REFIpb": t["nREFIpb"],
                    "RFCpb": t["nRFCpb"],
                    "RCD": t["nRCD"],
                    "RCD_L": t["nRCD"],
                    "RCD_S": t["nRCD"],
                    "RL": t["nCL"],
                    "WL": t["nCWL"],
                    "WR": t["nWR"],
                    "RRD": t["nRRDS"],
                    "BL_n_min_16": t["nBL_min"],
                    "BL_n_max_16": t["nBL_max"],
                    "WTR_L": t["nWTRL"],
                    "WTR_S": t["nWTRS"],
                    "pbR2act": t["nPBR2ACT"],
                    "pbR2pbR": t["nPBR2PBR"],
                }
            )
            domains = ("1", "2h", "2l")
        else:
            tm.update(
                {
                    "RCD": t["nRCDr"],
                    "RCD_L": t["nRCDr"],
                    "RCD_S": t["nRCDw"],
                    "RCD_r": t["nRCDr"],
                    "RCD_w": t["nRCDw"],
                    "RL": t["nRL"],
                    "WL": t["nWL"],
                    "WR": t["nWTP"],
                    "WTP": t["nWTP"],
                    "RRD": t["nRRD"],
                    "BL_n_min_24": t["nBL_min"],
                    "BL_n_max_24": t["nBL_max"],
                    "BL_n_min_48": t["nBL_min_L"],
                    "BL_n_max_48": t["nBL_max_L"],
                    "WTR_L": t["nWTRL"],
                    "WTR_S": t["nWTRS"],
                    "RTP_24": t["nRTP"],
                    "RTP_48": t["nRTP_L"],
                    "RTW_L_24": t["nRTW_L"],
                    "RTW_S_24": t["nRTW_S"],
                    "RTW_L_48": t["nRTW_L_L"],
                    "RTW_S_48": t["nRTW_S_L"],
                    "WCKPST": t["nWCKPST"],
                    "WCK2DQO": t["nWCK2DQO"],
                    "ACU": t["nACU"],
                    # No dual-bank refresh request exists in the current DSL.
                    "REFIdb": 0,
                    "RFCdb": 0,
                    "RFCpb": 0,
                }
            )
            domains = ("1", "2c", "2d")
        power = spec["mempowerspec"]
        rate_scale = self.nominal_rate_mbps / base_rate
        for domain in domains:
            baseline = power[f"idd3n{domain}"]
            for operation in ("r", "w"):
                key = f"idd4{operation}{domain}"
                power[key] = round(baseline + (power[key] - baseline) * rate_scale, 12)
        for values, overrides in (
            (power, power_overrides),
            (spec["memimpedancespec"], impedance_overrides),
        ):
            unknown = overrides.keys() - values.keys()
            if unknown:
                raise ValueError(f"Unknown LPDDR electrical parameters: {sorted(unknown)}")
            values.update(overrides)
        spec["memoryId"] = f"{self.dram.org_preset}_{self.dram.timing_preset}_generated"
        spec["generatedFrom"] = {
            "orgPreset": self.dram.org_preset,
            "timingPreset": self.dram.timing_preset,
            "generator": "ramulator.power.LPDDRPowerModel",
            "referenceElectricalProfile": str(self.reference_memspec_path),
            "wckSyncMode": self.wck_sync_mode,
        }
        spec["modelMetadata"] = {
            "modelKind": "exploratory_reference_profile"
            if rate_scale == 1
            else "rate_scaled_exploratory_profile",
            "parameterSource": (
                "Repository LPDDR electrical/impedance fixture; no target-vendor IDD calibration"
            ),
            "absoluteAccuracyValidated": False,
            "baseRateMbps": base_rate,
            "scope": (
                f"one x{self.controller_width_bits} {self.standard} controller, "
                f"{org['rank']} rank(s)"
            ),
            "references": [
                "https://www.micron.com/products/memory/lpddr-components/lpddr5",
                "https://www.businesswire.com/news/home/20250709315796/en/",
                "https://doi.org/10.1145/3721848.3721850",
            ],
            "notes": (
                "Organization/timing follow resolved Ramulator values. "
                "IDD and impedance values are "
                "exploratory placeholders, including effective 1.2-V current domains and sample "
                "1-pJ transition energies. IDD4 dynamic current alone is linearly rate-scaled; "
                "density/temperature are not electrically calibrated. "
                "CAS synchronization interface "
                "commands are omitted by the current coupling. LPDDR6 BL48 is not supported by "
                "the power coupling. Trace address changes affect commands, "
                "not bit-toggle parameters."
            ),
        }
        return spec
