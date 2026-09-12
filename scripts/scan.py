#!/usr/bin/env python3
"""Scan configured Facebook groups for new sublet leads.

Usage: python scripts/scan.py [--headed]
"""
import argparse

import _bootstrap  # noqa: F401

from src.cli import cmd_scan

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--headed", action="store_true", help="Show the browser window")
    cmd_scan(parser.parse_args())
