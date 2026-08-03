# polymarket-uk-alerts

WhatsApp alert (via CallMeBot) whenever a Polymarket event Jordan cares about
opens. Runs every 5 minutes in GitHub Actions — no server, no auth needed for
the Polymarket side (public Gamma API).

## Watch groups

1. **UK politics** (🇬🇧): events carrying a UK tag (`uk`, `united-kingdom`,
   `britain`) AND a politics-flavoured tag (`POLITICS_TAG_SLUGS` in
   [check.py](src/check.py) — topic, election, party, and person tags,
   because Polymarket's tagging is inconsistent).
2. **FIFA story** (⚽): events tagged `fifa`, `world-cup`, `fifa-world-cup`,
   `uefa`, or `soccer` whose title/description matches story keywords —
   `infantino` anywhere; FIFA/World Cup context + expansion / sell-off /
   boycott / 64 / 128 / breakaway / new format / privatisation words; UEFA
   context + boycott / withdraw / pull out / leave FIFA. Keyword-gated
   because the `soccer` tag is 2,000+ match markets of noise (`split` is
   deliberately not a UEFA keyword — Hajduk Split). Known gap: an event
   tagged only `sports` with none of the five football tags is missed.
3. **UEFA newsroom** (🔷): every new article on
   [uefa.com/news-media/news](https://www.uefa.com/news-media/news/), no
   keyword filter. There is no RSS feed; [uefa_news.py](src/uefa_news.py)
   polls the editorial API the page itself uses
   (`editorial.uefa.com/api/cachedsearch/build`, Corporate Communications
   folder, newest-first) and resolves article links via
   `www.uefa.com/api/v1/linkrules/article/<id>/`. Akamai quirks are
   documented in the module docstring (default python UA → 403, fake
   browser UA → blocked; plain custom UA works). Separate state file:
   `state/seen_uefa_articles.json`.

## How it works

Each group's events come from
`https://gamma-api.polymarket.com/events?tag_id=...` (newest 300 per tag —
new events always land on page 1 of a 5-minute poll, and the API rejects
deep pagination anyway). Anything matching a group that isn't in
[state/seen_events.json](state/seen_events.json) triggers a WhatsApp message
with title + link, then gets recorded. The workflow commits the state file
back to the repo.

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
  [check.yml](.github/workflows/check.yml). Every 5 minutes is GitHub's
  minimum schedule interval; runs can slip a few minutes at peak times. The
  repo is **public** so Actions minutes are free and uncapped (a private repo
  at this cadence would blow through the free 2,000 min/month).
- **Note**: GitHub disables scheduled workflows after 60 days with no repo
  activity; state commits from new markets normally reset that clock, but if
  alerts ever stop after a long quiet spell, re-enable the workflow from the
  Actions tab.
- **What counts as a match**: `UK_TAG_IDS` / `POLITICS_TAG_SLUGS` and
  `FIFA_TAG_IDS` / the `FIFA_*` and `UEFA_*` regexes in
  [check.py](src/check.py); new groups go in `WATCH_GROUPS`.

## Manual run

Actions tab → "Check for new UK politics markets" → Run workflow, or:

```bash
gh workflow run check.yml -R jordanredshaw/polymarket-uk-alerts
```
