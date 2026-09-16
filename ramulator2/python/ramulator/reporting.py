"""Helpers for presenting aggregate memory performance and DRAMPower energy."""

import math

_POWER_LABELS = {
    "activation_energy_j": "Activation energy (E_ACT)",
    "precharge_energy_j": "Precharge energy (E_PRE)",
    "read_energy_j": "Read energy (E_RD)",
    "write_energy_j": "Write energy (E_WR)",
    "refresh_energy_j": "Refresh energy (E_REF)",
    "rfm_energy_j": "RFM energy (E_RFM)",
    "background_energy_j": "Background energy (E_background)",
}


def build_memory_performance_report(
    stats,
    *,
    nominal_rate_mbps,
    total_dq_bits,
    tick_ps,
    frontend_ticks_per_memory_tick=1,
    transaction_bytes=32,
    read_queue_depth=32,
    write_queue_depth=32,
    product=None,
    org_preset=None,
    timing_preset=None,
    physical_channels=None,
    power_model_metadata=None,
    payload_fraction=1.0,
):
    """Return user-facing aggregate metrics from Ramulator controller stats.

    ``nominal_rate_mbps`` is the per-pin data rate, ``total_dq_bits`` is the
    total width represented by all controllers, and ``tick_ps`` is one
    controller statistics tick in picoseconds.
    ``payload_fraction`` excludes wire metadata from peak payload bandwidth.
    """
    if not 0 < payload_fraction <= 1:
        raise ValueError("payload_fraction must be in (0, 1]")
    ctrl_stats = stats["memory_system"]["controller"]
    controllers = ctrl_stats if isinstance(ctrl_stats, list) else [ctrl_stats]

    read_throughput = sum(c["read_throughput_MBps"] for c in controllers)
    write_throughput = sum(c["write_throughput_MBps"] for c in controllers)
    total_throughput = sum(c["total_throughput_MBps"] for c in controllers)
    num_controllers = len(controllers)
    controller_width_bits = total_dq_bits / num_controllers if num_controllers else 0
    active_controllers = sum(c["num_read_reqs"] > 0 or c["num_write_reqs"] > 0 for c in controllers)
    active_dq_bits = active_controllers * controller_width_bits
    full_wire_peak = nominal_rate_mbps * total_dq_bits / 8
    active_wire_peak = nominal_rate_mbps * active_dq_bits / 8
    full_peak_throughput = full_wire_peak * payload_fraction
    active_peak_throughput = active_wire_peak * payload_fraction

    read_served = sum(c["num_read_reqs_served"] for c in controllers)
    read_forwarded = sum(c["num_read_reqs_forwarded"] for c in controllers)
    read_latency_samples = read_served + read_forwarded
    total_read_latency = sum(c["read_latency"] for c in controllers)
    avg_read_latency_ticks = (
        total_read_latency / read_latency_samples if read_latency_samples else 0.0
    )
    write_latency_samples = sum(c.get("num_write_latency_samples", 0) for c in controllers)
    total_write_latency = sum(c.get("write_latency", 0) for c in controllers)
    avg_write_latency_ticks = (
        total_write_latency / write_latency_samples if write_latency_samples else 0.0
    )

    row_hits = sum(c["row_hits"] for c in controllers)
    row_misses = sum(c["row_misses"] for c in controllers)
    row_conflicts = sum(c["row_conflicts"] for c in controllers)
    row_accesses = row_hits + row_misses + row_conflicts

    frontend = stats.get("frontend", {})
    memory_access_cycle_share = {}
    for key, memory_cycles in frontend.items():
        prefix = "memory_access_cycles_recorded_core_"
        if not key.startswith(prefix):
            continue
        core_id = key.removeprefix(prefix)
        core_cycles = frontend.get(f"cycles_recorded_core_{core_id}", 0)
        memory_access_cycle_share[core_id] = (
            memory_cycles * frontend_ticks_per_memory_tick / core_cycles * 100
            if core_cycles
            else 0.0
        )

    memory_system = stats["memory_system"]
    powered_channels = memory_system.get("powered_channels", 0)
    power_categories = dict.fromkeys(_POWER_LABELS, 0.0)
    mapped_power_commands = 0
    unsupported_power_commands = 0
    ignored_interface_commands = 0
    for controller in controllers:
        plugins = controller.get("controller_plugin", [])
        if isinstance(plugins, dict):
            plugins = [plugins]
        for plugin in plugins:
            if plugin.get("impl") != "DRAMPower":
                continue
            for name in power_categories:
                power_categories[name] += plugin.get(name, 0.0)
            mapped_power_commands += plugin.get("mapped_commands", 0)
            unsupported_power_commands += plugin.get("unsupported_commands", 0)
            ignored_interface_commands += plugin.get("ignored_interface_commands", 0)

    # Interface energy is already the sum of controller- and DRAM-side energy;
    # add it once, rather than adding those subcomponents again.
    energy_sum = sum(power_categories.values()) + memory_system.get("dram_interface_energy_j", 0.0)
    total_energy = memory_system.get("dram_total_energy_j", 0.0)
    energy_sum_matches_total = math.isclose(energy_sum, total_energy, rel_tol=1e-6, abs_tol=1e-18)

    return {
        "product": product,
        "org_preset": org_preset,
        "timing_preset": timing_preset,
        "physical_channels": physical_channels,
        "controllers": num_controllers,
        "active_controllers": active_controllers,
        "controller_width_bits": controller_width_bits,
        "total_dq_bits": total_dq_bits,
        "active_dq_bits": active_dq_bits,
        "nominal_rate_mbps": nominal_rate_mbps,
        "tick_ps": tick_ps,
        "frontend_ticks_per_memory_tick": frontend_ticks_per_memory_tick,
        "transaction_bytes": transaction_bytes,
        "payload_fraction": payload_fraction,
        "full_wire_peak_throughput_MBps": full_wire_peak,
        "active_wire_peak_throughput_MBps": active_wire_peak,
        "read_queue_depth": read_queue_depth,
        "write_queue_depth": write_queue_depth,
        "read_requests": sum(c["num_read_reqs"] for c in controllers),
        "write_requests": sum(c["num_write_reqs"] for c in controllers),
        "read_requests_served": read_served,
        "write_requests_served": sum(c["num_write_reqs_served"] for c in controllers),
        "read_throughput_MBps": read_throughput,
        "write_throughput_MBps": write_throughput,
        "total_throughput_MBps": total_throughput,
        "peak_throughput_MBps": active_peak_throughput,
        "full_peak_throughput_MBps": full_peak_throughput,
        "active_peak_throughput_MBps": active_peak_throughput,
        "read_bandwidth_utilization_pct": (
            read_throughput / active_peak_throughput * 100 if active_peak_throughput else 0.0
        ),
        "write_bandwidth_utilization_pct": (
            write_throughput / active_peak_throughput * 100 if active_peak_throughput else 0.0
        ),
        "total_bandwidth_utilization_pct": (
            total_throughput / active_peak_throughput * 100 if active_peak_throughput else 0.0
        ),
        "avg_read_latency_ticks": avg_read_latency_ticks,
        "avg_read_latency_ns": avg_read_latency_ticks * tick_ps / 1000,
        "write_latency_available": write_latency_samples > 0,
        "write_latency_samples": write_latency_samples,
        "avg_write_latency_ticks": avg_write_latency_ticks,
        "avg_write_latency_ns": avg_write_latency_ticks * tick_ps / 1000,
        "row_hits": row_hits,
        "row_misses": row_misses,
        "row_conflicts": row_conflicts,
        "row_hit_rate_pct": row_hits / row_accesses * 100 if row_accesses else 0.0,
        "read_queue_len_avg_total": sum(c["read_queue_len_avg"] for c in controllers),
        "write_queue_len_avg_total": sum(c["write_queue_len_avg"] for c in controllers),
        "memory_access_cycle_share_pct": memory_access_cycle_share,
        "power_available": powered_channels > 0,
        "power_model_metadata": power_model_metadata or {},
        "powered_channels": powered_channels,
        "power_duration_seconds": memory_system.get("dram_power_duration_seconds", 0.0),
        "dram_core_energy_j": memory_system.get("dram_core_energy_j", 0.0),
        "dram_interface_energy_j": memory_system.get("dram_interface_energy_j", 0.0),
        "dram_total_energy_j": memory_system.get("dram_total_energy_j", 0.0),
        "dram_average_power_w": memory_system.get("dram_average_power_w", 0.0),
        "power_categories": power_categories,
        "power_energy_sum_j": energy_sum,
        "power_energy_sum_matches_total": energy_sum_matches_total,
        "mapped_power_commands": mapped_power_commands,
        "unsupported_power_commands": unsupported_power_commands,
        "ignored_interface_commands": ignored_interface_commands,
    }


