#!/usr/bin/env python3
"""Scan configured Facebook groups for apartments matching your search.

Usage: python scripts/scan.py [--headed] [--dry-run]
"""
import argparse

import _bootstrap  # noqa: F401

from src.cli import cmd_scan

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--headed", action="store_true", help="Show the browser window")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and print what would match, without writing to the DB or notifying",
    )
    cmd_scan(parser.parse_args())
