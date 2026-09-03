import os
import re
import time
import asyncio
import urllib.parse
from datetime import datetime, timedelta
import aiohttp
import feedparser
import discord
from discord.ext import commands

from database.db_manager import (
    get_connection,
    get_setting,
    set_setting,
    get_todos,
    add_todo,
    mark_todo_done,
    delete_todo,
    add_transaction,
    get_month_summary,
    add_reminder,
    add_memo,
    get_memos,
    delete_memo,
    get_bangkok_now,
    get_guild_settings,
    set_guild_youtube_channel,
    add_youtube_subscription,
    get_guild_youtube_subscriptions,
    delete_youtube_subscription,
    add_stream_tracker,
    get_stream_trackers,
    delete_stream_tracker,
    set_pomodoro_session,
    get_pomodoro_session,
    delete_pomodoro_session
)

async def tool_get_fuel_price() -> dict:
    from cogs.fuel import fetch_fuel_prices
    fuel_data = await fetch_fuel_prices()
    if not fuel_data:
        return {"error": "ไม่สามารถดึงข้อมูลราคาน้ำมันจาก Bangchak API ได้ในขณะนี้"}

    fuels = fuel_data.get("fuels", {})
    g95 = fuels.get("Gasohol 95 S EVO", {})
    g91 = fuels.get("Gasohol 91 S EVO", {})
    e20 = fuels.get("Gasohol E20 S EVO", {})
    diesel = fuels.get("Hi Diesel S", {})
    premium98 = fuels.get("Hi Premium 98 Plus", {})

    diff = g95.get("diff", 0.0) or diesel.get("diff", 0.0)
    if diff > 0:
        recommendation = f"พรุ่งนี้ราคาน้ำมันปรับขึ้น +{diff:.2f} บาท/ลิตร แนะนำเติมก่อนเที่ยงคืน"
    elif diff < 0:
        recommendation = f"พรุ่งนี้ราคาน้ำมันปรับลดลง {diff:.2f} บาท/ลิตร แนะนำรอเติมพรุ่งนี้เช้า"
    else:
        recommendation = "พรุ่งนี้ราคาน้ำมันยังคงเดิม ไม่มีการเปลี่ยนแปลง"

    return {
        "status_alert": recommendation,
        "effective_text": fuel_data.get("effective_text", ""),
        "fuels": {
            "Gasohol 95": {"today": g95.get("today", 0.0), "tomorrow": g95.get("tomorrow", 0.0), "diff": g95.get("diff", 0.0)},
            "Gasohol 91": {"today": g91.get("today", 0.0), "tomorrow": g91.get("tomorrow", 0.0), "diff": g91.get("diff", 0.0)},
            "Gasohol E20": {"today": e20.get("today", 0.0), "tomorrow": e20.get("tomorrow", 0.0), "diff": e20.get("diff", 0.0)},
            "Hi Diesel": {"today": diesel.get("today", 0.0), "tomorrow": diesel.get("tomorrow", 0.0), "diff": diesel.get("diff", 0.0)},
            "Premium 98": {"today": premium98.get("today", 0.0), "tomorrow": premium98.get("tomorrow", 0.0), "diff": premium98.get("diff", 0.0)}
        }
    }

