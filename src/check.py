"""Alert on new Polymarket events Jordan cares about, via WhatsApp (CallMeBot).

Two watch groups:
  - UK politics: events carrying a UK tag AND a politics-flavoured tag.
  - FIFA story: events in a pool of football tags whose title/description
    matches story keywords (Infantino, World Cup expansion/sell-off, UEFA
    boycott). Keyword-gated because Polymarket's football tagging is sloppy
    and the soccer tag is 2,000+ match markets of noise.

Seen event ids persist in state/seen_events.json, committed back by the
workflow. First run (no state file) seeds silently so the backlog of existing
markets doesn't spam WhatsApp.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

GAMMA = "https://gamma-api.polymarket.com"
UA = {"User-Agent": "polymarket-uk-alerts/1.0 (github.com/jordanredshaw/polymarket-uk-alerts)"}

# Gamma occasionally hangs or 5xxs (read timeout killed a run on 5 Aug 2026);
# retry API fetches with backoff. WhatsApp sends deliberately do NOT retry —
# a mid-flight retry could double-send, and a failed send already retries on
# the next workflow run.
API = requests.Session()
API.mount("https://", HTTPAdapter(max_retries=Retry(
    total=4, connect=4, read=4, backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET", "HEAD"],
)))
STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "seen_events.json"

# Fetch newest-first and stop after this many events per tag: new events always
# land on page 1 of a 5-minute poll, and the API 422s on deep offsets anyway.
MAX_EVENTS_PER_TAG = 300
MAX_EVENTS_PER_MESSAGE = 5

# ---------------------------------------------------------------- UK politics

# Tag ids that mark an event as UK-related (label / slug / id from /tags/slug/<slug>).
UK_TAG_IDS = {
    "734",     # uk
    "1372",    # united-kingdom
    "100245",  # britain
}

# A UK event must ALSO carry at least one of these tag slugs to count as
# "Politics". Polymarket's tagging is inconsistent (some political events lack
# the bare "politics" tag), so this list mixes topic, election, party, and
# person tags.
POLITICS_TAG_SLUGS = {
    "politics", "geopolitics", "elections", "uk-elections", "uk-by-elections",
    "global-elections", "world-elections", "main-election", "uk-politics",
    "international-election-props", "uk-labour-leadership", "parliament",
    "brexit", "labour", "reform-uk", "tories", "conservatives", "lib-dems",
    "snp", "keir-starmer", "nigel-farage", "andy-burnham", "kemi-badenoch",
}

# ------------------------------------------------------------------ FIFA story

FIFA_TAG_IDS = {
    "102183",  # fifa
    "519",     # world-cup
    "102232",  # fifa-world-cup
    "100781",  # uefa
    "100350",  # soccer (the noisy one — keyword gate below does the filtering)
}

# Alert rules, applied to title + description (case-insensitive):
#   1. "infantino" anywhere always alerts.
#   2. FIFA/World Cup context + a story word.
#   3. UEFA context + an action word. ("split" deliberately absent — it
#      matches every Hajduk Split fixture.)
FIFA_ALWAYS = re.compile(r"infantino", re.I)
FIFA_CONTEXT = re.compile(r"fifa|world cup", re.I)
FIFA_STORY = re.compile(
    r"boycott|expan(d|sion|ded)|\b64\b|\b128\b|sell[ -]?off|\bsale\b|\bsell\b"
    r"|\bsold\b|breakaway|new format|privati[sz]",
    re.I,
)
UEFA_CONTEXT = re.compile(r"uefa", re.I)
UEFA_ACTION = re.compile(r"boycott|withdraw|pulls? out|leaves? fifa", re.I)


def is_uk_politics(event: dict) -> bool:
    slugs = {t.get("slug") for t in event.get("tags") or []}
    return bool(slugs & POLITICS_TAG_SLUGS)


def is_fifa_story(event: dict) -> bool:
    text = (event.get("title") or "") + " " + (event.get("description") or "")
    if FIFA_ALWAYS.search(text):
        return True
    if FIFA_CONTEXT.search(text) and FIFA_STORY.search(text):
        return True
    return bool(UEFA_CONTEXT.search(text) and UEFA_ACTION.search(text))


WATCH_GROUPS = [
    {"name": "UK politics", "prefix": "\U0001f1ec\U0001f1e7 New UK politics on Polymarket:",
     "tag_ids": UK_TAG_IDS, "match": is_uk_politics},
    {"name": "FIFA story", "prefix": "⚽ New FIFA/World Cup market on Polymarket:",
     "tag_ids": FIFA_TAG_IDS, "match": is_fifa_story},
]

# ---------------------------------------------------------------------- engine


def fetch_events(tag_ids: set[str]) -> dict[str, dict]:
    """Active, unresolved events carrying any of the tags, keyed by event id."""
    events: dict[str, dict] = {}
    for tag_id in tag_ids:
        offset = 0
        while offset < MAX_EVENTS_PER_TAG:
            resp = API.get(
                f"{GAMMA}/events",
                params={
                    "tag_id": tag_id,
                    "active": "true",
                    "closed": "false",
                    "limit": 100,
                    "offset": offset,
                    "order": "startDate",
                    "ascending": "false",
                },
                headers=UA,
                timeout=30,
            )
            resp.raise_for_status()
            page = resp.json()
            for ev in page:
                events[str(ev["id"])] = ev
            if len(page) < 100:
                break
            offset += 100
    return events


def send_whatsapp(text: str) -> None:
    phone = os.environ.get("WHATSAPP_PHONE")
    key = os.environ.get("CALLMEBOT_KEY")
    if not phone or not key:
        raise RuntimeError("WhatsApp not configured (WHATSAPP_PHONE / CALLMEBOT_KEY)")
    resp = requests.get(
        "https://api.callmebot.com/whatsapp.php",
        params={"phone": phone, "text": text, "apikey": key},
        headers=UA,
        timeout=30,
    )
    resp.raise_for_status()
    # CallMeBot returns 200 with an error message in the body for bad keys.
    if "APIKey is invalid" in resp.text or "not activated" in resp.text:
        raise RuntimeError(f"CallMeBot rejected the request: {resp.text[:200]}")


def alert(prefix: str, new_events: list[dict]) -> None:
    for i in range(0, len(new_events), MAX_EVENTS_PER_MESSAGE):
        chunk = new_events[i : i + MAX_EVENTS_PER_MESSAGE]
        lines = [prefix]
        for ev in chunk:
            lines.append(f"\n• {ev.get('title') or ev.get('slug')}")
            lines.append(f"https://polymarket.com/event/{ev['slug']}")
        send_whatsapp("\n".join(lines))


def main() -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    seeding = not STATE_FILE.exists()
    seen: dict[str, dict] = {} if seeding else json.loads(STATE_FILE.read_text())
    alerted = 0

    for group in WATCH_GROUPS:
        pool = fetch_events(group["tag_ids"])
        matched = {eid: ev for eid, ev in pool.items() if group["match"](ev)}
        new = [ev for eid, ev in sorted(matched.items()) if eid not in seen]
        print(f"{group['name']}: {len(pool)} in pool, {len(matched)} matched, {len(new)} new")

        if new and not seeding:
            for ev in new:
                print(f"NEW: {ev.get('title')} — https://polymarket.com/event/{ev['slug']}")
            # Alert first, record after: if sending fails the workflow fails
            # and the next run retries these events instead of losing them.
            alert(group["prefix"], new)
            alerted += len(new)

        for ev in new:
            seen[str(ev["id"])] = {"slug": ev["slug"], "first_seen": now}

    STATE_FILE.write_text(json.dumps(seen, indent=2, sort_keys=True) + "\n")
    if seeding:
        print(f"Seeded state with {len(seen)} existing events — no alerts on first run")
    else:
        print(f"Alerted on {alerted} new event(s)" if alerted else "No new events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
