#!/usr/bin/env python3
"""Independently validate every stage-2 path and its merged root evidence."""
import argparse
import csv
import json
import math
from pathlib import Path

from check import check as check_axi
from check_aou import check as check_aou
from check_ramulator import check as check_ramulator
from inspect_link import inspect
from check_metrics import check as check_metrics


def rows(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def without_module(row):
    return {key: value for key, value in row.items() if key != 'module'}


def check(directory):
    root = Path(directory).resolve()
    topology = json.loads((root / 'topology_summary.json').read_text())
    resolved = json.loads((root / 'topology_resolved.json').read_text())
    count = topology['modules']
    assert count > 1 and count == len(topology['links']) == len(resolved['modules'])
    assert topology['passed'] and topology['accepted'] == topology['completed']

    per_link = []
    for descriptor in topology['links']:
        index = descriptor['id']
        link = root / descriptor['result_dir']
        axi = check_axi(link)
        check_aou(link)
        inspect(link)
        ramulator = check_ramulator(link) if (link / 'ramulator_commands.csv').exists() else None
        per_link.append(dict(id=index, transactions=axi['transactions'],
                             ramulator_children=ramulator['children'] if ramulator else None,
                             dram_energy_j=ramulator['total_energy_j'] if ramulator else None))

    merged = rows(root / 'transactions.csv')
    metadata = rows(root / 'request_metadata.csv')
    assert len(merged) == topology['completed'] == sum(x['transactions'] for x in per_link)
    assert len(metadata) == len(merged)
    assert len({row['uid'] for row in metadata}) == len(metadata)
    for descriptor in topology['links']:
        index = descriptor['id']
        link_rows = rows(root / descriptor['result_dir'] / 'transactions.csv')
        root_rows = [without_module(row) for row in merged if int(row['module']) == index]
        assert root_rows == link_rows, f'merged transaction evidence differs for module {index}'

    routing = resolved['routing']
    assert routing['policy'] == 'address_interleave'
    stripe = routing['stripe_bytes']
    assert stripe > 0 and not stripe & (stripe - 1)
    for transaction in merged:
        address = int(transaction['address'])
        size = int(transaction['bytes'])
        assert size <= stripe, 'a routed request is larger than one address stripe'
        assert address // stripe == (address + size - 1) // stripe, 'request crosses an address stripe'
        assert int(transaction['module']) == (address // stripe) & (count - 1)

    metric_result = check_metrics(root) if (root / 'metrics.json').exists() else None
    if metric_result:
        overall = json.loads((root / 'metrics.json').read_text())['overall']
        links = overall['topology']['links']
        assert [x['metrics']['traffic']['requests'] for x in links] == [x['transactions'] for x in per_link]
        energy = [x['dram_energy_j'] for x in per_link if x['dram_energy_j'] is not None]
        if energy:
            assert math.isclose(overall['dram_energy_j'], sum(energy), rel_tol=1e-10,
                                abs_tol=1e-20)
            intervals = rows(root/'power_intervals.csv')
            assert intervals and all(row['channel'].startswith('m') for row in intervals)
            assert math.isclose(sum(float(row['total_energy_j']) for row in intervals),
                                overall['dram_energy_j'], rel_tol=1e-9, abs_tol=1e-18)
            full = next(window for window in overall['window_statistics']
                        if window['name'] == 'full_run')
            assert math.isclose(full['dram_energy_j'], overall['dram_energy_j'],
                                rel_tol=1e-10, abs_tol=1e-20)

    result = dict(passed=True, modules=count, routing_policy=routing['policy'],
                  stripe_bytes=stripe, transactions=len(merged), links=per_link,
                  checks=['per-link AXI data and lifetime', 'per-link AXI/AoU/VCD equivalence',
                          'per-link UCIe exact delivery', 'per-link Ramulator command/data/power',
                          'merged evidence conservation', 'unique global request UID',
                          'address-interleave ownership', 'aggregate metric and energy conservation'])
    (root / 'topology_check.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    print(json.dumps(check(parser.parse_args().directory), indent=2))
