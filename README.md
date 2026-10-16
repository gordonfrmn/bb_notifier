# bb_notifier

Posts to Discord when a new bug bounty program or in-scope asset appears on
HackerOne, Bugcrowd, Intigriti or YesWeHack. Runs every 30 min on GitHub Actions
using data from [arkadiyt/bounty-targets-data](https://github.com/arkadiyt/bounty-targets-data).

## Setup
1. Discord: Server Settings → Integrations → Webhooks → New Webhook → copy URL.
2. Create a GitHub repo (public = unlimited free Actions minutes), push this folder.
3. Repo Settings → Secrets and variables → Actions → add `DISCORD_WEBHOOK`.
   (Locally, `secrets.env` is read instead; it's gitignored.)
4. Actions tab → `check-bounty-targets` → Run workflow. The first run seeds
   `state/` silently (no notifications); after that you only get new items.

## Config (`config.json`)
| key | meaning |
|---|---|
| `platforms` | which platforms to watch |
| `bounty_only` | skip VDPs / non-bounty-eligible assets |
| `mute_categories` | don't notify for assets in these categories (`[]` = notify everything). Categories: web, wildcard, api, android, ios, mobile, application, executable, windows app, source code, hardware, network, smart contract, ai model, other, unknown. New programs whose assets are all muted are muted too. |
| `stale_hours` | alert if upstream hasn't updated in this long |
| `min_ratio` | skip a platform if its program count drops below this fraction (scraper glitch) |
| `flood_threshold` | above this many new items, send one summary instead of individual alerts |
| `max_assets_per_program` | assets listed per Discord embed |

## Safeguards
- **Upstream stale** → one Discord warning, plus a "recovered" message when it updates again.
- **Programs that flap** (vanish and come back) → `state/seen.json` only ever grows, so a returning program doesn't trigger a second alert.
- **Broken or truncated upstream file** → that platform is skipped for the run and a warning is posted.
- **Script error** → GitHub emails you about the failed run.

## Local testing
```
DRY_RUN=1 python3 notifier.py                 # live data, prints instead of posting
DRY_RUN=1 DATA_DIR=./data python3 notifier.py # use local <platform>.json files
```
Removing keys from `state/seen.json` makes them show up as new on the next run.
