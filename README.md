# polymarket-uk-alerts

WhatsApp alert (via CallMeBot) whenever a new UK politics event opens on
Polymarket. Runs hourly in GitHub Actions — no server, no auth needed for the
Polymarket side (public Gamma API).

## How it works

1. [check.py](src/check.py) fetches all active, unresolved Polymarket events
   carrying a UK tag (`uk`, `united-kingdom`, `britain`) from
   `https://gamma-api.polymarket.com/events?tag_id=...`.
2. Keeps events that also carry a politics-flavoured tag
   (`POLITICS_TAG_SLUGS` in check.py — topic, election, party, and person
   tags, because Polymarket's tagging is inconsistent).
3. Anything not in [state/seen_events.json](state/seen_events.json) triggers a
   WhatsApp message with title + link, then gets recorded. The workflow
   commits the state file back to the repo.

The very first run seeds the state file silently (no alert backlog spam).

If the WhatsApp send fails, the run fails **before** recording the events, so
the next run retries them — and GitHub emails about the failed workflow, so
alerting can't break silently.

## Alert granularity

Alerts fire per **event** (the market page, e.g. "Next UK Prime Minister"),
not per outcome market inside it — one page with 8 candidate markets is one
alert, and adding a 9th candidate later does not re-alert.

## Secrets (repo → Settings → Secrets → Actions)

| Secret | Value |
|---|---|
| `WHATSAPP_PHONE` | same as in train-alerts |
| `CALLMEBOT_KEY` | same as in train-alerts |

## Tuning

- **Cadence**: edit the cron in
  [check.yml](.github/workflows/check.yml). Hourly ≈ 720 Actions
  minutes/month on a private repo; every 30 min doubles that — watch the free
  2,000-minute cap alongside train-alerts (~800/month). Making the repo
  public removes the cap entirely.
- **What counts as UK / politics**: `UK_TAG_IDS` and `POLITICS_TAG_SLUGS` at
  the top of [check.py](src/check.py).

## Manual run

Actions tab → "Check for new UK politics markets" → Run workflow, or:

```bash
gh workflow run check.yml -R jordanredshaw/polymarket-uk-alerts
```
