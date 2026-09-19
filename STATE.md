# Project State & Architecture Contract

## 1. Active Task & Goal
- **Current Objective:** Run 6-day field test of TikTok alert system (LIVE via Webcast API + Video via RSS.app) while preparing lightweight self-hosted video scraper.
- **Status:** Deployed to Production & Active (`discord-bot.service` @ 46MB RAM).

## 2. Technical Stack & Key Decisions
- **Host & Runtime:** Oracle Cloud VPS (Always Free, Ubuntu), Python 3.12, `discord.py` 2.x systemd service.
- **Database:** Supabase Cloud PostgreSQL (`psycopg` pool) with SQLite local fallback (zero DB RAM overhead on VPS).
- **TikTok LIVE Architecture:** `TikTokLive` v7.0.1 Webcast API polling (bypasses WAF, sub-second latency, ~5MB RAM).
- **TikTok Video Architecture:** RSS XML parser (`feedparser` in thread executor) via RSS.app (Trial active, 6 days remaining).
- **Memory Guard:** Mandatory `gc.collect()` at end of 3-min loop; strict ban on headless browsers (Puppeteer/Chromium).

## 3. Completed in this Session
- `database/db_manager.py`: Added `tiktok_subscriptions` schema (`rss_url`, `last_video_id`), auto-migrations, and CRUD helpers.
- `cogs/tiktok.py`: Added dual LIVE/RSS polling loop, thumbnail extractor, and slash commands (`/tiktok setup`, `follow`, `unfollow`, `list`, `check`, `feed`).
- Production VPS: Deployed, service restarted, linked `@chengaming54` feed (`7686406786701643029`), verified 27 slash commands synced.

## 4. Next Actions (Immediate)
1. Monitor live & video alerts in Discord channel `<#1536984286006083584>` during 6-day trial.
2. Design and implement lightweight Python TikTok video fetcher (Mobile Web endpoint / zero-browser) before RSS.app trial expires.
3. Replace RSS.app URL in `tiktok_subscriptions` with permanent free internal scraper.

## 5. Banned Practices & Gotchas
- **No Headless Browsers:** Never install Chromium/Playwright on VPS; will cause OOM kill on free tier.
- **TikTok Scraping:** Do not scrape `tiktok.com/@user` raw HTML from VPS datacenter IP (triggers SlardarWAF `_wafchallengeid`).
- **Coroutine Await:** `TikTokLiveClient.get_avatar_url()` is an async coroutine; always await before saving.
- **CDN Icons:** Never use temporary TikTok web static URLs in Discord embeds; use persistent CDN PNGs.