async def tool_youtube_add(context: dict, channel_url_or_id: str) -> dict:
    guild = context.get("guild")
    if not guild:
        return {"error": "คำสั่งนี้สามารถใช้ได้เฉพาะภายในเซิร์ฟเวอร์ Discord เท่านั้น"}

    is_admin = context.get("is_admin", False)
    if not is_admin:
        return {"error": "คุณไม่มีสิทธิ์จัดการช่อง YouTube ในเซิร์ฟเวอร์นี้ (ต้องมีสิทธิ์ Administrator หรือ Manage Channels)"}

    from cogs.youtube import extract_channel_id, fetch_youtube_feed, fetch_channel_avatar
    channel_id = await extract_channel_id(channel_url_or_id)
    if not channel_id:
        return {"error": "ไม่พบ ID ช่อง YouTube จากลิงก์หรือข้อความที่ระบุ กรุณาส่งลิงก์ เช่น https://www.youtube.com/@channel หรือ UC..."}

    feed = await fetch_youtube_feed(channel_id)
    if not feed or (not feed.entries and not feed.feed.get("title")):
        return {"error": f"ไม่สามารถดึงข้อมูล Feed จากช่อง YouTube ID {channel_id} ได้"}

    channel_title = feed.feed.get("title", channel_id)
    latest_video_id = None
    if feed.entries:
        latest_video_id = getattr(feed.entries[0], "yt_videoid", None) or getattr(feed.entries[0], "id", None)

    avatar_url = await fetch_channel_avatar(channel_id)

    settings = get_guild_settings(guild.id)
    alert_channel_id = settings.get("youtube_channel_id") if settings else None
    if not alert_channel_id:
        channel = context.get("channel")
        if channel and hasattr(channel, "id"):
            set_guild_youtube_channel(guild.id, channel.id)
            alert_channel_id = channel.id
        else:
            return {"error": "เซิร์ฟเวอร์ยังไม่ได้ตั้งค่าห้องแจ้งเตือน YouTube กรุณาระบุห้องหรือใช้ /youtube setup ก่อน"}

    add_youtube_subscription(
        guild_id=guild.id,
        youtube_channel_id=channel_id,
        channel_title=channel_title,
        last_video_id=latest_video_id,
        avatar_url=avatar_url
    )

    return {
        "success": True,
        "channel_title": channel_title,
        "channel_id": channel_id,
        "alert_channel_id": alert_channel_id
    }

async def tool_youtube_list(context: dict) -> dict:
    guild = context.get("guild")
    if not guild:
        return {"error": "คำสั่งนี้สามารถใช้ได้เฉพาะภายในเซิร์ฟเวอร์ Discord เท่านั้น"}

    subs = get_guild_youtube_subscriptions(guild.id)
    settings = get_guild_settings(guild.id)
    alert_channel_id = settings.get("youtube_channel_id") if settings else None

    return {
        "alert_channel_id": alert_channel_id,
        "total": len(subs),
        "subscriptions": [
            {
                "title": item.get("channel_title"),
                "channel_id": item.get("youtube_channel_id")
            }
            for item in subs
        ]
    }

async def tool_youtube_remove(context: dict, channel_id_or_title: str) -> dict:
    guild = context.get("guild")
    if not guild:
        return {"error": "คำสั่งนี้สามารถใช้ได้เฉพาะภายในเซิร์ฟเวอร์ Discord เท่านั้น"}

    is_admin = context.get("is_admin", False)
    if not is_admin:
        return {"error": "คุณไม่มีสิทธิ์ลบช่อง YouTube ในเซิร์ฟเวอร์นี้ (ต้องมีสิทธิ์ Administrator หรือ Manage Channels)"}

    deleted = delete_youtube_subscription(guild.id, channel_id_or_title)
    if not deleted:
        return {"error": f"ไม่พบช่อง '{channel_id_or_title}' ในรายการติดตามของเซิร์ฟเวอร์นี้"}

    return {"success": True, "target": channel_id_or_title}

async def tool_get_weather(city: str = "Bangkok") -> dict:
    from cogs.weather import fetch_weather_report
    report = await fetch_weather_report(city)
    if not report:
        return {"error": f"ไม่พบข้อมูลสภาพอากาศสำหรับ '{city}'"}
    return report

async def tool_get_air_quality(city: str = "Bangkok") -> dict:
    from cogs.weather import fetch_air_quality_report
    report = await fetch_air_quality_report(city)
    if not report:
        return {"error": f"ไม่พบข้อมูลคุณภาพอากาศสำหรับ '{city}'"}
    
    clean_eval = dict(report.get("eval", {}))
    if "color" in clean_eval:
        clean_eval["color"] = str(clean_eval["color"])

    return {
        "location": report.get("location"),
        "city_name": report.get("city_name"),
        "pm25": report.get("pm25"),
        "pm10": report.get("pm10"),
        "aqi": report.get("aqi"),
        "eval": clean_eval
    }

