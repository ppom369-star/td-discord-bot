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
    "matic": "matic-network",
    "pol": "matic-network"
}

BINANCE_SYMBOL_MAP = {
    "btc": "BTCUSDT", "bitcoin": "BTCUSDT",
    "eth": "ETHUSDT", "ethereum": "ETHUSDT",
    "sol": "SOLUSDT", "solana": "SOLUSDT",
    "bnb": "BNBUSDT", "binancecoin": "BNBUSDT",
    "xrp": "XRPUSDT", "ripple": "XRPUSDT",
    "doge": "DOGEUSDT", "dogecoin": "DOGEUSDT",
    "ada": "ADAUSDT", "cardano": "ADAUSDT",
    "avax": "AVAXUSDT", "dot": "DOTUSDT",
    "matic": "POLUSDT", "pol": "POLUSDT", "matic-network": "POLUSDT"
}

def resolve_coin_id(user_input: str) -> str:
    cleaned = user_input.strip().lower()
    return CRYPTO_ALIAS_MAP.get(cleaned, cleaned)

async def fetch_crypto_price(coin: str) -> dict | None:
    cleaned = coin.strip().lower()
    binance_symbol = BINANCE_SYMBOL_MAP.get(cleaned, f"{cleaned.upper()}USDT")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={binance_symbol}"
            async with session.get(url, timeout=6) as resp:
                if resp.status == 200:
                    d = await resp.json()
                    usd = float(d["lastPrice"])
                    change = float(d["priceChangePercent"])
                    thb_rate = 34.5
                    try:
                        async with session.get("https://open.er-api.com/v6/latest/USD", timeout=3) as r_fx:
                            if r_fx.status == 200:
                                fx_data = await r_fx.json()
                                thb_rate = fx_data.get("rates", {}).get("THB", 34.5)
                    except Exception:
                        pass

                    return {
                        "coin": coin.upper(),
                        "usd": usd,
                        "thb": round(usd * thb_rate, 2),
                        "change_24h_pct": change,
                        "source": "Binance"
                    }
        except Exception:
            pass

        coin_id = resolve_coin_id(coin)
        try:
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {
                "ids": coin_id,
                "vs_currencies": "usd,thb",
                "include_24hr_change": "true"
            }
            async with session.get(url, params=params, timeout=8) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    coin_data = data.get(coin_id)
                    if coin_data:
                        return {
                            "coin": coin.upper(),
                            "usd": coin_data.get("usd", 0.0),
                            "thb": coin_data.get("thb", 0.0),
                            "change_24h_pct": coin_data.get("usd_24h_change", 0.0),
                            "source": "CoinGecko"
                        }
        except Exception:
            pass

    return None

class FinanceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="crypto", description="เช็คราคาเหรียญคริปโตเคอร์เรนซีปัจจุบัน")
    @app_commands.describe(coin="ชื่อย่อหรือชื่อเหรียญ เช่น btc, eth, sol, doge, bitcoin")
    async def crypto(self, interaction: discord.Interaction, coin: str):
        if not interaction.response.is_done():
            await interaction.response.defer()

        result = await fetch_crypto_price(coin)
        if not result:
            embed = discord.Embed(
                title="❌ ไม่พบข้อมูลเหรียญ",
                description=f"ไม่สามารถค้นหาข้อมูลราคาสำหรับ `{coin}` ได้ในขณะนี้ กรุณาลองใช้ชื่อย่อ เช่น `btc`, `eth`, `sol`, `doge`",
                color=discord.Color.red()
            )
            await deliver_channel_card(interaction, embed)
            return

        price_usd = result["usd"]
        price_thb = result["thb"]
        change_24h = result["change_24h_pct"]
        source = result.get("source", "Crypto Feed")

        change_sign = "📈 +" if change_24h >= 0 else "📉 "
        embed_color = discord.Color.green() if change_24h >= 0 else discord.Color.red()

        embed = discord.Embed(
            title=f"🪙 ราคาเหรียญ {result['coin']}",
            color=embed_color
        )
        embed.add_field(name="💵 ราคา (USD)", value=f"${price_usd:,.2f}" if price_usd >= 1 else f"${price_usd:,.6f}", inline=True)
        embed.add_field(name="🇹🇭 ราคา (THB)", value=f"฿{price_thb:,.2f}" if price_thb >= 1 else f"฿{price_thb:,.6f}", inline=True)
        embed.add_field(name="📊 การเปลี่ยนแปลง 24 ชม.", value=f"{change_sign}{change_24h:.2f}%", inline=True)
        embed.set_footer(text=f"ข้อมูลแบบเรียลไทม์จาก {source}")
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
