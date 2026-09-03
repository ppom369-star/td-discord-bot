import os
import gc
from datetime import datetime
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from database.db_manager import (
    add_stream_tracker,
    get_stream_trackers,
    get_stream_tracker_by_login,
    update_stream_tracker_status,
    delete_stream_tracker,
    get_setting
)

TWITCH_GQL_URL = "https://gql.twitch.tv/gql"
TWITCH_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
DEFAULT_USER_ID = int(os.getenv("OWNER_USER_ID", "372796686323417089"))

async def fetch_twitch_user(session: aiohttp.ClientSession, login: str) -> dict | None:
    query = """
    query($login: String!) {
        user(login: $login) {
            id
            login
            displayName
            profileImageURL(width: 300)
            stream {
                id
                title
                game {
                    name
                }
                viewersCount
                createdAt
                previewImageURL(width: 1280, height: 720)
            }
        }
    }
    """
    payload = {"query": query, "variables": {"login": login.strip().lower()}}
    headers = {
        "Client-Id": TWITCH_CLIENT_ID,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    try:
        async with session.post(TWITCH_GQL_URL, json=payload, headers=headers, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("data", {}).get("user")
    except Exception:
        return None
    return None

def build_twitch_live_embed(user_data: dict) -> discord.Embed:
    display_name = user_data.get("displayName") or user_data.get("login")
    login = user_data.get("login")
    stream = user_data.get("stream") or {}
    stream_title = stream.get("title") or "ไม่มีชื่อสตรีม"
    game_name = stream.get("game", {}).get("name") if stream.get("game") else "ไม่ได้ระบุเกม"
    profile_pic = user_data.get("profileImageURL")
    preview_url = stream.get("previewImageURL")
    unix_now = int(datetime.now().timestamp())

    embed = discord.Embed(
        title=stream_title,
        url=f"https://www.twitch.tv/{login}",
        color=discord.Color.from_rgb(145, 70, 255),
        timestamp=datetime.now()
    )
    if profile_pic:
        embed.set_author(
            name=f"{display_name} (@{login}) กำลัง Live!",
            icon_url=profile_pic,
            url=f"https://www.twitch.tv/{login}"
        )
        embed.set_thumbnail(url=profile_pic)

    embed.add_field(name="🎮 เกม / หมวดหมู่", value=f"`{game_name}`", inline=False)

    if preview_url:
        embed.set_image(url=f"{preview_url}?t={unix_now}")

    embed.set_footer(text="TD Twitch Stream Alert")
    return embed

class TwitchCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.twitch_check_loop.start()

    def cog_unload(self):
        self.twitch_check_loop.cancel()

    @tasks.loop(minutes=3)
    async def twitch_check_loop(self):
        trackers = get_stream_trackers(platform="twitch")
        if not trackers:
            return

        target_user_id = int(get_setting("briefing_target_user_id") or DEFAULT_USER_ID)

        async with aiohttp.ClientSession() as session:
            for item in trackers:
                t_id = item["id"]
                login = item["channel_login"]
                dest_id = item["destination_channel_id"]
                last_id = item.get("last_stream_id")
                is_live = item.get("is_live", 0)

                user_data = await fetch_twitch_user(session, login)
                if not user_data:
                    continue

                stream = user_data.get("stream")
                display_name = user_data.get("displayName") or login

                if stream:
                    stream_id = stream.get("id")
                    if stream_id != last_id:
                        update_stream_tracker_status(t_id, is_live=1, last_stream_id=stream_id)
                        dest_channel = self.bot.get_channel(dest_id)
                        if not dest_channel:
                            try:
                                dest_channel = await self.bot.fetch_channel(dest_id)
                            except Exception:
                                dest_channel = None

                        if dest_channel:
                            embed = build_twitch_live_embed(user_data)
                            await dest_channel.send(
                                content=f"🔔 <@{target_user_id}> **{display_name} (@{login}) กำลังถ่ายทอดสดบน Twitch! 🔴**",
                                embed=embed
                            )
                    else:
                        if not is_live:
                            update_stream_tracker_status(t_id, is_live=1)
                else:
                    if is_live:
                        update_stream_tracker_status(t_id, is_live=0)


    @twitch_check_loop.before_loop
    async def before_twitch_loop(self):
        await self.bot.wait_until_ready()

    stream_group = app_commands.Group(name="stream", description="ระบบติดตามการถ่ายทอดสด Twitch สตรีมเมอร์")

    @stream_group.command(name="follow", description="เพิ่มสตรีมเมอร์ Twitch ที่ต้องการติดตามแจ้งเตือนไลฟ์")
    @app_commands.describe(
        username="ชื่อ ID Twitch เช่น ramuneshiranami หรือ url ช่อง",
        channel="เลือกห้อง Text Channel ที่ต้องการให้แจ้งเตือน (หากไม่ระบุจะใช้ห้องปัจจุบัน)"
    )
    async def stream_follow(self, interaction: discord.Interaction, username: str, channel: discord.TextChannel = None):
        await interaction.response.defer(ephemeral=True)
        target_channel = channel or interaction.channel
        cleaned = username.strip().rstrip("/").split("/")[-1].lower()

        async with aiohttp.ClientSession() as session:
            user_data = await fetch_twitch_user(session, cleaned)

        if not user_data:
            await interaction.followup.send(
                f"❌ ไม่พบสตรีมเมอร์ชื่อ `{cleaned}` บน Twitch กรุณาตรวจสอบการสะกดชื่อใหม่อีกครั้ง",
                ephemeral=True
            )
            return

        disp_name = user_data.get("displayName") or cleaned
        add_stream_tracker(
            platform="twitch",
            channel_login=cleaned,
            display_name=disp_name,
            destination_channel_id=target_channel.id
        )

        embed = discord.Embed(
            title="✅ เพิ่มการติดตามสำเร็จ!",
            description=(
                f"**สตรีมเมอร์:** `{disp_name}` (`@{cleaned}`)\n"
                f"**แพลตฟอร์ม:** Twitch\n"
                f"**ห้องแจ้งเตือน:** {target_channel.mention}\n"
                f"**รอบตรวจสอบ:** ทุก 3 นาที"
            ),
            color=discord.Color.from_rgb(145, 70, 255)
        )
        if user_data.get("profileImageURL"):
            embed.set_thumbnail(url=user_data["profileImageURL"])
        await interaction.followup.send(embed=embed, ephemeral=True)

    @stream_group.command(name="list", description="ดูรายชื่อสตรีมเมอร์ที่กำลังติดตามทั้งหมด")
    async def stream_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        trackers = get_stream_trackers(platform="twitch")
        if not trackers:
            await interaction.followup.send("📋 ยังไม่มีสตรีมเมอร์ในรายการติดตาม ใช้คำสั่ง `/stream follow` เพื่อเริ่มติดตามได้เลย", ephemeral=True)
            return

        embed = discord.Embed(
            title="🟣 รายชื่อสตรีมเมอร์ Twitch ที่กำลังติดตาม",
            description="ระบบจะตรวจสอบสถานะทุก 3 นาที และแจ้งเตือนไปยังห้องที่กำหนด",
            color=discord.Color.from_rgb(145, 70, 255),
            timestamp=datetime.now()
        )

        lines = []
        for item in trackers:
            status_badge = "🔴 กำลัง Live!" if item.get("is_live") else "⚪ ออฟไลน์"
            disp = item.get("display_name") or item["channel_login"]
            dest_ping = f"<#{item['destination_channel_id']}>"
            lines.append(f"• **{disp}** (`@{item['channel_login']}`) — {status_badge} ➔ {dest_ping}")

        embed.add_field(name=f"สตรีมเมอร์ทั้งหมด ({len(trackers)})", value="\n".join(lines), inline=False)
        embed.set_footer(text="TD Twitch Stream Alert")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @stream_group.command(name="remove", description="ยกเลิกการติดตามสตรีมเมอร์ Twitch")
    @app_commands.describe(username="ชื่อ ID Twitch ที่ต้องการยกเลิก")
    async def stream_remove(self, interaction: discord.Interaction, username: str):
        cleaned = username.strip().rstrip("/").split("/")[-1].lower()
        success = delete_stream_tracker(cleaned, platform="twitch")
        if success:
            await interaction.response.send_message(f"🗑️ ยกเลิกการติดตามสตรีมเมอร์ `@{cleaned}` เรียบร้อยแล้ว", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ ไม่พบสตรีมเมอร์ `@{cleaned}` ในรายการติดตาม", ephemeral=True)

    @stream_group.command(name="check", description="ตรวจสอบสถานะสตรีมเมอร์ Twitch ทันที")
    @app_commands.describe(username="ชื่อ ID Twitch เช่น ramuneshiranami")
    async def stream_check(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True)
        cleaned = username.strip().rstrip("/").split("/")[-1].lower()

        async with aiohttp.ClientSession() as session:
            user_data = await fetch_twitch_user(session, cleaned)

        if not user_data:
            await interaction.followup.send(f"❌ ไม่พบสตรีมเมอร์ชื่อ `{cleaned}` บน Twitch", ephemeral=True)
            return

        stream = user_data.get("stream")
        disp_name = user_data.get("displayName") or cleaned

        if stream:
            embed = build_twitch_live_embed(user_data)
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title=f"⚪ {disp_name} (@{cleaned}) ออฟไลน์อยู่",
                description="ขณะนี้สตรีมเมอร์ไม่ได้เปิดการถ่ายทอดสด",
                color=discord.Color.light_grey()
            )
            if user_data.get("profileImageURL"):
                embed.set_thumbnail(url=user_data["profileImageURL"])
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(TwitchCog(bot))
