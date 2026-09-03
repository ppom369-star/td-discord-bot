import asyncio
from datetime import datetime, timedelta
import os
import discord
from discord import app_commands
from discord.ext import commands
from database.db_manager import (
    get_setting,
    set_setting,
    get_todos,
    get_bangkok_now
)
from cogs.weather import (
    fetch_weather_report,
    WeatherDashboardView
)
from utils.dashboard import deliver_channel_card

async def build_briefing_embed(user_id: int, city: str = None) -> discord.Embed:
    now = get_bangkok_now()
    embed = discord.Embed(
        title="☀️ สรุปภาพรวมยามเช้า (Daily Morning Briefing)",
        description=f"ข้อมูลประจำวันที่ {now.strftime('%d/%m/%Y')}",
        color=discord.Color.gold(),
        timestamp=now
    )

    if city:
        weather = await fetch_weather_report(city)
        if weather:
            forecast = weather["forecast"]
            weather_val = (
                f"**{weather['icon']} {weather['condition']}** ({weather['location']})\n"
                f"• อุณหภูมิ: **{weather['temperature']} °C** (ต่ำสุด {forecast['temp_min']}°C / สูงสุด {forecast['temp_max']}°C)\n"
                f"• {forecast['rain_text']}\n"
                f"• {forecast['uv_text']}"
            )
        else:
            weather_val = f"ไม่สามารถดึงข้อมูลสำหรับ {city} ได้"
        embed.add_field(name="🌤️ สภาพอากาศและพยากรณ์วันนี้", value=weather_val, inline=False)
    else:
        home_city = get_setting("briefing_home_city", get_setting("briefing_city", "Bang Na"))
        work_city = get_setting("briefing_work_city", "Lat Phrao")

        home_weather, work_weather = await asyncio.gather(
            fetch_weather_report(home_city),
            fetch_weather_report(work_city)
        )

        weather_parts = []
        if home_weather:
            h_fc = home_weather["forecast"]
            weather_parts.append(
                f"🏠 **บ้าน ({home_city}):** {home_weather['icon']} {home_weather['condition']} ({home_weather['temperature']} °C)\n"
                f"• {h_fc['rain_text']}"
            )
        else:
            weather_parts.append(f"🏠 **บ้าน ({home_city}):** ไม่พบข้อมูลสภาพอากาศ")

        if work_weather:
            w_fc = work_weather["forecast"]
            weather_parts.append(
                f"🏢 **ที่ทำงาน ({work_city}):** {work_weather['icon']} {work_weather['condition']} ({work_weather['temperature']} °C)\n"
                f"• {w_fc['rain_text']}"
            )
        else:
            weather_parts.append(f"🏢 **ที่ทำงาน ({work_city}):** ไม่พบข้อมูลสภาพอากาศ")

        primary_weather = work_weather or home_weather
        if primary_weather:
            weather_parts.append(f"• {primary_weather['forecast']['uv_text']}")

        embed.add_field(name="🌤️ สภาพอากาศ & พยากรณ์ฝนวันนี้ (บ้าน & ที่ทำงาน)", value="\n\n".join(weather_parts), inline=False)

    pending_todos = get_todos(user_id, status="pending")
    if pending_todos:
        todo_lines = [f"`#{item['id']}` ⏳ {item['task']}" for item in pending_todos[:5]]
        if len(pending_todos) > 5:
            todo_lines.append(f"...และอีก {len(pending_todos) - 5} รายการ")
        todo_val = "\n".join(todo_lines)
    else:
        todo_val = "🎉 ไม่มีงานค้างในรายการ To-do วันนี้!"
    embed.add_field(name="📋 งานที่ต้องทำ (To-do)", value=todo_val, inline=False)


    try:
        from cogs.fuel import fetch_fuel_prices
        fuel_data = await fetch_fuel_prices()
        if fuel_data:
            fuels = fuel_data.get("fuels", {})
            g95 = fuels.get("Gasohol 95 S EVO", {}).get("today", 0)
            dsl = fuels.get("Hi Diesel S", {}).get("today", 0)
            diff = fuels.get("Gasohol 95 S EVO", {}).get("diff", 0) or fuels.get("Hi Diesel S", {}).get("diff", 0)
            if diff > 0:
                diff_str = f"🔺 **พรุ่งนี้ปรับขึ้น +{diff:.2f} ฿**"
            elif diff < 0:
                diff_str = f"🔻 **พรุ่งนี้ปรับลง {diff:.2f} ฿**"
            else:
                diff_str = "พรุ่งนี้ราคาคงเดิม"
            embed.add_field(
                name="⛽ ราคาน้ำมันวันนี้ (บางจาก)",
                value=f"• โซฮอล์ 95: **{g95:.2f} ฿** | ดีเซล: **{dsl:.2f} ฿** ({diff_str})",
                inline=False
            )
    except Exception:
        pass

    embed.set_footer(text="ขอให้เป็นวันที่ดีและมีพลัง! | TD Bot")
    return embed

class BriefingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.scheduler_task: asyncio.Task = None

    async def cog_load(self):
        self.restart_scheduler()

    def cog_unload(self):
        if self.scheduler_task and not self.scheduler_task.done():
            self.scheduler_task.cancel()

    def restart_scheduler(self):
        if self.scheduler_task and not self.scheduler_task.done():
            self.scheduler_task.cancel()
        self.scheduler_task = asyncio.create_task(self.run_briefing_scheduler())

    async def send_daily_briefing(self):
        channel_id_str = get_setting("briefing_channel_id", "1544548008786530374")
        today_date_str = get_bangkok_now().strftime("%Y-%m-%d")

        last_sent_date = get_setting("briefing_last_sent_date")
        if last_sent_date == today_date_str:
            return

        channel_id = int(channel_id_str)
        channel = self.bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception:
                channel = None

        if channel:
            user_id_str = get_setting("briefing_target_user_id")
            user_id = int(user_id_str) if user_id_str else (self.bot.owner_id or 0)

            embed = await build_briefing_embed(user_id)
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
                    await target_msg.edit(embed=embed, view=WeatherDashboardView())
                except Exception:
                    target_msg = await channel.send(embed=embed, view=WeatherDashboardView())
                    set_setting(setting_key, str(target_msg.id))
            else:
                target_msg = await channel.send(embed=embed, view=WeatherDashboardView())
                set_setting(setting_key, str(target_msg.id))
            
            set_setting("briefing_last_sent_date", today_date_str)

    async def run_briefing_scheduler(self):
        await self.bot.wait_until_ready()
        try:
            while True:
                target_time_str = get_setting("briefing_time", "08:00")
                try:
                    h, m = map(int, target_time_str.strip().split(":"))
                except Exception:
                    h, m = 8, 0

                now = get_bangkok_now()
                target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)

                wait_sec = max((target - now).total_seconds(), 0.0)
                if wait_sec > 0:
                    await asyncio.sleep(wait_sec)

                await self.send_daily_briefing()
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass

    briefing_group = app_commands.Group(name="briefing", description="จัดการระบบสรุปภาพรวมยามเช้า (Daily Morning Briefing)")

    @briefing_group.command(name="now", description="ขอดูสรุปภาพรวมประจำวันทันที (พิกัดบ้านและที่ทำงาน)")
    @app_commands.describe(city="ระบุชื่อเมืองที่ต้องการเช็คเป็นกรณีพิเศษ (หากไม่ระบุจะแสดงทั้งบ้านและที่ทำงาน)")
    async def briefing_now(self, interaction: discord.Interaction, city: str = None):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        embed = await build_briefing_embed(interaction.user.id, city)
        await deliver_channel_card(interaction, embed, view=WeatherDashboardView())

    @app_commands.command(name="today", description="สรุปภาพรวมประจำวันยามเช้าทันที (คำสั่งย่อของ /briefing now)")
    @app_commands.describe(city="ระบุชื่อเมืองที่ต้องการเช็คเป็นกรณีพิเศษ (หากไม่ระบุจะแสดงทั้งบ้านและที่ทำงาน)")
    async def today(self, interaction: discord.Interaction, city: str = None):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        embed = await build_briefing_embed(interaction.user.id, city)
        await deliver_channel_card(interaction, embed, view=WeatherDashboardView())

    @briefing_group.command(name="set_channel", description="กำหนดช่องที่จะให้บอทส่งข้อความสรุปยามเช้าอัตโนมัติ")
    @app_commands.describe(channel="ห้อง Text Channel ที่ต้องการ")
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        set_setting("briefing_channel_id", str(channel.id))
        set_setting("briefing_target_user_id", str(interaction.user.id))
        embed = discord.Embed(
            title="✅ ตั้งค่าห้องรับรายงานยามเช้าเรียบร้อย",
            description=f"บอทจะส่ง Daily Briefing เข้าช่อง {channel.mention}",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @briefing_group.command(name="set_time", description="ตั้งเวลาส่งสรุปยามเช้า (รูปแบบ 24 ชม. เช่น 08:00)")
    @app_commands.describe(time="เวลาในรูปแบบ HH:MM เช่น 07:30, 08:00, 09:00")
    async def set_time(self, interaction: discord.Interaction, time: str):
        try:
            datetime.strptime(time.strip(), "%H:%M")
        except ValueError:
            embed = discord.Embed(
                title="⚠️ รูปแบบเวลาไม่ถูกต้อง",
                description="กรุณากรอกเวลาเป็นตัวเลข 24 ชม. ในรูปแบบ `HH:MM` เช่น `08:00` หรือ `07:30`",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        set_setting("briefing_time", time.strip())
        self.restart_scheduler()
        embed = discord.Embed(
            title="✅ ตั้งเวลาส่งสรุปยามเช้าเรียบร้อย",
            description=f"บอทจะส่ง Daily Briefing ทุกวันเวลา `{time.strip()}` น.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @briefing_group.command(name="set_home", description="ตั้งพิกัดบ้านสำหรับสรุปยามเช้า (ค่าเริ่มต้น: Bang Na สำหรับโซนแบริ่ง)")
    @app_commands.describe(city="ชื่อเขตหรือเมือง เช่น Bang Na, Samut Prakan")
    async def set_home(self, interaction: discord.Interaction, city: str):
        set_setting("briefing_home_city", city.strip())
        embed = discord.Embed(
            title="🏠 ตั้งพิกัดบ้านเรียบร้อย",
            description=f"กำหนดพิกัดบ้านสำหรับ Daily Briefing เป็น `{city.strip()}`",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @briefing_group.command(name="set_work", description="ตั้งพิกัดที่ทำงานสำหรับสรุปยามเช้า (ค่าเริ่มต้น: Lat Phrao สำหรับโซนลาดพร้าว)")
    @app_commands.describe(city="ชื่อเขตหรือเมือง เช่น Lat Phrao, Bangkok")
    async def set_work(self, interaction: discord.Interaction, city: str):
        set_setting("briefing_work_city", city.strip())
        embed = discord.Embed(
            title="🏢 ตั้งพิกัดที่ทำงานเรียบร้อย",
            description=f"กำหนดพิกัดที่ทำงานสำหรับ Daily Briefing เป็น `{city.strip()}`",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @briefing_group.command(name="set_city", description="ตั้งค่าเมืองหลักสำหรับพยากรณ์อากาศในสรุปยามเช้า")
    @app_commands.describe(city="ชื่อเมือง เช่น Bangkok, Chiang Mai, Phuket")
    async def set_city(self, interaction: discord.Interaction, city: str):
        set_setting("briefing_home_city", city.strip())
        set_setting("briefing_city", city.strip())
        embed = discord.Embed(
            title="✅ ตั้งค่าเมืองหลักเรียบร้อย",
            description=f"กำหนดเมืองสำหรับ Daily Briefing เป็น `{city.strip()}`",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(BriefingCog(bot))