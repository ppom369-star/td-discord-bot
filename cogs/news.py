import asyncio
from datetime import datetime
import feedparser
import discord
from discord import app_commands
from discord.ext import commands, tasks
from database.db_manager import (
    add_rss_feed,
    get_rss_feeds,
    update_rss_last_entry,
    delete_rss_feed,
    get_setting,
    set_setting
)
from utils.dashboard import deliver_channel_card

async def fetch_feed_data(url: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, feedparser.parse, url)

class NewsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rss_check_loop.start()

    def cog_unload(self):
        self.rss_check_loop.cancel()

    @tasks.loop(minutes=10)
    async def rss_check_loop(self):
        feeds = get_rss_feeds()
        for feed_record in feeds:
            feed_id = feed_record["id"]
            url = feed_record["feed_url"]
            channel_id = feed_record["channel_id"]
            last_entry_id = feed_record["last_entry_id"]

            try:
                parsed = await fetch_feed_data(url)
                if not parsed.entries:
                    continue

                latest_entry = parsed.entries[0]
                entry_identifier = getattr(latest_entry, "id", None) or getattr(latest_entry, "link", None) or latest_entry.title

                if last_entry_id is None:
                    update_rss_last_entry(feed_id, entry_identifier)
                    continue

                if entry_identifier != last_entry_id:
                    channel = self.bot.get_channel(channel_id)
                    if not channel:
                        try:
                            channel = await self.bot.fetch_channel(channel_id)
                        except Exception:
                            channel = None

                    if channel:
                        feed_title = parsed.feed.get("title", "ข่าวสาร / RSS Feed")
                        title = getattr(latest_entry, "title", "บทความใหม่")
                        link = getattr(latest_entry, "link", "")
                        summary = getattr(latest_entry, "summary", "")
                        
                        if len(summary) > 300:
                            summary = summary[:297] + "..."

                        embed = discord.Embed(
                            title=f"📰 {feed_title}: {title}",
                            url=link if link.startswith("http") else None,
                            description=summary if summary else "คลิกที่ลิงก์เพื่ออ่านรายละเอียด",
                            color=discord.Color.teal(),
                            timestamp=datetime.now()
                        )
                        published = getattr(latest_entry, "published", None)
                        if published:
                            embed.set_footer(text=f"เผยแพร่เมื่อ: {published}")

                        setting_key = f"channel_card_{channel.id}"
                        msg_id_str = get_setting(setting_key)
                        target_msg = None
                        if msg_id_str:
                            try:
                                target_msg = await channel.fetch_message(int(msg_id_str))
                            except Exception:
                                target_msg = None

                        if target_msg:
                            try:
                                await target_msg.edit(embed=embed)
                            except Exception:
                                sent = await channel.send(embed=embed)
                                set_setting(setting_key, str(sent.id))
                        else:
                            sent = await channel.send(embed=embed)
                            set_setting(setting_key, str(sent.id))

                    update_rss_last_entry(feed_id, entry_identifier)

            except Exception:
                continue

    @rss_check_loop.before_loop
    async def before_rss_loop(self):
        await self.bot.wait_until_ready()

    rss_group = app_commands.Group(name="rss", description="จัดการระบบติดตามข่าวสาร RSS Feed")

    @rss_group.command(name="add", description="เพิ่มลิงก์ RSS Feed เข้าสู่ระบบ")
    @app_commands.describe(
        url="URL ของ RSS Feed เช่น https://www.blognone.com/atom.xml",
        channel="ช่อง Text Channel ที่ต้องการให้แจ้งเตือน (ถ้าไม่ใส่จะใช้ห้องปัจจุบัน)"
    )
    async def rss_add(self, interaction: discord.Interaction, url: str, channel: discord.TextChannel = None):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        target_channel = channel or interaction.channel

        try:
            parsed = await fetch_feed_data(url)
            if not parsed.entries:
                embed = discord.Embed(
                    title="⚠️ ตรวจสอบ RSS Feed ไม่สำเร็จ",
                    description="ไม่สามารถอ่านข้อมูลฟีดจาก URL ที่ระบุได้ กรุณาตรวจสอบว่าเป็นลิงก์ RSS/Atom XML ที่ถูกต้อง",
                    color=discord.Color.red(),
                    timestamp=datetime.now()
                )
                await deliver_channel_card(interaction, embed)
                return

            feed_title = parsed.feed.get("title", url)
            latest_id = getattr(parsed.entries[0], "id", None) or getattr(parsed.entries[0], "link", None) or parsed.entries[0].title
            feed_id = add_rss_feed(url, target_channel.id, feed_title)
            update_rss_last_entry(feed_id, latest_id)

            embed = discord.Embed(
                title="✅ เพิ่ม RSS Feed สำเร็จ",
                description=f"**ชื่อฟีด:** {feed_title}\n**ช่อง:** {target_channel.mention}\n**URL:** {url}",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.set_footer(text=f"Feed ID: #{feed_id}")
            await deliver_channel_card(interaction, embed)

        except Exception as err:
            embed = discord.Embed(
                title="❌ เกิดข้อผิดพลาด",
                description=f"ไม่สามารถประมวลผล Feed ได้: {err}",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            await deliver_channel_card(interaction, embed)

    @rss_group.command(name="list", description="ดูรายการ RSS Feed ทั้งหมดที่กำลังติดตาม")
    async def rss_list(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        feeds = get_rss_feeds()
        if not feeds:
            embed = discord.Embed(
                title="📰 รายการ RSS Feed",
                description="ยังไม่มีการติดตาม RSS Feed ในระบบ ใช้ `/rss add` เพื่อเริ่มติดตาม",
                color=discord.Color.light_grey(),
                timestamp=datetime.now()
            )
            await deliver_channel_card(interaction, embed)
            return

        lines = []
        for item in feeds:
            channel_ping = f"<#{item['channel_id']}>"
            title = item.get("title") or item["feed_url"]
            lines.append(f"`#{item['id']}` **{title}** -> {channel_ping}")

        embed = discord.Embed(
            title="📰 รายการ RSS Feed ที่ติดตามอยู่",
            description="\n".join(lines),
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.set_footer(text="ใช้ /rss remove <id> เพื่อยกเลิกฟีด")
        await deliver_channel_card(interaction, embed)

    @rss_group.command(name="remove", description="ยกเลิกการติดตาม RSS Feed")
    @app_commands.describe(feed_id="รหัส ID ของ Feed ที่ต้องการลบ")
    async def rss_remove(self, interaction: discord.Interaction, feed_id: int):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        success = delete_rss_feed(feed_id)
        if success:
            embed = discord.Embed(
                title="🗑️ ลบ RSS Feed เรียบร้อย",
                description=f"ยกเลิกการติดตาม Feed ID `#{feed_id}` สำเร็จ",
                color=discord.Color.orange(),
                timestamp=datetime.now()
            )
        else:
            embed = discord.Embed(
                title="❌ ไม่พบ Feed ที่ระบุ",
                description=f"ไม่พบ Feed ID `#{feed_id}` ในระบบ",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
        await deliver_channel_card(interaction, embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(NewsCog(bot))
