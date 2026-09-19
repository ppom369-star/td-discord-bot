import asyncio
import os
import gc
import re
from datetime import datetime
import httpx
import feedparser
import discord
from discord import app_commands
from discord.ext import commands, tasks
from TikTokLive import TikTokLiveClient
from database.db_manager import (
    add_tiktok_subscription,
    get_guild_tiktok_subscriptions,
    get_all_tiktok_subscriptions,
    update_tiktok_live_status,
    delete_tiktok_subscription,
    set_guild_tiktok_channel,
    get_guild_tiktok_channel,
    set_tiktok_subscription_rss,
    update_tiktok_last_video
)

TIKTOK_COLOR = discord.Color.from_rgb(254, 44, 85)
TIKTOK_ICON = "https://cdn.jsdelivr.net/gh/walkxcode/dashboard-icons/png/tiktok.png"

async def fetch_tiktok_oembed(username: str) -> dict | None:
    url = f"https://www.tiktok.com/oembed?url=https://www.tiktok.com/@{username}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        return None
    return None

async def check_tiktok_live_status(username: str) -> tuple[bool, str | None, str | None, str | None]:
    clean_user = username.strip().lstrip("@").lower()
    client = TikTokLiveClient(unique_id=clean_user)
    try:
        is_live = await client.is_live()
        room_id = str(client.room_id) if client.room_id else None
        title = None
        live_avatar = None
        if is_live:
            try:
                fetched = await client.get_avatar_url()
                if isinstance(fetched, str) and fetched.startswith("http"):
                    live_avatar = fetched
            except Exception:
                live_avatar = None
            try:
                if hasattr(client, "web"):
                    if hasattr(client.web, "fetch_room_id_from_html"):
                        r_id = await client.web.fetch_room_id_from_html(clean_user)
                        if r_id:
                            room_id = str(r_id)
                            client.web.params["room_id"] = room_id
                    elif hasattr(client.web, "fetch_room_id_from_api"):
                        r_id = await client.web.fetch_room_id_from_api(clean_user)
                        if r_id:
                            room_id = str(r_id)
                            client.web.params["room_id"] = room_id
            except Exception:
                pass
            try:
                room_info = await client.web.fetch_room_info()
                if isinstance(room_info, dict):
                    title = room_info.get("title")
                    if not live_avatar and "owner" in room_info and isinstance(room_info["owner"], dict):
                        urls = room_info["owner"].get("avatar_thumb", {}).get("url_list", [])
                        if urls and isinstance(urls[0], str):
                            live_avatar = urls[0]
                else:
                    title = getattr(room_info, "title", None)
            except Exception:
                title = None
        return is_live, room_id, title, live_avatar
    except Exception as err:
        print(f"[TIKTOK LIVE CHECK ERROR] {clean_user}: {err}", flush=True)
        return False, None, None, None

def build_tiktok_live_embed(username: str, nickname: str, room_id: str | None, title: str | None, avatar_url: str | None) -> discord.Embed:
    stream_title = title or f"{nickname} กำลังถ่ายทอดสด!"
    stream_url = f"https://www.tiktok.com/@{username}/live"

    embed = discord.Embed(
        title=stream_title,
        url=stream_url,
        color=TIKTOK_COLOR,
        timestamp=datetime.now()
    )
    author_icon = avatar_url or TIKTOK_ICON
    embed.set_author(
        name=f"{nickname} กำลังถ่ายทอดสด!",
        icon_url=author_icon,
        url=f"https://www.tiktok.com/@{username}"
    )
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    embed.add_field(name="📌 ประเภท", value="`🔴 ถ่ายทอดสด`", inline=False)
    if room_id and room_id != "live_now":
        embed.add_field(name="🆔 Room ID", value=f"`{room_id}`", inline=True)
    embed.add_field(name="🔗 ลิงก์รับชม", value=f"[คลิกเพื่อเข้าชมไลฟ์]({stream_url})", inline=False)
    embed.set_footer(text="TD TikTok Live Alert", icon_url=TIKTOK_ICON)
    return embed

