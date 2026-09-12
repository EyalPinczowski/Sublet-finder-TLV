# TLV Apartment Sublet Agent

Finds people in Facebook groups who are looking for a sublet apartment in
Tel Aviv, screens and scores them against your specific apartment using
Google's Gemini API (free tier, no credit card required), drafts a
personalized outreach message for each good match, and queues everything
for you to review before anything is sent. **It never sends messages on
its own.**

## How it works

1. Log into Facebook once to create a session:
   - **No display available (e.g. Termux/proot)**: `python scripts/login_facebook_headless.py`
     asks for your email and password right in the terminal (password hidden)
     and logs in headlessly. If Facebook challenges the login, it asks you
     for the code, or tells you to approve it from your phone's Facebook app.
   - **Normal machine with a screen**: `python scripts/login_facebook.py`
     opens a real visible browser for you to log in.
   Either way, the session is saved to `data/storage_state.json`.
2. `scripts/scan.py` uses that session to open each group in `config.yaml`,
   pulls recent posts, keyword-filters them, and sends candidates to Gemini
   to screen (are they looking for housing? how good a fit?) and draft a
   reply for the good matches. Everything is stored in `data/leads.db`
   (SQLite), so re-running never double-processes a post.
3. `scripts/review.py` walks you through new leads one at a time — approve,
   reject, or edit the draft.
4. `scripts/approved.py` prints the final messages + post links for
   everything you approved, so you can copy them into Facebook Messenger
   yourself.

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
member of, and your keywords.

## Usage

```bash
python scripts/login_facebook_headless.py   # or login_facebook.py with a screen
python scripts/scan.py                      # pulls + screens + drafts new leads
python scripts/review.py                    # approve/reject/edit drafts
python scripts/approved.py                  # get the final messages to send
```

Re-run the login script whenever the session expires (Facebook logs you out
after a while of inactivity, or if it flags the login as suspicious).

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
- The Gemini free tier is rate-limited (roughly 10-15 requests/minute,
  a few hundred/day) and Google can change these limits without notice.
  `scripts/scan.py` already pauses a few seconds between calls to stay
  under them; if you hit a quota error, wait and re-run later — scanning
  never reprocesses posts it already saw.
