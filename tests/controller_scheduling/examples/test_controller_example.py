import pytest

import ramulator
import tests.controller_scheduling.harness as cs


pytestmark = pytest.mark.controller_scheduling


def make_hbm3():
    return ramulator.dram.HBM3(org_preset="HBM3_8Gb_8hi", timing_preset="HBM3_6400Mbps")


def make_dut():
    return cs.ControllerUnderTest.make_hbm34(
        make_hbm3(),
        row_policy=ramulator.row_policy.Open(),
    )


def test_controller_under_test_example_request_flow():
    # Build a deterministic controller stack around one HBM3 device.
    dram = make_hbm3()
    dut = cs.ControllerUnderTest.make_hbm34(dram)

    row0 = dut.addr_vec(PseudoChannel=0, Sid=0, BankGroup=0, Bank=0, Row=0, Column=0)
    row1 = dut.addr_vec(PseudoChannel=0, Sid=0, BankGroup=0, Bank=0, Row=1, Column=0)

    # Two reads to different rows in the same bank create a row conflict.
    dut.send_request("Read", row0)
    dut.send_request("Read", row1)
    history = dut.run_until_idle(max_ticks=512)

    dut.assert_commands(["ACT", "RD", "PREpb", "ACT", "RD"], history=history)
    # HBM column commands also wait for a rising edge. Timing values are
    # expressed in half-CK ticks, with command-duration offsets applied.
    assert history[1].clk - history[0].clk >= dut.timings["nRCDRD"] + 1
    assert history[3].clk - history[2].clk >= dut.timings["nRP"] - 2
    assert history[4].clk - history[3].clk >= dut.timings["nRCDRD"] + 1


def test_controller_under_test_example_priority_flow():
    # Use a fresh DUT so the maintenance example is easy to read in isolation.
    dut = make_dut()
    refresh = dut.addr_vec(
        PseudoChannel=0, Sid=dut.ALL, BankGroup=dut.ALL,
        Bank=dut.ALL, Row=dut.ALL, Column=dut.ALL,
    )

    dut.priority_send("REFab", refresh)
    history = dut.run_until_idle(max_ticks=128)
    stats = dut.stats()

    dut.assert_commands(["REFab"], history=history)
    assert stats["num_maintenance_reqs"] == 1
    assert stats["num_maintenance_reqs_served"] == 1
