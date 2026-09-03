import json
from datetime import datetime
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from database.db_manager import get_setting, set_setting
from utils.dashboard import deliver_channel_card

FUEL_CHANNEL_ID = 1544575570380197888

async def fetch_fuel_prices() -> dict | None:
    url = "https://oil-price.bangchak.co.th/ApiOilPrice2/en"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=10) as response:
                if response.status != 200:
                    return None
                data = await response.json()
                if not data or not isinstance(data, list):
                    return None
                record = data[0]
                oil_list = json.loads(record.get("OilList", "[]"))
                
                fuels = {}
                for item in oil_list:
                    name = item.get("OilName", "")
                    fuels[name] = {
                        "today": float(item.get("PriceToday", 0)),
                        "tomorrow": float(item.get("PriceTomorrow", 0)),
                        "diff": float(item.get("PriceDifTomorrow", 0))
                    }
                return {
                    "effective_text": record.get("OilRemark2", ""),
                    "fuels": fuels
                }
        except Exception:
            return None

def build_fuel_embed(fuel_data: dict) -> discord.Embed:
    fuels = fuel_data.get("fuels", {})
    
    g95 = fuels.get("Gasohol 95 S EVO", {})
    g91 = fuels.get("Gasohol 91 S EVO", {})
    e20 = fuels.get("Gasohol E20 S EVO", {})
    diesel = fuels.get("Hi Diesel S", {})
    premium98 = fuels.get("Hi Premium 98 Plus", {})

    diff = g95.get("diff", 0.0) or diesel.get("diff", 0.0)
    
    if diff > 0:
        alert_status = f"🚨 **แจ้งเตือน:** พรุ่งนี้ราคาน้ำมันปรับขึ้น **+{diff:.2f} บาท/ลิตร** (แนะนำเติมก่อนเที่ยงคืน)"
        embed_color = discord.Color.from_rgb(239, 68, 68)
    elif diff < 0:
        alert_status = f"🟢 **ข่าวดี:** พรุ่งนี้ราคาน้ำมันปรับลดลง **{diff:.2f} บาท/ลิตร** (รอเติมพรุ่งนี้เช้า)"
        embed_color = discord.Color.from_rgb(16, 185, 129)
    else:
        alert_status = "⚪ **สถานะ:** พรุ่งนี้ราคาน้ำมันยังคงเดิม ไม่มีการเปลี่ยนแปลง"
        embed_color = discord.Color.from_rgb(245, 158, 11)

    embed = discord.Embed(
        title="⛽ ราคาน้ำมันวันนี้ • บางจาก (Bangchak)",
        description=f"> {alert_status}",
        color=embed_color,
        timestamp=datetime.now()
    )

    def format_price_line(item: dict) -> str:
        today_p = item.get("today", 0.0)
        diff_p = item.get("diff", 0.0)
        if diff_p > 0:
            change_badge = f" (พรุ่งนี้: **{today_p + diff_p:.2f}** 🔺 +{diff_p:.2f})"
        elif diff_p < 0:
            change_badge = f" (พรุ่งนี้: **{today_p + diff_p:.2f}** 🔻 {diff_p:.2f})"
        else:
            change_badge = " (พรุ่งนี้: คงเดิม)"
        return f"**{today_p:.2f}** บาท/ลิตร{change_badge}"

    if g95:
        embed.add_field(name="🟢 แก๊สโซฮอล์ 95 (Gasohol 95)", value=format_price_line(g95), inline=False)
    if g91:
        embed.add_field(name="🟡 แก๊สโซฮอล์ 91 (Gasohol 91)", value=format_price_line(g91), inline=False)
    if e20:
        embed.add_field(name="🔵 แก๊สโซฮอล์ E20 (Gasohol E20)", value=format_price_line(e20), inline=False)
    if diesel:
        embed.add_field(name="🔴 ดีเซล (Hi Diesel S)", value=format_price_line(diesel), inline=False)
    if premium98:
        embed.add_field(name="🟣 พรีเมียม 98 (Premium 98)", value=format_price_line(premium98), inline=False)

    embed.set_footer(text="ข้อมูลตรงจาก Bangchak Oil Price API | กดปุ่มด้านล่างเพื่ออัปเดต")
    return embed

class FuelDashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="อัปเดตราคาล่าสุด ⛽", style=discord.ButtonStyle.primary, custom_id="btn_fuel_refresh")
    async def refresh_fuel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        fuel_data = await fetch_fuel_prices()
        if not fuel_data:
            await interaction.followup.send("⚠️ ไม่สามารถเชื่อมต่อ Bangchak Oil API ได้ในขณะนี้", ephemeral=True)
            return
        embed = build_fuel_embed(fuel_data)
        await deliver_channel_card(interaction, embed, view=self)

class FuelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="oil", description="เช็คราคาน้ำมันวันนี้และตรวจสอบแนวโน้มการปรับราคาพรุ่งนี้")
    async def oil(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        fuel_data = await fetch_fuel_prices()
        if not fuel_data:
            embed = discord.Embed(
                title="⚠️ ไม่สามารถดึงข้อมูลราคาน้ำมันได้",
                description="ไม่สามารถเชื่อมต่อ Bangchak Oil API ได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง",
                color=discord.Color.red()
            )
            await deliver_channel_card(interaction, embed)
            return

        embed = build_fuel_embed(fuel_data)
        await deliver_channel_card(interaction, embed, view=FuelDashboardView())

async def setup(bot: commands.Bot):
    await bot.add_cog(FuelCog(bot))
