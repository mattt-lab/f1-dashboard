# 🏎️ F1 Dashboard

> A live Formula 1 companion — race weekends, standings, results, and AI-generated race summaries, all in one dark-mode dashboard.

**[🔴 Live Demo →](https://mattt-lab.github.io/f1-dashboard/)**

---

## What it does

The dashboard automatically detects where you are in the F1 calendar and shows you exactly what's relevant right now:

- **Race weekend?** Live countdown to the next session, all results as they come in, and a circuit map watermark in the banner.
- **Post-race (within 48h)?** A Race Wrap card appears above the session results — an AI-written summary of what happened, pulled from BBC Sport.
- **Between races?** Countdown to the next grand prix, the full weekend schedule, and a Race Preview card with storylines and title battle context.
- **Any time:** scroll the season calendar, click any past race to expand results inline, and jump to full driver or constructor standings.

---

## Features

### 🏁 Race Weekend Hub
- Phase detection — knows if you're in FP, qualifying, sprint, or post-race
- Session-by-session countdown clock (hours:minutes:seconds)
- Collapsible results for every session — only the most recent auto-expands
- Qualifying results with Q1/Q2/Q3 section dividers
- Race & sprint results with intervals, DNF/classified-retirement detection, and points earned
- Circuit map watermark in the race banner, auto-rotated for portrait-shaped tracks (e.g. Monaco)
- YouTube highlights link for every past race

### 📰 Race Wrap / Race Preview Card
- Appears between the race banner and the sessions panel
- **Post-race (0–48h after the race):** AI-written recap — winner, key moment, championship implication — sourced from BBC Sport headlines
- **Between races (48h+ after the race):** AI-written preview — headline storyline, tactical angle, championship stakes — for the upcoming grand prix
- Written in sports-journalist style: active verbs, specific facts, no clichés
- Powered by Claude (Haiku) via GitHub Actions; falls back to BBC RSS descriptions if the API is unavailable
- Shows blank if the cached JSON doesn't match the current race/phase — never shows stale content

### 📅 Season Calendar
- Full scrollable race strip, auto-centered on the current/next round
- Click any completed race to expand a top-10 results panel inline
- Sprint weekend winners called out separately

### 📊 Standings Pages
- Full driver and constructor championship tables with team colours
- "Closest Battles" — sorted by tightest points gap
- "Who Can Still Win" and "Points Needed" championship analysis
- Season at a glance: leader gaps, races remaining, max points available

### ✨ Details
- Zero runtime dependencies — vanilla HTML, CSS, and JavaScript
- Race data from [Jolpica/Ergast](https://api.jolpi.ca/) with a same-day [OpenF1](https://openf1.org/) fallback — no key needed for either
- Fully responsive, works on mobile
- Dark mode only (obviously)

---

## Pages

| File | Description |
|---|---|
| `f1-dashboard.html` | Main hub — race weekend, between-races, standings snapshot |
| `f1-drivers.html` | Full driver championship standings |
| `f1-constructors.html` | Full constructor championship standings |

---

## Data sources: Jolpica + OpenF1

Session results (qualifying/race/sprint) come from **two APIs, each doing what it's good at** — this isn't redundancy, it's a deliberate split:

| | [Jolpica (Ergast)](https://api.jolpi.ca/ergast/f1) | [OpenF1](https://openf1.org/) |
|---|---|---|
| Role | Source of truth | Same-day accelerant |
| Season calendar, incl. future races | ✅ | ❌ (sessions populate near the event) |
| Championship standings | ✅ | ❌ (no standings endpoint at all) |
| Historical archive | Back to 1950 | Recent seasons only |
| Retirement detail | Human-readable ("Collision damage") | Boolean flags only (`dnf`/`dns`/`dsq`) |
| Same-day result freshness | Can lag by hours | Posts within minutes of a session ending |

**Why not standardize on one?** Jolpica alone means qualifying/race results can sit empty for hours after a session ends (confirmed live: Hungarian GP qualifying had zero results on Jolpica two hours after it finished). OpenF1 alone doesn't work at all — it has no standings and no forward-looking calendar, so the Drivers/Constructors pages and the whole phase-detection state machine (which relies on the full season schedule) would break.

**How the fallback works:** `fetchRoundResults()` in `f1-dashboard.html` always asks Jolpica first. Only for whichever session type Jolpica hasn't posted yet does it fall back to OpenF1, converting OpenF1's response into the same object shape Jolpica returns — so the render functions don't know or care which source a given result came from. Jolpica always wins once it has data.

OpenF1's free tier rate-limits bursts of requests from the same client (soft 429s were observed during testing), so the fallback fetches session types one at a time rather than in parallel, and only for the specific sessions that are actually missing.

> **Live timing / telemetry** (car positions, live sector times, tire data) is possible via OpenF1 but was scoped out for now — live data requires their paid Sponsor tier (€9.90/mo) and is meant to be consumed via WebSocket/MQTT push rather than polling, which is a bigger integration than this app's fetch-on-load model. The public API has also had documented multi-day outages with no SLA, which matters more for a live feature than for an occasional same-day fallback.

---

## Race Wrap pipeline

A GitHub Actions workflow runs on a schedule and writes `data/race-news.json`, which the dashboard fetches on load.

```
BBC Sport F1 RSS
      │
      ▼
fetch_news.py (GitHub Actions)
  • Detects phase: post-race (0–48h) or upcoming
  • Filters RSS for current-race headlines (with circuit-name aliases)
  • Calls Claude API → 3-sentence sports-journalist summary
  • Falls back to stitched RSS descriptions if Claude unavailable
      │
      ▼
data/race-news.json  ←  committed back to repo
      │
      ▼
Dashboard fetches on load, validates race name + phase before rendering
```

**Schedule:**
- Friday–Sunday (race weekends): every 3 hours
- Monday–Thursday (between races): once daily at 09:15 UTC

**Required GitHub secret:** `ANTHROPIC_API_KEY` — add it under Settings → Secrets and variables → Actions.

---

## Running locally

These files make API calls at runtime, so they need to be served over HTTP.

```bash
# Option 1 — Node.js
npx serve .

# Option 2 — Python
python -m http.server 8080
```

Then open `http://localhost:8080/f1-dashboard.html`.

### Secret preview mode

Append `?mock=qual` to the dashboard URL to preview the post-qualifying UI state with mock data — useful for development between race weekends.

---

## Tech

| Concern | Solution |
|---|---|
| F1 data | [Jolpica Ergast API](https://api.jolpi.ca/ergast/f1) (primary) + [OpenF1](https://openf1.org/) (same-day fallback) — free, no key for either |
| Race summaries | BBC Sport F1 RSS + Claude Haiku (via GitHub Actions) |
| F1 news feed | BBC Sport F1 RSS via [rss2json](https://rss2json.com) |
| YouTube highlights | F1 channel RSS feed via rss2json, cached in localStorage |
| Hosting | GitHub Pages |
| Runtime dependencies | None |

---

## Data freshness

| Data | Freshness |
|---|---|
| Standings, calendar | Live from Jolpica on every page load |
| Qualifying / race / sprint results | Live from Jolpica; falls back to OpenF1 same-day if Jolpica hasn't posted yet |
| Race Wrap / Preview blurb | Regenerated by GitHub Actions (every 3h on race weekends, daily otherwise) |
| YouTube highlights | Cached in localStorage for 6 hours |

---

*Built for personal use. Not affiliated with Formula 1, FOM, or the FIA.*
