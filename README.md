# TLV Apartment Sublet Agent

Finds people in Facebook groups who are looking for a sublet apartment in
Tel Aviv, screens and scores them against your specific apartment using
Claude, drafts a personalized outreach message for each good match, and
queues everything for you to review before anything is sent. **It never
sends messages on its own.**

## How it works

1. `scripts/login_facebook.py` opens a real browser so you can log into
   Facebook yourself. Your session is saved locally to `data/storage_state.json`.
2. `scripts/scan.py` uses that session to open each group in `config.yaml`,
   pulls recent posts, keyword-filters them, and sends candidates to Claude
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

cp .env.example .env   # then fill in ANTHROPIC_API_KEY
```

Edit `config.yaml` with your apartment's real details, the groups you're a
member of, and your keywords.

## Usage

```bash
python scripts/login_facebook.py   # once, and again whenever the session expires
python scripts/scan.py             # pulls + screens + drafts new leads
python scripts/review.py           # approve/reject/edit drafts
python scripts/approved.py         # get the final messages to send
```

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
