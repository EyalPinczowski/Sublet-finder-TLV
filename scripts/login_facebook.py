#!/usr/bin/env python3
"""Open a browser to log into Facebook and save the session for scanning.

Usage: python scripts/login_facebook.py
"""
import _bootstrap  # noqa: F401

from src.browser import login_and_save_session

if __name__ == "__main__":
    login_and_save_session()
