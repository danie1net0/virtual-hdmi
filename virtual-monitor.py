#!/usr/bin/env python3
"""
Virtual monitor: opens the window, or runs in the terminal with options.

  python3 virtual-monitor.py                      opens the window
  python3 virtual-monitor.py --list               session, connector and modes
  python3 virtual-monitor.py --apply ID [--temp]  applies mode ID (without --temp, remembers it at login)
  python3 virtual-monitor.py --restore            reapplies the last remembered mode
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from virtual_monitor.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
