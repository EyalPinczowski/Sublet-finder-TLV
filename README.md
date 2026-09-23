# TLV Sublet Finder

Watches Tel Aviv Facebook groups for people **offering** a sublet, checks
each one against one or more named search profiles (e.g. a single room for
yourself vs. two rooms to move in with a friend — see
[Multiple search profiles](#multiple-search-profiles)), scores and ranks
the matches, and pings you on Telegram — with a summary, the address, a
phone/WhatsApp link, the post's photos, and a link back to the post itself
— the instant a good one shows up.

Everything beyond the core scan/match/notify loop is **optional and off by
default**: skip any of it and the tool keeps working with what's configured.

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
   pulls recent posts, and for each new one that looks like an *offer* (not
   someone else looking for a place), extracts price/rooms/available-rooms/
   address/roommates/bathrooms/phone/photos and checks it against **every**
   profile in your `searches:` list (and, if configured, the zone-distance
   check below) — a post can match more than one profile. Extraction uses
   the Gemini LLM when `GEMINI_API_KEY` is set (far more reliable on
   colloquial Hebrew), automatically falling back to a regex/keyword parser
   otherwise or whenever the LLM is unavailable this run. Everything is
   stored in `data/listings.db` (SQLite), so re-running never double-
   processes a post — including cross-posts and comment-less posts with no
   recoverable permalink, which are matched on their content instead.
3. Each matched profile gets its own score (0-100, `src/scoring.py`) and its
   own Telegram alert — with that profile's emoji/name in the header (the
   "color"), a summary, price/rooms/roommates/bathrooms/available-rooms, the
   address, a phone/WhatsApp link when there is one, a link to the post, a
   Google Maps link, and the post's own photos — plus ⭐ Save / 🗑 Dismiss
   buttons if you're running the [vote listener](#telegram-vote-buttons).
4. `scripts/matches.py` lists everything that's matched so far, best score
   first, whether or not Telegram is set up.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Edit `config.yaml` with the groups you're a member of, your own search
profile(s) (price range, neighborhoods, room/roommate/bathroom requirements
— see [Multiple search profiles](#multiple-search-profiles)), and the
`llm:`/`zone:` blocks described below.

Copy `.env.example` to `.env` and fill in whichever of the following you
want — **every one of them is optional**, and the tool degrades gracefully
(falls back or simply skips that feature) when a given one is left unset:

| Variable | Enables | Get it from |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Instant match alerts | [@BotFather](https://t.me/BotFather) to create a bot + message it once, then `https://api.telegram.org/bot<TOKEN>/getUpdates` for your chat id |
| `GEMINI_API_KEY` | LLM-based extraction (recommended) | https://aistudio.google.com/apikey (free tier) |
| `GOOGLE_SHEET_ID` | [Google Sheets sink](#google-sheets) | see below |
| `DASHBOARD_TOKEN` | [Live dashboard](#dashboard) | any random string — auto-generated if left blank |
| `SITE_REPO_URL` | [Published snapshot](#publishing-a-snapshot) | a dedicated repo you create |

Skip all of them to just run `scripts/scan.py` and check
`scripts/matches.py` by hand.

### LLM-based extraction

With `GEMINI_API_KEY` set and `llm.enabled: true` in `config.yaml` (the
default), each post is sent to Gemini's free tier for extraction — far more
reliable on colloquial Hebrew than the regex parser, and it also classifies
offer-vs-seeker posts and writes a real one-line summary. A daily request
budget (`llm.daily_budget`, default 400 — well under Gemini's free-tier
~500/day/model cap) and a minimum interval between calls
(`llm.min_interval_seconds`) keep you inside the free tier. Whenever the key
is unset, the budget is spent, or a call fails, extraction falls back to
`src/listing_parser.py`'s regex/keyword heuristic automatically — a run
never hard-fails over this.

### Zone scoring

`config.yaml`'s `zone:` block scores listings by straight-line distance to a
single point you care about (a workplace, a landmark — defaults to
Dizengoff Square), in addition to (not instead of) a profile's own
`neighborhoods` keyword list: a listing within `zone.max_distance_meters`
counts as a location match even if its address text doesn't mention any of
that profile's configured neighborhoods. Geocoding is free (OpenStreetMap
Nominatim, no key, cached to `data/geocode_cache.json` so nothing is looked
up twice). There's no walk-time/routing — just distance.

### Multiple search profiles

`config.yaml`'s `searches:` is a list of **named** profiles — every post is
checked against **all** of them in the same scan (no separate runs, and
nothing gets re-scraped or re-processed per profile). The shipped default
has two:

```yaml
searches:
  - name: "single room"
    emoji: "🟢"
    min_available_rooms: 1
    max_available_rooms: 1
    price_min: 2700
    price_max: 3600
    # ... neighborhoods, max_roommates, min_bathrooms, etc. — same fields
    # as before, just nested under a named profile now.
  - name: "two rooms (with a friend)"
    emoji: "🔵"
    min_available_rooms: 2
    price_min: 5400
    price_max: 7200
```

`min_available_rooms`/`max_available_rooms` filter on **how many rooms/spots
the post is offering right now** — a new field, distinct from `min_rooms`
(the apartment's total size). This is what makes "single room" and "two
rooms" mean different things: a post offering one open room in a 3-room
apartment has `available_rooms: 1` even though `rooms: 3`.

A post can match more than one profile (e.g. if your profiles' price ranges
overlap) — it gets a separate alert per profile it matches, each scored
independently (a listing can score very differently under two profiles with
different price ranges) and prefixed with that profile's own `emoji`. That
emoji is the "color" mentioned above — Telegram alerts can't carry literal
text color, so a distinct emoji per profile is what makes two profiles'
alerts visually distinct at a glance, in the chat and in notifications.
`scripts/matches.py`, the dashboard, and the published snapshot all show
which profile(s) each listing matched too.

Add, remove, rename, or retune profiles freely — a single legacy `search:`
block (no `searches:` list) still works and is treated as one profile named
`"default"`.

### Stay length and dates

`config.yaml`'s top-level `stay:` block (shared across every profile — it's
about when *you* can move, not room count) requires a minimum stay and a
rolling window for when the lease must start:

```yaml
stay:
  min_days: 14                # anything shorter is dropped
  search_window_days: 21      # only listings starting today..+21 days
```

**A listing needs *some* date/duration info to be considered at all — a
deliberate exception to this tool's usual rule that missing data passes a
filter.** Every other field (price, rooms, bathrooms, …) shows up as a
match when unknown; a post that says nothing about when it starts or how
long it runs is dropped outright, since there's nothing to check the
minimum-stay and search-window rules against. This is enforced in
`src/listing_filters.matches()`, clearly marked as the one hard gate in an
otherwise soft-filter function. A post stating only a duration ("שבועיים",
no specific start date) still passes the window check — you said dates
"could be... a period of time," so a bare duration is enough to clear the
hard gate, it just can't be checked against the *window* specifically.

**Price proration**: your `price_min`/`price_max` are a monthly budget.
When a listing's stay is under 30 days, that budget is prorated down
(`price * duration_days/30`) before comparing it against the post's price
— which is treated as the **total for its stated period**, not a monthly
rate, for a short-term post. A stay of a month or longer is never
prorated *up*; ordinary monthly-rate listings are unaffected. Dates are
extracted the same way as everything else — Gemini gets today's date in
its prompt so it can resolve "מיידי"/bare `DD.MM`/date ranges into real
dates; the regex fallback handles a handful of common phrasings
(`שבוע`/`שבועיים`/`חודש`, `DD.MM`–`DD.MM` ranges, `X ימים`/`שבועות`/`חודשים`)
with a year inferred from whether the date has already passed this year.

A missing price is still shown explicitly, everywhere (the Telegram alert,
the Sheets row, the dashboard, the published snapshot) — an
otherwise-matching listing with no stated price says "Price not listed"
rather than silently omitting the line, so it doesn't look identical to
one that was simply cut off.

## Usage

```bash
python scripts/login_facebook_headless.py   # or login_facebook.py with a screen
python scripts/scan.py                      # pulls posts and checks for matches
python scripts/scan.py --dry-run            # classify and print, without writing/notifying
python scripts/matches.py                   # list everything matched so far, best score first
```

Re-run the login script whenever the session expires (Facebook logs you out
after a while of inactivity, or if it flags the login as suspicious). A scan
refuses to start a second time while one is already running (a lock file in
`data/scan.lock`), and stops cleanly instead of scraping garbage if Facebook
shows a checkpoint/login wall.

## Optional extras

### Telegram vote buttons

Each alert carries ⭐ Save / 🗑 Dismiss buttons. Saving nudges a listing's
score; dismissing hides it from `matches.py`/the dashboard without deleting
it. Handling taps needs a **separate, continuously-running** process (long-
polling isn't cron-friendly):

```bash
python scripts/bot_listener.py
```

Run it under a systemd service, a `tmux`/`screen` session, `pm2`, or
similar — whatever keeps a process alive on your machine. It needs nothing
beyond the same `TELEGRAM_BOT_TOKEN` already configured.

### Dashboard

```bash
python scripts/dashboard.py [--port 8765]
```

A local page (stdlib-only, no extra dependency) that reads `data/listings.db`
live and lists matches best-first, with the same Save/Dismiss actions. Every
route requires `?token=<DASHBOARD_TOKEN>` — there is no unauthenticated mode,
since listings carry addresses and phone numbers. Binds to `127.0.0.1` only:
**LAN/local-only by design, never expose this port to the internet.**

### Publishing a snapshot

```bash
python scripts/publish.py
```

Renders a static HTML snapshot and pushes it to a **dedicated** repo
(`SITE_REPO_URL`) for GitHub Pages, so you can check matches away from your
network. Read this before using it:

- **Create a separate repo for this** — never point `SITE_REPO_URL` at this
  code repo, or addresses/prices/phone numbers end up permanently in its
  public git history.
- **GitHub Pages on a public repo has no access control.** The published
  page carries a `noindex` hint (keeps it out of search engines), but
  anyone with the URL can open it. A private Pages site needs GitHub
  Pro/Enterprise. If that's not acceptable, use the [dashboard](#dashboard)
  instead and skip this.

### Google Sheets

Mirrors every matched listing into a shared Sheet you can sort/filter by
hand — additive to SQLite, disabled until set up. Includes a `suitable_for`
column ("1 person" / "2 people" / …) derived from the post's
`available_rooms`, plus `lease_start`/`stay_days` columns, so you can sort
and filter by move-in date and stay length right there too. A missing
price shows as the text "not listed" rather than a blank cell.

1. In **Google Cloud Console**: create a project → enable the **Google
   Sheets API** → create a **service account** → download its JSON key.
2. Save that file as `auth/google_service_account.json` (the `auth/` folder
   is git-ignored — the key never gets committed).
3. Create a Google Sheet, open the JSON key and copy its `client_email`,
   then **share the sheet with that email as Editor**.
4. Copy the sheet's id from its URL
   (`docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit`) into `.env` as
   `GOOGLE_SHEET_ID`.

## Tests

```bash
pip install pytest ruff
pytest
ruff check .
```

Tests are all offline/pure-function — no live Facebook, Telegram, Gemini,
Nominatim, or Google Sheets calls, and they never touch `data/listings.db`
(each test that needs a database points `src.store` at a throwaway file).

## Important caveats

- **Facebook's Terms of Service prohibit automated scraping**, even of
  groups you belong to. This tool automates *your own* logged-in browser
  session for personal use, not bulk data collection or spam — but that's
  still a gray area under Facebook's ToS, and your account could be flagged
  or restricted. Use at your own risk, keep scan frequency low, and never
  leave it running unattended at scale. `src/scraper.py` jitters its delays
  and detects a checkpoint/login wall rather than scraping through it, but
  neither of those makes automated scraping compliant with Facebook's ToS —
  they only reduce how detectable and how damaging a scan is.
- Facebook's markup changes often and uses randomized class names, so the
  scraper in `src/scraper.py` relies on structural hints (`role="article"`,
  permalink patterns) that may need small tweaks over time if extraction
  stops finding posts.
- **The regex/keyword parser (`src/listing_parser.py`) is a fallback, not
  a language model** — used automatically whenever the LLM path isn't
  available. It will miss some genuine listings and occasionally flag a
  false positive; the address/phone/`available_rooms`/date fields it
  recovers in particular are best-effort (each only catches a handful of
  common Hebrew phrasings). Since dates are now a *hard* requirement (see
  "Stay length and dates" above), this fallback path will drop more
  genuine listings than the LLM path would, on posts phrasing their dates
  in ways its regexes don't cover. Tune a profile's `excluded_keywords` to
  cut down on noise, or set `GEMINI_API_KEY` for meaningfully better
  extraction across the board.
