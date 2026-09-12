#!/usr/bin/env python3
"""List apartments found matching your own search criteria (config.yaml's
apartment_search section) — the mirror of scripts/approved.py, which lists
subletters found for your own apartment.

Usage: python scripts/matches.py
"""
import _bootstrap  # noqa: F401

from src.cli import cmd_matches

if __name__ == "__main__":
    cmd_matches(None)
