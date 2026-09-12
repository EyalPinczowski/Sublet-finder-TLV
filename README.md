# TLV Sublet Finder

Watches Tel Aviv Facebook groups for people **offering** a sublet, checks
each one against your own price/rooms/neighborhood/roommate/bathroom
criteria using cheap local keyword/regex matching (no API calls, fully
free), and optionally pings you on Telegram the instant a match shows up.

## How it works

1. Log into Facebook once to create a session:
   - **No display available (e.g. Termux/proot)**: `python scripts/login_facebook_headless.py`
     asks for your email and password right in the terminal (password hidden)
     and logs in headlessly. If Facebook challenges the login, it asks you
     for the code, or tells you to approve it from your phone's Facebook app.
     Note: Facebook may throw a CAPTCHA at headless logins — if it does,
     you'll need a real screen (below) since a CAPTCHA has to be clicked by
     a human, not scripted.
   - **Normal machine with a screen**: `python scripts/login_facebook.py`
     opens a real visible browser for you to log in.
   Either way, the session is saved to `data/storage_state.json`.
2. `scripts/scan.py` uses that session to open each group in `config.yaml`,
   pulls recent posts, and for each new one that looks like an *offer*
   (not someone else looking for a place), parses out price/rooms/
   neighborhood/roommates/bathrooms and checks it against your `search`
   criteria. Everything is stored in `data/listings.db` (SQLite), so
   re-running never double-processes a post.
3. A match is printed to the console and, if Telegram is configured, sent
   to you immediately.
4. `scripts/matches.py` lists everything that's matched so far, whether or
   not Telegram is set up.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Edit `config.yaml` with the groups you're a member of and your own search
criteria (price range, neighborhoods, room/roommate/bathroom requirements).

To also get instant Telegram pings for matches: message
[@BotFather](https://t.me/BotFather) on Telegram to create a bot and get its
token, message your new bot once, then fetch
`https://api.telegram.org/bot<TOKEN>/getUpdates` to find your chat ID.
Copy `.env.example` to `.env` and fill in `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_ID`. Skip this entirely to just use `scripts/matches.py`.

## Usage

```bash
python scripts/login_facebook_headless.py   # or login_facebook.py with a screen
python scripts/scan.py                      # pulls posts and checks for matches
python scripts/matches.py                   # list everything matched so far
```

Re-run the login script whenever the session expires (Facebook logs you out
after a while of inactivity, or if it flags the login as suspicious).

## Tests

```bash
pip install pytest
pytest
```

Tests cover the listing parser and filter logic (no live Facebook or
Telegram calls).

## Important caveats

- **Facebook's Terms of Service prohibit automated scraping**, even of
  groups you belong to. This tool automates *your own* logged-in browser
  session for personal use, not bulk data collection or spam — but that's
  still a gray area under Facebook's ToS, and your account could be flagged
  or restricted. Use at your own risk, keep scan frequency low, and never
  leave it running unattended at scale.
- Facebook's markup changes often and uses randomized class names, so the
  scraper in `src/scraper.py` relies on structural hints (`role="article"`,
  permalink patterns) that may need small tweaks over time if extraction
  stops finding posts.
- **The listing parser (`src/listing_parser.py`) is a keyword/regex
  heuristic, not a language model** — it will miss some genuine listings
  and occasionally flag a false positive. Tune `search.excluded_keywords`
  in your config to cut down on noise.
