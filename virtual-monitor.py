#!/usr/bin/env python3
"""
Virtual monitor: opens the window, or runs in the terminal with options.

  python3 virtual-monitor.py           opens the window
  python3 virtual-monitor.py --help    lists the terminal options
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from virtual_monitor.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
