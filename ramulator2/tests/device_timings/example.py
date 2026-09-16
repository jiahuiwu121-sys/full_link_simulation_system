import pytest

import ramulator
import tests.device_timings.harness as device_timings


pytestmark = pytest.mark.device_timings


def test_device_under_test_example_flow():
    # Build a normal DRAM object first, then wrap it in DeviceUnderTest.
    dram = ramulator.dram.HBM3(org_preset="HBM3_8Gb_8hi", timing_preset="HBM3_6400Mbps")
    dut = device_timings.DeviceUnderTest(dram)

    # Named address construction keeps short protocol tests readable.
    a = dut.addr_vec(PseudoChannel=0, Sid=0, BankGroup=0, Bank=0, Row=12, Column=0)

    # A closed-bank read is functionally blocked until the row is opened.
    closed = dut.probe("RD", a, clk=0)
    # Without ACT issued, the prerequisite is ACT.
    assert closed.preq == "ACT"
    # Here we only check the timing constraints. The timing is OK here since no ACT has been issued yet!
    assert closed.timing_OK is True
    # ready means the command is fully issuable now: correct prerequisite and timing_OK.
    assert closed.ready is False

    # Open the row at cycle 0.
    dut.issue("ACT", a, clk=0)

    # ACT occupies 3 half-CK ticks and RD occupies 2. The interval measured
    # between their first ticks is nRCDRD + (3 - 2).
    rd_clk = dut.timings["nRCDRD"] + 1
    early = dut.probe("RD", a, clk=rd_clk - 1)
    assert early.preq == "RD"
    assert early.timing_OK is False
    assert early.ready is False
    assert early.row_hit is True
    assert early.row_open is True

    # At rd_clk, the same command becomes legal at device level.
    # The controller additionally restricts RD to rising edges.
    ontime = dut.probe("RD", a, clk=rd_clk)
    assert ontime.preq == "RD"
    assert ontime.timing_OK is True
    assert ontime.ready is True

    # The actual read can now issue.
    dut.issue("RD", a, clk=rd_clk)

    # The "probe at clk-1 is blocked, probe at clk is ready" pair is the
    # canonical "this timing gate is tight" check. assert_earliest_ready_at
    # bundles both probes into a single self-describing assertion.
    # Here: PREpb after RD must wait for both nRTP (RD→PRE) and nRAS (ACT→PRE).
    t_pre = max(
        rd_clk + dut.timings["nRTP"] + 1,  # RD (2 ticks) -> PRE (1 tick)
        dut.timings["nRAS"] + 2,  # ACT (3 ticks) -> PRE (1 tick)
    )
    dut.assert_earliest_ready_at("PREpb", a, t_pre)
    dut.issue("PREpb", a, clk=t_pre)
