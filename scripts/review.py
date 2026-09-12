#!/usr/bin/env python3
"""Review new leads one by one and approve/reject/edit outreach drafts.

Usage: python scripts/review.py
"""
import _bootstrap  # noqa: F401

from src.cli import cmd_review

if __name__ == "__main__":
    cmd_review(None)
