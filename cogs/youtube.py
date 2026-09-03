import asyncio
import os
import re
import gc
from datetime import datetime
import aiohttp
import feedparser
import discord
from discord import app_commands
from discord.ext import commands, tasks
from database.db_manager import (
    set_guild_youtube_channel,
    get_guild_settings,
    add_youtube_subscription,
    get_guild_youtube_subscriptions,
    get_all_youtube_subscriptions,
    update_youtube_last_video,
    update_youtube_avatar,
    delete_youtube_subscription
)

OWNER_USER_ID = int(os.getenv("OWNER_USER_ID", "372796686323417089"))
YOUTUBE_ICON = "https://www.gstatic.com/youtube/img/branding/favicon/favicon_144x144.png"

AVATAR_CACHE: dict[str, str] = {}

async def fetch_channel_avatar(channel_id: str) -> str:
    if channel_id in AVATAR_CACHE and AVATAR_CACHE[channel_id] != YOUTUBE_ICON:
        return AVATAR_CACHE[channel_id]

    url = f"https://www.youtube.com/channel/{channel_id}"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    
                    all_yt3 = re.findall(r'(https://yt3\.googleusercontent\.com/[^"\'\s<>\\]+)', html)
                    valid_yt3 = [u.rstrip('"').rstrip("'") for u in all_yt3 if "default-user" not in u]
                    if valid_yt3:
                        avatar_url = valid_yt3[0]
                        AVATAR_CACHE[channel_id] = avatar_url
                        return avatar_url

                    match = re.search(r'property="og:image"\s+content="([^"]+)"', html)
                    if match:
                        found_url = match.group(1)
                        AVATAR_CACHE[channel_id] = found_url
                        return found_url
    except Exception as e:
        print(f"[FETCH AVATAR ERROR] {channel_id}: {e}")

    return YOUTUBE_ICON

async def extract_channel_id(input_str: str) -> str | None:
    cleaned = input_str.strip()

    match_rss = re.search(r"channel_id=(UC[\w-]{22})", cleaned)
    if match_rss:
        return match_rss.group(1)

    match_channel = re.search(r"youtube\.com/channel/(UC[\w-]{22})", cleaned)
    if match_channel:
        return match_channel.group(1)

    if re.fullmatch(r"UC[\w-]{22}", cleaned):
        return cleaned

    target_url = cleaned if cleaned.startswith("http") else f"https://www.youtube.com/{cleaned}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(target_url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    match_meta = re.search(r'itemprop="channelId" content="(UC[\w-]{22})"', html)
                    if match_meta:
                        return match_meta.group(1)
                    match_browse = re.search(r'"browseId":"(UC[\w-]{22})"', html)
                    if match_browse:
                        return match_browse.group(1)
    except Exception:
        pass

    return None

class YouTubeFeedEntry:
    def __init__(self, video_id: str, title: str):
        self.yt_videoid = video_id
        self.id = video_id
        self.title = title
        self.link = f"https://www.youtube.com/watch?v={video_id}"

class YouTubeFeedResult:
    def __init__(self, entries):
        self.entries = entries

async def scrape_youtube_fallback(session: aiohttp.ClientSession, channel_id: str) -> YouTubeFeedResult:
    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status == 200:
                html = await resp.text()
                matches = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
                seen = set()
                entries = []
                for v in matches:
                    if v not in seen:
                        seen.add(v)
                        entries.append(YouTubeFeedEntry(v, "คลิปใหม่"))
                return YouTubeFeedResult(entries)
    except Exception:
        pass
    return YouTubeFeedResult([])

async def fetch_youtube_feed(channel_id: str):
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(feed_url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    loop = asyncio.get_running_loop()
                    parsed = await loop.run_in_executor(None, feedparser.parse, content)
                    if parsed and parsed.entries:
                        return parsed
            return await scrape_youtube_fallback(session, channel_id)
    except Exception:
        pass
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, feedparser.parse, feed_url)

async def detect_video_type(session: aiohttp.ClientSession, video_id: str, video_link: str, video_title: str) -> str:
    if "/shorts/" in video_link or "#shorts" in video_title.lower():
        return "shorts"

    if video_id:
        url = f"https://www.youtube.com/watch?v={video_id}"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"}
        try:
            async with session.get(url, headers=headers, timeout=8) as resp:
                if resp.status == 200:
                    tail = ""
                    while True:
                        chunk = await resp.content.read(65536)
                        if not chunk:
                            break
                        text = chunk.decode("utf-8", errors="ignore")
                        window = tail + text
                        tail = text[-100:]
                        if ('"isLiveNow":true' in window or 
                            '"isLiveNow": true' in window or 
                            '"isLive":true' in window or 
                            '"isLive": true' in window):
                            return "live"
        except Exception:
            pass
    return "video"

