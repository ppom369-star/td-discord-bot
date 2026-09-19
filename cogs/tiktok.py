import asyncio
import os
import gc
from datetime import datetime
import httpx
import discord
from discord import app_commands
from discord.ext import commands, tasks
from TikTokLive import TikTokLiveClient
from database.db_manager import (
    add_tiktok_subscription,
    get_guild_tiktok_subscriptions,
    get_all_tiktok_subscriptions,
    update_tiktok_live_status,
    delete_tiktok_subscription
)

TIKTOK_COLOR = discord.Color.from_rgb(254, 44, 85)
TIKTOK_ICON = "https://sf16-website-login.neutral.ttwstatic.com/obj/tiktok_web_login_static/tiktok/webapp/main/webapp-desktop/8372691238e8334be559.png"

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

async def check_tiktok_live_status(username: str) -> tuple[bool, str | None, str | None]:
    client = TikTokLiveClient(unique_id=username)
    try:
        is_live = await client.is_live()
        room_id = str(client.room_id) if client.room_id else None
        title = None
        if is_live:
            try:
                room_info = await client.web.fetch_room_info()
                if isinstance(room_info, dict):
                    title = room_info.get("title")
                else:
                    title = getattr(room_info, "title", None)
            except Exception:
                title = None
        return is_live, room_id, title
    except Exception:
        return False, None, None

def build_tiktok_live_embed(username: str, nickname: str, room_id: str | None, title: str | None, avatar_url: str | None) -> discord.Embed:
    stream_title = title or f"{nickname} กำลัง Live อยู่ในขณะนี้!"
    stream_url = f"https://www.tiktok.com/@{username}/live"

    embed = discord.Embed(
        title=stream_title,
        url=stream_url,
        color=TIKTOK_COLOR,
        timestamp=datetime.now()
    )
    author_icon = avatar_url or TIKTOK_ICON
    embed.set_author(
        name=f"{nickname} (@{username}) กำลังถ่ายทอดสดบน TikTok!",
        icon_url=author_icon,
        url=stream_url
    )
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    embed.add_field(name="🔴 สถานะ", value="`กำลัง Live สด`", inline=True)
    if room_id:
        embed.add_field(name="🆔 Room ID", value=f"`{room_id}`", inline=True)
    embed.add_field(name="🔗 ลิงก์รับชม", value=f"[คลิกเพื่อเข้าชมไลฟ์]({stream_url})", inline=False)
    embed.set_footer(text="TD TikTok Live Alert", icon_url=TIKTOK_ICON)
    return embed

class TikTokCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tiktok_check_loop.start()

    def cog_unload(self):
        self.tiktok_check_loop.cancel()

    @tasks.loop(minutes=2)
    async def tiktok_check_loop(self):
        try:
            subscriptions = get_all_tiktok_subscriptions()
            if not subscriptions:
                return

            grouped_subs: dict[str, list[dict]] = {}
            for sub in subscriptions:
                uname = sub["tiktok_username"].lower()
                grouped_subs.setdefault(uname, []).append(sub)

            for username, sub_list in grouped_subs.items():
                is_live, room_id, title = await check_tiktok_live_status(username)

                for sub in sub_list:
                    sub_id = sub["id"]
                    last_id = sub.get("last_room_id")
                    current_live = sub.get("is_live", 0)
                    nickname = sub.get("nickname") or username
                    avatar_url = sub.get("avatar_url")
                    dest_channel_id = sub["alert_channel_id"]

                    if is_live:
                        effective_room_id = room_id or "live_now"
                        if effective_room_id != last_id:
                            update_tiktok_live_status(sub_id, is_live=1, last_room_id=effective_room_id)
                            dest_channel = self.bot.get_channel(dest_channel_id)
                            if not dest_channel:
                                try:
                                    dest_channel = await self.bot.fetch_channel(dest_channel_id)
                                except Exception:
                                    dest_channel = None

                            if dest_channel:
                                embed = build_tiktok_live_embed(username, nickname, room_id, title, avatar_url)
                                stream_url = f"https://www.tiktok.com/@{username}/live"
                                await dest_channel.send(
                                    content=f"🔔 **{nickname} (@{username}) กำลังถ่ายทอดสดบน TikTok! 🔴**\n{stream_url}",
                                    embed=embed
                                )
                        else:
                            if not current_live:
                                update_tiktok_live_status(sub_id, is_live=1)
                    else:
                        if current_live:
                            update_tiktok_live_status(sub_id, is_live=0)

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

    @tiktok_group.command(name="follow", description="เพิ่มบัญชี TikTok ที่ต้องการติดตามแจ้งเตือนไลฟ์")
    @app_commands.describe(
        username="ชื่อบัญชี TikTok (เช่น chengaming54 หรือ @chengaming54)",
        channel="ห้อง Text Channel ที่ต้องการรับการแจ้งเตือน (หากไม่ระบุจะใช้ห้องปัจจุบัน)"
    )
    async def tiktok_follow(self, interaction: discord.Interaction, username: str, channel: discord.TextChannel = None):
        await interaction.response.defer(ephemeral=True)
        clean_user = username.strip().lstrip("@").lower()
        target_channel = channel or interaction.channel

        oembed_data = await fetch_tiktok_oembed(clean_user)
        nickname = clean_user
        if oembed_data and oembed_data.get("author_name"):
            nickname = oembed_data["author_name"]

        avatar_url = None
        client = TikTokLiveClient(unique_id=clean_user)
        try:
            avatar_url = client.get_avatar_url()
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
                f"**รอบตรวจสอบ:** ทุก 2 นาที"
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

        if not subs:
            await interaction.followup.send("📋 ยังไม่มีบัญชี TikTok ในรายการติดตาม ใช้คำสั่ง `/tiktok follow` เพื่อเริ่มติดตามได้เลย", ephemeral=True)
            return

        embed = discord.Embed(
            title="🎵 รายชื่อบัญชี TikTok ที่กำลังติดตาม",
            description="ระบบจะตรวจสอบสถานะ Live ทุก 2 นาที และแจ้งเตือนอัตโนมัติ",
            color=TIKTOK_COLOR,
            timestamp=datetime.now()
        )

        lines = []
        for sub in subs:
            uname = sub["tiktok_username"]
            nickname = sub.get("nickname") or uname
            ch_id = sub["alert_channel_id"]
            live_status = "🔴 **กำลัง Live**" if sub.get("is_live") else "⚪ ออฟไลน์"
            ch_mention = f"<#{ch_id}>"
            lines.append(f"• **[{nickname}](https://www.tiktok.com/@{uname})** (`@{uname}`) -> {ch_mention} | {live_status}")

        embed.description = "\n".join(lines)
        embed.set_footer(text=f"รวมทั้งหมด {len(subs)} บัญชี", icon_url=TIKTOK_ICON)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tiktok_group.command(name="check", description="ตรวจสอบสถานะ Live ปัจจุบันของบัญชี TikTok ทันที")
    @app_commands.describe(username="ชื่อบัญชี TikTok ที่ต้องการตรวจสอบ")
    async def tiktok_check(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True)
        clean_user = username.strip().lstrip("@").lower()

        is_live, room_id, title = await check_tiktok_live_status(clean_user)
        oembed_data = await fetch_tiktok_oembed(clean_user)
        nickname = (oembed_data.get("author_name") if oembed_data else None) or clean_user

        if is_live:
            embed = discord.Embed(
                title=f"🔴 {nickname} (@{clean_user}) กำลังถ่ายทอดสด!",
                description=title or "กำลังสตรีมสดบน TikTok",
                url=f"https://www.tiktok.com/@{clean_user}/live",
                color=TIKTOK_COLOR
            )
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

        embed.set_footer(text="TD TikTok Live Checker", icon_url=TIKTOK_ICON)
        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(TikTokCog(bot))
