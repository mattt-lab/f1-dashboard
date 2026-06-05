# 🏎️ F1 Dashboard

> A live Formula 1 companion — race weekends, standings, and results, all in one dark-mode dashboard.

**[🔴 Live Demo →](https://mattt-lab.github.io/f1-dashboard/)**

---

## What it does

The dashboard automatically detects where you are in the F1 calendar and shows you exactly what's relevant right now:

- **Race weekend?** You get a live countdown to the next session, all results as they come in (qualifying, sprint, race), and a direct link to YouTube highlights.
- **Between races?** You get a countdown to the next grand prix, the full weekend schedule, and a season snapshot.
- **Any time:** scroll the season calendar strip, click any past race to expand the top-10 results inline, and jump to the full driver or constructor standings.

---

## Features

### 🏁 Race Weekend Hub
- Live phase detection — knows if you're in FP, qualifying, sprint, or race weekend
- Session-by-session countdown clock (hours:minutes:seconds)
- Collapsible results for every session — only the most recent auto-expands
- Qualifying results with Q1/Q2/Q3 section dividers
- Race & sprint results with intervals, DNF detection, and points earned
- YouTube highlights link for every past race in the calendar

### 📅 Season Calendar
- Full scrollable race strip, auto-centered on the current/next round
- Click any completed race to expand a top-10 results panel inline
- Sprint weekend winners called out separately

### 📊 Standings Pages
- Full driver and constructor championship tables with team colours
- "Closest Battles" — sorted by tightest points gap, not race order
- "Who Can Still Win" and "Points Needed" championship analysis
- Season at a glance: leader gaps, races remaining, max points available

### ✨ Details
- Zero dependencies — vanilla HTML, CSS, and JavaScript
- All data from the free [Jolpica/Ergast F1 API](https://api.jolpi.ca/) — no API key needed
- YouTube highlights via RSS, cached in `localStorage` for 6 hours
- Fully responsive, works on mobile
- Dark mode only (obviously)

---

## Pages

| File | Description |
|---|---|
| `f1-dashboard.html` | Main hub — race weekend or next race countdown |
| `f1-drivers.html` | Full driver championship standings |
| `f1-constructors.html` | Full constructor championship standings |

---

## Running locally

These files make API calls at runtime, so they need to be served over HTTP — just double-clicking won't work.

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
| F1 data | [Jolpica Ergast API](https://api.jolpi.ca/ergast/f1) — free, no key |
| F1 news | BBC Sport F1 RSS via [rss2json](https://rss2json.com) |
| YouTube highlights | F1 channel RSS feed via rss2json, cached in localStorage |
| Hosting | GitHub Pages |
| Dependencies | None |

---

## Data freshness

Results appear as soon as the Jolpica API updates after each session — typically within minutes of the chequered flag. YouTube highlights are fetched from the F1 channel RSS feed (last 15 videos) and cached per race weekend for 6 hours.

---

*Built for personal use. Not affiliated with Formula 1, FOM, or the FIA.*
