#!/usr/bin/env python3
"""Exercise the real C ABI, completion timing, capacity, drain and power."""
import argparse
import ctypes as C
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'env'))
from generate_ramulator_config import generate_config
sys.path.insert(0, str(ROOT / 'gem5_axi/scripts'))
from check_ramulator import command_check


class Info(C.Structure):
    _fields_ = [(n, C.c_uint32) for n in ('abi_version','struct_bytes','transaction_bytes','channels')] + [
        (n, C.c_uint64) for n in ('period_fs','capacity_bytes','read_latency','write_latency')]


class Event(C.Structure):
    _fields_ = [(n, C.c_uint32) for n in ('abi_version','struct_bytes','kind','write')] + [
        (n, C.c_uint64) for n in ('token','cycle','issue_cycle','address')] + [
        (n, C.c_int32) for n in ('channel','command','levels')] + [
        ('coordinates', C.c_int32 * 8), ('command_name', C.c_char * 24)]


def bind(path):
    lib = C.CDLL(str(Path(path).resolve()), mode=C.RTLD_LOCAL)
    lib.ssr_error.restype = C.c_char_p
    signatures = {
        'create': ([C.c_char_p,C.c_uint32,C.c_uint32,C.c_char_p], C.c_void_p),
        'get_info': ([C.c_void_p,C.POINTER(Info)], C.c_int),
        'submit': ([C.c_void_p,C.c_uint64,C.c_uint64,C.c_uint32], C.c_int),
        'step': ([C.c_void_p], C.c_int), 'poll_event': ([C.c_void_p,C.POINTER(Event)], C.c_int),
        'is_idle': ([C.c_void_p], C.c_int), 'finish': ([C.c_void_p], C.c_int),
        'destroy': ([C.c_void_p], None),
    }
    for name, (args, result) in signatures.items():
        f = getattr(lib, 'ssr_' + name); f.argtypes = args; f.restype = result
    return lib


def check(library, directory):
    lib = bind(library); out = Path(directory).resolve(); out.mkdir(parents=True, exist_ok=True)
    def run(name, channels=2, enabled=True, scale=1):
        p = out / name; p.mkdir(exist_ok=True)
        config = generate_config(p, channels, 1, scale, enabled)
        h = lib.ssr_create(config.encode(), 2, 1, str(p).encode())
        assert h, lib.ssr_error().decode()
        try:
            info = Info(); assert lib.ssr_get_info(h, C.byref(info)) == 1
            assert (info.abi_version,info.struct_bytes) == (1,C.sizeof(Info))
            assert info.transaction_bytes == 32 and info.period_fs == 250000 * scale
            assert info.capacity_bytes == channels * 2**30
            assert lib.ssr_submit(h, 0, 0, 1) == -1
            assert lib.ssr_submit(h, 1, 1, 1) == -1
            assert lib.ssr_submit(h, 1, info.capacity_bytes, 1) == -1
            assert lib.ssr_submit(h, 1, 0, 1) == 1
            assert lib.ssr_submit(h, 1, 32, 0) == -1
            assert lib.ssr_submit(h, 2, 0, 0) == 0  # No same-transaction coalescing/forwarding.
            second = 2**32 if channels == 8 else 32
            assert lib.ssr_submit(h, 2, second, 0) == 1
            assert lib.ssr_submit(h, 3, 64, 0) == 0  # Bounded native children.
            assert lib.ssr_finish(h) == -1
            trace = []; terminals = {}; services = {}
            # Continue through refresh and idle background, not just demand completion.
            for cycle in range(1, 6001):
                assert lib.ssr_step(h) == 1, lib.ssr_error().decode()
                if cycle == 1:
                    assert lib.ssr_step(h) == -1  # Events must be consumed; no hidden advancement.
                while True:
                    e = Event(); n = lib.ssr_poll_event(h, C.byref(e))
                    assert n >= 0, lib.ssr_error().decode()
                    if not n: break
                    assert e.abi_version == 1 and e.struct_bytes == C.sizeof(Event) and e.cycle == cycle
                    command = e.command_name.decode()
                    trace.append((e.kind,e.token,e.cycle,e.issue_cycle,e.address,e.channel,command,tuple(e.coordinates)))
                    if e.kind == 1 and e.token and command in ('RD','WR'):
                        assert e.token not in terminals; terminals[e.token] = (cycle,e.address,e.channel,command)
                    if e.kind == 2:
                        assert e.token not in services
                        issued,addr,ch,cmd = terminals[e.token]
                        assert e.issue_cycle == issued and e.address == addr and e.channel == ch
                        assert cycle - issued == (info.write_latency if e.write else info.read_latency)
                        services[e.token] = cycle
            models = json.loads((p/'ramulator_model.json').read_text())['controllers']
            decoded = [dict(cycle=t[2],channel=t[5],command=t[6], **{f'level{i}':t[7][i] for i in range(8)})
                       for t in trace if t[0] == 1]
            assert command_check(decoded, models) > 0
            assert services.keys() == {1,2} and lib.ssr_is_idle(h) == 1
            assert any(t[6].startswith('REF') for t in trace if t[0] == 1)
            if channels == 8:
                assert terminals[1][1:3] != terminals[2][1:3]
                assert next(t[7] for t in trace if t[0] == 1 and t[1] == 1) != next(t[7] for t in trace if t[0] == 1 and t[1] == 2)
            assert lib.ssr_finish(h) == 1, lib.ssr_error().decode()
            assert lib.ssr_step(h) == -1 and lib.ssr_finish(h) == -1
            power = json.loads((p/'dram_power.json').read_text())
            assert power['passed']
            if enabled:
                assert power['total_energy_j'] > 0
                for c in power['channels']:
                    assert c['enabled'] and not c['unsupported_commands']
                    assert abs(c['duration_seconds'] - 6000 * info.period_fs * 1e-15) < 1e-15
                    assert c['mapped_commands'] == sum(t[0] == 1 and t[5] == c['channel'] for t in trace)
            else:
                assert power['total_energy_j'] == 0
            return trace
        finally:
            lib.ssr_destroy(h)
    fast = run('fast'); off = run('power_off'); assert fast == off
    run('slow', scale=4); run('high_address', channels=8)
    assert not lib.ssr_create(b'/nonexistent/ramulator.yaml', 2, 1, str(out).encode())
    result = {'passed':True,'high_address_no_alias':True,'bounded_backpressure':True,
              'actual_issue_to_service_latency':True,'power_transparent':True,
              'refresh_observed':True,'strict_power_timebase':True,'fully_drained':True}
    (out/'api_check.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('library'); parser.add_argument('directory')
    args = parser.parse_args(); check(args.library,args.directory)
