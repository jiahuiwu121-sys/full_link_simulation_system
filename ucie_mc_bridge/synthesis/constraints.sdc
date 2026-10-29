# Integration template, not a characterized timing result. Values must be
# replaced with the target MC clock and real IO timing before STA/signoff.
create_clock -name bridge_clk -period 1.000 [get_ports clk]
set_false_path -from [get_ports rst_n]
# Add actual set_input_delay/set_output_delay, reset recovery/removal handling,
# clock uncertainty, library/SRAM constraints in the target project.
