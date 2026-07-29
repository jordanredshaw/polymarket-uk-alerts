"""Alert on new UK politics events on Polymarket.

Polls the public Gamma API for active events carrying a UK tag, keeps the
ones that also carry a politics-flavoured tag, and WhatsApps Jordan (via
CallMeBot) about any not seen before. Seen event ids persist in
state/seen_events.json, committed back by the workflow.

First run (no state file yet) seeds the state silently so the backlog of
existing markets doesn't spam WhatsApp.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

GAMMA = "https://gamma-api.polymarket.com"
UA = {"User-Agent": "polymarket-uk-alerts/1.0 (github.com/jordanredshaw/polymarket-uk-alerts)"}
STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "seen_events.json"

# Tag ids that mark an event as UK-related (label / slug / id from /tags/slug/<slug>).
UK_TAG_IDS = {
    "734",     # uk
    "1372",    # united-kingdom
    "100245",  # britain
}

# An event must ALSO carry at least one of these tag slugs to count as "Politics".
# Polymarket's tagging is inconsistent (some political events lack the bare
# "politics" tag), so this list mixes topic, election, party, and person tags.
POLITICS_TAG_SLUGS = {
    "politics", "geopolitics", "elections", "uk-elections", "uk-by-elections",
    "global-elections", "world-elections", "main-election", "uk-politics",
    "international-election-props", "uk-labour-leadership", "parliament",
    "brexit", "labour", "reform-uk", "tories", "conservatives", "lib-dems",
    "snp", "keir-starmer", "nigel-farage", "andy-burnham", "kemi-badenoch",
}

MAX_EVENTS_PER_MESSAGE = 5


def fetch_uk_events() -> dict[str, dict]:
    """All active, unresolved events carrying any UK tag, keyed by event id."""
    events: dict[str, dict] = {}
    for tag_id in UK_TAG_IDS:
        offset = 0
        while True:
            resp = requests.get(
                f"{GAMMA}/events",
                params={
                    "tag_id": tag_id,
                    "active": "true",
                    "closed": "false",
                    "limit": 100,
                    "offset": offset,
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


def is_politics(event: dict) -> bool:
    slugs = {t.get("slug") for t in event.get("tags") or []}
    return bool(slugs & POLITICS_TAG_SLUGS)


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


def alert(new_events: list[dict]) -> None:
    for i in range(0, len(new_events), MAX_EVENTS_PER_MESSAGE):
        chunk = new_events[i : i + MAX_EVENTS_PER_MESSAGE]
        lines = ["\U0001f1ec\U0001f1e7 New UK politics on Polymarket:"]
        for ev in chunk:
            lines.append(f"\n• {ev.get('title') or ev.get('slug')}")
            lines.append(f"https://polymarket.com/event/{ev['slug']}")
        send_whatsapp("\n".join(lines))


def main() -> int:
    uk_events = fetch_uk_events()
    politics = {eid: ev for eid, ev in uk_events.items() if is_politics(ev)}
    print(f"{len(uk_events)} active UK-tagged events, {len(politics)} politics")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if not STATE_FILE.exists():
        seen = {
            eid: {"slug": ev["slug"], "first_seen": now} for eid, ev in politics.items()
        }
        STATE_FILE.write_text(json.dumps(seen, indent=2, sort_keys=True) + "\n")
        print(f"Seeded state with {len(seen)} existing events — no alerts on first run")
        return 0

    seen = json.loads(STATE_FILE.read_text())
    new = [ev for eid, ev in sorted(politics.items()) if eid not in seen]
    if not new:
        print("No new events")
        return 0

    for ev in new:
        print(f"NEW: {ev.get('title')} — https://polymarket.com/event/{ev['slug']}")

    # Alert first, record after: if sending fails the workflow fails and the
    # next run retries these events instead of losing them.
    alert(new)

    for ev in new:
        seen[str(ev["id"])] = {"slug": ev["slug"], "first_seen": now}
    STATE_FILE.write_text(json.dumps(seen, indent=2, sort_keys=True) + "\n")
    print(f"Alerted on {len(new)} new event(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