def print_memory_performance_report(stats, **kwargs):
    """Print performance and finalized, command-level DRAMPower metrics.

    Call ``sim.finalize()`` before collecting ``stats`` for an end-of-run report.
    Missing power backends are reported as unavailable, not as zero energy.
    """
    report = build_memory_performance_report(stats, **kwargs)

    print("=== Initial configuration ===")
    if report["product"]:
        print(f"Product:                       {report['product']}")
    if report["org_preset"]:
        print(f"Organization preset:           {report['org_preset']}")
    if report["timing_preset"]:
        print(f"Timing preset:                 {report['timing_preset']}")
    if report["physical_channels"] is not None:
        print(f"Physical channels:             {report['physical_channels']}")
    print(f"Modeled channels/controllers:  {report['controllers']}")
    print(f"Channel width:                 {report['controller_width_bits']:g} bit")
    print(f"Total modeled DQ width:        {report['total_dq_bits']} bit")
    print(f"Nominal pin rate:              {report['nominal_rate_mbps'] / 1000:g} Gbps/pin")
    print(f"Transaction size:              {report['transaction_bytes']} B")
    if report["payload_fraction"] != 1:
        print(f"Wire payload fraction:         {report['payload_fraction']:.6f}")
    print(f"Controller tick:               {report['tick_ps']:g} ps")
    print(f"Read queue depth/controller:   {report['read_queue_depth']} entries")
    print(f"Write queue depth/controller:  {report['write_queue_depth']} entries")
    print()
    print("=== Simulation results ===")
    print(f"Active modeled channels:       {report['active_controllers']}")
    print(f"Active DQ width:               {report['active_dq_bits']:g} bit")
    print(f"Read requests:                 {report['read_requests']}")
    print(f"Write requests:                {report['write_requests']}")
    print(f"Read bandwidth:                {report['read_throughput_MBps'] / 1000:.6f} GB/s")
    print(f"Write bandwidth:               {report['write_throughput_MBps'] / 1000:.6f} GB/s")
    print(f"Total bandwidth:               {report['total_throughput_MBps'] / 1000:.6f} GB/s")
    if report["payload_fraction"] != 1:
        print(
            "Full-interface wire peak:      "
            f"{report['full_wire_peak_throughput_MBps'] / 1000:.3f} GB/s"
        )
        print(
            "Active-channel wire peak:      "
            f"{report['active_wire_peak_throughput_MBps'] / 1000:.3f} GB/s"
        )
        print(
            f"Full-interface payload peak:   {report['full_peak_throughput_MBps'] / 1000:.3f} GB/s"
        )
        print(
            "Active-channel payload peak:   "
            f"{report['active_peak_throughput_MBps'] / 1000:.3f} GB/s"
        )
    else:
        print(
            f"Full-interface peak bandwidth: {report['full_peak_throughput_MBps'] / 1000:.3f} GB/s"
        )
        print(
            "Active-channel peak bandwidth: "
            f"{report['active_peak_throughput_MBps'] / 1000:.3f} GB/s"
        )
    print(f"Read utilization (active):     {report['read_bandwidth_utilization_pct']:.6f}%")
    print(f"Write utilization (active):    {report['write_bandwidth_utilization_pct']:.6f}%")
    print(f"Total utilization (active):    {report['total_bandwidth_utilization_pct']:.6f}%")
    print(f"Average read latency:          {report['avg_read_latency_ticks']:.3f} ticks")
    print(f"Average read latency:          {report['avg_read_latency_ns']:.3f} ns")
    if report["write_latency_available"]:
        print(f"Average write latency:         {report['avg_write_latency_ticks']:.3f} ticks")
        print(f"Average write latency:         {report['avg_write_latency_ns']:.3f} ns")
    else:
        print("Average write latency:         N/A (no completed write samples)")
    print(f"row_hits:                      {report['row_hits']}")
    print(f"row_misses:                    {report['row_misses']}")
    print(f"row_conflicts:                 {report['row_conflicts']}")
    print(f"Row hit rate:                  {report['row_hit_rate_pct']:.3f}%")
    print(f"Average read queue entries:    {report['read_queue_len_avg_total']:.3f}")
    print(f"Average write queue entries:   {report['write_queue_len_avg_total']:.3f}")
    for core_id, share in sorted(
        report["memory_access_cycle_share_pct"].items(), key=lambda item: int(item[0])
    ):
        print(f"Core {core_id} memory-cycle share:    {share:.3f}%")

    print()
    print("=== DRAMPower results ===")
    if report["power_available"]:
        metadata = report["power_model_metadata"]
        if metadata:
            print(f"Power model kind:               {metadata.get('modelKind', 'unspecified')}")
            print(
                "Absolute accuracy validated:    "
                f"{metadata.get('absoluteAccuracyValidated', False)}"
            )
            print(
                "Power scope:                    modeled DRAM energy; not full memory-system power"
            )
            if metadata.get("notes"):
                print(f"Power model notes:              {metadata['notes']}")
        print(f"Powered modeled channels:       {report['powered_channels']}")
        print(f"Power interval (T_simulation):   {report['power_duration_seconds']:.6e} s")
        print(f"Core energy:                    {report['dram_core_energy_j']:.6e} J")
        for name, label in _POWER_LABELS.items():
            print(f"{label + ':':34}{report['power_categories'][name]:.6e} J")
        print(f"{'Interface energy (E_interface):':34}{report['dram_interface_energy_j']:.6e} J")
        print(f"{'Energy component sum:':34}{report['power_energy_sum_j']:.6e} J")
        print(f"{'Total DRAM energy (E_total):':34}{report['dram_total_energy_j']:.6e} J")
        print(f"{'Average DRAM power (P_avg):':34}{report['dram_average_power_w']:.6f} W")
        check = (
            "PASS"
            if report["power_energy_sum_matches_total"]
            else "WARNING (component sum differs from total)"
        )
        print(f"Energy sum check:               {check}")
        print(
            "Energy accounting:              E_total = E_ACT + E_PRE + E_RD + E_WR "
            "+ E_REF + E_RFM + E_background + E_interface"
        )
        print("Average power accounting:       P_avg = E_total / T_simulation")
        print(f"Mapped DRAM commands:           {report['mapped_power_commands']}")
        print(f"Ignored interface commands:     {report['ignored_interface_commands']}")
        print(f"Unsupported DRAM commands:      {report['unsupported_power_commands']}")
    else:
        print("Power statistics:               N/A (no DRAMPower backend attached)")
        for label in (
            *_POWER_LABELS.values(),
            "Interface energy (E_interface)",
            "Total DRAM energy (E_total)",
            "Average DRAM power (P_avg)",
        ):
            print(f"{label + ':':34}N/A")

    return report