async def fetch_tiktok_rss(feed_url: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(feed_url)
            if resp.status_code != 200:
                return None
            content = resp.text
        loop = asyncio.get_running_loop()
        parsed = await loop.run_in_executor(None, feedparser.parse, content)
        if not parsed or not getattr(parsed, "entries", None):
            return None

        valid_entry = None
        for entry in parsed.entries:
            link = getattr(entry, "link", "")
            if "/video/" in link:
                valid_entry = entry
                break

        if not valid_entry:
            return None

        link = valid_entry.link
        video_id = link.split("/video/")[-1].split("?")[0].strip()
        title = getattr(valid_entry, "title", "คลิปใหม่บน TikTok")

        thumbnail = None
        media_content = getattr(valid_entry, "media_content", [])
        if media_content and isinstance(media_content, list) and len(media_content) > 0:
            thumbnail = media_content[0].get("url")

        if not thumbnail and hasattr(valid_entry, "description"):
            img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', valid_entry.description)
            if img_match:
                thumbnail = img_match.group(1)

        return {
            "video_id": video_id,
            "url": link,
            "title": title,
            "thumbnail": thumbnail
        }
    except Exception:
        return None

def build_tiktok_video_embed(username: str, nickname: str, video_title: str, video_url: str, thumbnail_url: str | None, avatar_url: str | None) -> discord.Embed:
    display_title = (video_title[:250] + "...") if len(video_title) > 250 else video_title
    embed = discord.Embed(
        title=display_title,
        url=video_url,
        color=TIKTOK_COLOR,
        timestamp=datetime.now()
    )
    author_icon = avatar_url or TIKTOK_ICON
    embed.set_author(
        name=f"{nickname} อัปโหลดคลิปใหม่!",
        icon_url=author_icon,
        url=f"https://www.tiktok.com/@{username}"
    )
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    embed.add_field(name="📌 ประเภท", value="`🎬 วิดีโอ (TikTok)`", inline=False)
    if thumbnail_url:
        embed.set_image(url=thumbnail_url)

    embed.add_field(name="🔗 ลิงก์รับชม", value=f"[คลิกเพื่อรับชมคลิปบน TikTok]({video_url})", inline=False)
    embed.set_footer(text="TD TikTok Video Alert", icon_url=TIKTOK_ICON)
    return embed

class TikTokCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tiktok_check_loop.start()

    def cog_unload(self):
        self.tiktok_check_loop.cancel()

    @tasks.loop(minutes=3)
    async def tiktok_check_loop(self):
        try:
            subscriptions = get_all_tiktok_subscriptions()
            if not subscriptions:
                return

            grouped_subs: dict[str, list[dict]] = {}
            for sub in subscriptions:
                uname = sub["tiktok_username"].lower()
                grouped_subs.setdefault(uname, []).append(sub)

            rss_cache: dict[str, dict | None] = {}

            for username, sub_list in grouped_subs.items():
                is_live, room_id, title, live_avatar = await check_tiktok_live_status(username)

                for sub in sub_list:
                    sub_id = sub["id"]
                    last_id = sub.get("last_room_id")
                    current_live = sub.get("is_live", 0)
                    nickname = sub.get("nickname") or username
                    avatar_url = live_avatar or sub.get("avatar_url")
                    dest_channel_id = sub["alert_channel_id"]

                    if is_live:
                        effective_room_id = room_id or "live_now"
                        should_alert = False

                        if not current_live:
                            should_alert = True
                        elif last_id in (None, "", "live_now"):
                            should_alert = True
                        elif room_id and last_id and room_id != last_id:
                            should_alert = True

                        if should_alert:
                            alert_marker = room_id or f"live_alerted_{int(datetime.now().timestamp())}"
                            update_tiktok_live_status(sub_id, is_live=1, last_room_id=alert_marker, avatar_url=avatar_url)
                            dest_channel = self.bot.get_channel(dest_channel_id)
                            if not dest_channel:
                                try:
                                    dest_channel = await self.bot.fetch_channel(dest_channel_id)
                                except Exception:
                                    dest_channel = None

                            if dest_channel:
                                embed = build_tiktok_live_embed(username, nickname, room_id, title, avatar_url)
                                stream_url = f"https://www.tiktok.com/@{username}/live"
                                content_text = f"🔴 @everyone **{nickname}** กำลังถ่ายทอดสดบน TikTok! 🔴\n{stream_url}"
                                try:
                                    await dest_channel.send(
                                        content=content_text,
                                        embed=embed,
                                        allowed_mentions=discord.AllowedMentions(everyone=True)
                                    )
                                except Exception as send_err:
                                    print(f"[TIKTOK LIVE SEND ERROR] Channel {dest_channel_id}: {send_err}", flush=True)
                        else:
                            if not current_live:
                                update_tiktok_live_status(sub_id, is_live=1)
                    else:
                        if current_live:
                            update_tiktok_live_status(sub_id, is_live=0, last_room_id="")

                    rss_url = sub.get("rss_url")
                    if rss_url:
                        if rss_url not in rss_cache:
                            rss_cache[rss_url] = await fetch_tiktok_rss(rss_url)
                        rss_data = rss_cache[rss_url]

                        if rss_data:
                            latest_vid = rss_data["video_id"]
                            last_vid = sub.get("last_video_id")

                            if not last_vid:
                                update_tiktok_last_video(sub_id, latest_vid)
                            elif latest_vid != last_vid:
                                update_tiktok_last_video(sub_id, latest_vid)
                                dest_channel = self.bot.get_channel(dest_channel_id)
                                if not dest_channel:
                                    try:
                                        dest_channel = await self.bot.fetch_channel(dest_channel_id)
                                    except Exception:
                                        dest_channel = None

                                if dest_channel:
                                    embed = build_tiktok_video_embed(
                                        username=username,
                                        nickname=nickname,
                                        video_title=rss_data["title"],
                                        video_url=rss_data["url"],
                                        thumbnail_url=rss_data["thumbnail"],
                                        avatar_url=avatar_url
                                    )
                                    content_text = f"🔔 @everyone **{nickname}** อัปโหลดคลิปใหม่บน TikTok! 🎬\n{rss_data['url']}"
                                    try:
                                        await dest_channel.send(
                                            content=content_text,
                                            embed=embed,
                                            allowed_mentions=discord.AllowedMentions(everyone=True)
                                        )
                                    except Exception as send_err:
                                        print(f"[TIKTOK VIDEO SEND ERROR] Channel {dest_channel_id}: {send_err}", flush=True)

                await asyncio.sleep(1)

            gc.collect()
        except Exception as err:
            print(f"[TIKTOK CHECK LOOP ERROR] {err}", flush=True)

    @tiktok_check_loop.error
    async def on_tiktok_loop_error(self, error):
        print(f"[TIKTOK TASK LOOP ERROR] {error}", flush=True)
        await asyncio.sleep(5)
        if not self.tiktok_check_loop.is_running():
            try:
                self.tiktok_check_loop.restart()
            except Exception:
                pass

    @tiktok_check_loop.before_loop
    async def before_tiktok_loop(self):
        await self.bot.wait_until_ready()

    tiktok_group = app_commands.Group(name="tiktok", description="ระบบติดตามการแจ้งเตือน LIVE TikTok")

    @tiktok_group.command(name="setup", description="กำหนดห้อง Text Channel สำหรับรับการแจ้งเตือน TikTok Live")
    @app_commands.describe(channel="เลือกห้องที่ต้องการให้บอทส่งข้อความแจ้งเตือน")
    async def tiktok_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        set_guild_tiktok_channel(interaction.guild_id, channel.id)

        embed = discord.Embed(
            title="✅ ตั้งค่าห้องแจ้งเตือน TikTok สำเร็จ!",
            description=(
                f"**เซิร์ฟเวอร์:** `{interaction.guild.name}`\n"
                f"**ห้องแจ้งเตือน:** {channel.mention}\n"
                f"**รอบตรวจสอบ:** ทุก 3 นาที\n\n"
                f"💡 บัญชี TikTok ที่ติดตามทั้งหมดในเซิร์ฟเวอร์นี้จะแจ้งเตือนไปยังห้องนี้"
            ),
            color=TIKTOK_COLOR,
            timestamp=datetime.now()
        )
        embed.set_footer(text="TD TikTok Live Alert", icon_url=TIKTOK_ICON)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tiktok_group.command(name="follow", description="เพิ่มบัญชี TikTok ที่ต้องการติดตามแจ้งเตือนไลฟ์")
    @app_commands.describe(
        username="ชื่อบัญชี TikTok (เช่น chengaming54 หรือ @chengaming54)",
        channel="ห้อง Text Channel ที่ต้องการรับการแจ้งเตือน (หากไม่ระบุจะใช้ห้องตามที่ตั้งค่าไว้)"
    )
    async def tiktok_follow(self, interaction: discord.Interaction, username: str, channel: discord.TextChannel = None):
        await interaction.response.defer(ephemeral=True)
        clean_user = username.strip().lstrip("@").lower()

        default_channel_id = get_guild_tiktok_channel(interaction.guild_id)
        default_channel = self.bot.get_channel(default_channel_id) if default_channel_id else None
        target_channel = channel or default_channel or interaction.channel

        oembed_data = await fetch_tiktok_oembed(clean_user)
        nickname = clean_user
        if oembed_data and oembed_data.get("author_name"):
            nickname = oembed_data["author_name"]

        avatar_url = None
        client = TikTokLiveClient(unique_id=clean_user)
        try:
            fetched_avatar = await client.get_avatar_url()
            if isinstance(fetched_avatar, str) and fetched_avatar.startswith("http"):
                avatar_url = fetched_avatar
        except Exception:
            avatar_url = None

        add_tiktok_subscription(
            guild_id=interaction.guild_id,
            tiktok_username=clean_user,
            nickname=nickname,
            alert_channel_id=target_channel.id,
            avatar_url=avatar_url
        )

        embed = discord.Embed(
            title="✅ เพิ่มการติดตาม TikTok สำเร็จ!",
            description=(
                f"**ผู้สร้าง:** `{nickname}` (`@{clean_user}`)\n"
                f"**แพลตฟอร์ม:** TikTok Live\n"
                f"**ห้องแจ้งเตือน:** {target_channel.mention}\n"
                f"**รอบตรวจสอบ:** ทุก 3 นาที"
            ),
            color=TIKTOK_COLOR
        )
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tiktok_group.command(name="unfollow", description="ยกเลิกการติดตามแจ้งเตือน TikTok")
    @app_commands.describe(username="ชื่อบัญชี TikTok ที่ต้องการยกเลิก")
    async def tiktok_unfollow(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True)
        clean_user = username.strip().lstrip("@").lower()
        success = delete_tiktok_subscription(interaction.guild_id, clean_user)

        if success:
            embed = discord.Embed(
                title="🗑️ ยกเลิกการติดตามเรียบร้อย",
                description=f"ยกเลิกการติดตามบัญชี TikTok `@{clean_user}` ออกจากเซิร์ฟเวอร์นี้แล้ว",
                color=TIKTOK_COLOR
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(f"❌ ไม่พบบัญชี `@{clean_user}` ในรายการติดตามของเซิร์ฟเวอร์นี้", ephemeral=True)

    @tiktok_group.command(name="list", description="ดูรายชื่อบัญชี TikTok ที่กำลังติดตามในเซิร์ฟเวอร์นี้")
    async def tiktok_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        subs = get_guild_tiktok_subscriptions(interaction.guild_id)
        default_channel_id = get_guild_tiktok_channel(interaction.guild_id)
        default_channel_text = f"<#{default_channel_id}>" if default_channel_id else "ยังไม่ได้กำหนด (ใช้ /tiktok setup)"

        if not subs:
            embed = discord.Embed(
                title="🎵 รายชื่อบัญชี TikTok ที่กำลังติดตาม",
                description=f"**ห้องแจ้งเตือนหลัก:** {default_channel_text}\n\n📋 ยังไม่มีบัญชี TikTok ในรายการติดตาม ใช้คำสั่ง `/tiktok follow` เพื่อเริ่มติดตามได้เลย",
                color=TIKTOK_COLOR
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="🎵 รายชื่อบัญชี TikTok ที่กำลังติดตาม",
            description=f"**ห้องแจ้งเตือนหลัก:** {default_channel_text}\nระบบจะตรวจสอบสถานะ Live ทุก 3 นาที และแจ้งเตือนอัตโนมัติ\n",
            color=TIKTOK_COLOR,
            timestamp=datetime.now()
        )

        lines = []
        for sub in subs:
            uname = sub["tiktok_username"]
            nickname = sub.get("nickname") or uname
            ch_id = sub["alert_channel_id"]
            live_status = "🔴 **กำลัง Live**" if sub.get("is_live") else "⚪ ออฟไลน์"
            feed_status = "🎬 มี Feed คลิป" if sub.get("rss_url") else "⚪ ไม่มี Feed"
            ch_mention = f"<#{ch_id}>"
            lines.append(f"• **[{nickname}](https://www.tiktok.com/@{uname})** (`@{uname}`) -> {ch_mention} | {live_status} | {feed_status}")

        embed.description += "\n" + "\n".join(lines)
        embed.set_footer(text=f"รวมทั้งหมด {len(subs)} บัญชี", icon_url=TIKTOK_ICON)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tiktok_group.command(name="check", description="ตรวจสอบสถานะ Live ปัจจุบันของบัญชี TikTok ทันที")
    @app_commands.describe(username="ชื่อบัญชี TikTok ที่ต้องการตรวจสอบ")
    async def tiktok_check(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True)
        clean_user = username.strip().lstrip("@").lower()

        is_live, room_id, title, live_avatar = await check_tiktok_live_status(clean_user)
        oembed_data = await fetch_tiktok_oembed(clean_user)
        nickname = (oembed_data.get("author_name") if oembed_data else None) or clean_user

        if is_live:
            embed = discord.Embed(
                title=f"🔴 {nickname} (@{clean_user}) กำลังถ่ายทอดสด!",
                description=title or "กำลังสตรีมสดบน TikTok",
                url=f"https://www.tiktok.com/@{clean_user}/live",
                color=TIKTOK_COLOR
            )
            embed.set_author(name=f"{nickname} (@{clean_user})", icon_url=live_avatar or TIKTOK_ICON, url=f"https://www.tiktok.com/@{clean_user}/live")
            if live_avatar:
                embed.set_thumbnail(url=live_avatar)
            if room_id:
                embed.add_field(name="Room ID", value=f"`{room_id}`", inline=True)
            embed.add_field(name="ลิงก์", value=f"[เข้าชมไลฟ์](https://www.tiktok.com/@{clean_user}/live)", inline=True)
        else:
            embed = discord.Embed(
                title=f"⚪ {nickname} (@{clean_user}) ไม่ได้ไลฟ์อยู่ในขณะนี้",
                description="ผู้ใช้นี้อยู่ในสถานะออฟไลน์",
                url=f"https://www.tiktok.com/@{clean_user}",
                color=discord.Color.dark_grey()
            )
            embed.set_author(name=f"{nickname} (@{clean_user})", icon_url=TIKTOK_ICON, url=f"https://www.tiktok.com/@{clean_user}")

        embed.set_footer(text="TD TikTok Live Checker", icon_url=TIKTOK_ICON)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tiktok_group.command(name="test", description="ทดสอบส่งการแจ้งเตือน TikTok Live ไปยังห้องแจ้งเตือน (ส่งจริง)")
    @app_commands.describe(username="ชื่อบัญชี TikTok ที่ต้องการทดสอบ")
    async def tiktok_test(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True)
        clean_user = username.strip().lstrip("@").lower()
        subs = get_guild_tiktok_subscriptions(interaction.guild_id)
        target_sub = next((s for s in subs if s["tiktok_username"] == clean_user), None)

        default_channel_id = get_guild_tiktok_channel(interaction.guild_id)
        dest_channel_id = (target_sub["alert_channel_id"] if target_sub else None) or default_channel_id
        if not dest_channel_id:
            dest_channel = interaction.channel
        else:
            dest_channel = self.bot.get_channel(dest_channel_id)
            if not dest_channel:
                try:
                    dest_channel = await self.bot.fetch_channel(dest_channel_id)
                except Exception:
                    dest_channel = None

        if not dest_channel:
            await interaction.followup.send("❌ ไม่พบห้องแจ้งเตือน กรุณาตั้งค่าห้องด้วย `/tiktok setup` ก่อน", ephemeral=True)
            return

        nickname = (target_sub.get("nickname") if target_sub else None) or clean_user
        avatar_url = target_sub.get("avatar_url") if target_sub else None

        embed = build_tiktok_live_embed(clean_user, nickname, "test_room_12345", f"ถ่ายทอดสด {nickname}", avatar_url)
        stream_url = f"https://www.tiktok.com/@{clean_user}/live"
        content_text = f"🔴 @everyone **{nickname}** กำลังถ่ายทอดสดบน TikTok! 🔴\n{stream_url}"

        try:
            await dest_channel.send(
                content=content_text,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(everyone=True)
            )
            await interaction.followup.send(f"✅ ส่งข้อความทดสอบไปยังห้อง {dest_channel.mention} เรียบร้อยแล้ว", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ ส่งข้อความทดสอบไม่สำเร็จ: {e}", ephemeral=True)

    @tiktok_group.command(name="feed", description="เชื่อมต่อ RSS Feed สำหรับแจ้งเตือนคลิปใหม่ของ TikTok")
    @app_commands.describe(
        username="ชื่อบัญชี TikTok (เช่น chengaming54 หรือ @chengaming54)",
        rss_url="ลิงก์ RSS XML Feed (จาก RSS.app เช่น https://rss.app/feeds/xxxx.xml)"
    )
    async def tiktok_feed(self, interaction: discord.Interaction, username: str, rss_url: str):
        await interaction.response.defer(ephemeral=True)
        clean_user = username.strip().lstrip("@").lower()
        clean_feed = rss_url.strip()

        rss_data = await fetch_tiktok_rss(clean_feed)
        if not rss_data:
            await interaction.followup.send(
                "❌ ไม่สามารถดึงข้อมูล RSS Feed ได้ กรุณาตรวจสอบว่าเป็นลิงก์ XML ของ TikTok ที่ถูกต้องและเปิดใช้งานอยู่",
                ephemeral=True
            )
            return

        subs = get_guild_tiktok_subscriptions(interaction.guild_id)
        target_sub = next((s for s in subs if s["tiktok_username"] == clean_user), None)

        if not target_sub:
            default_channel_id = get_guild_tiktok_channel(interaction.guild_id)
            target_channel = self.bot.get_channel(default_channel_id) if default_channel_id else interaction.channel

            oembed_data = await fetch_tiktok_oembed(clean_user)
            nickname = (oembed_data.get("author_name") if oembed_data else None) or clean_user

            avatar_url = None
            client = TikTokLiveClient(unique_id=clean_user)
            try:
                fetched_avatar = await client.get_avatar_url()
                if isinstance(fetched_avatar, str) and fetched_avatar.startswith("http"):
                    avatar_url = fetched_avatar
            except Exception:
                avatar_url = None

            add_tiktok_subscription(
                guild_id=interaction.guild_id,
                tiktok_username=clean_user,
                nickname=nickname,
                alert_channel_id=target_channel.id,
                avatar_url=avatar_url,
                rss_url=clean_feed,
                last_video_id=rss_data["video_id"]
            )
        else:
            set_tiktok_subscription_rss(
                guild_id=interaction.guild_id,
                tiktok_username=clean_user,
                rss_url=clean_feed,
                last_video_id=rss_data["video_id"]
            )

        embed = discord.Embed(
            title="✅ เชื่อมต่อ RSS Feed สำเร็จ!",
            description=(
                f"**บัญชี:** `@{clean_user}`\n"
                f"**ลิงก์ฟีด:** [คลิกเพื่อดู XML]({clean_feed})\n"
                f"**คลิปล่าสุด:** {rss_data['title']}\n"
                f"**URL คลิป:** [ดูคลิปบน TikTok]({rss_data['url']})\n\n"
                f"💡 บันทึกคลิปล่าสุดแล้ว ระบบจะแจ้งเตือนอัตโนมัติเมื่อมีคลิปใหม่ลงช่อง"
            ),
            color=TIKTOK_COLOR,
            timestamp=datetime.now()
        )
        if rss_data.get("thumbnail"):
            embed.set_image(url=rss_data["thumbnail"])
        embed.set_footer(text="TD TikTok Video Feed", icon_url=TIKTOK_ICON)
        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(TikTokCog(bot))
