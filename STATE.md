# Project State & Architecture Contract

## 1. Active Task & Goal
- **Current Objective:** Test TikTok alert system in production (6-day RSS.app trial) and prepare cutover to standalone GitHub Actions feed engine (`td-tiktok-feed`).
- **Status:** Deployed & Active on VPS (`discord-bot.service` @ 46MB RAM).

## 2. Technical Stack & Key Decisions
- **Host & Runtime:** Oracle Cloud VPS (Always Free, Ubuntu), Python 3.12, `discord.py` 2.x systemd service.
- **Database:** Supabase Cloud PostgreSQL (`psycopg` pool) with SQLite fallback (zero DB RAM overhead on VPS).
- **TikTok LIVE Architecture:** `TikTokLive` v7.0.1 Webcast API polling (bypasses WAF, sub-second latency, ~5MB RAM).
- **TikTok Video Architecture (Current):** RSS XML parser (`feedparser` in executor) via RSS.app (Trial active, 6 days remaining).
- **TikTok Video Architecture (Permanent Free):** Decoupled Public GitHub Actions repo (`td-tiktok-feed`) running Playwright stealth cron every 10 min -> outputs static `feeds/*.xml` (0MB RAM on VPS, unlimited minutes).

## 3. Completed in this Session
- `database/db_manager.py`: Added `tiktok_subscriptions` schema (`rss_url`, `last_video_id`), auto-migrations, and CRUD helpers.
- `cogs/tiktok.py`: Added dual LIVE/RSS polling loop (3-min interval), thumbnail extractor, and slash commands (`setup`, `follow`, `unfollow`, `list`, `check`, `feed`).
- Production VPS: Deployed, service running, linked `@chengaming54` feed (`7686406786701643029`), verified 27 slash commands synced.
- Prepared blueprint: Step-by-step setup for `td-tiktok-feed` GitHub Actions engine (Playwright + Stealth + RSS XML generator).

## 4. Next Actions (Immediate)
1. Monitor live & video alerts in Discord channel `<#1536984286006083584>` during 6-day trial.
2. User deploys `td-tiktok-feed` public repository on GitHub using the provided 3-file setup.
3. Switch ChenBot feed URL to `raw.githubusercontent.com/.../chengaming54.xml` via `/tiktok feed` before RSS.app trial ends.

## 5. Banned Practices & Gotchas
- **No Headless Browsers on VPS:** Never install Chromium/Playwright directly on Oracle VPS; runs exclusively in GitHub Actions.
- **TikTok Scraping:** Do not scrape `tiktok.com/@user` raw HTML from VPS datacenter IP (triggers SlardarWAF `_wafchallengeid`).
- **Private Repo Action Minutes:** Do not run TikTok cron under 25-min interval on private repos (consumes 2,000 min quota).
- **Coroutine Await:** `TikTokLiveClient.get_avatar_url()` is an async coroutine; always await before saving.
- **CDN Icons:** Never use temporary TikTok web static URLs in Discord embeds; use persistent CDN PNGs.