async def tool_get_daily_briefing(context: dict) -> dict:
    user_id = context.get("user_id")
    home_city = get_setting("briefing_home_city", "Bang Na")
    work_city = get_setting("briefing_work_city", "Lat Phrao")

    from cogs.weather import fetch_weather_report
    from cogs.fuel import fetch_fuel_prices

    home_w, work_w, fuel_data = await asyncio.gather(
        fetch_weather_report(home_city),
        fetch_weather_report(work_city),
        fetch_fuel_prices()
    )

    pending_todos = get_todos(user_id, status="pending") if user_id else []

    return {
        "home_city": home_city,
        "home_weather": home_w,
        "work_city": work_city,
        "work_weather": work_w,
        "fuel": fuel_data.get("fuels") if fuel_data else None,
        "pending_todos_count": len(pending_todos),
        "pending_todos": [t.get("task") for t in pending_todos[:5]]
    }

async def tool_get_crypto_price(coin: str) -> dict:
    from cogs.finance import fetch_crypto_price
    result = await fetch_crypto_price(coin)
    if not result:
        return {"error": f"ไม่พบข้อมูลราคาสำหรับเหรียญ '{coin}' ในระบบ"}
    return result

async def tool_get_exchange_rate(from_curr: str, to_curr: str, amount: float = 1.0) -> dict:
    base = from_curr.strip().upper()
    target = to_curr.strip().upper()
    url = f"https://open.er-api.com/v6/latest/{base}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return {"error": "ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์อัตราแลกเปลี่ยนได้"}
                data = await resp.json()
                if data.get("result") != "success":
                    return {"error": f"ไม่พบสกุลเงิน '{base}'"}
                rates = data.get("rates", {})
                rate = rates.get(target)
                if not rate:
                    return {"error": f"ไม่พบสกุลเงิน '{target}'"}
                return {
                    "from_currency": base,
                    "to_currency": target,
                    "amount": amount,
                    "rate": rate,
                    "converted": round(amount * rate, 4)
                }
        except Exception as e:
            return {"error": str(e)}

async def tool_record_expense(context: dict, trans_type: str, amount: float, category: str = "ทั่วไป", note: str = "") -> dict:
    user_id = context.get("user_id")
    if not user_id:
        return {"error": "ไม่พบรหัสผู้ใช้งาน"}
    trans_id = add_transaction(
        user_id=user_id,
        trans_type=trans_type,
        amount=float(amount),
        category=category,
        note=note or "บันทึกผ่าน AI"
    )
    return {
        "success": True,
        "id": trans_id,
        "type": trans_type,
        "amount": amount,
        "category": category,
        "note": note
    }

async def tool_get_expense_summary(context: dict) -> dict:
    user_id = context.get("user_id")
    if not user_id:
        return {"error": "ไม่พบรหัสผู้ใช้งาน"}
    summary = get_month_summary(user_id)
    return summary

async def tool_add_todo(context: dict, task: str) -> dict:
    user_id = context.get("user_id")
    if not user_id:
        return {"error": "ไม่พบรหัสผู้ใช้งาน"}
    todo_id = add_todo(user_id=user_id, task=task)
    return {"success": True, "id": todo_id, "task": task}

async def tool_get_todo_list(context: dict, status: str = "pending") -> dict:
    user_id = context.get("user_id")
    if not user_id:
        return {"error": "ไม่พบรหัสผู้ใช้งาน"}
    query_status = status if status in ("pending", "done") else None
    todos = get_todos(user_id=user_id, status=query_status)
    return {
        "total": len(todos),
        "status_filter": status,
        "todos": [
            {"id": t["id"], "task": t["task"], "status": t["status"]}
            for t in todos
        ]
    }

async def tool_complete_todo(context: dict, todo_id: int) -> dict:
    user_id = context.get("user_id")
    if not user_id:
        return {"error": "ไม่พบรหัสผู้ใช้งาน"}
    success = mark_todo_done(todo_id=int(todo_id), user_id=user_id)
    return {"success": success, "todo_id": todo_id}

async def tool_delete_todo(context: dict, todo_id: int) -> dict:
    user_id = context.get("user_id")
    if not user_id:
        return {"error": "ไม่พบรหัสผู้ใช้งาน"}
    success = delete_todo(todo_id=int(todo_id), user_id=user_id)
    return {"success": success, "todo_id": todo_id}

