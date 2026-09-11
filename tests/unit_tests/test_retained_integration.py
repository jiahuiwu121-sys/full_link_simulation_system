"""Exercise shared integration paths with every retained DRAM family."""

import csv
import json
import struct
from collections import Counter

import pytest
import yaml

import ramulator
from ramulator.export import dict_to_json, dict_to_yaml
from ramulator.gem5 import _build_config, _build_vector_port_config
from tests.smoke.testcases import STANDARDS
from tests.utils import create_dram


def make_controller(standard, plugins=()):
    return getattr(ramulator.controller, STANDARDS[standard]["controller_class"])(
        dram=create_dram(STANDARDS[standard]),
        scheduler=ramulator.scheduler.FRFCFS(),
        refresh_manager=ramulator.refresh_manager.NoRefresh(),
        row_policy=ramulator.row_policy.Open(),
        addr_mapper=ramulator.addr_mapper.RoBaRaCoCh(),
        controller_plugins=list(plugins),
    )


@pytest.mark.parametrize("standard", sorted(STANDARDS))
def test_export_multichannel_stats_and_trace_recorders(standard, tmp_path):
    trace = tmp_path / "inst.trace"
    trace.write_text("".join(f"10 {32 * i}\n" for i in range(64)))
    frontend = ramulator.frontend.SimpleO3(
        clock_ratio=8,
        traces=[str(trace)],
        num_expected_insts=4096,
        llc_linesize=32,
        translation=ramulator.translation.NoTranslation(max_addr=2147483648),
    )
    commands = create_dram(STANDARDS[standard]).commands
    controllers = [
        make_controller(standard, [
            ramulator.controller_plugin.CmdTraceRecorder(path=str(tmp_path / "commands.csv")),
            ramulator.controller_plugin.BinTraceRecorder(
                path=str(tmp_path / "commands"), dram_type=standard,
            ),
            ramulator.controller_plugin.CommandCounter(
                commands_to_count=commands, path=str(tmp_path / f"counts{channel}.csv"),
            ),
        ])
        for channel in range(2)
    ]
    memory = ramulator.memory_system.GenericDRAM(
        clock_ratio=1,
        controllers=controllers,
        channel_mapper=ramulator.channel_mapper.CacheLineInterleave(),
    )
    config = {"frontend": frontend.to_config(), "memory_system": memory.to_config()}
    exported = yaml.safe_load(dict_to_yaml(config))
    assert exported == json.loads(dict_to_json(config)) == config

    sim = ramulator.Simulation(**exported)
    sim.run()
    stats = sim.stats
    assert yaml.safe_load(sim.stats_yaml) == stats
    assert len(stats["memory_system"]["controller"]) == 2
    assert all(c["num_read_reqs"] > 0 for c in stats["memory_system"]["controller"])
    sim.finalize()
    sim.finalize()  # Finalization must remain idempotent.
    assert sim.stats == stats

    for channel in range(2):
        with (tmp_path / f"commands.csv.ch{channel}").open() as stream:
            rows = list(csv.DictReader(stream))
        assert rows
        actual_counts = Counter(row["command"] for row in rows)
        with (tmp_path / f"counts{channel}.csv").open() as stream:
            counts = {name: int(count) for name, count in csv.reader(stream)}
        assert all(counts[name] == actual_counts[name] for name in commands)

        data = (tmp_path / f"commands.ch{channel}.ram2bin").read_bytes()
        assert data[:8] == b"RAM2BIN\0"
        assert data[48:64].rstrip(b"\0").decode() == standard
        levels = struct.unpack_from("<H", data, 12)[0]
        entries, offset = struct.unpack_from("<QQ", data, 32)
        assert entries == len(rows)
        assert len(data) == offset + entries * (20 + 4 * levels)


@pytest.mark.parametrize("standard", sorted(STANDARDS))
def test_gem5_configs_create_external_memory_systems(standard):
    memory = ramulator.memory_system.GenericDRAM(
        clock_ratio=1,
        controllers=[make_controller(standard) for _ in range(2)],
        channel_mapper=ramulator.channel_mapper.CacheLineInterleave(),
    )
    single_port = json.loads(_build_config(memory))
    memory_without_mapper = memory.to_config()
    del memory_without_mapper["channel_mapper"]
    vector_port = json.loads(_build_vector_port_config(memory_without_mapper, 2, 32))
    assert "channel_mapper" not in memory_without_mapper
    for config in (single_port, vector_port):
        assert config["frontend"]["impl"] == "External"
        sim = ramulator.Simulation(**config)
        assert sim.stats["memory_system"]["total_num_read_requests"] == 0
        assert len(sim.stats["memory_system"]["controller"]) == 2
        sim.finalize()
