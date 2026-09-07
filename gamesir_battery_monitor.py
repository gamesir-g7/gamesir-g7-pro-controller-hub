#!/usr/bin/env python3
"""Compatibility entry point for the former project name."""

from openpad.cli import main
from openpad.drivers.cyclone2 import parse_cyclone2_report, parse_upower

__all__ = ["main", "parse_cyclone2_report", "parse_upower"]


if __name__ == "__main__":
    raise SystemExit(main())
