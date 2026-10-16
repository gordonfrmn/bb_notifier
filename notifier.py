#!/usr/bin/env python3
"""Notify Discord about new bug bounty programs / in-scope assets.

Data source: https://github.com/arkadiyt/bounty-targets-data
State: state/seen.json (cumulative set of seen keys), state/meta.json.

Env vars:
  DISCORD_WEBHOOK   Discord webhook URL (required unless DRY_RUN=1); for local
                    runs it can also be set in secrets.env (KEY=value lines)
  GITHUB_TOKEN      optional, raises GitHub API rate limit for the freshness check
  DRY_RUN=1         print messages instead of posting them
  DATA_DIR=path     read <platform>.json from a local dir instead of downloading
                    (also skips the upstream freshness check)
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"
SEEN_FILE = STATE_DIR / "seen.json"
META_FILE = STATE_DIR / "meta.json"
CONFIG_FILE = ROOT / "config.json"
SECRETS_FILE = ROOT / "secrets.env"

UPSTREAM = "arkadiyt/bounty-targets-data"
RAW_URL = f"https://raw.githubusercontent.com/{UPSTREAM}/main/data/{{}}_data.json"
COMMITS_URL = f"https://api.github.com/repos/{UPSTREAM}/commits?per_page=1"

PLATFORM_LABEL = {
    "hackerone": "HackerOne",
    "bugcrowd": "Bugcrowd",
    "intigriti": "Intigriti",
    "yeswehack": "YesWeHack",
}
PLATFORM_COLOR = {
    "hackerone": 0x494649,
    "bugcrowd": 0xF26822,
    "intigriti": 0x161A36,
    "yeswehack": 0x2ECC71,
}

# Platform-specific asset types -> common category shown in Discord.
# Unmapped types are shown as-is (lowercased).
ASSET_CATEGORY = {
    "url": "web", "website": "web", "web-application": "web",
    "wildcard": "wildcard",
    "api": "api",
    "google_play_app_id": "android", "other_apk": "android", "android": "android",
    "mobile-application-android": "android",
    "apple_store_app_id": "ios", "testflight": "ios", "other_ipa": "ios", "ios": "ios",
    "mobile-application-ios": "ios",
    "mobile-application": "mobile", "application": "application",
    "downloadable_executables": "executable", "windows_app_store_app_id": "windows app",
    "source_code": "source code",
    "hardware": "hardware", "iot": "hardware", "device": "hardware",
    "cidr": "network", "ip_address": "network", "iprange": "network", "network": "network",
    "smart_contract": "smart contract",
    "ai_model": "ai model", "ai-model": "ai model",
    "other": "other", "challenge": "other",
}


def asset_category(typ):
    t = (typ or "").strip().lower()
    return ASSET_CATEGORY.get(t, t or "unknown")

if SECRETS_FILE.exists():
    for line in SECRETS_FILE.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"\''))

DRY_RUN = os.environ.get("DRY_RUN") == "1"
DATA_DIR = os.environ.get("DATA_DIR")


# --------------------------------------------------------------------------- http

def http(url, data=None, headers=None, timeout=60):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    req.add_header("User-Agent", "bb-notifier")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def get_json(url, headers=None):
    return json.loads(http(url, headers=headers))


# --------------------------------------------------------------------------- normalize

def norm_asset(s):
    return " ".join(str(s).split()).lower().rstrip("/")


def _program(pid, name, url, bounty, bounty_str, assets):
    return {
        "id": str(pid),
        "name": (name or str(pid)).strip(),
        "url": url,
        "bounty": bool(bounty),
        "bounty_str": bounty_str,
        # list of (asset, type, eligible_for_bounty)
        "assets": [a for a in assets if a[0]],
    }


def normalize(platform, data):
    out = []
    for p in data:
        ins = (p.get("targets") or {}).get("in_scope") or []
        if platform == "hackerone":
            bounty = p.get("offers_bounties")
            out.append(_program(
                p["handle"], p.get("name"), p.get("url"), bounty,
                "Bounty" if bounty else "VDP",
                [(t.get("asset_identifier"), t.get("asset_type"),
                  t.get("eligible_for_bounty", True)) for t in ins]))
        elif platform == "bugcrowd":
            mx = p.get("max_payout") or 0
            out.append(_program(
                p["url"], p.get("name"), p.get("url"), mx > 0,
                f"up to ${mx:,}" if mx else "No bounty listed",
                [(t.get("target") or t.get("uri") or t.get("name"), t.get("type"), True)
                 for t in ins]))
        elif platform == "intigriti":
            mn = (p.get("min_bounty") or {}).get("value") or 0
            mx = (p.get("max_bounty") or {}).get("value") or 0
            cur = (p.get("max_bounty") or {}).get("currency") or ""
            out.append(_program(
                p.get("id") or p["url"], p.get("name"), p.get("url"), mx > 0,
                f"{mn:,}–{mx:,} {cur}" if mx else "VDP",
                [(t.get("endpoint"), t.get("type"), True) for t in ins]))
        elif platform == "yeswehack":
            mn = p.get("min_bounty") or 0
            mx = p.get("max_bounty") or 0
            out.append(_program(
                p["id"], p.get("name"), f"https://yeswehack.com/programs/{p['id']}",
                mx > 0, f"€{mn:,}–€{mx:,}" if mx else "VDP",
                [(t.get("target"), t.get("type"), True) for t in ins]))
    return out


def load_platform(platform):
    if DATA_DIR:
        with open(Path(DATA_DIR) / f"{platform}.json", encoding="utf-8") as f:
            raw = json.load(f)
    else:
        raw = get_json(RAW_URL.format(platform))
    if not isinstance(raw, list):
        raise ValueError(f"expected a list, got {type(raw).__name__}")
    return normalize(platform, raw)


# --------------------------------------------------------------------------- discord

def post_discord(payload):
    if DRY_RUN:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    url = os.environ["DISCORD_WEBHOOK"]
    body = json.dumps(payload).encode()
    for _ in range(5):
        try:
            http(url, data=body, headers={"Content-Type": "application/json"})
            time.sleep(1)
            return
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            retry = json.loads(e.read() or b"{}").get("retry_after", 2)
            time.sleep(float(retry) + 0.5)
    raise RuntimeError("Discord rate limit: gave up after 5 retries")


def send_text(msg):
    post_discord({"content": msg[:2000]})


def embed_size(e):
    return len(e.get("title", "")) + len(e.get("description", "")) + \
        len(e.get("footer", {}).get("text", ""))


def send_embeds(embeds):
    batch, size = [], 0
    for e in embeds:
        s = embed_size(e)
        if batch and (len(batch) == 10 or size + s > 5800):
            post_discord({"embeds": batch})
            batch, size = [], 0
        batch.append(e)
        size += s
    if batch:
        post_discord({"embeds": batch})


def build_embed(platform, prog, assets, is_new, max_assets):
    label = PLATFORM_LABEL[platform]
    if is_new:
        title = f"🆕 New program: {prog['name']}"
    else:
        title = f"➕ {len(assets)} new asset{'s' if len(assets) != 1 else ''}: {prog['name']}"
    lines = [f"**{label}** · {prog['bounty_str']}"]
    if assets:
        cats = Counter(asset_category(t) for _, t, _ in assets)
        lines.append("Types: " + " · ".join(f"{n} {c}" for c, n in cats.most_common()))
        lines.append("")
        for asset, typ, _ in assets[:max_assets]:
            a = asset if len(asset) <= 150 else asset[:147] + "..."
            lines.append(f"`{asset_category(typ)}` {a}")
        if len(assets) > max_assets:
            lines.append(f"…and {len(assets) - max_assets} more")
    embed = {
        "title": title[:256],
        "description": "\n".join(lines)[:4000],
        "color": PLATFORM_COLOR[platform],
    }
    if prog.get("url"):
        embed["url"] = prog["url"]
    return embed


# --------------------------------------------------------------------------- state

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")


# --------------------------------------------------------------------------- main

def check_freshness(cfg, meta):
    """Alert once when upstream goes stale, once more when it recovers."""
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    commit = get_json(COMMITS_URL, headers=headers)[0]
    date_s = commit["commit"]["committer"]["date"]
    last = datetime.fromisoformat(date_s.replace("Z", "+00:00"))
    age_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600
    stale = age_h > cfg["stale_hours"]
    if stale and not meta.get("stale_alerted"):
        send_text(f"⚠️ **bounty-targets-data is stale**: last upstream update was "
                  f"{date_s} ({age_h:.1f} h ago). Notifications may be delayed.")
        meta["stale_alerted"] = True
    elif not stale and meta.get("stale_alerted"):
        send_text(f"✅ bounty-targets-data is updating again (last update {date_s}).")
        meta["stale_alerted"] = False
    return stale


def run():
    cfg = load_json(CONFIG_FILE, {})
    cfg.setdefault("platforms", list(PLATFORM_LABEL))
    cfg.setdefault("bounty_only", False)
    cfg.setdefault("exclude_asset_types", [])
    cfg.setdefault("stale_hours", 6)
    cfg.setdefault("min_ratio", 0.5)
    cfg.setdefault("flood_threshold", 200)
    cfg.setdefault("max_assets_per_program", 15)
    excluded_types = {t.lower() for t in cfg["exclude_asset_types"]}

    seen_list = load_json(SEEN_FILE, [])
    seen = set(seen_list)
    meta = load_json(META_FILE, {})
    meta_before = json.dumps(meta, sort_keys=True)
    counts = meta.setdefault("program_counts", {})
    first_run = not seen

    if not DATA_DIR:
        check_freshness(cfg, meta)

    embeds, warnings, total_new = [], [], 0
    new_keys = set()
    for platform in cfg["platforms"]:
        try:
            programs = load_platform(platform)
        except Exception as e:  # noqa: BLE001 - one bad platform shouldn't kill the run
            warnings.append(f"{PLATFORM_LABEL[platform]}: failed to load ({e})")
            continue
        prev = counts.get(platform, 0)
        if prev and len(programs) < prev * cfg["min_ratio"]:
            warnings.append(f"{PLATFORM_LABEL[platform]}: only {len(programs)} programs "
                            f"(was {prev}), skipping this run")
            continue
        counts[platform] = len(programs)

        for prog in programs:
            pkey = f"{platform}|{prog['id']}"
            is_new = pkey not in seen
            fresh = []
            for asset, typ, eligible in prog["assets"]:
                akey = f"{pkey}|{norm_asset(asset)}"
                if akey in seen or akey in new_keys:
                    continue
                new_keys.add(akey)
                if (typ or "").lower() in excluded_types:
                    continue
                if cfg["bounty_only"] and not eligible:
                    continue
                fresh.append((asset, typ, eligible))
            new_keys.add(pkey)

            if first_run:
                continue
            if cfg["bounty_only"] and not prog["bounty"]:
                continue
            if is_new or fresh:
                total_new += 1 + len(fresh) if is_new else len(fresh)
                embeds.append(build_embed(platform, prog, fresh, is_new,
                                          cfg["max_assets_per_program"]))

    # Notify before saving state: if Discord fails, the run fails and retries next time.
    if warnings:
        send_text("⚠️ " + "\n⚠️ ".join(warnings))
    if first_run:
        print(f"First run: seeded {len(new_keys)} keys without notifying.")
    elif total_new > cfg["flood_threshold"]:
        names = ", ".join(e["title"].split(": ", 1)[-1] for e in embeds[:20])
        send_text(f"📦 {total_new} new programs/assets across {len(embeds)} programs "
                  f"(too many to list individually). Includes: {names}"
                  + ("…" if len(embeds) > 20 else ""))
    elif embeds:
        send_embeds(embeds)
    print(f"{len(embeds)} programs with changes, {total_new} new items, "
          f"{len(warnings)} warnings.")

    if new_keys - seen:
        save_json(SEEN_FILE, sorted(seen | new_keys))
    if json.dumps(meta, sort_keys=True) != meta_before:
        save_json(META_FILE, meta)


if __name__ == "__main__":
    run()