def get_alert_content(channel_title: str, video_type: str) -> str:
    if video_type == "live":
        return f"🔴 @everyone **{channel_title}** กำลังถ่ายทอดสดบน YouTube! 🔴"
    elif video_type == "shorts":
        return f"🔔 @everyone **{channel_title}** อัปโหลดคลิปใหม่บน YouTube! 📱"
    else:
        return f"🔔 @everyone **{channel_title}** อัปโหลดคลิปใหม่บน YouTube! 🎬"

def build_youtube_alert_embed(entry, channel_title: str, channel_id: str, avatar_url: str = None, video_type: str = "video") -> discord.Embed:
    video_title = getattr(entry, "title", "ไม่มีชื่อวิดีโอ")
    video_link = getattr(entry, "link", f"https://www.youtube.com/channel/{channel_id}")
    video_id = getattr(entry, "yt_videoid", "")

    avatar = avatar_url or YOUTUBE_ICON

    thumb_url = None
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        thumb_url = entry.media_thumbnail[0].get("url")
    if not thumb_url and video_id:
        thumb_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

    embed = discord.Embed(
        title=video_title,
        url=video_link,
        color=discord.Color.from_rgb(255, 0, 0),
        timestamp=datetime.now()
    )

    if video_type == "live":
        author_text = f"{channel_title} กำลังถ่ายทอดสด!"
        type_badge = "🔴 ถ่ายทอดสด"
    elif video_type == "shorts":
        author_text = f"{channel_title} อัปโหลดคลิปใหม่!"
        type_badge = "📱 YouTube Shorts"
    else:
        author_text = f"{channel_title} อัปโหลดคลิปใหม่!"
        type_badge = "🎬 วิดีโอ (Video)"

    embed.set_author(
        name=author_text,
        icon_url=avatar,
        url=f"https://www.youtube.com/channel/{channel_id}"
    )

    embed.set_thumbnail(url=avatar)

    embed.add_field(name="📌 ประเภท", value=f"`{type_badge}`", inline=False)

    if thumb_url:
        embed.set_image(url=thumb_url)

    embed.set_footer(text="TD YouTube Alert")
    return embed

def check_admin_or_mod(interaction: discord.Interaction) -> bool:
    if interaction.user.id == OWNER_USER_ID:
        return True
    if not interaction.guild:
        return False
    if interaction.guild.owner_id == interaction.user.id:
        return True
    perms = interaction.user.guild_permissions
    return perms.administrator or perms.manage_guild or perms.manage_channels

class YouTubeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.youtube_check_loop.start()

    def cog_unload(self):
        self.youtube_check_loop.cancel()

    @tasks.loop(minutes=3)
    async def youtube_check_loop(self):
        subscriptions = get_all_youtube_subscriptions()
        if not subscriptions:
            return

        grouped: dict[str, list[dict]] = {}
        for sub in subscriptions:
            c_id = sub["youtube_channel_id"]
            grouped.setdefault(c_id, []).append(sub)

        for channel_id, subs in grouped.items():
            try:
                feed = await fetch_youtube_feed(channel_id)
                if not feed.entries:
                    continue

                latest_entry = feed.entries[0]
                latest_video_id = getattr(latest_entry, "yt_videoid", None) or getattr(latest_entry, "id", None)
                channel_title = feed.feed.get("title", subs[0].get("channel_title") or "YouTube Channel")

                has_any_new = False
                for sub in subs:
                    last_id = sub.get("last_video_id")
                    if not last_id or latest_video_id != last_id:
                        has_any_new = True
                        break

                if not has_any_new:
                    continue

                channel_avatar = subs[0].get("avatar_url")
                is_valid = channel_avatar and "wikimedia.org" not in channel_avatar and channel_avatar != YOUTUBE_ICON
                if not is_valid:
                    channel_avatar = await fetch_channel_avatar(channel_id)
                    for sub in subs:
                        update_youtube_avatar(sub["id"], channel_avatar)

                for sub in subs:
                    last_id = sub.get("last_video_id")
                    sub_id = sub["id"]
                    guild_dest_channel_id = sub.get("alert_channel_id")

                    if not last_id:
                        update_youtube_last_video(sub_id, latest_video_id)
                        continue

                    if latest_video_id != last_id:
                        new_entries = []
                        for entry in feed.entries:
                            v_id = getattr(entry, "yt_videoid", None) or getattr(entry, "id", None)
                            if v_id == last_id:
                                break
                            new_entries.append(entry)

                        update_youtube_last_video(sub_id, latest_video_id)

                        if not guild_dest_channel_id or not new_entries:
                            continue

                        dest_channel = self.bot.get_channel(guild_dest_channel_id)
                        if not dest_channel:
                            try:
                                dest_channel = await self.bot.fetch_channel(guild_dest_channel_id)
                            except Exception:
                                dest_channel = None

                        if dest_channel:
                            async with aiohttp.ClientSession() as session:
                                for new_entry in reversed(new_entries):
                                    v_id = getattr(new_entry, "yt_videoid", "")
                                    v_link = getattr(new_entry, "link", "")
                                    v_title = getattr(new_entry, "title", "")
                                    v_type = await detect_video_type(session, v_id, v_link, v_title)

                                    embed = build_youtube_alert_embed(new_entry, channel_title, channel_id, channel_avatar, v_type)
                                    content_text = get_alert_content(channel_title, v_type)

                                    try:
                                        await dest_channel.send(content=content_text, embed=embed)
                                        await asyncio.sleep(1)
                                    except Exception as e:
                                        print(f"[YOUTUBE ALERT ERROR] Failed to send to {guild_dest_channel_id}: {e}")

            except Exception as err:
                print(f"[YOUTUBE CHECK ERROR] Feed {channel_id}: {err}")
                continue

        gc.collect()

    @youtube_check_loop.before_loop
    async def before_youtube_loop(self):
        await self.bot.wait_until_ready()

    youtube_group = app_commands.Group(
        name="youtube",
        description="ระบบแจ้งเตือนคลิปและ Shorts จาก YouTube ประจำเซิร์ฟเวอร์",
        default_permissions=discord.Permissions(manage_channels=True)
    )

    @youtube_group.command(name="setup", description="กำหนดห้อง Text Channel สำหรับรับการแจ้งเตือนคลิป YouTube")
    @app_commands.describe(channel="เลือกห้องที่ต้องการให้บอทส่งข้อความแจ้งเตือน")
    async def youtube_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not check_admin_or_mod(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมิน, ผู้ดูแลห้อง หรือเจ้าของบอท)", ephemeral=True)
            return

        set_guild_youtube_channel(interaction.guild_id, channel.id)

        embed = discord.Embed(
            title="✅ ตั้งค่าห้องแจ้งเตือน YouTube สำเร็จ!",
            description=(
                f"**เซิร์ฟเวอร์:** `{interaction.guild.name}`\n"
                f"**ห้องแจ้งเตือน:** {channel.mention}\n"
                f"**การแท็ก:** `@everyone`\n\n"
                f"💡 คุณสามารถใช้คำสั่ง `/youtube add <ลิงก์ช่อง>` เพื่อเริ่มติดตามช่องที่ต้องการได้เลย"
            ),
            color=discord.Color.from_rgb(255, 0, 0),
            timestamp=datetime.now()
        )
        embed.set_footer(text="TD YouTube Alert • พร้อมทำงาน")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @youtube_group.command(name="add", description="เพิ่มช่อง YouTube ที่ต้องการติดตามแจ้งเตือนคลิปและ Shorts")
    @app_commands.describe(channel_url_or_id="ใส่ URL ช่อง เช่น https://www.youtube.com/@ChenGaming หรือ ID ช่อง (UC...)")
    async def youtube_add(self, interaction: discord.Interaction, channel_url_or_id: str):
        if not check_admin_or_mod(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมิน, ผู้ดูแลห้อง หรือเจ้าของบอท)", ephemeral=True)
            return

        settings = get_guild_settings(interaction.guild_id)
        if not settings or not settings.get("youtube_channel_id"):
            await interaction.response.send_message(
                "⚠️ เซิร์ฟเวอร์นี้ยังไม่ได้กำหนดห้องแจ้งเตือน กรุณาใช้คำสั่ง `/youtube setup <#ห้อง>` ก่อน",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        channel_id = await extract_channel_id(channel_url_or_id)
        if not channel_id:
            await interaction.followup.send(
                "❌ ไม่พบ ID ช่อง YouTube จากข้อมูลที่ระบุ กรุณาตรวจสอบลิงก์ (รองรับทั้ง youtube.com/@handle, youtube.com/channel/UC... หรือ ID UC...)",
                ephemeral=True
            )
            return

        feed = await fetch_youtube_feed(channel_id)
        if not feed.entries and not feed.feed.get("title"):
            await interaction.followup.send(
                f"❌ ไม่สามารถดึงข้อมูล Feed จากช่อง ID `{channel_id}` ได้ กรุณาตรวจสอบความถูกต้องของช่อง",
                ephemeral=True
            )
            return

        channel_title = feed.feed.get("title", channel_id)
        latest_video_id = None
        if feed.entries:
            latest_video_id = getattr(feed.entries[0], "yt_videoid", None) or getattr(feed.entries[0], "id", None)

        avatar_url = await fetch_channel_avatar(channel_id)

        add_youtube_subscription(
            guild_id=interaction.guild_id,
            youtube_channel_id=channel_id,
            channel_title=channel_title,
            last_video_id=latest_video_id,
            avatar_url=avatar_url
        )

        embed = discord.Embed(
            title="✅ เพิ่มช่อง YouTube สำเร็จ!",
            description=(
                f"**ช่อง YouTube:** `{channel_title}`\n"
                f"**Channel ID:** `{channel_id}`\n"
                f"**ห้องแจ้งเตือน:** <#{settings['youtube_channel_id']}>\n"
                f"**รอบตรวจสอบ:** ทุก 3 นาที\n"
                f"**การแจ้งเตือน:** คลิปใหม่ & YouTube Shorts (@everyone)"
            ),
            color=discord.Color.from_rgb(255, 0, 0),
            timestamp=datetime.now()
        )
        embed.set_thumbnail(url=avatar_url)
        embed.set_footer(text="TD YouTube Alert")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @youtube_group.command(name="list", description="ดูรายชื่อช่อง YouTube ทั้งหมดที่เซิร์ฟเวอร์นี้กำลังติดตาม")
    async def youtube_list(self, interaction: discord.Interaction):
        if not check_admin_or_mod(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        settings = get_guild_settings(interaction.guild_id)
        subs = get_guild_youtube_subscriptions(interaction.guild_id)

        dest_text = f"<#{settings['youtube_channel_id']}>" if settings and settings.get("youtube_channel_id") else "⚠️ ยังไม่ได้ตั้งค่า (ใช้ /youtube setup)"

        if not subs:
            embed = discord.Embed(
                title="📺 รายการช่อง YouTube ที่ติดตาม",
                description=f"ห้องแจ้งเตือนปัจจุบัน: {dest_text}\n\n*ยังไม่มีช่อง YouTube ในรายการติดตาม ใช้ `/youtube add` เพื่อเริ่มติดตามได้เลย*",
                color=discord.Color.light_grey()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="📺 รายชื่อช่อง YouTube ที่กำลังติดตาม",
            description=f"📍 **ห้องแจ้งเตือน:** {dest_text}\n⏱️ **รอบตรวจสอบ:** ทุก 3 นาที (@everyone)\n",
            color=discord.Color.from_rgb(255, 0, 0),
            timestamp=datetime.now()
        )

        lines = []
        for idx, item in enumerate(subs, 1):
            c_title = item.get("channel_title") or item["youtube_channel_id"]
            c_id = item["youtube_channel_id"]
            lines.append(f"`{idx}.` **[{c_title}](https://www.youtube.com/channel/{c_id})** (`{c_id}`)")

        embed.add_field(name=f"ช่องทั้งหมด ({len(subs)})", value="\n".join(lines), inline=False)
        embed.set_footer(text="ใช้ /youtube remove เพื่อยกเลิกการติดตาม")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @youtube_group.command(name="remove", description="ยกเลิกการติดตามช่อง YouTube")
    @app_commands.describe(channel_url_or_id="ใส่ URL ช่อง, ID ช่อง (UC...) หรือชื่อช่องที่ต้องการลบ")
    async def youtube_remove(self, interaction: discord.Interaction, channel_url_or_id: str):
        if not check_admin_or_mod(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้", ephemeral=True)
            return

        raw_input = channel_url_or_id.strip()
        channel_id = await extract_channel_id(raw_input) or raw_input

        success = delete_youtube_subscription(interaction.guild_id, channel_id)
        if success:
            await interaction.response.send_message(f"🗑️ ยกเลิกการติดตามช่อง `{raw_input}` เรียบร้อยแล้ว", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ ไม่พบช่อง `{raw_input}` ในรายการติดตามของเซิร์ฟเวอร์นี้", ephemeral=True)

    @youtube_group.command(name="test", description="ส่งแจ้งเตือนคลิปล่าสุดทันที โดยไม่ต้องรอลูป 3 นาที")
    async def youtube_test(self, interaction: discord.Interaction):
        if not check_admin_or_mod(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้", ephemeral=True)
            return

        settings = get_guild_settings(interaction.guild_id)
        if not settings or not settings.get("youtube_channel_id"):
            await interaction.response.send_message(
                "⚠️ เซิร์ฟเวอร์นี้ยังไม่ได้ตั้งค่าห้องแจ้งเตือน กรุณาใช้คำสั่ง `/youtube setup <#ห้อง>` ก่อน",
                ephemeral=True
            )
            return

        dest_channel = self.bot.get_channel(settings["youtube_channel_id"])
        if not dest_channel:
            try:
                dest_channel = await self.bot.fetch_channel(settings["youtube_channel_id"])
            except Exception:
                dest_channel = None

        if not dest_channel:
            await interaction.response.send_message(
                f"❌ บอทไม่สามารถเข้าถึงห้อง <#{settings['youtube_channel_id']}> ได้ กรุณาตรวจสอบสิทธิ์ของบอทในห้องนั้น",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        subs = get_guild_youtube_subscriptions(interaction.guild_id)
        if not subs:
            await interaction.followup.send("⚠️ เซิร์ฟเวอร์นี้ยังไม่ได้เพิ่มช่อง YouTube กรุณาใช้คำสั่ง `/youtube add` ก่อน", ephemeral=True)
            return

        total_sent = 0
        async with aiohttp.ClientSession() as session:
            for target_sub in subs:
                sample_id = target_sub["youtube_channel_id"]
                sample_title = target_sub.get("channel_title") or sample_id
                last_id = target_sub.get("last_video_id")

                feed = await fetch_youtube_feed(sample_id)
                if not feed.entries:
                    continue

                db_avatar = target_sub.get("avatar_url")
                is_valid = db_avatar and "wikimedia.org" not in db_avatar and db_avatar != YOUTUBE_ICON
                if not is_valid:
                    channel_avatar = await fetch_channel_avatar(sample_id)
                    update_youtube_avatar(target_sub["id"], channel_avatar)
                else:
                    channel_avatar = db_avatar

                new_entries = []
                for entry in feed.entries:
                    v_id = getattr(entry, "yt_videoid", None) or getattr(entry, "id", None)
                    if v_id == last_id:
                        break
                    new_entries.append(entry)

                entries_to_send = list(reversed(new_entries)) if new_entries else [feed.entries[0]]

                for item in entries_to_send:
                    v_id = getattr(item, "yt_videoid", "")
                    v_link = getattr(item, "link", "")
                    v_title = getattr(item, "title", "")
                    v_type = await detect_video_type(session, v_id, v_link, v_title)

                    embed = build_youtube_alert_embed(item, sample_title, sample_id, channel_avatar, v_type)
                    content_text = get_alert_content(sample_title, v_type)

                    try:
                        await dest_channel.send(content=content_text, embed=embed)
                        total_sent += 1
                        await asyncio.sleep(1)
                    except Exception as e:
                        print(f"[YOUTUBE TEST SEND ERROR]: {e}")

                top_entry = feed.entries[0]
                top_video_id = getattr(top_entry, "yt_videoid", None) or getattr(top_entry, "id", None)
                if top_video_id:
                    update_youtube_last_video(target_sub["id"], top_video_id)

        gc.collect()

        if total_sent > 0:
            await interaction.followup.send(f"✅ ส่งการแจ้งเตือนคลิปล่าสุด (รวม {total_sent} รายการจากทุกช่องที่ติดตาม) ไปยังห้อง {dest_channel.mention} เรียบร้อยแล้ว!", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ ไม่สามารถส่งข้อความเข้าห้อง {dest_channel.mention} ได้ กรุณาตรวจสอบสิทธิ์ของบอท", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(YouTubeCog(bot))
