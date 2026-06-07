#!/usr/bin/env python3
"""
fetch_news.py  —  Fetch F1 race news and summaries for the dashboard.

Sources (in priority order):
  1. Formula 1 official race report  (formula1.com)
  2. Wikipedia race article extract  (en.wikipedia.org REST API)
  3. BBC Sport F1 RSS headlines

Writes data/race-news.json which the dashboard fetches on load.
Run every 3 hours via GitHub Actions (.github/workflows/update-news.yml).
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# ── Constants ──────────────────────────────────────────────────────────────
JOLPICA_API = "https://api.jolpi.ca/ergast/f1"
BBC_RSS     = "http://feeds.bbci.co.uk/sport/formula1/rss.xml"
DDG_SEARCH  = "https://html.duckduckgo.com/html/"
OUTPUT_FILE = "data/race-news.json"
UA          = "F1Dashboard/1.0 (+https://github.com/mattt-lab/f1-dashboard)"

TIMEOUT = 12  # seconds per request


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

def get_current_race():
    """
    Returns (race_dict, phase) where phase is one of:
      'post-race'  – race weekend has finished
      'upcoming'   – next race is in the future
    """
    # Try last completed race first
    data = fetch_json(f"{JOLPICA_API}/current/last/results.json")
    if data:
        races = data["MRData"]["RaceTable"]["Races"]
        if races:
            return races[0], "post-race"

    # Fall back to next scheduled race
    data = fetch_json(f"{JOLPICA_API}/current.json?limit=100")
    if data:
        races = data["MRData"]["RaceTable"]["Races"]
        now = datetime.now(timezone.utc)
        for r in races:
            race_dt_str = f"{r['date']}T{r.get('time', '12:00:00Z')}"
            race_dt = datetime.fromisoformat(race_dt_str.replace("Z", "+00:00"))
            if race_dt > now:
                return r, "upcoming"

    return None, None


# ── Source 1: Formula 1 official article ──────────────────────────────────

def find_f1com_article_url(race_name, year):
    """
    Use DuckDuckGo to find the F1.com race report URL.
    Returns URL string or None.
    """
    query = f'site:formula1.com "{year}" "{race_name}" race result'
    params = urllib.parse.urlencode({"q": query, "kl": "us-en"})
    html = fetch(f"{DDG_SEARCH}?{params}", {
        "Referer": "https://duckduckgo.com/",
        "Accept": "text/html",
    })
    if not html:
        return None

    # Extract formula1.com article URLs from search results
    urls = re.findall(
        r'https://www\.formula1\.com/en/latest/article/[^\s"\'<>&]+',
        html
    )
    # Prefer URLs that look like race reports
    for url in urls:
        lower = url.lower()
        if any(kw in lower for kw in ["race-result", "race-report", "grand-prix", "wins", "victory", "secures"]):
            return url
    return urls[0] if urls else None


def fetch_f1com_summary(race_name, year):
    """
    Fetch and return the first substantive paragraphs from an F1.com race report.
    Returns dict with 'text', 'url', 'source' or None.
    """
    print(f"  Searching F1.com for '{race_name} {year}'…")
    url = find_f1com_article_url(race_name, year)
    if not url:
        print("  F1.com: no article URL found via search")
        return None

    print(f"  F1.com article: {url}")
    html = fetch(url)
    if not html:
        return None

    # Extract <p> paragraphs from the article body
    # F1.com wraps article content in divs; we grab all <p> tags
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", html, re.DOTALL | re.IGNORECASE)
    clean = []
    for p in paragraphs:
        text = strip_tags(p).strip()
        # Skip short snippets, nav items, cookie notices, etc.
        if len(text) > 80 and not any(kw in text.lower() for kw in [
            "cookie", "subscribe", "newsletter", "sign up", "privacy",
            "terms", "javascript", "browser"
        ]):
            clean.append(text)
        if len(clean) >= 3:
            break

    if not clean:
        print("  F1.com: could not extract article text")
        return None

    return {
        "text": " ".join(clean),
        "url": url,
        "source": "Formula 1",
    }


# ── Source 2: Wikipedia ────────────────────────────────────────────────────

def fetch_wikipedia_summary(race_name, year):
    """
    Fetch the Wikipedia article extract for the race.
    Returns dict with 'text', 'url', 'source' or None.
    """
    # "Monaco Grand Prix" → "2026_Monaco_Grand_Prix"
    title = f"{year}_{race_name.replace(' ', '_')}"
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}"
    print(f"  Wikipedia: {url}")
    data = fetch_json(url)
    if not data or data.get("type") == "https://mediawiki.org/wiki/HyperSwitch/errors/not_found":
        print("  Wikipedia: article not found")
        return None

    extract = data.get("extract", "").strip()
    if not extract or len(extract) < 100:
        print("  Wikipedia: extract too short or missing")
        return None

    wiki_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
    return {
        "text": extract,
        "url": wiki_url,
        "source": "Wikipedia",
    }


# ── Source 3: BBC Sport F1 RSS ─────────────────────────────────────────────

def fetch_bbc_headlines(n=5):
    """
    Fetch up to n headlines from BBC Sport F1 RSS.
    Returns list of dicts with 'title', 'url', 'description', 'published'.
    """
    print(f"  Fetching BBC Sport RSS…")
    xml_text = fetch(BBC_RSS)
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text)
        headlines = []
        for item in root.findall(".//item")[:n]:
            title = item.findtext("title", "").strip()
            link  = item.findtext("link",  "").strip()
            desc  = strip_tags(item.findtext("description", "")).strip()
            pub   = item.findtext("pubDate", "").strip()
            if title and link:
                headlines.append({
                    "title":       title,
                    "url":         link,
                    "description": desc[:300],
                    "published":   pub,
                })
        print(f"  BBC: {len(headlines)} headlines")
        return headlines
    except ET.ParseError as e:
        print(f"  BBC RSS parse error: {e}", file=sys.stderr)
        return []


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print(f"fetch_news.py  —  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # 1. Determine current race
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
        "updated":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "phase":    phase,
        "race": {
            "name":    race_name,
            "round":   round_num,
            "season":  year,
            "date":    date,
            "circuit": circuit,
        },
        "summary":   None,   # best available race narrative
        "article":   None,   # F1.com article teaser + link
        "headlines": [],     # BBC headlines
    }

    # 2. Race summaries (only useful post-race)
    if phase == "post-race":
        print("\n── Fetching race summary ──")

        # Try F1.com first (richest source)
        f1 = fetch_f1com_summary(race_name, year)
        if f1:
            result["article"] = f1
            # Use F1.com text as the primary summary too
            result["summary"] = f1

        # Always try Wikipedia as well (good intro paragraph)
        wiki = fetch_wikipedia_summary(race_name, year)
        if wiki:
            result["summary"] = wiki          # prefer Wikipedia for the summary card
            if not result["article"]:
                result["article"] = wiki      # fallback if F1.com failed

    # 3. BBC headlines (always useful)
    print("\n── Fetching BBC headlines ──")
    result["headlines"] = fetch_bbc_headlines()

    # 4. Write output
    os.makedirs("data", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)

    print(f"\n✓  Written → {OUTPUT_FILE}")
    summary_src = result["summary"]["source"] if result["summary"] else "none"
    article_src = result["article"]["source"] if result["article"] else "none"
    print(f"   summary source : {summary_src}")
    print(f"   article source : {article_src}")
    print(f"   headlines      : {len(result['headlines'])}")


if __name__ == "__main__":
    main()
