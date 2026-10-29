#!/usr/bin/env python3
"""Repository convenience entry; implementation stays inside the new bridge."""
from pathlib import Path
import runpy
import sys

if __name__ == '__main__':
    tools = Path(__file__).resolve().parents[1]/'ucie_mc_bridge/tools'
    sys.path.insert(0,str(tools))
    runpy.run_path(str(tools/'run.py'),run_name='__main__')
