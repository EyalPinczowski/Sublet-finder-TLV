#!/usr/bin/env python3
"""List approved leads ready to send, with their final message text.

Usage: python scripts/approved.py
"""
import _bootstrap  # noqa: F401

from src.cli import cmd_approved

if __name__ == "__main__":
    cmd_approved(None)
