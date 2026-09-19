# Project State & Architecture Contract

## 1. Active Task & Goal
- **Current Objective:** Implement lightweight TikTok LIVE notification system (`TikTokLive` library) without heavy headless browsers on Oracle Cloud Free Tier VPS.
- **Status:** Implemented & Verified on Production VPS.

## 2. Technical Stack & Key Decisions
- **Runtime & Deployment:** Python 3.12, `discord.py` 2.x systemd service (`discord-bot.service`) on Oracle Cloud VPS (`141.147.170.119`, user `ubuntu`).
- **Database:** Supabase PostgreSQL (Cloud) via `psycopg` (with SQLite fallback).
- **TikTok LIVE Architecture:** `TikTokLive` v7.0.1 Webcast API polling (bypasses datacenter WAF, sub-second latency, ~5MB memory overhead).
- **TikTok Subscriptions:** Stored in `tiktok_subscriptions` table (`guild_id`, `tiktok_username`, `nickname`, `alert_channel_id`, `last_room_id`, `is_live`, `avatar_url`).
- **Polling Loop:** Aligned to 3-minute interval (`@tasks.loop(minutes=3)`), identical to YouTube and Twitch checkers.
- **Memory Optimization:** Periodic loop calls `gc.collect()` to maintain VPS bot RAM <= 55MB.

## 3. Completed in this Session
- `database/db_manager.py`: Added `tiktok_subscriptions` table, added `tiktok_channel_id` to `guild_settings`, registered in `ID_TABLES`, added CRUD and channel helper methods (`set_guild_tiktok_channel`, `get_guild_tiktok_channel`).
- `cogs/tiktok.py`:
  - 3-minute polling loop with error isolation and auto-restart handler.
  - Added `/tiktok setup <channel>` to configure the default alert channel for the server and retroactively update all tracked TikTok accounts.
  - Updated `/tiktok follow <username> [channel]` to automatically fall back to the setup channel.
  - Slash commands: `/tiktok setup`, `/tiktok follow`, `/tiktok unfollow`, `/tiktok list`, `/tiktok check`.
- `main.py`: Added `tiktok` command permission verification in `global_interaction_check`.
- `requirements.txt`: Added `TikTokLive>=7.0.1` and `httpx>=0.27.0`.

## 4. Next Actions
1. Discuss strategy for TikTok RSS / new video alerts (e.g. external RSS bridge, ProxiTok, or official RSS).

## 5. Banned Practices & Gotchas
- **TikTok Web Scraping:** Do not attempt direct HTTP GET on `tiktok.com/@username` from datacenter IPs (blocked by SlardarWAF / `_wafchallengeid`).
- **Tasks Loop Silence:** Never leave uncaught exceptions in `discord.ext.tasks` functions; discord.py will permanently cancel the loop silently.
- **Postgres Socket Reuse:** Never rely solely on `_PG_CONN.closed` for health; cloud Postgres closes idle TCP connections without updating local object state.
