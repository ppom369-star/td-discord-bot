import os
import platform
import random
import re
import sys
import time
from datetime import datetime, timedelta
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
import psutil
from database.db_manager import (
    add_memo,
    get_memos,
    delete_memo,
    add_reminder,
    set_pomodoro_session,
    get_pomodoro_session,
    get_bangkok_now,
    get_database_diagnostics
)
from utils.dashboard import deliver_channel_card
from cogs.todo import parse_duration_string
from cogs.pomodoro import build_pomodoro_embed, PomodoroControlView

def format_uptime(uptime_seconds: float) -> str:
    delta = timedelta(seconds=int(uptime_seconds))
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    parts = []
    if days > 0:
        parts.append(f"{days} วัน")
    if hours > 0:
        parts.append(f"{hours} ชั่วโมง")
    if minutes > 0:
        parts.append(f"{minutes} นาที")
    parts.append(f"{seconds} วินาที")
    return " ".join(parts)

def get_current_ram_mb() -> float:
    # 1. พยายามอ่านจาก Linux cgroup ของ Discloud (ตรงกับ Discloud Dashboard 100%)
    for path in ["/sys/fs/cgroup/memory/memory.usage_in_bytes", "/sys/fs/cgroup/memory.current"]:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    val = int(f.read().strip())
                    return val / (1024 * 1024)
            except Exception:
                pass

    # 2. กรณีรันบน Windows หรือไม่มี cgroup ใช้ Private Working Set หรือ RSS
    try:
        proc = psutil.Process()
        full = proc.memory_full_info()
        if hasattr(full, "uss") and full.uss > 0:
            return full.uss / (1024 * 1024)
        return proc.memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0

class UtilityCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = time.time()
        self.process = psutil.Process()

    @app_commands.command(name="help", description="ดูคู่มือคำสั่งทั้งหมดและการใช้งานแยกตามแต่ละห้อง")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚡ TD Command Center • Directory",
            description=(
                "> 🟢 **สถานะระบบ:** ทำงานปกติ (24/7 Online)\n"
                "> 🗂️ **โครงสร้างห้อง:** ควบคุมด้วยระบบ Single Dashboard Card (อัปเดตที่เดิม ไม่เลื่อนแชท)"
            ),
            color=discord.Color.from_rgb(79, 70, 229),
            timestamp=datetime.now()
        )
        embed.add_field(
            name="🌅 ห้อง `daily-brief` — สรุปภาพรวมเช้า, อากาศ & PM2.5",
            value=(
                "• `/today` หรือ `/briefing now` — เรียกดูสรุปประจำวันทันที\n"
                "• `/weather <city>` — สภาพอากาศ อุณหภูมิ และพยากรณ์ฝน\n"
                "• `/pm25 <city>` — ตรวจค่าฝุ่น PM2.5 และคำแนะนำสุขภาพ\n"
                "*(มีการ์ด Dashboard พร้อมปุ่มกด [สภาพอากาศ], [ตรวจฝุ่น PM2.5], [สรุปภาพรวมเช้า])*"
            ),
            inline=False
        )
        embed.add_field(
            name="🤖 ห้อง `commands` — เครื่องมือ การเงิน และระบบ",
            value=(
                "• `/oil` — เช็คราคาน้ำมันวันนี้และแนวโน้มพรุ่งนี้ (บางจาก)\n"
                "• `/pomodoro start [work] [break] [loops]` — เริ่มรอบโฟกัสทำงาน (เช่น 25/5 นาที 4 รอบ)\n"
                "• `/crypto <coin>` — เช็คราคาเหรียญคริปโต (เช่น `btc`, `eth`, `sol`)\n"
                "• `/rate <from> <to> [amt]` — คำนวณอัตราแลกเปลี่ยนเงินตรา\n"
                "• `/remind <time> <msg>` — ตั้งเวลาเตือนความจำ (เช่น `10m`, `1h`)\n"
                "• `/ping` / `/status` — เช็คสปีด Latency และทรัพยากรเซิร์ฟเวอร์\n"
                "• `/stream follow [name]` / `/stream list` — ติดตาม Twitch สตรีมเมอร์แจ้งเตือนไลฟ์สด\n"
                "• `/choose` / `/roll` / `/flip` — มินิเกมสุ่มตัวเลือกและทอยเต๋า"
            ),
            inline=False
        )
        embed.add_field(
            name="📝 ห้อง `quick-notes` — To-do List & จดบันทึก",
            value=(
                "• `/todo add <task>` / `/todo list` / `/todo done <id>` / `/todo delete <id>`\n"
                "• `/memo add <title> <content>` / `/memo list` / `/memo delete <id>`"
            ),
            inline=False
        )
        embed.add_field(
            name="💰 ห้อง `รับจ่าย` — สมุดบันทึกรายรับ-รายจ่าย",
            value=(
                "• `/spend <ยอด> [หมวด] [โน้ต]` — บันทึกรายจ่ายด่วน\n"
                "• `/income <ยอด> [หมวด] [โน้ต]` — บันทึกรายรับด่วน\n"
                "• `/expense card` — เรียกดูการ์ดสรุปยอดประจำเดือน\n"
                "• `/expense list [limit]` — ดูประวัติรายการแบบเต็มจำนวน\n"
                "• `/expense delete <id>` — ลบรายการที่ระบุ"
            ),
            inline=False
        )
        embed.add_field(
            name="⛽ ห้อง `ราคาน้ำมัน` — เช็คราคาน้ำมันและแนวโน้มพรุ่งนี้",
            value=(
                "• `/oil` — เรียกดูการ์ดราคาน้ำมันบางจากวันนี้ + แนวโน้มพรุ่งนี้\n"
                "*(มีการ์ด Dashboard พร้อมปุ่มกด [อัปเดตราคาล่าสุด] และรีเฟรชอัตโนมัติ)*"
            ),
            inline=False
        )
        embed.add_field(
            name="🧪 ห้อง `sandbox` — ฟีดข่าวสาร RSS",
            value=(
                "• `/rss add <url>` — ติดตามฟีดข่าว RSS/Atom อัตโนมัติ\n"
                "• `/rss list` / `/rss remove <id>` — จัดการฟีดข่าวที่ติดตาม"
            ),
            inline=False
        )
        embed.set_footer(text="TD Personal Assistant | คุมห้องละ 1 การ์ดไม่รกสายตา")
        await deliver_channel_card(interaction, embed)

    memo_group = app_commands.Group(name="memo", description="สมุดจดบันทึกสั้นส่วนตัว")

    @memo_group.command(name="add", description="เพิ่มโน้ตใหม่")
    @app_commands.describe(title="หัวข้อของโน้ต", content="เนื้อหาหรือลิงก์ที่ต้องการบันทึก")
    async def memo_add(self, interaction: discord.Interaction, title: str, content: str):
        if not interaction.response.is_done():
            await interaction.response.defer()
        memo_id = add_memo(interaction.user.id, title, content)
        embed = discord.Embed(
            title="📝 บันทึกโน้ตสำเร็จ",
            description=f"**ID #{memo_id}:** {title}\n{content}",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        await deliver_channel_card(interaction, embed)

    @memo_group.command(name="list", description="ดูรายการโน้ตทั้งหมดที่บันทึกไว้")
    async def memo_list(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        memos = get_memos(interaction.user.id)
        if not memos:
            embed = discord.Embed(
                title="📝 ไม่มีโน้ตที่บันทึกไว้",
                description="ยังไม่มีโน้ตที่บันทึกไว้ ใช้ `/memo add` เพื่อเพิ่มโน้ต",
                color=discord.Color.light_grey(),
                timestamp=datetime.now()
            )
            await deliver_channel_card(interaction, embed)
            return

        embed = discord.Embed(
            title="📝 รายการโน้ตของคุณ",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        for m in memos[:10]:
            snippet = m["content"] if len(m["content"]) <= 100 else m["content"][:97] + "..."
            embed.add_field(
                name=f"#{m['id']} {m['title']}",
                value=snippet,
                inline=False
            )
        embed.set_footer(text="ใช้ /memo delete <id> เพื่อลบโน้ต")
        await deliver_channel_card(interaction, embed)

    @memo_group.command(name="delete", description="ลบโน้ตที่บันทึกไว้")
    @app_commands.describe(memo_id="รหัส ID ของโน้ตที่ต้องการลบ")
    async def memo_delete(self, interaction: discord.Interaction, memo_id: int):
        if not interaction.response.is_done():
            await interaction.response.defer()
        success = delete_memo(memo_id, interaction.user.id)
        if success:
            embed = discord.Embed(
                title="🗑️ ลบโน้ตเรียบร้อย",
                description=f"ลบโน้ต ID `#{memo_id}` สำเร็จ",
                color=discord.Color.orange(),
                timestamp=datetime.now()
            )
        else:
            embed = discord.Embed(
                title="❌ ไม่พบโน้ตที่ระบุ",
                description=f"ไม่พบโน้ต ID `#{memo_id}` หรือคุณไม่มีสิทธิ์ลบ",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
        await deliver_channel_card(interaction, embed)

    @app_commands.command(name="db_check", description="ตรวจสอบสถานะฐานข้อมูลและพื้นที่บนเซิร์ฟเวอร์")
    async def db_check(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        diag = get_database_diagnostics()
        embed = discord.Embed(
            title="🔍 Database & System Diagnostics",
            color=discord.Color.green() if diag["write_ok"] else discord.Color.red(),
            timestamp=get_bangkok_now()
        )
        embed.add_field(name="📁 DB Path", value=f"`{diag['path']}`", inline=False)
        embed.add_field(name="💾 DB File Size", value=f"`{diag['size_kb']}`", inline=True)
        embed.add_field(name="💽 Disk Space", value=f"`{diag['disk']}`", inline=True)
        status_text = "✅ ปกติ (เขียนข้อมูลได้สำเร็จ)" if diag["write_ok"] else f"❌ ล้มเหลว: `{diag['write_error']}`"
        embed.add_field(name="✍️ Write Test", value=status_text, inline=False)
        counts_lines = [f"• `{k}`: {v} รายการ" for k, v in diag["counts"].items()]
        embed.add_field(name="📊 Record Counts", value="\n".join(counts_lines) if counts_lines else "N/A", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="choose", description="สุ่มเลือกตัวเลือกจากรายการที่ระบุ")
    @app_commands.describe(options="ตัวเลือกที่ต้องการให้สุ่ม เช่น ข้าวมันไก่ กะเพรา ก๋วยเตี๋ยว หรือคั่นด้วยเครื่องหมายจุลภาค")
    async def choose(self, interaction: discord.Interaction, options: str):
        if "," in options:
            items = [item.strip() for item in options.split(",") if item.strip()]
        else:
            items = options.split()

        if len(items) < 2:
            embed = discord.Embed(
                title="⚠️ ข้อมูลไม่เพียงพอ",
                description="กรุณาใส่ตัวเลือกอย่างน้อย 2 อย่าง เช่น `/choose ชาเขียว กาแฟ โกโก้`",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            await deliver_channel_card(interaction, embed)
            return

        chosen = random.choice(items)
        embed = discord.Embed(
            title="🎯 ผลการสุ่มเลือก",
            description=f"ตัวเลือกที่เลือกให้คือ: **{chosen}** 🎉",
            color=discord.Color.teal(),
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"จากตัวเลือกทั้งหมด {len(items)} รายการ")
        await deliver_channel_card(interaction, embed)

    @app_commands.command(name="roll", description="ทอยลูกเต๋า")
    @app_commands.describe(dice="ระบุจำนวนหน้าและจำนวนเต๋า เช่น 1d6, 2d20, 1d100 (ค่าเริ่มต้น 1d6)")
    async def roll(self, interaction: discord.Interaction, dice: str = "1d6"):
        match = re.fullmatch(r"(\d+)d(\d+)", dice.strip().lower())
        if not match:
            embed = discord.Embed(
                title="⚠️ รูปแบบไม่ถูกต้อง",
                description="กรุณาระบุรูปแบบเป็น `XdY` เช่น `1d6`, `2d20`, `1d100`",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            await deliver_channel_card(interaction, embed)
            return

        count = min(int(match.group(1)), 20)
        sides = min(int(match.group(2)), 1000)

        if count <= 0 or sides <= 0:
            embed = discord.Embed(
                title="⚠️ ตัวเลขต้องมากกว่า 0",
                description="จำนวนเต๋าและจำนวนหน้าต้องมากกว่าศูนย์",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            await deliver_channel_card(interaction, embed)
            return

        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls)

        embed = discord.Embed(
            title=f"🎲 ผลการทอย {count}d{sides}",
            description=f"แต้มที่ออก: `{' + '.join(map(str, rolls))}`\n\n**ผลรวมทั้งหมด: {total}**",
            color=discord.Color.purple(),
            timestamp=datetime.now()
        )
        await deliver_channel_card(interaction, embed)

    @app_commands.command(name="flip", description="โยนเหรียญเสี่ยงทาย (หัว หรือ ก้อย)")
    async def flip(self, interaction: discord.Interaction):
        result = random.choice(["หัว 🪙", "ก้อย 🪙"])
        embed = discord.Embed(
            title="🪙 ผลการโยนเหรียญ",
            description=f"เหรียญออก: **{result}**",
            color=discord.Color.gold(),
            timestamp=datetime.now()
        )
        await deliver_channel_card(interaction, embed)

    @app_commands.command(name="ping", description="ทดสอบความเร็วและการตอบสนองของบอท")
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)
        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"WebSocket Latency: **{latency_ms} ms**",
            color=discord.Color.green() if latency_ms < 150 else discord.Color.gold(),
            timestamp=datetime.now()
        )
        await deliver_channel_card(interaction, embed)

    @app_commands.command(name="status", description="ตรวจสอบสถานะการทำงานของบอทและทรัพยากรเครื่อง")
    async def status(self, interaction: discord.Interaction):
        uptime_sec = time.time() - self.start_time
        uptime_str = format_uptime(uptime_sec)
        
        ram_used_mb = get_current_ram_mb()
        cpu_usage = self.process.cpu_percent(interval=0.1)

        embed = discord.Embed(
            title="📊 สถานะระบบบอท TD",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.add_field(name="⏱️ Uptime", value=uptime_str, inline=True)
        embed.add_field(name="🏓 Latency", value=f"{round(self.bot.latency * 1000)} ms", inline=True)
        embed.add_field(name="💾 RAM Usage", value=f"{ram_used_mb:.1f} MB", inline=True)
        embed.add_field(name="⚡ CPU Process", value=f"{cpu_usage:.1f}%", inline=True)
        embed.add_field(name="🐍 Python", value=platform.python_version(), inline=True)
        embed.add_field(name="🤖 discord.py", value=discord.__version__, inline=True)
        embed.set_footer(text=f"รันบน: {platform.system()} {platform.release()}")

        await deliver_channel_card(interaction, embed)

    @app_commands.command(name="cmd", description="แสดงแผงควบคุมหลัก Command Center พร้อมปุ่มลัดเครื่องมือ")
    async def cmd_dashboard(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        embed = build_command_center_embed(self.bot)
        await deliver_channel_card(interaction, embed, view=CommandCenterView())

async def fetch_top_crypto_embed() -> discord.Embed:
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": "bitcoin,ethereum,solana",
        "vs_currencies": "thb,usd",
        "include_24hr_change": "true"
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params, timeout=10) as response:
                if response.status != 200:
                    return discord.Embed(title="⚠️ ไม่สามารถดึงราคา Crypto ได้ในขณะนี้", color=discord.Color.red())
                data = await response.json()
                embed = discord.Embed(
                    title="🪙 ราคาเหรียญคริปโตชั้นนำ • Real-time",
                    color=discord.Color.from_rgb(245, 158, 11),
                    timestamp=datetime.now()
                )
                coins = [
                    ("BTC (Bitcoin)", "bitcoin", "🟧"),
                    ("ETH (Ethereum)", "ethereum", "🔷"),
                    ("SOL (Solana)", "solana", "🟣")
                ]
                for name, cid, icon in coins:
                    cdata = data.get(cid, {})
                    thb = cdata.get("thb", 0)
                    chg = cdata.get("thb_24h_change", 0)
                    sign = "+" if chg >= 0 else ""
                    embed.add_field(
                        name=f"{icon} {name}",
                        value=f"฿{thb:,.2f} ({sign}{chg:.2f}%)",
                        inline=True
                    )
                embed.set_footer(text="ข้อมูลจาก CoinGecko API • อัปเดตล่าสุด")
                return embed
        except Exception:
            return discord.Embed(title="⚠️ เกิดข้อผิดพลาดในการเชื่อมต่อ CoinGecko", color=discord.Color.red())

def build_command_center_embed(bot: commands.Bot) -> discord.Embed:
    latency_ms = round(bot.latency * 1000)
    cpu_pct = psutil.cpu_percent()
    ram_mb = get_current_ram_mb()

    embed = discord.Embed(
        title="🎛️ Command Central • ศูนย์รวมเครื่องมือประจำตัว",
        description=(
            f"> 🟢 **สถานะระบบ:** ทำงานปกติ 24/7 (Latency: `{latency_ms} ms`)\n"
            f"> 🖥️ **ทรัพยากรเครื่อง:** CPU `{cpu_pct}%` | RAM `{ram_mb:.1f} MB` ({ram_mb:.1f}%)\n"
            f"> 💡 *แตะปุ่มด้านล่างเพื่อเปิดใช้งานเครื่องมือด่วนได้ทันที*"
        ),
        color=discord.Color.from_rgb(99, 102, 241),
        timestamp=datetime.now()
    )
    embed.add_field(
        name="⚡ เมนูคำสั่งและปุ่มลัด (Quick Actions)",
        value=(
            "• **🍅 Pomodoro 25m:** เริ่มจับเวลาโฟกัสทำงาน 25 นาที / พัก 5 นาที\n"
            "• **⏰ ตั้งเตือน Remind:** ตั้งเวลาแจ้งเตือนล่วงหน้า (เช่น 15m, 1h)\n"
            "• **🪙 เช็ค Crypto:** ตรวจสอบราคาเหรียญ BTC, ETH, SOL แบบ Real-time\n"
            "• **🎲 สุ่มตัวเลือก:** สุ่มเมนูอาหารหรือทางเลือกเมื่อตัดสินใจไม่ได้\n"
            "• **⚡ เช็คระบบ Ping:** ตรวจสอบความเร็ว Latency และทรัพยากรเซิร์ฟเวอร์"
        ),
        inline=False
    )
    embed.set_footer(text="TD Command Center • กดปุ่มด้านล่างเพื่อเริ่มใช้งาน")
    return embed

class CommandRemindModal(discord.ui.Modal, title="ตั้งเวลาเตือนความจำ 🔔"):
    duration = discord.ui.TextInput(
        label="เวลาที่ต้องการเตือน (เช่น 15m, 1h, 2d, 30s)",
        placeholder="เช่น 15m หรือ 1h หรือ 2h30m",
        required=True,
        max_length=20
    )
    message = discord.ui.TextInput(
        label="ข้อความที่ต้องการให้แจ้งเตือน",
        placeholder="เช่น ซักผ้า, กินยา, เข้าประชุม",
        required=True,
        max_length=150
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        delta = parse_duration_string(self.duration.value)
        if not delta or delta.total_seconds() <= 0:
            await interaction.followup.send("❌ รูปแบบเวลาไม่ถูกต้อง เช่น `10m`, `1h`, `30s`", ephemeral=True)
            return

        due_time = get_bangkok_now() + delta
        msg_text = self.message.value.strip()
        sandbox_id = 1544548171584245860
        try:
            reminder_id = add_reminder(user_id=interaction.user.id, channel_id=sandbox_id, message=msg_text, remind_at=due_time)
            from cogs.todo import start_reminder_task
            start_reminder_task(
                bot=interaction.client,
                reminder_id=reminder_id,
                user_id=interaction.user.id,
                message=msg_text,
                delay_seconds=delta.total_seconds()
            )
            unix_ts = int(due_time.timestamp())
            await interaction.followup.send(
                f"✅ ตั้งเตือนเรียบร้อยแล้ว: **{msg_text}** (<t:{unix_ts}:R>)\n*(ระบบจะส่งการแจ้งเตือนไปที่ห้อง `sandbox`)*",
                ephemeral=True
            )
        except Exception as err:
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาดในการตั้งเตือน: {err}", ephemeral=True)

class CommandChooseModal(discord.ui.Modal, title="สุ่มตัวเลือก 🎯"):
    options = discord.ui.TextInput(
        label="รายการตัวเลือก (คั่นด้วยเครื่องหมายจุลภาค ,)",
        placeholder="เช่น ชาบู, ส้มตำ, ข้าวมันไก่, ข้าวแกง",
        required=True,
        max_length=200
    )

    async def on_submit(self, interaction: discord.Interaction):
        items = [x.strip() for x in self.options.value.split(",") if x.strip()]
        if not items:
            await interaction.response.send_message("❌ กรุณาระบุตัวเลือกอย่างน้อย 2 ตัวเลือก", ephemeral=True)
            return
        chosen = random.choice(items)
        embed = discord.Embed(
            title="🎯 ผลการสุ่มตัวเลือก",
            description=f"ระบบสุ่มเลือกให้: **{chosen}** 🎉\n*(จากตัวเลือก: {', '.join(items)})*",
            color=discord.Color.gold(),
            timestamp=datetime.now()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class CommandCenterView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="เริ่ม Pomodoro 🍅", style=discord.ButtonStyle.danger, custom_id="btn_cmd_pomo", row=0)
    async def pomo_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.pomodoro import PomodoroSetupModal
        await interaction.response.send_modal(PomodoroSetupModal())

    @discord.ui.button(label="ตั้งเตือน Remind 🔔", style=discord.ButtonStyle.success, custom_id="btn_cmd_remind", row=0)
    async def remind_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CommandRemindModal())

    @discord.ui.button(label="ราคา Crypto 🪙", style=discord.ButtonStyle.primary, custom_id="btn_cmd_crypto", row=0)
    async def crypto_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        embed = await fetch_top_crypto_embed()
        await deliver_channel_card(interaction, embed, view=self)

    @discord.ui.button(label="สุ่มตัวเลือก 🎲", style=discord.ButtonStyle.secondary, custom_id="btn_cmd_choose", row=1)
    async def choose_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CommandChooseModal())

    @discord.ui.button(label="เช็คระบบ Ping ⚡", style=discord.ButtonStyle.secondary, custom_id="btn_cmd_ping", row=1)
    async def ping_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        embed = build_command_center_embed(interaction.client)
        await deliver_channel_card(interaction, embed, view=self)

    @discord.ui.button(label="รีเฟรช 🔄", style=discord.ButtonStyle.secondary, custom_id="btn_cmd_refresh", row=1)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        embed = build_command_center_embed(interaction.client)
        await interaction.edit_original_response(embed=embed, view=self)

async def setup(bot: commands.Bot):
    await bot.add_cog(UtilityCog(bot))