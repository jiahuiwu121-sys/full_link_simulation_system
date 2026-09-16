"""Per-standard testcase data for smoke tests."""

from tests.smoke.testcases.hbm3 import CONFIG as HBM3_CONFIG
from tests.smoke.testcases.hbm4 import CONFIG as HBM4_CONFIG
from tests.smoke.testcases.lpddr5 import CONFIG as LPDDR5_CONFIG
from tests.smoke.testcases.lpddr6 import CONFIG as LPDDR6_CONFIG

STANDARDS = {
    "HBM3": HBM3_CONFIG,
    "HBM4": HBM4_CONFIG,
    "LPDDR5": LPDDR5_CONFIG,
    "LPDDR6": LPDDR6_CONFIG,
}
