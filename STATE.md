# Project State & Architecture Contract

## 1. Active Task & Goal
- **Current Objective:** Implement TikTok new video alert system via External RSS Generator (e.g. RSS.app) integrated into `cogs/tiktok.py` alongside the active LIVE notifier.
- **Status:** In Progress (LIVE completed & verified, RSS ready to implement).

## 2. Technical Stack & Key Decisions
- **Runtime & Deployment:** Python 3.12, `discord.py` 2.x systemd service (`discord-bot.service`) on Oracle Cloud VPS (`141.147.170.119`, user `ubuntu`).
- **Database:** Supabase PostgreSQL (Cloud) via `psycopg` (with SQLite fallback).
- **TikTok LIVE Architecture:** `TikTokLive` v7.0.1 Webcast API polling (bypasses datacenter WAF, sub-second latency, ~5MB RAM overhead).
- **TikTok RSS Video Strategy:** External RSS Generator (e.g. RSS.app) parsed via `feedparser` to bypass SlardarWAF without headless browser RAM usage.
- **Polling Loop:** Unified 3-minute interval (`@tasks.loop(minutes=3)`) matching YouTube & Twitch checkers, with periodic `gc.collect()`.

## 3. Completed in this Session
- `database/db_manager.py`:
  - Added `tiktok_subscriptions` table and `tiktok_channel_id` to `guild_settings`, registered in `ID_TABLES`.
  - Added `rss_url` and `last_video_id` columns with auto-migration (PostgreSQL & SQLite).
  - Added CRUD & channel helpers (`set_guild_tiktok_channel`, `get_guild_tiktok_channel`, `set_tiktok_subscription_rss`, `update_tiktok_last_video`).
- `cogs/tiktok.py`:
  - Implemented 3-minute polling loop with error isolation and auto-restart handler for both LIVE and RSS video feeds.
  - Resolved coroutine unawaited bug on `client.get_avatar_url()` and fixed broken icon URL with reliable CDN PNG.
  - Implemented RSS XML parser (`feedparser` in thread executor) and video embed builder with thumbnail extraction.
  - Added slash commands: `/tiktok setup`, `/tiktok follow`, `/tiktok unfollow`, `/tiktok list`, `/tiktok check`, `/tiktok feed`.
- `main.py` & `requirements.txt`: Added `tiktok` permission verification; verified `TikTokLive>=7.0.1`, `httpx>=0.27.0`, and `feedparser>=6.0.10`.

## 4. Next Actions (Immediate)
1. Commit & push changes to GitHub.
2. Deploy to production Oracle Cloud VPS (`git pull && sudo systemctl restart discord-bot.service`).
3. Run `/tiktok feed chengaming54 https://rss.app/feeds/6uRa8DlPU3jLP3MK.xml` on Discord server to activate video alerts.

## 5. Banned Practices & Gotchas
- **TikTok Scraping:** Do not scrape `tiktok.com/@user` directly from VPS; datacenter IPs trigger SlardarWAF (`_wafchallengeid`).
- **Coroutine Await:** `TikTokLiveClient.get_avatar_url()` is an async coroutine; always await and sanitize before passing to psycopg.
- **CDN Icons:** Never use temporary TikTok web static URLs for Discord embeds; use persistent CDN PNGs.
