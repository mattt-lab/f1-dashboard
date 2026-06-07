#!/usr/bin/env python3
"""
fetch_news.py  —  Fetch F1 race summary for the dashboard.

Source: BBC Sport F1 RSS feed.
  - Finds the race-report headline for the current race.
  - Fetches the full BBC article and extracts the opening paragraphs.
  - Falls back to combining the best RSS descriptions if the article
    fetch fails.
  - For upcoming races, uses the Wikipedia evergreen article for
    circuit/race background (the only time generic info is appropriate).

Writes data/race-news.json — consumed by the dashboard's race wrap card.
Run every 3 hours via GitHub Actions (.github/workflows/update-news.yml).
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# ── Constants ──────────────────────────────────────────────────────────────
JOLPICA_API = "https://api.jolpi.ca/ergast/f1"
BBC_RSS     = "http://feeds.bbci.co.uk/sport/formula1/rss.xml"
OUTPUT_FILE = "data/race-news.json"
UA          = "F1Dashboard/1.0 (+https://github.com/mattt-lab/f1-dashboard)"
TIMEOUT     = 12  # seconds per request

SKIP_PHRASES = {"cookie", "subscribe", "newsletter", "sign up", "privacy",
                "terms and conditions", "javascript", "bbc sport footer"}


# ── HTTP helpers ───────────────────────────────────────────────────────────

def fetch(url, extra_headers=None):
    """GET url → str, or None on error."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "text/html,application/xhtml+xml,application/json,*/*")
    req.add_header("Accept-Language", "en-US,en;q=0.9")
    if extra_headers:
        for k, v in extra_headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            charset = r.headers.get_content_charset() or "utf-8"
            return r.read().decode(charset, errors="replace")
    except Exception as e:
        print(f"  [fetch] {url[:80]}  →  {e}", file=sys.stderr)
        return None


def fetch_json(url):
    """GET url → parsed JSON dict, or None."""
    text = fetch(url, {"Accept": "application/json"})
    if text:
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            print(f"  [json] parse error: {e}", file=sys.stderr)
    return None


def strip_tags(html):
    """Remove HTML tags and decode common entities."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">") \
               .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


# ── Jolpica: current race info ─────────────────────────────────────────────

def _weekend_start(race_dict):
    """
    Return the datetime of the earliest session in a race weekend.
    Falls back to the race time itself if no session data is present.
    """
    race_dt_str = f"{race_dict['date']}T{race_dict.get('time', '15:00:00Z')}"
    earliest = datetime.fromisoformat(race_dt_str.replace("Z", "+00:00"))

    for session_key in ("FirstPractice", "SecondPractice", "ThirdPractice",
                        "Sprint", "SprintQualifying", "Qualifying"):
        s = race_dict.get(session_key)
        if not s:
            continue
        try:
            s_dt = datetime.fromisoformat(
                f"{s['date']}T{s.get('time', '12:00:00Z')}".replace("Z", "+00:00")
            )
            if s_dt < earliest:
                earliest = s_dt
        except (KeyError, ValueError):
            continue

    return earliest


def get_current_race():
    """
    Returns (race_dict, phase):
      'post-race'  – between race weekends; show wrap of last completed race
      'upcoming'   – next race weekend has started (FP1 has begun); show preview

    Switches to 'upcoming' only when the next weekend's first on-track session
    begins — matching the dashboard's own race-weekend detection logic.
    """
    data = fetch_json(f"{JOLPICA_API}/current.json?limit=100")
    if not data:
        return None, None

    races = data["MRData"]["RaceTable"]["Races"]
    now   = datetime.now(timezone.utc)

    next_race = None
    last_race = None

    for r in races:
        race_dt_str = f"{r['date']}T{r.get('time', '15:00:00Z')}"
        race_dt = datetime.fromisoformat(race_dt_str.replace("Z", "+00:00"))
        if race_dt > now:
            if next_race is None:
                next_race = (r, race_dt)
        else:
            last_race = (r, race_dt)

    if next_race and _weekend_start(next_race[0]) <= now:
        return next_race[0], "upcoming"

    if last_race:
        return last_race[0], "post-race"

    if next_race:
        return next_race[0], "upcoming"

    return None, None


# ── BBC Sport ──────────────────────────────────────────────────────────────

def fetch_bbc_rss():
    """Fetch and parse the BBC Sport F1 RSS feed. Returns list of items."""
    print("  Fetching BBC Sport F1 RSS…")
    xml_text = fetch(BBC_RSS)
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text)
        items = []
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link",  "").strip()
            desc  = strip_tags(item.findtext("description", "")).strip()
            pub   = item.findtext("pubDate", "").strip()
            if title and link:
                items.append({"title": title, "url": link,
                              "description": desc, "published": pub})
        print(f"  BBC RSS: {len(items)} items")
        return items
    except ET.ParseError as e:
        print(f"  BBC RSS parse error: {e}", file=sys.stderr)
        return []


def fetch_bbc_article(url, max_paragraphs=4):
    """
    Fetch a BBC Sport article page and return its opening paragraphs as a
    single string. Returns None if the article can't be extracted.
    """
    clean_url = url.split("?")[0]   # strip RSS tracking params
    print(f"  Fetching BBC article: {clean_url}")
    html = fetch(clean_url)
    if not html:
        return None

    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", html, re.DOTALL | re.IGNORECASE)
    clean = []
    for p in paragraphs:
        text = strip_tags(p).strip()
        low  = text.lower()
        if len(text) < 60:
            continue
        if any(phrase in low for phrase in SKIP_PHRASES):
            continue
        clean.append(text)
        if len(clean) >= max_paragraphs:
            break

    if not clean:
        print("  BBC article: no usable paragraphs extracted")
        return None

    return " ".join(clean)


# Keywords that identify a race-result article vs a preview/feature
RESULT_KW  = {"wins", "victory", "takes win", "clinches", "triumphs",
              "wins the", "takes the win", "race winner"}
PREVIEW_KW = {"preview", "guide", "ones to watch", "what to expect",
              "talking points", "five things", "what we learned"}


def _score_item(item, race_name):
    """Return (result_score, preview_score) for a BBC RSS item."""
    combined = (item["title"] + " " + item.get("description", "")).lower()
    race_low  = race_name.lower()

    # Must mention this race (or Grand Prix generically)
    if race_low not in combined and "grand prix" not in combined:
        return 0, 0

    r_score = sum(1 for kw in RESULT_KW  if kw in combined)
    p_score = sum(1 for kw in PREVIEW_KW if kw in combined)
    return r_score, p_score


def build_post_race_summary(race_name, items):
    """
    Find the race-report article in the BBC RSS feed, fetch its full text,
    and return a summary string.  Falls back to combining RSS descriptions.
    """
    # Sort items by result relevance
    scored = [(item, *_score_item(item, race_name)) for item in items]
    result_items   = sorted(
        [(it, rs) for it, rs, _ in scored if rs > 0],
        key=lambda x: -x[1]
    )
    relevant_items = [it for it, rs, ps in scored if rs > 0 or ps == 0 and
                      (race_name.lower() in (it["title"] + it.get("description","")).lower()
                       or "grand prix" in (it["title"] + it.get("description","")).lower())]

    # 1. Try fetching the main race-report article
    if result_items:
        text = fetch_bbc_article(result_items[0][0]["url"])
        if text:
            return text

    # 2. Fall back: combine the best RSS descriptions
    print("  Falling back to combining RSS descriptions…")
    parts = []
    seen  = set()
    for item, r_score, _ in scored:
        desc = item.get("description", "").strip()
        if desc and desc not in seen and r_score > 0:
            parts.append(desc)
            seen.add(desc)
        if len(parts) >= 3:
            break

    if not parts:
        # Last resort: any relevant item's description
        for item in relevant_items[:3]:
            desc = item.get("description", "").strip()
            if desc and desc not in seen:
                parts.append(desc)
                seen.add(desc)

    return " ".join(parts) if parts else None


def build_preview_summary(race_name, items):
    """
    For an upcoming race, find a preview article in the BBC feed or fall back
    to the Wikipedia evergreen article (circuit background is useful pre-race).
    """
    scored = [(item, *_score_item(item, race_name)) for item in items]
    preview_items = sorted(
        [(it, ps) for it, _, ps in scored if ps > 0],
        key=lambda x: -x[1]
    )

    if preview_items:
        text = fetch_bbc_article(preview_items[0][0]["url"])
        if text:
            return text

    # Wikipedia evergreen fallback (good for circuit background pre-race)
    print("  Trying Wikipedia evergreen article for preview…")
    title = race_name.replace(" ", "_")
    url   = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}"
    data  = fetch_json(url)
    if data and "not_found" not in str(data.get("type", "")):
        extract = data.get("extract", "").strip()
        if len(extract) >= 100:
            return extract

    return None


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print(f"fetch_news.py  —  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    race, phase = get_current_race()
    if not race:
        print("ERROR: Could not determine current race from Jolpica API")
        sys.exit(1)

    race_name = race["raceName"]
    year      = race["season"]
    round_num = race["round"]
    circuit   = race.get("Circuit", {}).get("circuitName", "")
    date      = race.get("date", "")

    print(f"\nRace   : {race_name}  (Round {round_num}, {year})")
    print(f"Phase  : {phase}")
    print(f"Circuit: {circuit}")

    result = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "phase":   phase,
        "race": {
            "name":    race_name,
            "round":   round_num,
            "season":  year,
            "date":    date,
            "circuit": circuit,
        },
        "summary": None,
    }

    print(f"\n── Fetching {'post-race summary' if phase == 'post-race' else 'race preview'} ──")
    items = fetch_bbc_rss()

    if phase == "post-race":
        text = build_post_race_summary(race_name, items)
    else:
        text = build_preview_summary(race_name, items)

    if text:
        result["summary"] = text
        print(f"  ✓ summary: {len(text)} chars")
    else:
        print("  ✗ no summary found", file=sys.stderr)

    os.makedirs("data", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)

    print(f"\n✓  Written → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