async def tool_set_reminder(context: dict, time_str: str, message: str) -> dict:
    user_id = context.get("user_id")
    bot = context.get("bot")
    channel = context.get("channel")
    channel_id = channel.id if channel and hasattr(channel, "id") else 1544548171584245860

    from cogs.todo import parse_duration_string, start_reminder_task
    delta = parse_duration_string(time_str) or timedelta(minutes=10)
    due_time = get_bangkok_now() + delta

    r_id = add_reminder(user_id=user_id, channel_id=channel_id, message=message, remind_at=due_time)
    if bot:
        start_reminder_task(
            bot=bot,
            reminder_id=r_id,
            user_id=user_id,
            message=message,
            delay_seconds=delta.total_seconds()
        )

    return {
        "success": True,
        "reminder_id": r_id,
        "message": message,
        "timestamp": int(due_time.timestamp()),
        "time_str": time_str
    }

async def tool_add_memo(context: dict, title: str, content: str) -> dict:
    user_id = context.get("user_id")
    if not user_id:
        return {"error": "ไม่พบรหัสผู้ใช้งาน"}
    m_id = add_memo(user_id=user_id, title=title, content=content)
    return {"success": True, "id": m_id, "title": title}

async def tool_get_memos(context: dict) -> dict:
    user_id = context.get("user_id")
    if not user_id:
        return {"error": "ไม่พบรหัสผู้ใช้งาน"}
    memos = get_memos(user_id=user_id)
    return {
        "total": len(memos),
        "memos": [
            {"id": m["id"], "title": m["title"], "content": m["content"], "date": str(m.get("created_at", ""))[:10]}
            for m in memos
        ]
    }

async def tool_get_system_status(context: dict) -> dict:
    bot = context.get("bot")
    from cogs.utility import format_uptime, get_current_ram_mb
    uptime_str = "N/A"
    if bot:
        cog = bot.get_cog("UtilityCog")
        if cog and hasattr(cog, "start_time"):
            uptime_str = format_uptime(time.time() - cog.start_time)

    ram_mb = get_current_ram_mb()
    latency_ms = round(bot.latency * 1000, 2) if bot else 0.0

    return {
        "uptime": uptime_str,
        "ram_mb": f"{ram_mb:.1f} MB",
        "latency_ms": f"{latency_ms} ms"
    }

async def tool_stream_follow(context: dict, channel_login: str) -> dict:
    channel = context.get("channel")
    dest_channel_id = channel.id if channel and hasattr(channel, "id") else 1544548048837808278
    from cogs.twitch import fetch_twitch_user
    async with aiohttp.ClientSession() as session:
        user_data = await fetch_twitch_user(session, channel_login)
        if not user_data:
            return {"error": f"ไม่พบสตรีมเมอร์ Twitch บัญชี '{channel_login}'"}
        display_name = user_data.get("displayName") or channel_login
        add_stream_tracker("twitch", channel_login, display_name, dest_channel_id)
        return {"success": True, "display_name": display_name, "login": channel_login}

async def tool_stream_list() -> dict:
    trackers = get_stream_trackers("twitch")
    return {
        "total": len(trackers),
        "streamers": [
            {
                "display_name": t["display_name"],
                "login": t["channel_login"],
                "is_live": bool(t.get("is_live", 0))
            }
            for t in trackers
        ]
    }

async def tool_stream_unfollow(channel_login: str) -> dict:
    deleted = delete_stream_tracker(channel_login, "twitch")
    return {"success": deleted, "login": channel_login}

async def tool_pomodoro_start(context: dict, work_min: int = 25, break_min: int = 5, loops: int = 4) -> dict:
    user_id = context.get("user_id")
    bot = context.get("bot")
    channel = context.get("channel")
    if not user_id:
        return {"error": "ไม่พบรหัสผู้ใช้งาน"}

    channel_id = channel.id if channel and hasattr(channel, "id") else 1544548171584245860
    end_time = get_bangkok_now() + timedelta(minutes=work_min)
    set_pomodoro_session(user_id, channel_id, "work", end_time, work_min, break_min, 0, loops)

    if bot:
        from cogs.pomodoro import start_pomodoro_task, build_pomodoro_embed, PomodoroControlView
        start_pomodoro_task(bot, user_id)
        session = get_pomodoro_session(user_id)
        embed = build_pomodoro_embed(session)
        if channel and hasattr(channel, "send"):
            try:
                await channel.send(embed=embed, view=PomodoroControlView())
            except Exception:
                pass

    return {
        "success": True,
        "work_min": work_min,
        "break_min": break_min,
        "loops": loops,
        "end_time": end_time.strftime("%H:%M")
    }

