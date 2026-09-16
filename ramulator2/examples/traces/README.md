# Trace simulations and power output

The `.trace` files contain memory accesses, not simulator configuration.
The following Python configurations consume traces from this directory and
attach DRAMPower to every modeled controller:

| Configuration in `examples/` | DRAM model | Modeled controllers |
| --- | --- | --- |
| `example_config.py` | HBM4, 8 Gbps/pin | 1 |
| `HBM4_example_config.py` | HBM4, 8 Gbps/pin | 4 |
| `HBM3_image_config.py` | HBM3, 6.4 Gbps/pin | 32 |
| `HBM3E_image_config.py` | HBM3E preset, 8 Gbps/pin | 32 |
| `HBM4_image_config.py` | HBM4, 11 Gbps/pin | 64 |
| `LPDDR5_example_config.py` | LPDDR5, 6.4 Gbps/pin | 2 |
| `LPDDR6_example_config.py` | LPDDR6, 10.667 Gbps/pin | 2 x12 subchannels |

Run from the repository root, for example:

```bash
PYTHONPATH=python python3 examples/HBM3_image_config.py
PYTHONPATH=python python3 examples/HBM3E_image_config.py
PYTHONPATH=python python3 examples/HBM4_image_config.py
PYTHONPATH=python python3 examples/LPDDR5_example_config.py
PYTHONPATH=python python3 examples/LPDDR6_example_config.py
```

To select another trace, change the configuration's `frontend.traces` value.
Organization and timing remain shared with DRAMPower through `HBM34PowerModel`;
changing a trace does not require a separate power configuration edit.

Every completed Python example finalizes the simulation before printing
bandwidth, latency, and the following power metrics:

- `E_ACT`, `E_PRE`, `E_RD`, `E_WR`, `E_REF`, `E_RFM`: command-related energy in J.
- `E_background`: state-duration-related background energy in J.
- `E_interface`: separately modeled interface energy in J.
- `E_total`: total energy across all powered modeled controllers in J.
- `T_simulation`: the power accounting interval in seconds.
- `P_avg`: total energy divided by the accounting interval, in W.
- Energy component sum and a `PASS`/`WARNING` consistency check.
- Mapped, ignored-interface, and unsupported command counts.
- Model estimation/extrapolation status and absolute-validation status.

The sum check uses a relative tolerance of `1e-6` and an absolute tolerance of
`1e-18 J`; it checks bookkeeping, not physical accuracy.

The current electrical profiles are estimates, not target-device calibrated
measurements. HBM4 above 8 Gbps/pin is explicitly marked as out-of-range
extrapolation. Refresh/RFM currents are estimates. Interface energy is disabled
in the generated profiles to avoid double counting read/write current; a zero
interface result does not mean the physical interface consumes no energy.
The result is not complete memory-system power (PHY, controller, and other
unmodeled circuitry are not included). An attached backend may legitimately
report zero RFM energy if no RFM commands were issued; a missing backend is
reported as `N/A`, not zero.

LPDDR examples use their own LPDDR5/LPDDR6 controllers and matching generated
power specs. See [LPDDR_POWER.md](../LPDDR_POWER.md) for options and public
sources. LPDDR interface energy uses exploratory impedance inputs rather than
HBM's disabled link model; neither profile is a validated absolute power model.
