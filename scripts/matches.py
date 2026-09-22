#!/usr/bin/env python3
"""List apartments found matching your search criteria (config.yaml's
search section), best score first.

Usage: python scripts/matches.py
"""
import _bootstrap  # noqa: F401

from src.cli import cmd_matches

if __name__ == "__main__":
    cmd_matches(None)