async def tool_pomodoro_stop(context: dict) -> dict:
    user_id = context.get("user_id")
    if not user_id:
        return {"error": "ไม่พบรหัสผู้ใช้งาน"}
    from cogs.pomodoro import stop_pomodoro_task
    stop_pomodoro_task(user_id)
    delete_pomodoro_session(user_id)
    return {"success": True, "message": "ยุติเซสชัน Pomodoro เรียบร้อยแล้ว"}

async def tool_pomodoro_status(context: dict) -> dict:
    user_id = context.get("user_id")
    if not user_id:
        return {"error": "ไม่พบรหัสผู้ใช้งาน"}
    session = get_pomodoro_session(user_id)
    if not session:
        return {"active": False, "message": "ไม่มีเซสชัน Pomodoro ที่กำลังทำงาน"}
    return {
        "active": True,
        "mode": session.get("mode"),
        "work_min": session.get("work_min"),
        "break_min": session.get("break_min"),
        "cycles_done": session.get("cycles_done"),
        "target_cycles": session.get("target_cycles"),
        "end_time": str(session.get("end_time"))
    }

def format_feed_snippet(entry, source: str) -> str:
    title = getattr(entry, "title", "").strip()
    desc = re.sub(r"<[^>]+>", "", getattr(entry, "description", "")).strip()
    pub = getattr(entry, "published", "").strip()
    if not title and not desc:
        return ""
    time_info = f" ({pub[:16]})" if pub else ""
    return f"[{source}{time_info}] {title}: {desc}"

SEARCH_CACHE = {}
SEARCH_CACHE_TTL = 3600
SEARCH_CACHE_MAX_ENTRIES = 100

def get_cached_search(query: str) -> dict | None:
    normalized = query.strip().lower()
    if normalized in SEARCH_CACHE:
        entry = SEARCH_CACHE[normalized]
        if time.time() - entry["timestamp"] < SEARCH_CACHE_TTL:
            return entry["data"]
        del SEARCH_CACHE[normalized]
    return None

def set_cached_search(query: str, data: dict):
    normalized = query.strip().lower()
    if len(SEARCH_CACHE) >= SEARCH_CACHE_MAX_ENTRIES:
        oldest_key = min(SEARCH_CACHE.keys(), key=lambda k: SEARCH_CACHE[k]["timestamp"])
        del SEARCH_CACHE[oldest_key]
    SEARCH_CACHE[normalized] = {
        "timestamp": time.time(),
        "data": data
    }

