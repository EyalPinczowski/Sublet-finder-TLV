#!/usr/bin/env python3
"""Long-polls Telegram for taps on the ⭐ Save / \U0001f5d1 Dismiss
buttons attached to each alert, and records them.

This must run continuously (a systemd service, a tmux/screen session,
`pm2`, etc.) — long-polling `getUpdates` isn't cron-friendly. It needs
nothing beyond the same TELEGRAM_BOT_TOKEN already configured for outbound
alerts.

Usage: python scripts/bot_listener.py
"""
from __future__ import annotations

import time

import _bootstrap  # noqa: F401
import requests

from src import store
from src.config import load_config

POLL_TIMEOUT_SEC = 30


def _answer_callback(bot_token: str, callback_id: str, text: str) -> None:
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": text},
            timeout=10,
        )
    except Exception as exc:
        print(f"[bot_listener] answerCallbackQuery failed: {exc}")


def _handle_update(conn, bot_token: str, update: dict) -> None:
    cq = update.get("callback_query")
    if not cq or "|" not in (cq.get("data") or ""):
        return
    action, token = cq["data"].split("|", 1)
    post_url = store.post_url_for_token(conn, token)
    if not post_url:
        _answer_callback(bot_token, cq["id"], "This listing is no longer available.")
        return

    user_id = str(cq.get("from", {}).get("id", "unknown"))
    if action == "save":
        store.add_mark(conn, post_url, user_id, "save")
        _answer_callback(bot_token, cq["id"], "Saved ⭐")
    elif action == "dismiss":
        store.add_mark(conn, post_url, user_id, "dismiss")
        _answer_callback(bot_token, cq["id"], "Dismissed \U0001f5d1")


def main() -> None:
    config = load_config()
    if not config.telegram:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set in .env — nothing to listen for."
        )
    bot_token = config.telegram.bot_token
    offset = None
    print("Listening for Telegram button taps (Ctrl+C to stop)...")
    # One connection for the whole run, not one per poll cycle — store.
    # connect() re-runs a schema/migration check on open, which is wasted
    # work every ~30s for the lifetime of a long-running process. Each
    # batch of updates still gets its own explicit commit below, so a vote
    # tap is durable promptly rather than sitting in one long-lived
    # transaction for as long as the process happens to stay up.
    with store.connect() as conn:
        while True:
            try:
                resp = requests.get(
                    f"https://api.telegram.org/bot{bot_token}/getUpdates",
                    params={"timeout": POLL_TIMEOUT_SEC, "offset": offset},
                    timeout=POLL_TIMEOUT_SEC + 10,
                )
                resp.raise_for_status()
                updates = resp.json().get("result", [])
            except Exception as exc:
                print(f"[bot_listener] getUpdates failed: {exc}")
                time.sleep(5)
                continue

            if not updates:
                continue
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    _handle_update(conn, bot_token, update)
                except Exception as exc:
                    print(f"[bot_listener] error handling update {update.get('update_id')}: {exc}")
            conn.commit()


if __name__ == "__main__":
    main()
