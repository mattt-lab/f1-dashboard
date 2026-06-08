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

    # Mirror the dashboard's findWeekendRace window exactly:
    #   post-race  →  FP1 up to race + 48 h
    #   upcoming   →  everything else (48 h after last race until next FP1,
    #                  AND during the next race weekend itself)
    if last_race:
        hours_since = (now - last_race[1]).total_seconds() / 3600
        if hours_since <= 48:
            return last_race[0], "post-race"

    if next_race:
        return next_race[0], "upcoming"

    # Fallback: no completed race yet (very start of season)
    if last_race:
        return last_race[0], "post-race"

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
        for item in root.findall(".//item")[:5]:
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




# Keywords that identify race-result vs preview items
RESULT_KW  = {"wins", "victory", "takes win", "clinches", "triumphs",
              "wins the", "takes the win", "race winner"}
PREVIEW_KW = {"preview", "guide", "ones to watch", "what to expect",
              "talking points", "five things", "what we learned"}

# BBC often uses the circuit city/name instead of the official Jolpica race name.
# Each entry is (official name fragment → [additional search terms]).
RACE_NAME_ALIASES = {
    "spanish":        ["barcelona", "catalunya"],
    "british":        ["silverstone"],
    "united states":  ["austin", "cota"],
    "mexican":        ["mexico city"],
    "são paulo":      ["brazil", "interlagos"],
    "azerbaijan":     ["baku"],
    "belgian":        ["spa"],
    "emilia romagna": ["imola"],
    "dutch":          ["zandvoort"],
    "hungarian":      ["hungaroring", "budapest"],
    "japanese":       ["suzuka"],
    "australian":     ["melbourne"],
    "canadian":       ["montreal"],
    "saudi arabian":  ["jeddah"],
    "chinese":        ["shanghai"],
    "qatar":          ["lusail"],
}


def _search_terms(race_name):
    """Return a list of strings, any of which counts as a match for this race."""
    terms = [race_name.lower()]
    low = race_name.lower()
    for key, aliases in RACE_NAME_ALIASES.items():
        if key in low:
            terms.extend(aliases)
    return terms


def _score_item(item, race_name):
    """Return (result_score, preview_score) for a BBC RSS item.
    Accepts any of the race's known aliases so BBC's city-based naming
    (e.g. 'Barcelona-Catalunya') matches Jolpica's official name ('Spanish GP')."""
    combined = (item["title"] + " " + item.get("description", "")).lower()
    terms    = _search_terms(race_name)
    if not any(t in combined for t in terms):
        return 0, 0
    r_score = sum(1 for kw in RESULT_KW  if kw in combined)
    p_score = sum(1 for kw in PREVIEW_KW if kw in combined)
    return r_score, p_score


def _race_relevant_items(race_name, items):
    """Return all RSS items that explicitly mention this race, scored."""
    scored = [(item, *_score_item(item, race_name)) for item in items]
    return scored


def _collect_snippets(race_name, items, max_items=6):
    """
    Gather up to max_items race-relevant snippets (title + description)
    to use as LLM input. Result items first, then color items.
    """
    scored = _race_relevant_items(race_name, items)
    result_items = sorted([(it, rs) for it, rs, _ in scored if rs > 0], key=lambda x: -x[1])
    terms = _search_terms(race_name)
    color_items  = [(it, 0) for it, rs, ps in scored
                    if rs == 0 and any(t in (it["title"] + it.get("description", "")).lower()
                                       for t in terms)]

    snippets, seen = [], set()
    for it, _ in (result_items + color_items):
        title = it.get("title", "").strip()
        desc  = it.get("description", "").strip()
        blob  = f"{title}: {desc}" if desc else title
        if blob not in seen:
            snippets.append(blob)
            seen.add(blob)
        if len(snippets) >= max_items:
            break
    return snippets


def claude_summarize(race_name, snippets, mode="post-race"):
    """
    Call the Anthropic Messages API to write a newsy race summary.
    Uses stdlib urllib — no extra packages required.
    Returns the summary string, or None if the key is missing / call fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("  ANTHROPIC_API_KEY not set — skipping LLM step")
        return None

    if mode == "post-race":
        instruction = (
            f"Write a 3-sentence race summary of the {race_name} for an F1 dashboard. "
            f"Write like a sports journalist — no clichés like 'claimed victory', "
            f"'took the chequered flag', or 'dominant performance'. "
            f"Use specific facts and active verbs. "
            f"Sentence 1: who won and how, with a specific detail. "
            f"Sentence 2: a key dramatic moment or quote. "
            f"Sentence 3: what it means for the championship standings. "
            f"Output only the summary text, no preamble."
        )
    else:
        instruction = (
            f"Write a 3-sentence preview of the upcoming {race_name} for an F1 dashboard. "
            f"Write like a sports journalist — active verbs, specific details, no filler. "
            f"Sentence 1: the headline storyline or title battle coming into the weekend. "
            f"Sentence 2: a secondary rivalry, wildcard, or tactical angle to watch. "
            f"Sentence 3: what would make this race significant in the championship. "
            f"Output only the preview text, no preamble."
        )

    content = instruction + "\n\nSource material:\n" + "\n".join(f"• {s}" for s in snippets)

    payload = json.dumps({
        "model":      "claude-haiku-4-5",
        "max_tokens": 250,
        "messages":   [{"role": "user", "content": content}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode())
            text = resp["content"][0]["text"].strip()
            print(f"  Claude summary: {len(text)} chars")
            return text
    except Exception as e:
        print(f"  Claude API error: {e}", file=sys.stderr)
        return None


def build_post_race_summary(race_name, items):
    """
    1. Collect race-relevant BBC RSS snippets.
    2. Ask Claude to write a newsy summary from them.
    3. Fall back to stitching raw descriptions if Claude unavailable.
    """
    snippets = _collect_snippets(race_name, items)
    if not snippets:
        print("  No relevant RSS items found", file=sys.stderr)
        return None

    # Try LLM first
    summary = claude_summarize(race_name, snippets, mode="post-race")
    if summary:
        return summary

    # Fallback: stitch the top descriptions together
    print("  Falling back to raw descriptions…")
    parts, seen = [], set()
    for s in snippets[:3]:
        desc = s.split(": ", 1)[-1]   # strip "Title: " prefix
        if desc not in seen:
            parts.append(desc)
            seen.add(desc)
    return " ".join(parts) if parts else None


def build_preview_summary(race_name, items):
    """
    1. Collect preview-tagged BBC RSS snippets.
    2. Ask Claude to write a preview from them.
    3. Fall back to Wikipedia evergreen article if nothing available.
    """
    snippets = _collect_snippets(race_name, items)
    if snippets:
        summary = claude_summarize(race_name, snippets, mode="upcoming")
        if summary:
            return summary

    # Wikipedia evergreen fallback (circuit background is useful pre-race)
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
