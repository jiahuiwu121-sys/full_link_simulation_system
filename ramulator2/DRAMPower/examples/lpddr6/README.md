# LPDDR6 example power profile

`lpddr6_16gb_x12_10667_bl24_estimated.json` matches Ramulator's
`LPDDR6_16Gb_x12` / `LPDDR6_10667_BL24` organization and timing. Electrical
and impedance values are inherited from the public DRAMPower LPDDR6 test
profile; they are suitable for integration and comparative experiments, not
absolute vendor-silicon validation. The integrated backend currently rejects
BL48 commands rather than silently evaluating them as BL24.