async def tool_search_web(query: str, max_results: int = 4) -> dict:
    cached_result = get_cached_search(query)
    if cached_result:
        return cached_result

    tavily_key = os.getenv("TAVILY_API_KEY")
    if tavily_key:
        try:
            payload = {
                "api_key": tavily_key,
                "query": query,
                "search_depth": "basic",
                "include_answer": True,
                "max_results": max_results
            }
            async with aiohttp.ClientSession() as session:
                async with session.post("https://api.tavily.com/search", json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        snippets = []
                        if data.get("answer"):
                            snippets.append(f"[AI Summary]: {data['answer']}")
                        for item in data.get("results", []):
                            title = item.get("title", "")
                            item_url = item.get("url", "")
                            content = (item.get("content", "") or "")[:700]
                            snippets.append(f"[{title}] ({item_url}): {content}")
                        if snippets:
                            result = {"query": query, "results": snippets}
                            set_cached_search(query, result)
                            return result
        except Exception:
            pass

    try:
        encoded_q = urllib.parse.quote(query)
        has_english = any(c.isascii() and c.isalpha() for c in query)
        bing_market = "&setmkt=en-US" if has_english else ""
        bing_url = f"https://www.bing.com/search?q={encoded_q}&format=rss{bing_market}"
        news_url = f"https://news.google.com/rss/search?q={encoded_q}&hl=th&gl=TH&ceid=TH:th"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        snippets = []
        async with aiohttp.ClientSession(headers=headers) as session:
            async def fetch_feed(url: str, source: str):
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            feed = feedparser.parse(content)
                            return source, feed.entries
                except Exception:
                    pass
                return source, []

            res = await asyncio.gather(
                fetch_feed(bing_url, "Bing"),
                fetch_feed(news_url, "Google News")
            )
            for source, entries in res:
                for entry in entries[:max_results]:
                    snippet = format_feed_snippet(entry, source)
                    if snippet:
                        snippets.append(snippet)

        if not snippets:
            return {"error": "ไม่สามารถค้นหาข้อมูลได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง"}

        result = {"query": query, "results": snippets}
        set_cached_search(query, result)
        return result
    except Exception:
        return {"error": "ไม่สามารถค้นหาข้อมูลได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง"}

TOOL_HANDLERS = {
    "get_fuel_price": lambda args, ctx: tool_get_fuel_price(),
    "youtube_add": lambda args, ctx: tool_youtube_add(ctx, args.get("channel_url_or_id", "")),
    "youtube_list": lambda args, ctx: tool_youtube_list(ctx),
    "youtube_remove": lambda args, ctx: tool_youtube_remove(ctx, args.get("channel_id_or_title", "")),
    "get_weather": lambda args, ctx: tool_get_weather(args.get("city", "Bangkok")),
    "get_air_quality": lambda args, ctx: tool_get_air_quality(args.get("city", "Bangkok")),
    "get_daily_briefing": lambda args, ctx: tool_get_daily_briefing(ctx),
    "get_crypto_price": lambda args, ctx: tool_get_crypto_price(args.get("coin", "btc")),
    "get_exchange_rate": lambda args, ctx: tool_get_exchange_rate(args.get("from_currency", "USD"), args.get("to_currency", "THB"), float(args.get("amount", 1.0))),
    "record_expense": lambda args, ctx: tool_record_expense(ctx, args.get("type", "expense"), float(args.get("amount", 0)), args.get("category", "ทั่วไป"), args.get("note", "")),
    "get_expense_summary": lambda args, ctx: tool_get_expense_summary(ctx),
    "add_todo": lambda args, ctx: tool_add_todo(ctx, args.get("task", "")),
    "get_todo_list": lambda args, ctx: tool_get_todo_list(ctx, args.get("status", "pending")),
    "complete_todo": lambda args, ctx: tool_complete_todo(ctx, args.get("todo_id", 0)),
    "delete_todo": lambda args, ctx: tool_delete_todo(ctx, args.get("todo_id", 0)),
    "set_reminder": lambda args, ctx: tool_set_reminder(ctx, args.get("time_str", "10m"), args.get("message", "")),
    "add_memo": lambda args, ctx: tool_add_memo(ctx, args.get("title", ""), args.get("content", "")),
    "get_memos": lambda args, ctx: tool_get_memos(ctx),
    "get_system_status": lambda args, ctx: tool_get_system_status(ctx),
    "stream_follow": lambda args, ctx: tool_stream_follow(ctx, args.get("channel_login", "")),
    "stream_list": lambda args, ctx: tool_stream_list(),
    "stream_unfollow": lambda args, ctx: tool_stream_unfollow(args.get("channel_login", "")),
    "pomodoro_start": lambda args, ctx: tool_pomodoro_start(ctx, int(args.get("work_min", 25)), int(args.get("break_min", 5)), int(args.get("loops", 4))),
    "pomodoro_stop": lambda args, ctx: tool_pomodoro_stop(ctx),
    "pomodoro_status": lambda args, ctx: tool_pomodoro_status(ctx),
    "search_web": lambda args, ctx: tool_search_web(args.get("query", ""))
}

async def execute_ai_tool(tool_name: str, args: dict, context: dict) -> dict:
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        return {"error": f"ไม่พบเครื่องมือ '{tool_name}' ในระบบ"}
    try:
        return await handler(args, context)
    except Exception as e:
        return {"error": f"เกิดข้อผิดพลาดในการประมวลผล {tool_name}: {str(e)}"}
