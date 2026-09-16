"""Keep the public configuration API and compiled factory in agreement."""

import pytest

import ramulator
from ramulator._ramulator_test import _ControllerUnderTest, _DeviceUnderTest
from tests.smoke.testcases import STANDARDS
from tests.utils import create_dram


SUPPORTED = {"HBM3", "HBM4", "LPDDR5", "LPDDR6"}
REMOVED = (
    "DDR3", "DDR4", "DDR4_VRR", "DDR5", "DDR5_RFM", "DDR5_RFM_VRR",
    "DDR5_VRR", "GDDR6", "GDDR7", "HBM1", "HBM2",
)


def test_public_standard_and_controller_catalogs():
    assert set(ramulator.dram.__all__) == SUPPORTED
    assert set(STANDARDS) == SUPPORTED
    assert set(ramulator.controller.__all__) == {"HBM34", "LPDDR5", "LPDDR6"}


@pytest.mark.parametrize("standard", sorted(SUPPORTED))
def test_retained_standard_loads_in_cpp(standard):
    dram = create_dram(STANDARDS[standard])
    dut = _DeviceUnderTest(dram.to_config())
    assert list(dut.command_names) == dram.commands
    assert list(dut.level_names) == list(dram.levels)


@pytest.mark.parametrize("standard", REMOVED)
def test_removed_standard_is_not_registered(standard):
    assert not hasattr(ramulator.dram, standard)
    with pytest.raises(RuntimeError, match="Unknown DRAM standard"):
        _DeviceUnderTest({"impl": standard})


@pytest.mark.parametrize("controller", ("GenericDDR", "HBM12", "GDDR7", "PRAC", "BlockHammer"))
def test_removed_controller_is_not_registered(controller):
    assert not hasattr(ramulator.controller, controller)
    with pytest.raises(RuntimeError, match="not registered"):
        _ControllerUnderTest({"impl": controller})
