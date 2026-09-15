"""Helpers for presenting aggregate memory bandwidth and access latency."""


def build_memory_performance_report(
    stats,
    *,
    nominal_rate_mbps,
    total_dq_bits,
    tick_ps,
):
    """Return user-facing aggregate metrics from Ramulator controller stats.

    ``nominal_rate_mbps`` is the per-pin data rate, ``total_dq_bits`` is the
    total width represented by all controllers, and ``tick_ps`` is one
    controller statistics tick in picoseconds.
    """
    ctrl_stats = stats["memory_system"]["controller"]
    controllers = ctrl_stats if isinstance(ctrl_stats, list) else [ctrl_stats]

    read_throughput = sum(c["read_throughput_MBps"] for c in controllers)
    write_throughput = sum(c["write_throughput_MBps"] for c in controllers)
    total_throughput = sum(c["total_throughput_MBps"] for c in controllers)
    peak_throughput = nominal_rate_mbps * total_dq_bits / 8

    read_served = sum(c["num_read_reqs_served"] for c in controllers)
    read_forwarded = sum(c["num_read_reqs_forwarded"] for c in controllers)
    read_latency_samples = read_served + read_forwarded
    total_read_latency = sum(c["read_latency"] for c in controllers)
    avg_read_latency_ticks = (
        total_read_latency / read_latency_samples if read_latency_samples else 0.0
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
            memory_cycles / core_cycles * 100 if core_cycles else 0.0
        )

    return {
        "controllers": len(controllers),
        "active_controllers": sum(
            c["num_read_reqs"] > 0 or c["num_write_reqs"] > 0 for c in controllers
        ),
        "total_dq_bits": total_dq_bits,
        "read_requests": sum(c["num_read_reqs"] for c in controllers),
        "write_requests": sum(c["num_write_reqs"] for c in controllers),
        "read_requests_served": read_served,
        "write_requests_served": sum(c["num_write_reqs_served"] for c in controllers),
        "read_throughput_MBps": read_throughput,
        "write_throughput_MBps": write_throughput,
        "total_throughput_MBps": total_throughput,
        "peak_throughput_MBps": peak_throughput,
        "read_bandwidth_utilization_pct": (
            read_throughput / peak_throughput * 100 if peak_throughput else 0.0
        ),
        "write_bandwidth_utilization_pct": (
            write_throughput / peak_throughput * 100 if peak_throughput else 0.0
        ),
        "total_bandwidth_utilization_pct": (
            total_throughput / peak_throughput * 100 if peak_throughput else 0.0
        ),
        "avg_read_latency_ticks": avg_read_latency_ticks,
        "avg_read_latency_ns": avg_read_latency_ticks * tick_ps / 1000,
        "write_latency_available": False,
        "row_hit_rate_pct": row_hits / row_accesses * 100 if row_accesses else 0.0,
        "read_queue_len_avg_total": sum(c["read_queue_len_avg"] for c in controllers),
        "write_queue_len_avg_total": sum(c["write_queue_len_avg"] for c in controllers),
        "memory_access_cycle_share_pct": memory_access_cycle_share,
    }


def print_memory_performance_report(stats, **kwargs):
    """Print aggregate bandwidth, utilization, and read-access latency."""
    report = build_memory_performance_report(stats, **kwargs)

    print(f"Modeled controllers:           {report['controllers']}")
    print(f"Active controllers:            {report['active_controllers']}")
    print(f"Total modeled DQ width:        {report['total_dq_bits']} bit")
    print(f"Read requests:                 {report['read_requests']}")
    print(f"Write requests:                {report['write_requests']}")
    print(
        f"Read bandwidth:                {report['read_throughput_MBps'] / 1000:.6f} GB/s"
    )
    print(
        f"Write bandwidth:               {report['write_throughput_MBps'] / 1000:.6f} GB/s"
    )
    print(
        f"Total bandwidth:               {report['total_throughput_MBps'] / 1000:.6f} GB/s"
    )
    print(f"Theoretical peak bandwidth:    {report['peak_throughput_MBps'] / 1000:.3f} GB/s")
    print(f"Read bandwidth utilization:    {report['read_bandwidth_utilization_pct']:.6f}%")
    print(f"Write bandwidth utilization:   {report['write_bandwidth_utilization_pct']:.6f}%")
    print(f"Total bandwidth utilization:   {report['total_bandwidth_utilization_pct']:.6f}%")
    print(f"Average read latency:          {report['avg_read_latency_ticks']:.3f} ticks")
    print(f"Average read latency:          {report['avg_read_latency_ns']:.3f} ns")
    print("Average write latency:         N/A (completion latency is not modeled)")
    print(f"Row hit rate:                  {report['row_hit_rate_pct']:.3f}%")
    print(f"Average read queue entries:    {report['read_queue_len_avg_total']:.3f}")
    print(f"Average write queue entries:   {report['write_queue_len_avg_total']:.3f}")
    for core_id, share in sorted(
        report["memory_access_cycle_share_pct"].items(), key=lambda item: int(item[0])
    ):
        print(f"Core {core_id} memory-cycle share:    {share:.3f}%")

    return report
