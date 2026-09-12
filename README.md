# TLV Apartment Sublet Agent

Scans Tel Aviv Facebook groups for **both sides of a sublet move**, in one
pass over the same posts:

- **Finding a subletter for your current apartment** — screens posts where
  people are *looking for* a place using Google's Gemini API (free tier, no
  credit card required), scores their fit against your apartment, and drafts
  a personalized outreach message for each good match. Everything is queued
  for you to review before anything is sent — **it never sends messages on
  its own.**
- **Finding your next apartment** — checks posts where people are *offering*
  a sublet against your own price/rooms/neighborhood/roommate/bathroom
  criteria using cheap local keyword/regex matching (no API calls), and can
  ping you on Telegram the moment a match shows up.

Both sides only need you to log into Facebook and configure `config.yaml`
once; skip the `apartment_search`/`telegram` config if you only want the
subletter-finding side, or skip `apartment` if you only want the
apartment-finding side.

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
2. `scripts/scan.py` uses that session to open each group in `config.yaml`
   and pulls recent posts. For each new post:
   - If it looks like someone **offering** a sublet, it's parsed for price/
     rooms/neighborhood/roommates/bathrooms and checked against your
     `apartment_search` criteria — a match is stored and, if `telegram` is
     configured, sent to you immediately.
   - Otherwise, if it looks like someone **seeking** a place, it's sent to
     Gemini to screen (how good a fit for your apartment?) and draft a
     reply for good matches.
   Everything is stored in `data/leads.db` (SQLite), so re-running never
   double-processes a post.
3. `scripts/review.py` walks you through new subletter leads one at a
   time — approve, reject, or edit the draft.
4. `scripts/approved.py` prints the final messages + post links for
   everything you approved, so you can copy them into Facebook Messenger
   yourself.
5. `scripts/matches.py` lists apartments found matching your own search
   criteria, whether or not Telegram is set up.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env   # then fill in GEMINI_API_KEY
```

Get a free Gemini API key (no credit card needed) at
[aistudio.google.com/apikey](https://aistudio.google.com/apikey).

Edit `config.yaml` with your apartment's real details, the groups you're a
member of, your keywords, and (if you want the apartment-finding side) your
own search criteria under `apartment_search`.

To also get instant Telegram pings for apartment matches: message
[@BotFather](https://t.me/BotFather) on Telegram to create a bot and get its
token, message your new bot once, then fetch
`https://api.telegram.org/bot<TOKEN>/getUpdates` to find your chat ID.
Uncomment and fill in the `telegram` section in `config.yaml`.

## Usage

```bash
python scripts/login_facebook_headless.py   # or login_facebook.py with a screen
python scripts/scan.py                      # pulls, classifies, screens/drafts, matches
python scripts/review.py                    # approve/reject/edit subletter drafts
python scripts/approved.py                  # get the final subletter messages to send
python scripts/matches.py                   # list apartments matching your own search
```

Re-run the login script whenever the session expires (Facebook logs you out
after a while of inactivity, or if it flags the login as suspicious).

## Tests

```bash
pip install pytest
pytest
```

Tests cover the listing parser and filter logic used for the
apartment-finding side (no live Facebook, Gemini, or Telegram calls).

## Important caveats

- **Facebook's Terms of Service prohibit automated scraping**, even of
  groups you belong to. This tool automates *your own* logged-in browser
  session for personal use (finding a subletter for your own apartment),
  not bulk data collection or spam — but that's still a gray area under
  Facebook's ToS, and your account could be flagged or restricted. Use at
  your own risk, keep scan frequency low, and never leave it running
  unattended at scale.
- Facebook's markup changes often and uses randomized class names, so the
  scraper in `src/scraper.py` relies on structural hints (`role="article"`,
  permalink patterns) that may need small tweaks over time if extraction
  stops finding posts.
- Messages are **never sent automatically** — `scripts/approved.py` only
  prints text for you to paste in yourself.
- **The apartment-offer parser (`src/listing_parser.py`) is a keyword/regex
  heuristic, not a language model** — it will miss some genuine listings and
  occasionally flag a false positive. Tune `apartment_search.excluded_keywords`
  in your config to cut down on noise.
- The Gemini free tier is rate-limited (roughly 10-15 requests/minute,
  a few hundred/day) and Google can change these limits without notice.
  `scripts/scan.py` already pauses a few seconds between calls to stay
  under them; if you hit a quota error, wait and re-run later — scanning
  never reprocesses posts it already saw.
