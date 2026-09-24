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
   pulls posts **since a cutoff** (see [Scan window &
   scheduling](#scan-window--scheduling) — the first scan ever looks back
   several days, every scan after that only looks back to the last
   successful scan), and for each new one that looks like an *offer* (not
   someone else looking for a place), extracts price/rooms/available-rooms/
   address/roommates/bathrooms/phone/photos and checks it against **every**
   profile in your `searches:` list (and, if configured, the zone-distance
   check below) — a post can match more than one profile. Extraction uses
   the Gemini LLM when `GEMINI_API_KEY` is set (far more reliable on
   colloquial Hebrew), automatically falling back to a regex/keyword parser
   otherwise or whenever the LLM is unavailable this run. Everything is
   stored in `data/listings.db` (SQLite), so re-running never double-
   processes a post — including cross-posts and comment-less posts with no
   recoverable permalink, and reworded reposts sharing the same address or
   phone number, all of which are matched on their content instead of
   relying on the post URL alone. Each scan also revisits a handful of your
   most-recent matches to prune any that Facebook now shows as removed
   (rented out) — see [Dead-link pruning](#dead-link-pruning).
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
profile(s) (price range, neighborhoods, room/roommate requirements — see
[Multiple search profiles](#multiple-search-profiles)), and the
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

Google's own server-side quota resets at Pacific midnight, which doesn't
line up with `llm.daily_budget`'s local-midnight reset — the two can
disagree, and a fresh local day can still land inside an already-exhausted
Google quota window (especially on a heavy testing day). The first real
`429 RESOURCE_EXHAUSTED` response is remembered for the rest of that day,
so every later post skips straight to the regex fallback instead of each
one separately re-hitting the same already-exhausted quota.

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
    # ... neighborhoods, max_roommates, etc. — same fields as before, just
    # nested under a named profile now.
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

When a post doesn't state an explicit count ("2 חדרים פנויים"/"חדר פנוי")
but is clearly offering a WHOLE apartment rather than one room in a shared
one, `available_rooms` is inferred from how many bedrooms are mentioned
("חדר שינה" -> 1, "שני חדרי שינה" -> 2) — a living room/workspace/balcony
never counts as a bedroom. This is what stops a 1-bedroom-plus-living-room
sublet from wrongly matching a "two rooms" profile just because the post
never spelled out a number.

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

**Dates are soft-optional, like every other field here** — a post that
says nothing about when it starts or how long it runs still passes,
rather than being dropped outright. Whenever a piece of date info IS
known, though, it's still checked: a stay shorter than `min_days` is
rejected, and a known start date outside the `search_window_days` window
is rejected — just not the *absence* of that info on its own. A post
stating only a duration ("שבועיים", no specific start date) is checked
against `min_days` but not the window (nothing to check a window against
without a start date); a post with a start date but no stated
duration/end is checked against the window but not `min_days`.

**One exception stays a hard rejection**: a post whose *only* date signal
is an end date that's already in the past (e.g. "available until Sept 1"
scraped on Sept 23 — a stale or reposted ad) is dropped outright, rather
than being folded into "no date info, so pass." The post's own text says
it's over — that's a real negative signal, not silence.

**Price proration**: your `price_min`/`price_max` are a monthly budget.
When a listing's stay is under 30 days, that budget is prorated down
(`price * duration_days/30`) before comparing it against the post's price
— which is treated as the **total for its stated period**, not a monthly
rate, for a short-term post. A post priced by the week or day ("1000
ש"ח לשבוע") gets converted to that period-total automatically (rate ×
number of weeks/days in the stay) rather than being taken as the total
literally. A stay of a month or longer is never
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

Price is a **soft** filter — a listing with no stated price still passes,
rather than being dropped as unverifiable — which means it was never
actually confirmed to be in your budget. Every surface labels it
distinctly as a result: the Telegram alert's header reads "Potential
match (price unknown)" instead of "New sublet match", and the Sheets row,
dashboard card, and published snapshot each show a small "potential"
badge next to the price — a visual cue to double-check that one by hand
before the rest.

Any alert with a phone number also gets a **💬 WhatsApp** button, alongside
Save/Dismiss — "Ask about price" with a pre-filled inquiry message when the
price is still unknown (a "potential match" alert), or a plain "Contact via
WhatsApp" link with nothing pre-filled when the price is already known.
Either way it opens WhatsApp via `wa.me`'s own `text` query param, so you
just tap Send. This is a plain link button, not bot automation: Telegram
bots have no API to send a WhatsApp message on your behalf, so nothing
goes out until you tap Send yourself in WhatsApp.

Any alert with a known address or coordinates also gets a **🗺️ Google
Maps** button — the same link already shown as text in the message body,
just as a tap target too. Offered independently of price/phone, so it
shows up on every alert that has a location, not just "potential match"
ones.

Two more buttons are config-driven rather than per-listing, so they
appear on every alert once set up: **📊 Dashboard** links to the
[local dashboard](#dashboard)'s listing list (only once `DASHBOARD_HOST`
is set — see below, since a `127.0.0.1` link wouldn't load on your
phone), and **📄 Sheets** links to the [Google Sheet](#google-sheets)
itself (once `GOOGLE_SHEET_ID` is set). Neither points at that specific
listing's row — the dashboard has no per-listing URL, and a Sheets row
moves every time the sheet re-sorts by score.

### Scan window & scheduling

`config.yaml`'s `scan_window:` block controls how far back a scan looks:

```yaml
scan_window:
  initial_lookback_days: 4
```

The **very first scan ever run** looks back this many days. **Every scan
after that** looks back to the last successful scan instead — running
twice a day (see the cron setup below) this naturally works out to about
12 hours, and if a run gets missed (phone off, no network), the next one
self-heals by covering the gap — but it's capped so a long outage never
scans further back than `initial_lookback_days`, however long the tool was
down. This is separate from (and layered on top of) the existing
`post_url`/content-hash dedup — the DB already guarantees nothing
already-suggested is suggested again, so the cutoff is purely about not
wastefully re-scraping/re-classifying old posts on every run, not about
correctness.

This needs the group feed sorted chronologically ("New posts", not
Facebook's default "Most relevant") to work correctly — the scanner
switches it automatically. If that switch ever fails (a selector changed),
the scan safely falls back to the old fixed-count behavior for that run
rather than silently under-scanning.

**Running it on a schedule** (e.g. twice daily via `cron`, inside a Termux/
proot-distro chroot on a phone/tablet with no desktop environment):

```bash
apt install -y cron
crontab -e
```
Add:
```
0 7 * * *  sleep $(python3 -c "import random; print(random.randint(0, 7200))") && cd /path/to/Sublet-finder-TLV && .venv/bin/python -m src.cli scan >> data/scan.log 2>&1
0 19 * * * sleep $(python3 -c "import random; print(random.randint(0, 7200))") && cd /path/to/Sublet-finder-TLV && .venv/bin/python -m src.cli scan >> data/scan.log 2>&1
```
`0 7`/`0 19` is the fixed cron trigger; the `sleep` picks a fresh random
0-2h delay each firing, so the actual scan start lands uniformly between
7-9am and 7-9pm instead of the exact same clock minute every day — a
smaller automation fingerprint at no extra request cost, since it's still
the same two scans a day, just at a jittered time. Then `service cron
start`. A few things worth knowing on Termux specifically: confirm the
chroot's timezone first (`date`) so `0 7`/`0 19` line up with your actual
local time; cron here only runs while Termux itself is alive
(force-closing the app or rebooting the device stops it until you reopen
Termux and run `service cron start` again); and Android's battery
optimization can pause Termux in the background regardless — set it to
"Unrestricted" for reliable scheduled runs.

**Exit codes**, so a cron log (or `echo $?`) tells you what happened
without reading the full output: `0` = ran cleanly, `2` = either Facebook
showed a checkpoint/login wall mid-scan (your saved session likely
expired — a debug screenshot is saved to
`data/checkpoint_<group name>.png`, and `python -m src.cli login` or the
headless-login trick needs to be redone), or 2+ groups in the same run
loaded normally but returned zero posts (a Facebook soft-block can serve a
working-looking page with no login wall at all — see the heartbeat message
below to tell the two apart), any other non-zero code = a genuine bug, not
a session problem.

**Telegram heartbeat**: if `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` are
configured, every scan (outside of `--dry-run`) ends with a short Telegram
message — ✅ success with the new-match count, 🔴 blocked (session likely
expired), 🔴 possible soft-block (multiple groups returned zero posts
despite loading normally), or 🔴 crashed — so an unattended cron run's
outcome shows up on the channel you're already watching instead of only in
`data/scan.log`. It also doubles as a check that cron itself ran at all:
if the expected message doesn't show up by ~9am/9pm, that silence is the
signal.

### Dead-link pruning

Once a day (not every scan — the check itself costs real time and traffic,
so it's throttled), a scan revisits a capped batch (20) of your
most-recently-matched listings and checks whether Facebook now shows a
"content isn't available" placeholder for the post — meaning the apartment's
likely been rented out or the post removed. A confirmed-dead listing is
hidden from `matches.py`/the dashboard/the published snapshot the same way a
manual 🗑 Dismiss is, instead of sitting there indefinitely. This check is
best-effort and never fails or blocks a scan — a network hiccup or a
markup change just means it's skipped for that run.

## Usage

```bash
python scripts/login_facebook_headless.py   # or login_facebook.py with a screen
python scripts/scan.py                      # pulls posts and checks for matches
python scripts/scan.py --dry-run            # classify and print, without writing/notifying
python scripts/scan.py --explain            # sanity check: why isn't anything matching?
python scripts/scan.py --posts-per-group 3  # a cheap, light test run — see below
python scripts/matches.py                   # list everything matched so far, best score first
```

**`--explain`** is a diagnostic sanity check for "why is a scan finding 0
matches" — it implies `--dry-run` (never writes to the DB or notifies), and
for every extracted offer-listing that fails to match any search profile, it
prints the specific reason(s) it was rejected (price out of range, stay too
short, wrong neighborhood, broker/girls-only mention, etc.) instead of just
silently skipping it. Run it once if match counts look suspiciously low —
either it'll turn up a real bug, or it'll confirm your `config.yaml` criteria
(price range, neighborhoods, the lease-dates requirement) are just
genuinely strict for what's actually being posted right now.

**`--posts-per-group N`** overrides `config.yaml`'s `posts_per_group` for
that one run only, without touching the real setting your twice-daily cron
scans use. Useful for a quick manual test: a full scan across every
configured group can extract (and LLM-classify) well over a hundred posts,
which adds up fast against Gemini's free-tier daily quota — note that
`--dry-run` does **not** save LLM calls (it only skips the DB write/
notification at the very end, after extraction already happened).
`--posts-per-group 3 --dry-run` gets you a real end-to-end pipeline check
(scraping, extraction, matching, scoring) on a small sample, for a fraction
of the cost of a full scan.

Re-run the login script whenever the session expires (Facebook logs you out
after a while of inactivity, or if it flags the login as suspicious). A scan
refuses to start a second time while one is already running (a lock file in
`data/scan.lock`), and stops cleanly instead of scraping garbage if Facebook
shows a checkpoint/login wall — exiting with code `2` and saving a debug
screenshot (`data/checkpoint_<group name>.png`) so an unattended/cron run is
easy to distinguish from an ordinary crash; see [Scan window &
scheduling](#scan-window--scheduling).

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
since listings carry addresses and phone numbers. Binds to `127.0.0.1` by
default: **LAN/local-only, never expose this port to the internet.**

Set `DASHBOARD_HOST` (e.g. to your tablet's own LAN IP, `192.168.1.23`) to
make it reachable from your phone over WiFi, and to make the **📊
Dashboard** button in Telegram alerts actually work — while it's still
`127.0.0.1`, that button is simply omitted, since a `127.0.0.1` link
would only load when opened on the exact device running the dashboard
(your phone's `127.0.0.1` is the phone itself, not your tablet).
**Never** set it to `0.0.0.0` or a public address — the token is the
*only* auth, and this still isn't meant to leave your home network.
`DASHBOARD_PORT` overrides the default port (`8765`) the same way.

Above the list, a map (Leaflet + OpenStreetMap — free, no API key) plots
every currently-valid match that has a known location: green markers for
listings suitable for 1-2 people, blue for everything else, each one's
popup showing price and score. Every marker and card also links out to
**Google Maps** (from the listing's address when known, else its
coordinates) and to the **original Facebook post**. A listing without a
geocoded address just doesn't get a marker — it still shows up in the card
list below.

Each card with a phone number also gets a **WhatsApp** link — "Ask about
price" with a pre-filled inquiry message when the price is unknown, or a
plain "Contact via WhatsApp" link when it's already known — same rule and
same shared `wa.me` link-building (`src/contact.py`) as the Telegram
alert's button.

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

`whatsapp` and `maps` columns are clickable `=HYPERLINK(...)` cells (the
label reads "Ask about price"/"Contact via WhatsApp" for the WhatsApp one,
same rule as the dashboard/Telegram links), built with the same shared
helpers (`src/contact.py`, `src/geocode.py`) as everywhere else — blank
when there's no phone/address to link from.

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
  and scroll distances, shuffles the group scan order, strips a couple of
  the most obvious automation markers from the headless browser (a
  `HeadlessChrome`-free user agent, `--disable-blink-features=
  AutomationControlled`), and detects a checkpoint/login wall rather than
  scraping through it — but none of that makes automated scraping compliant
  with Facebook's ToS, it only reduces how detectable and how damaging a
  scan is.
- Facebook's markup changes often and uses randomized class names, so the
  scraper in `src/scraper.py` relies on structural hints (`role="article"`,
  permalink patterns) that may need small tweaks over time if extraction
  stops finding posts.
- **The regex/keyword parser (`src/listing_parser.py`) is a fallback, not
  a language model** — used automatically whenever the LLM path isn't
  available. It will miss some genuine listings and occasionally flag a
  false positive; the address/phone/`available_rooms`/date fields it
  recovers in particular are best-effort (each only catches a handful of
  common Hebrew phrasings), so it will miss more of the `min_days`/
  `search_window_days` checks in "Stay length and dates" above than the
  LLM path would on posts phrasing their dates in ways its regexes don't
  cover. Tune a profile's `excluded_keywords` to cut down on noise, or set
  `GEMINI_API_KEY` for meaningfully better extraction across the board.
- **Broker/agency posts are filtered out automatically** — any mention of
  "תיווך"/"מתווך" drops a post, unless it's negated ("ללא תיווך"/"בלי
  תיווך"/"אין תיווך", i.e. "no broker fee") which is the opposite signal, a
  direct-from-tenant post advertising that it's *not* brokered. This is a
  fixed rule, not a per-profile `excluded_keywords` entry, since it needs
  the negation handling to avoid dropping exactly the listings you want.
- **"Girls only" listings are filtered out automatically** the same way —
  an explicit exclusivity claim ("רק לבנות"/"בנות בלבד"/"דירת בנות", or
  "girls/women/females only" in English) drops a post, unless it's negated
  ("לא רק לבנות"/"not girls only"). A post that just mentions the current
  residents are women (without an explicit "only"/"בלבד") is left alone —
  only an explicit exclusivity claim is treated as a hard gate.
