#!/usr/bin/env python3
"""Fast profile compiler acceptance and rejection checks."""
import json
import math
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'env'))
from system_profile import compile_profile

source = ROOT / 'configs/system/llm8b-4axi512-ucie64-hbm3.json'
with tempfile.TemporaryDirectory() as directory:
    output = Path(directory) / 'compiled'
    topology, capacity = compile_profile(source, output)
    assert len(topology['axi_ports']) == 4
    assert len(topology['modules']) == 1
    assert math.isclose(capacity['axi_aggregate_Bps'], 256e9)
    assert math.isclose(capacity['gearbox_output_aggregate_Bps'], 256e9)
    assert capacity['fabric_clock_period_fs'] == 250_000
    assert math.isclose(capacity['ucie_raw_aggregate_Bps'], 256e9)
    assert math.isclose(capacity['ucie_aou_payload_aggregate_Bps'], 250e9)
    assert capacity['memory_capacity_bytes'] == 16 * (1 << 30)
    assert capacity['memory_theoretical_Bps'] == 819.2e9
    assert capacity['bottleneck'] == 'UCIe AoU payload'
    assert (output / 'build.env').is_file()
    assert (output / 'validation_plan.json').is_file()

    invalid = json.loads(source.read_text())
    invalid['bridge']['resource_planes'] = 5
    bad = Path(directory) / 'bad.json'
    bad.write_text(json.dumps(invalid))
    try:
        compile_profile(bad, Path(directory) / 'bad-output')
    except ValueError as error:
        assert 'resource_planes' in str(error)
    else:
        raise AssertionError('invalid resource plane count was accepted')

    user_source = ROOT / 'configs/user/full-link-research-template.json'
    user_output = Path(directory) / 'user-compiled'
    user_topology, user_capacity = compile_profile(user_source, user_output)
    assert user_topology['name'] == 'user-full-link-research'
    assert user_capacity['bottleneck'] == 'UCIe AoU payload'
    archived_profile = json.loads((user_output / 'system_profile.json').read_text())
    runtime_profile = json.loads((user_output / 'runtime_topology.json').read_text())
    assert '_guide' in archived_profile and '_guide' not in runtime_profile
    modules = ('sources', 'execution', 'workload', 'protocol', 'axi', 'axi_ports',
               'ucie_links', 'memory_nodes',
               'routing', 'bridge', 'backend', 'simulation', 'observability', 'sweep',
               'requirements')
    archived_keys = list(archived_profile)
    for module in modules:
        note = f'_{module}_module'
        assert archived_keys.index(note) + 1 == archived_keys.index(module)
        assert set(archived_profile[note]) == {'模块说明', '当前系统支持的可选选项'}
        assert archived_profile[note]['当前系统支持的可选选项']
        assert note not in runtime_profile
    assert '_help' not in json.dumps(archived_profile, ensure_ascii=False)
    run_env = (user_output / 'run.env').read_text()
    for expected in (
            'export SS_TRAFFIC_SIZE=256\n',
            'export SS_TRAFFIC_MAX_INFLIGHT=256\n',
            'export SS_RAMULATOR_RESPONSE_HOLD=0\n',
            'export SS_RAMULATOR_NO_POWER=0\n',
            'export SS_UCIE_REPLAY=0\n',
            'export SS_EXECUTION_MODE=traffic\n',
            'export SS_FDI_FIFO_DEPTH=8\n',
            'export SS_MEMORY_FIFO_DEPTH=4\n',
            "export SS_PROFILE_SWEEP_DIRECTIONS='mixed read write'\n"):
        assert expected in run_env, expected
    frontend = json.loads((user_output / 'frontend_plan.json').read_text())
    protocol = json.loads((user_output / 'protocol_profile.json').read_text())
    assert frontend['mode'] == 'traffic' and not frontend['requires_xpu']
    assert protocol['profile'] == 'aou-format6-256'
    assert protocol['aou_frame_bytes'] == 256 and protocol['aou_payload_bytes'] == 250
    assert protocol['fdi_fifo_depth'] == 8 and protocol['memory_fifo_depth'] == 4
    plan = json.loads((user_output / 'validation_plan.json').read_text())
    assert plan['load_sweep_percent'] == [10, 25, 50, 75, 90, 100, 110, 125]
    assert plan['directions'] == ['mixed', 'read', 'write']

    invalid = json.loads(user_source.read_text())
    invalid['workload']['traffic']['request_size_bytes'] = 300
    bad = Path(directory) / 'bad-traffic.json'
    bad.write_text(json.dumps(invalid))
    try:
        compile_profile(bad, Path(directory) / 'bad-traffic-output')
    except ValueError as error:
        assert 'request_size_bytes' in str(error)
    else:
        raise AssertionError('request size that does not divide the stripe was accepted')

    invalid = json.loads(user_source.read_text())
    invalid['workload']['traffic'].update(working_set_bytes=8192, max_inflight=32)
    bad = Path(directory) / 'bad-working-set.json'
    bad.write_text(json.dumps(invalid))
    try:
        compile_profile(bad, Path(directory) / 'bad-working-set-output')
    except ValueError as error:
        assert 'more request blocks than max_inflight' in str(error)
    else:
        raise AssertionError('working set without a free request block was accepted')

    cpu_profile = json.loads(user_source.read_text())
    cpu_profile['name'] = 'configured-cpu'
    cpu_profile['execution'].update(mode='cpu', host={
        'binary': sys.executable,
        'arguments': ['--example'], 'environment': {'PROFILE_TEST': '1'},
        'target_size_bytes': 16384})
    cpu_source = Path(directory) / 'cpu.json'
    cpu_source.write_text(json.dumps(cpu_profile))
    compile_profile(cpu_source, Path(directory) / 'cpu-output')
    cpu_plan = json.loads((Path(directory) / 'cpu-output/frontend_plan.json').read_text())
    assert cpu_plan['mode'] == 'cpu' and cpu_plan['cpu']['count'] == 1
    assert cpu_plan['host']['arguments'] == ['--example']
    assert cpu_plan['host']['environment'] == {'PROFILE_TEST': '1'}

    expected_devices = {
        'traffic': [], 'cpu': ['cpu'], 'gpu': ['cpu', 'gpu'],
        'npu': ['cpu', 'npu'], 'cpu_gpu': ['cpu', 'gpu'],
        'cpu_npu': ['cpu', 'npu'], 'cpu_gpu_npu': ['cpu', 'gpu', 'npu'],
    }
    for mode, devices in expected_devices.items():
        configured = json.loads(user_source.read_text())
        configured['name'] = 'mode-' + mode
        configured['execution']['mode'] = mode
        configured['execution']['cpu'].pop('count', None)
        path = Path(directory) / (mode + '.json')
        path.write_text(json.dumps(configured))
        compile_profile(path, Path(directory) / (mode + '-output'))
        mode_plan = json.loads((Path(directory) / (mode + '-output/frontend_plan.json')).read_text())
        assert mode_plan['devices'] == devices
        assert mode_plan['requires_xpu'] == ('gpu' in devices or 'npu' in devices)

    gpu_profile = json.loads(user_source.read_text())
    gpu_profile['execution']['mode'] = 'gpu'
    gpu_profile['execution']['cpu']['count'] = 1
    bad = Path(directory) / 'bad-gpu.json'
    bad.write_text(json.dumps(gpu_profile))
    try:
        compile_profile(bad, Path(directory) / 'bad-gpu-output')
    except ValueError as error:
        assert 'requires execution.cpu.count >= 2' in str(error)
    else:
        raise AssertionError('Vortex profile with one CPU context was accepted')

    bad_protocol = json.loads(user_source.read_text())
    bad_protocol['protocol']['aou_payload_bytes'] = 249
    bad = Path(directory) / 'bad-protocol.json'
    bad.write_text(json.dumps(bad_protocol))
    try:
        compile_profile(bad, Path(directory) / 'bad-protocol-output')
    except ValueError as error:
        assert 'aou_payload_bytes=250' in str(error)
    else:
        raise AssertionError('incompatible AoU payload size was accepted')

print('system profile compiler: PASS')
