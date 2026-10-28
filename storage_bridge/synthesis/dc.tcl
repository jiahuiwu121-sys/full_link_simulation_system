# Optional Synopsys Design Compiler handoff, NOT an executed PPA result.
# All delay values below assume target Liberty time_unit = "1ns".
foreach name {BRIDGE_TARGET_LIBS BRIDGE_CLOCK_NS BRIDGE_INPUT_DELAY_NS BRIDGE_OUTPUT_DELAY_NS BRIDGE_CLOCK_UNCERTAINTY_NS BRIDGE_LOAD_PF} {
    if {![info exists ::env($name)] || $::env($name) eq ""} {
        error "Required environment variable: $name (see synthesis/README.md)"
    }
}
set root [file normalize [file join [file dirname [info script]] ../..]]
set out [file join $root build storage_bridge-synthesis]
file mkdir $out
set target_library $::env(BRIDGE_TARGET_LIBS)
foreach lib $target_library { if {![file isfile $lib]} { error "Missing target library: $lib" } }
set link_library [concat {*} $target_library]
set parameters {}
foreach {name default} {AXI_DATA_WIDTH 256 RESOURCE_PLANES 1 REQUEST_SLOTS 4 MAX_OUTSTANDING 8 WDATA_GRANULES 64 FRAME_FIFO_DEPTH 2 TX_FLUSH_CYCLES 2} {
    set key BRIDGE_$name
    set value $default
    if {[info exists ::env($key)]} { set value $::env($key) }
    if {![string is integer -strict $value] || $value < 1} { error "Invalid $key" }
    lappend parameters $name=$value
}
set sources {}
set stream [open [file join $root storage_bridge rtl files.f] r]
foreach name [split [read $stream] \n] {
    if {[string trim $name] ne ""} { lappend sources [file join $root storage_bridge rtl $name] }
}
close $stream
define_design_lib WORK -path [file join $out WORK]
analyze -format sverilog $sources
elaborate storage_bridge_top -parameters [join $parameters ,]
current_design storage_bridge_top
link
if {![check_design]} { error "check_design failed; inspect target-library and RTL diagnostics" }
create_clock -name bridge_clk -period $::env(BRIDGE_CLOCK_NS) [get_ports clk]
set_clock_uncertainty $::env(BRIDGE_CLOCK_UNCERTAINTY_NS) [get_clocks bridge_clk]
set_input_delay $::env(BRIDGE_INPUT_DELAY_NS) -clock bridge_clk [remove_from_collection [all_inputs] [get_ports {clk rst_n}]]
set_output_delay $::env(BRIDGE_OUTPUT_DELAY_NS) -clock bridge_clk [all_outputs]
set_load $::env(BRIDGE_LOAD_PF) [all_outputs]
# Functional normal operation only; reset recovery/removal requires a separate scenario.
set_case_analysis 1 [get_ports rst_n]
compile_ultra
redirect [file join $out area.rpt] { report_area -hierarchy }
redirect [file join $out timing.rpt] { report_timing -max_paths 20 }
redirect [file join $out constraints.rpt] { report_constraint -all_violators }
redirect [file join $out resources.rpt] { report_resources }
write -format verilog -hierarchy -output [file join $out storage_bridge.v]
write_sdc [file join $out storage_bridge.sdc]
write -format ddc -hierarchy -output [file join $out storage_bridge.ddc]
set stream [open [file join $out handoff.txt] w]
puts $stream "Parameters: $parameters"
foreach name {BRIDGE_TARGET_LIBS BRIDGE_CLOCK_NS BRIDGE_INPUT_DELAY_NS BRIDGE_OUTPUT_DELAY_NS BRIDGE_CLOCK_UNCERTAINTY_NS BRIDGE_LOAD_PF} {
    puts $stream "$name=$::env($name)"
}
puts $stream "Pre-layout synthesis only. SRAM mapping, reset/CDC, DFT, activity power and signoff remain unverified."
close $stream
