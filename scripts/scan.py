#!/usr/bin/env python3
"""Scan configured Facebook groups for apartments matching your search.

Usage: python scripts/scan.py [--headed] [--dry-run] [--explain] [--posts-per-group N]
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
    parser.add_argument(
        "--explain",
        action="store_true",
        help=(
            "Sanity-check mode: for every extracted offer-listing that matches no "
            "search profile, print the specific reason(s) it was rejected. Implies "
            "--dry-run (never writes to the DB or notifies)."
        ),
    )
    parser.add_argument(
        "--posts-per-group",
        type=int,
        default=None,
        help=(
            "Override config.yaml's posts_per_group for this run only — e.g. "
            "--posts-per-group 3 for a quick manual test that burns through far "
            "fewer LLM calls than a full scan."
        ),
    )
    cmd_scan(parser.parse_args())
