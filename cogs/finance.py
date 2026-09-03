import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from utils.dashboard import deliver_channel_card

CRYPTO_ALIAS_MAP = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "bnb": "binancecoin",
    "xrp": "ripple",
    "doge": "dogecoin",
    "ada": "cardano",
    "avax": "avalanche-2",
    "dot": "polkadot",
    "matic": "matic-network"
}

def resolve_coin_id(user_input: str) -> str:
    cleaned = user_input.strip().lower()
    return CRYPTO_ALIAS_MAP.get(cleaned, cleaned)

class FinanceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="crypto", description="เช็คราคาเหรียญคริปโตเคอร์เรนซีปัจจุบัน")
    @app_commands.describe(coin="ชื่อย่อหรือชื่อเหรียญ เช่น btc, eth, sol, doge, bitcoin")
    async def crypto(self, interaction: discord.Interaction, coin: str):
        if not interaction.response.is_done():
            await interaction.response.defer()
        coin_id = resolve_coin_id(coin)
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": coin_id,
            "vs_currencies": "usd,thb",
            "include_24hr_change": "true"
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params, timeout=10) as response:
                    if response.status != 200:
                        embed = discord.Embed(
                            title="⚠️ ไม่สามารถดึงราคาได้",
                            description="เกิดข้อผิดพลาดในการเชื่อมต่อ CoinGecko API ชั่วคราว",
                            color=discord.Color.red()
                        )
                        await deliver_channel_card(interaction, embed)
                        return

                    data = await response.json()
                    coin_data = data.get(coin_id)
                    if not coin_data:
                        embed = discord.Embed(
                            title="❌ ไม่พบเหรียญที่ระบุ",
                            description=f"ไม่พบข้อมูลสำหรับเหรียญ `{coin}` กรุณาลองใช้ชื่อย่อ เช่น `btc`, `eth`, `sol`",
                            color=discord.Color.red()
                        )
                        await deliver_channel_card(interaction, embed)
                        return

                    price_usd = coin_data.get("usd", 0)
                    price_thb = coin_data.get("thb", 0)
                    change_24h = coin_data.get("usd_24h_change", 0)
                    
                    change_sign = "📈 +" if change_24h >= 0 else "📉 "
                    embed_color = discord.Color.green() if change_24h >= 0 else discord.Color.red()

                    embed = discord.Embed(
                        title=f"🪙 ราคาเหรียญ {coin.upper()}",
                        color=embed_color
                    )
                    embed.add_field(name="💵 ราคา (USD)", value=f"${price_usd:,.2f}" if price_usd >= 1 else f"${price_usd:,.6f}", inline=True)
                    embed.add_field(name="🇹🇭 ราคา (THB)", value=f"฿{price_thb:,.2f}" if price_thb >= 1 else f"฿{price_thb:,.6f}", inline=True)
                    embed.add_field(name="📊 การเปลี่ยนแปลง 24 ชม.", value=f"{change_sign}{change_24h:.2f}%", inline=True)
                    embed.set_footer(text="ข้อมูลจาก CoinGecko")
                    await deliver_channel_card(interaction, embed)

            except Exception as err:
                embed = discord.Embed(
                    title="❌ เกิดข้อผิดพลาด",
                    description=str(err),
                    color=discord.Color.red()
                )
                await deliver_channel_card(interaction, embed)

    @app_commands.command(name="rate", description="คำนวณและแปลงอัตราแลกเปลี่ยนสกุลเงิน")
    @app_commands.describe(
        from_curr="สกุลเงินต้นทาง เช่น USD, THB, JPY, EUR",
        to_curr="สกุลเงินปลายทาง เช่น THB, USD, JPY, EUR",
        amount="จำนวนเงินที่ต้องการแปลง (ค่าเริ่มต้นคือ 1)"
    )
    async def rate(self, interaction: discord.Interaction, from_curr: str, to_curr: str, amount: float = 1.0):
        if not interaction.response.is_done():
            await interaction.response.defer()
        base = from_curr.strip().upper()
        target = to_curr.strip().upper()

        if amount <= 0:
            embed = discord.Embed(
                title="⚠️ จำนวนเงินไม่ถูกต้อง",
                description="จำนวนเงินต้องมากกว่า 0",
                color=discord.Color.red()
            )
            await deliver_channel_card(interaction, embed)
            return

        url = f"https://open.er-api.com/v6/latest/{base}"

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, timeout=10) as response:
                    if response.status != 200:
                        embed = discord.Embed(
                            title="⚠️ ตรวจสอบอัตราแลกเปลี่ยนไม่สำเร็จ",
                            description="ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์อัตราแลกเปลี่ยนได้ในขณะนี้",
                            color=discord.Color.red()
                        )
                        await deliver_channel_card(interaction, embed)
                        return

                    data = await response.json()
                    if data.get("result") != "success":
                        embed = discord.Embed(
                            title="❌ ไม่พบสกุลเงินต้นทาง",
                            description=f"ไม่พบสกุลเงิน `{base}` ในระบบ",
                            color=discord.Color.red()
                        )
                        await deliver_channel_card(interaction, embed)
                        return

                    rates = data.get("rates", {})
                    target_rate = rates.get(target)
                    if not target_rate:
                        embed = discord.Embed(
                            title="❌ ไม่พบสกุลเงินปลายทาง",
                            description=f"ไม่พบสกุลเงิน `{target}` ในระบบ",
                            color=discord.Color.red()
                        )
                        await deliver_channel_card(interaction, embed)
                        return

                    converted_value = amount * target_rate
                    embed = discord.Embed(
                        title="💱 อัตราแลกเปลี่ยนเงินตรา",
                        description=f"**{amount:,.2f} {base}** = **{converted_value:,.2f} {target}**",
                        color=discord.Color.gold()
                    )
                    embed.add_field(name="เรทราคา", value=f"1 {base} = {target_rate:,.4f} {target}", inline=True)
                    embed.set_footer(text=f"อัปเดตล่าสุด: {data.get('time_last_update_utc', 'N/A')}")
                    await deliver_channel_card(interaction, embed)

            except Exception as err:
                embed = discord.Embed(
                    title="❌ เกิดข้อผิดพลาด",
                    description=str(err),
                    color=discord.Color.red()
                )
                await deliver_channel_card(interaction, embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(FinanceCog(bot))
