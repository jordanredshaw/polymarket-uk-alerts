"""Alert on new articles in UEFA's newsroom (uefa.com/news-media/news/).

No RSS feed exists; the page is client-rendered from an editorial API
(discovered via the page's own network calls):

    GET https://editorial.uefa.com/api/cachedsearch/build
        ?param.attributes.workFolder=/UEFA/Corporate Communications
        &sorting=-attributes.firstPublicationDate ...

Akamai notes: a missing/default python-requests User-Agent gets 403, and a
fake browser UA gets blocked too — a plain custom UA works. The
`param.attributes.hideFromWeb!` key relies on requests keeping `key!=value`
intact (don't percent-encode the `=`).

Article links go through https://www.uefa.com/api/v1/linkrules/article/<id>/
which 301s to the friendly URL; we resolve it at alert time and fall back to
the linkrules URL itself.

Same state pattern as check.py: seen ids in state/seen_uefa_articles.json,
committed back by the workflow; first run seeds silently; alerts send BEFORE
state is written so a failed send retries next run.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

UA = {
    "User-Agent": "polymarket-uk-alerts/1.0 (+github.com/jordanredshaw/polymarket-uk-alerts)",
    "Accept": "application/json",
}
STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "seen_uefa_articles.json"

SEARCH_PARAMS = {
    "param.attributes.hideFromWeb!": "true",
    "aggregator": "lightnodejson",
    "limit": 16,
    "offset": 0,
    "param.attributes.language": "en",
    "param.attributes.main.kind": (
        "Booking List,Photo Gallery,News Article,Interviews,Media Information,"
        "Media Info,Video,Finance,Cases,Bids,Association Profile,Regulations"
    ),
    "param.attributes.workFolder": "/UEFA/Corporate Communications",
    "sorting": "-attributes.firstPublicationDate",
    "type": "article,promo",
}

MAX_ARTICLES_PER_MESSAGE = 5


def fetch_articles() -> dict[str, dict]:
    """Newest newsroom articles keyed by article id."""
    resp = requests.get(
        "https://editorial.uefa.com/api/cachedsearch/build",
        params=SEARCH_PARAMS,
        headers=UA,
        timeout=30,
    )
    resp.raise_for_status()
    articles = {}
    for item in resp.json()["result"]:
        nd = item["nodeData"]
        articles[nd["id"]] = {
            "title": nd.get("title") or nd["id"],
            "published": (nd.get("attributes") or {}).get("firstPublicationDate", ""),
        }
    return articles


def article_url(article_id: str) -> str:
    link = f"https://www.uefa.com/api/v1/linkrules/article/{article_id}/"
    try:
        resp = requests.head(link, headers=UA, allow_redirects=False, timeout=15)
        loc = resp.headers.get("Location", "")
        if loc.startswith("/"):
            return f"https://www.uefa.com{loc}"
        if loc.startswith("http"):
            return loc
    except requests.RequestException:
        pass
    return link  # the redirect works in a browser even if we couldn't resolve it


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
    if "APIKey is invalid" in resp.text or "not activated" in resp.text:
        raise RuntimeError(f"CallMeBot rejected the request: {resp.text[:200]}")


def main() -> int:
    articles = fetch_articles()
    print(f"UEFA newsroom: {len(articles)} articles in feed")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if not STATE_FILE.exists():
        seen = {aid: {**a, "first_seen": now} for aid, a in articles.items()}
        STATE_FILE.write_text(json.dumps(seen, indent=2, sort_keys=True) + "\n")
        print(f"Seeded state with {len(seen)} existing articles — no alerts on first run")
        return 0

    seen = json.loads(STATE_FILE.read_text())
    new = [(aid, a) for aid, a in articles.items() if aid not in seen]
    if not new:
        print("No new articles")
        return 0

    new.sort(key=lambda x: x[1]["published"])
    entries = []
    for aid, a in new:
        url = article_url(aid)
        print(f"NEW: {a['title']} — {url}")
        entries.append((a["title"], url))

    for i in range(0, len(entries), MAX_ARTICLES_PER_MESSAGE):
        chunk = entries[i : i + MAX_ARTICLES_PER_MESSAGE]
        lines = ["\U0001f537 New UEFA newsroom article:"]
        for title, url in chunk:
            lines.append(f"\n• {title}")
            lines.append(url)
        send_whatsapp("\n".join(lines))

    for aid, a in new:
        seen[aid] = {**a, "first_seen": now}
    STATE_FILE.write_text(json.dumps(seen, indent=2, sort_keys=True) + "\n")
    print(f"Alerted on {len(new)} new article(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
