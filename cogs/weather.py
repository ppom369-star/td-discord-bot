from datetime import datetime
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from database.db_manager import get_setting
from utils.dashboard import deliver_channel_card


WEATHER_CODE_MAP = {
    0: ("ท้องฟ้าแจ่มใส", "☀️"),
    1: ("ท้องฟ้าโปร่งเกือบทั้งหมด", "🌤️"),
    2: ("มีเมฆบางส่วน", "⛅"),
    3: ("มีเมฆครึ้ม", "☁️"),
    45: ("มีหมอก", "🌫️"),
    48: ("มีหมอกน้ำค้างแข็ง", "🌫️"),
    51: ("ฝนละอองเบา", "🌦️"),
    53: ("ฝนละอองปานกลาง", "🌦️"),
    55: ("ฝนละอองหนาแน่น", "🌧️"),
    61: ("ฝนตกเล็กน้อย", "🌧️"),
    63: ("ฝนตกปานกลาง", "🌧️"),
    65: ("ฝนตกหนัก", "🌧️"),
    71: ("หิมะตกเล็กน้อย", "❄️"),
    73: ("หิมะตกปานกลาง", "❄️"),
    75: ("หิมะตกหนัก", "❄️"),
    80: ("ฝนซู่ตกเบา", "🌧️"),
    81: ("ฝนซู่ตกปานกลาง", "🌧️"),
    82: ("ฝนซู่ตกหนักรุนแรง", "⛈️"),
    95: ("พายุฝนฟ้าคะนอง", "⛈️"),
    96: ("พายุฝนฟ้าคะนองพร้อมลูกเห็บเล็กน้อย", "⛈️"),
    99: ("พายุฝนฟ้าคะนองพร้อมลูกเห็บรุนแรง", "⛈️")
}

def translate_weather_code(code: int) -> tuple[str, str]:
    return WEATHER_CODE_MAP.get(code, ("ไม่ระบุสภาพอากาศ", "🌡️"))

def evaluate_air_quality(pm25: float, aqi: int) -> dict:
    if aqi <= 50 or pm25 <= 15.0:
        return {
            "status": "อากาศดีมาก (Good) 🟢",
            "badge": "🟢 ดีมาก",
            "color": discord.Color.from_rgb(16, 185, 129),
            "outdoor": "🏃 ทำกิจกรรมกลางแจ้งและออกกำลังกายได้ตามปกติ",
            "mask": "😷 ไม่จำเป็นต้องใส่หน้ากากอนามัยป้องกันฝุ่น",
            "meaning": "คุณภาพอากาศดีมาก ไม่มีผลกระทบต่อสุขภาพ เหมาะแก่การเปิดหน้าต่างระบายอากาศ"
        }
    if aqi <= 100 or pm25 <= 25.0:
        return {
            "status": "คุณภาพปานกลาง (Moderate) 🟡",
            "badge": "🟡 ปานกลาง",
            "color": discord.Color.from_rgb(245, 158, 11),
            "outdoor": "🚶 คนทั่วไปใช้ชีวิตได้ตามปกติ (หากเริ่มระคายเคืองควรเข้าที่ร่ม)",
            "mask": "😷 กลุ่มเสี่ยง (ภูมิแพ้/หอบหืด/เด็ก/ผู้สูงอายุ) ควรพกหน้ากาก",
            "meaning": "คุณภาพอากาศยอมรับได้ คนทั่วไปไม่กระทบ แต่กลุ่มแพ้ง่ายอาจเริ่มมีอาการระคายเคืองตาหรือจมูก"
        }
    if aqi <= 150 or pm25 <= 37.5:
        return {
            "status": "เริ่มมีผลกระทบต่อสุขภาพ (Sensitive Alert) 🟠",
            "badge": "🟠 เริ่มกระทบ",
            "color": discord.Color.from_rgb(249, 115, 22),
            "outdoor": "⚠️ ควรลดเวลาหรือเลี่ยงการออกกำลังกายหนักกลางแจ้ง",
            "mask": "😷 แนะนำให้สวมหน้ากากป้องกันฝุ่น (N95 หรือ KF94)",
            "meaning": "ฝุ่นเริ่มสะสมหนาแน่น กลุ่มเสี่ยงจะเริ่มมีอาการชัดเจน ควรปิดหน้าต่างและเปิดเครื่องฟอกอากาศ"
        }
    if aqi <= 200 or pm25 <= 75.0:
        return {
            "status": "มีผลกระทบต่อสุขภาพ (Unhealthy) 🔴",
            "badge": "🔴 อากาศแย่",
            "color": discord.Color.from_rgb(239, 68, 68),
            "outdoor": "🚫 ควรงดกิจกรรมกลางแจ้งทุกชนิด",
            "mask": "😷 ต้องสวมหน้ากาก N95 ตลอดเวลาเมื่อออกนอกอาคาร",
            "meaning": "ทุกคนเริ่มมีผลกระทบต่อระบบทางเดินหายใจ แสบคอ หายใจติดขัด ควรอยู่ในห้องปิดและเปิดเครื่องฟอกอากาศ"
        }
    return {
        "status": "อันตรายต่อสุขภาพ (Hazardous) 🟣",
        "badge": "🟣 อันตราย",
        "color": discord.Color.from_rgb(139, 92, 246),
        "outdoor": "⛔ งดออกนอกอาคารโดยเด็ดขาด",
        "mask": "😷 ต้องสวมหน้ากาก N95 มิดชิดเท่านั้น",
        "meaning": "ระดับมลพิษขั้นวิกฤต เป็นอันตรายร้ายแรงต่อทุกคน ควรปิดประตูหน้าต่างให้มิดชิดที่สุด"
    }

def analyze_weather_forecast(hourly: dict, daily: dict) -> dict:
    times = hourly.get("time", [])
    probs = hourly.get("precipitation_probability", [])
    precips = hourly.get("precipitation", [])

    rain_hours = []
    for t, p, pr in zip(times, probs, precips):
        hour_int = int(t.split("T")[1].split(":")[0])
        if p >= 40 or pr >= 0.2:
            rain_hours.append((hour_int, p, pr))

    if rain_hours:
        start_h = rain_hours[0][0]
        end_h = rain_hours[-1][0]
        max_p = max(item[1] for item in rain_hours)
        if start_h < 12:
            time_desc = "ช่วงเช้าถึงสาย"
        elif start_h < 16:
            time_desc = "ช่วงบ่ายถึงเย็น"
        elif start_h < 19:
            time_desc = "ช่วงเย็นถึงค่ำ"
        else:
            time_desc = "ช่วงดึก"
        rain_text = f"🌧️ มีโอกาสเกิดฝนตก{time_desc} ({start_h:02d}:00 - {end_h + 1:02d}:00 น.) โอกาสตกสูงสุด {max_p}% แนะนำพกร่มติดตัว"
    else:
        rain_text = "🌤️ วันนี้ไม่มีแนวโน้มฝนตก ท้องฟ้าโปร่งตลอดวัน"

    uv_max = daily.get("uv_index_max", [0])[0] or 0.0
    if uv_max >= 8.0:
        uv_text = f"☀️ รังสี UV สูงมาก (สูงสุดระดับ {uv_max:.1f} 🔴) แดดแผดเผา ควรทาครีมกันแดด SPF50+ และสวมแว่นกันแดด/หมวก"
    elif uv_max >= 6.0:
        uv_text = f"☀️ รังสี UV ค่อนข้างสูง (ระดับ {uv_max:.1f} 🟠) แนะนำทาครีมกันแดด SPF30+ หากต้องออกแดด"
    elif uv_max >= 3.0:
        uv_text = f"🌤️ รังสี UV ปานกลาง (ระดับ {uv_max:.1f} 🟡) แดดกำลังดี สวมแว่นกันแดดเมื่ออยู่กลางแจ้ง"
    else:
        uv_text = f"⛅ แดดอ่อน (UV {uv_max:.1f} 🟢) ท้องฟ้าครึ้ม ไม่ต้องกังวลเรื่องรังสีแดด"

    temp_max = daily.get("temperature_2m_max", [0])[0]
    temp_min = daily.get("temperature_2m_min", [0])[0]

    return {
        "rain_text": rain_text,
        "uv_text": uv_text,
        "temp_min": temp_min,
        "temp_max": temp_max,
        "uv_max": uv_max
    }

async def geocode_city(session: aiohttp.ClientSession, city: str) -> dict | None:
    geocode_url = "https://geocoding-api.open-meteo.com/v1/search"
    geocode_params = {
        "name": city,
        "count": 1,
        "language": "th",
        "format": "json"
    }
    async with session.get(geocode_url, params=geocode_params, timeout=10) as geo_res:
        if geo_res.status != 200:
            return None
        geo_data = await geo_res.json()
        results = geo_data.get("results")
        if not results:
            return None
        top_result = results[0]
        return {
            "latitude": top_result["latitude"],
            "longitude": top_result["longitude"],
            "location_name": top_result.get("name", city),
            "country": top_result.get("country", "")
        }

async def fetch_weather_report(city: str) -> dict | None:
    async with aiohttp.ClientSession() as session:
        geo = await geocode_city(session, city)
        if not geo:
            return None

        forecast_url = "https://api.open-meteo.com/v1/forecast"
        forecast_params = {
            "latitude": geo["latitude"],
            "longitude": geo["longitude"],
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
            "hourly": "temperature_2m,precipitation_probability,precipitation,uv_index",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max",
            "timezone": "auto",
            "forecast_days": 1
        }
        
        async with session.get(forecast_url, params=forecast_params, timeout=10) as forecast_res:
            if forecast_res.status != 200:
                return None
            forecast_data = await forecast_res.json()
            current = forecast_data.get("current")
            if not current:
                return None
            
            hourly = forecast_data.get("hourly", {})
            daily = forecast_data.get("daily", {})
            forecast_analysis = analyze_weather_forecast(hourly, daily)

            status_text, icon = translate_weather_code(current.get("weather_code", 0))
            return {
                "location": f"{geo['location_name']}, {geo['country']}".strip(", "),
                "city_name": geo["location_name"],
                "temperature": current.get("temperature_2m"),
                "apparent_temperature": current.get("apparent_temperature"),
                "humidity": current.get("relative_humidity_2m"),
                "wind_speed": current.get("wind_speed_10m"),
                "precipitation": current.get("precipitation"),
                "condition": status_text,
                "icon": icon,
                "forecast": forecast_analysis
            }

async def fetch_air_quality_report(city: str) -> dict | None:
    async with aiohttp.ClientSession() as session:
        geo = await geocode_city(session, city)
        if not geo:
            return None

        aq_url = "https://air-quality-api.open-meteo.com/v1/air-quality"
        aq_params = {
            "latitude": geo["latitude"],
            "longitude": geo["longitude"],
            "current": "pm10,pm2_5,us_aqi",
            "timezone": "auto"
        }

        async with session.get(aq_url, params=aq_params, timeout=10) as aq_res:
            if aq_res.status != 200:
                return None
            aq_data = await aq_res.json()
            current = aq_data.get("current")
            if not current:
                return None

            pm25 = float(current.get("pm2_5", 0.0))
            pm10 = float(current.get("pm10", 0.0))
            aqi = int(current.get("us_aqi", 0))
            eval_info = evaluate_air_quality(pm25, aqi)

            return {
                "location": f"{geo['location_name']}, {geo['country']}".strip(", "),
                "city_name": geo["location_name"],
                "pm25": pm25,
                "pm10": pm10,
                "aqi": aqi,
                "eval": eval_info
            }

def build_single_aqi_embed(aq_info: dict) -> discord.Embed:
    eval_info = aq_info["eval"]
    embed = discord.Embed(
        title=f"🌫️ คุณภาพอากาศ & ฝุ่น PM2.5 • {aq_info['location']}",
        description=f"**ระดับคุณภาพ:** {eval_info['status']}\n> *{eval_info['meaning']}*",
        color=eval_info["color"],
        timestamp=datetime.now()
    )
    embed.add_field(name="💨 ฝุ่น PM2.5", value=f"**{aq_info['pm25']}** μg/m³\n*(เกณฑ์ดี: ≤ 15.0)*", inline=True)
    embed.add_field(name="🌫️ ฝุ่น PM10", value=f"**{aq_info['pm10']}** μg/m³\n*(เกณฑ์ดี: ≤ 50.0)*", inline=True)
    embed.add_field(name="📊 ดัชนี US AQI", value=f"**{aq_info['aqi']}**\n*(เกณฑ์ดี: 0 - 50)*", inline=True)
    
    advice_text = (
        f"• {eval_info['outdoor']}\n"
        f"• {eval_info['mask']}"
    )
    embed.add_field(name="💡 คำแนะนำการดูแลสุขภาพ", value=advice_text, inline=False)
    embed.set_footer(text="Open-Meteo Air Quality API | อัปเดตล่าสุด")
    return embed

async def build_home_work_aqi_embed() -> discord.Embed:
    import asyncio
    home_city = get_setting("briefing_home_city", "Bang Na")
    work_city = get_setting("briefing_work_city", "Lat Phrao")

    home_aq, work_aq = await asyncio.gather(
        fetch_air_quality_report(home_city),
        fetch_air_quality_report(work_city)
    )

    primary_eval = work_aq["eval"] if work_aq else (home_aq["eval"] if home_aq else evaluate_air_quality(0, 0))

    embed = discord.Embed(
        title="🌫️ คุณภาพอากาศ & ฝุ่น PM2.5 (บ้าน & ที่ทำงาน)",
        description="เปรียบเทียบคุณภาพอากาศและค่าฝุ่นระหว่างจุดพักอาศัยและที่ทำงาน",
        color=primary_eval["color"],
        timestamp=datetime.now()
    )

    if home_aq:
        home_eval = home_aq["eval"]
        embed.add_field(
            name=f"🏠 บ้าน ({home_city}) — {home_eval['badge']}",
            value=(
                f"• PM2.5: **{home_aq['pm25']}** μg/m³ | US AQI: **{home_aq['aqi']}**\n"
                f"• สถานะ: {home_eval['status'].split('(')[0].strip()}"
            ),
            inline=False
        )
    else:
        embed.add_field(name=f"🏠 บ้าน ({home_city})", value="ไม่พบข้อมูลคุณภาพอากาศ", inline=False)

    if work_aq:
        work_eval = work_aq["eval"]
        embed.add_field(
            name=f"🏢 ที่ทำงาน ({work_city}) — {work_eval['badge']}",
            value=(
                f"• PM2.5: **{work_aq['pm25']}** μg/m³ | US AQI: **{work_aq['aqi']}**\n"
                f"• สถานะ: {work_eval['status'].split('(')[0].strip()}"
            ),
            inline=False
        )
    else:
        embed.add_field(name=f"🏢 ที่ทำงาน ({work_city})", value="ไม่พบข้อมูลคุณภาพอากาศ", inline=False)

    advice_eval = work_aq["eval"] if work_aq and work_aq["pm25"] >= (home_aq["pm25"] if home_aq else 0) else (home_aq["eval"] if home_aq else primary_eval)
    advice_text = (
        f"• {advice_eval['outdoor']}\n"
        f"• {advice_eval['mask']}\n"
        f"> *{advice_eval['meaning']}*"
    )
    embed.add_field(name="💡 คำแนะนำการปฏิบัติตัว", value=advice_text, inline=False)
    embed.set_footer(text="เกณฑ์ PM2.5: 🟢 ≤15 ดีมาก | 🟡 15-25 ปานกลาง | 🟠 25-37.5 เริ่มกระทบ | 🔴 >37.5 แย่")
    return embed

async def build_home_work_weather_embed() -> discord.Embed:
    import asyncio
    home_city = get_setting("briefing_home_city", "Bang Na")
    work_city = get_setting("briefing_work_city", "Lat Phrao")

    home_w, work_w = await asyncio.gather(
        fetch_weather_report(home_city),
        fetch_weather_report(work_city)
    )

    embed = discord.Embed(
        title="🌦️ สภาพอากาศและพยากรณ์ฝน (บ้าน & ที่ทำงาน)",
        description="พยากรณ์ช่วงเวลาฝนตก อุณหภูมิ และรังสี UV ประจำวัน",
        color=discord.Color.from_rgb(14, 165, 233),
        timestamp=datetime.now()
    )

    if home_w:
        h_fc = home_w["forecast"]
        embed.add_field(
            name=f"🏠 บ้าน ({home_city}) — {home_w['condition']} {home_w['icon']}",
            value=(
                f"• อุณหภูมิ: **{home_w['temperature']} °C** (รู้สึก **{home_w['apparent_temperature']} °C**)\n"
                f"• ช่วงวันนี้: ต่ำสุด **{h_fc['temp_min']} °C** / สูงสุด **{h_fc['temp_max']} °C**\n"
                f"• {h_fc['rain_text']}"
            ),
            inline=False
        )

    if work_w:
        w_fc = work_w["forecast"]
        embed.add_field(
            name=f"🏢 ที่ทำงาน ({work_city}) — {work_w['condition']} {work_w['icon']}",
            value=(
                f"• อุณหภูมิ: **{work_w['temperature']} °C** (รู้สึก **{work_w['apparent_temperature']} °C**)\n"
                f"• ช่วงวันนี้: ต่ำสุด **{w_fc['temp_min']} °C** / สูงสุด **{w_fc['temp_max']} °C**\n"
                f"• {w_fc['rain_text']}"
            ),
            inline=False
        )

    primary_w = work_w or home_w
    if primary_w:
        embed.add_field(
            name="☀️ ดัชนีรังสี UV & การป้องกันแดด",
            value=f"• {primary_w['forecast']['uv_text']}",
            inline=False
        )

    embed.set_footer(text="กดปุ่มด้านล่างเพื่อสลับหน้ารายงาน | Open-Meteo Forecast API")
    return embed

class WeatherDashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="สภาพอากาศ 🌦️", style=discord.ButtonStyle.success, custom_id="btn_weather_forecast")
    async def check_weather(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        embed = await build_home_work_weather_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="ตรวจฝุ่น PM2.5 🌫️", style=discord.ButtonStyle.secondary, custom_id="btn_weather_pm25")
    async def check_pm25(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        embed = await build_home_work_aqi_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="สรุปภาพรวมเช้า ☀️", style=discord.ButtonStyle.primary, custom_id="btn_weather_briefing")
    async def refresh_briefing(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        from cogs.briefing import build_briefing_embed
        embed = await build_briefing_embed(interaction.user.id)
        await interaction.edit_original_response(embed=embed, view=self)

class WeatherCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="weather", description="เช็คสภาพอากาศและพยากรณ์ล่วงหน้าของเมืองที่ต้องการ")
    @app_commands.describe(city="ชื่อเมือง หรือ จังหวัด เช่น Bangkok, Lat Phrao, Bang Na")
    async def weather(self, interaction: discord.Interaction, city: str):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        weather_info = await fetch_weather_report(city)
        if not weather_info:
            embed = discord.Embed(
                title="ไม่พบข้อมูลเมืองที่ระบุ",
                description=f"ไม่สามารถค้นหาข้อมูลสภาพอากาศสำหรับ `{city}` ได้ กรุณาตรวจสอบการสะกดชื่อเมือง",
                color=discord.Color.from_rgb(239, 68, 68)
            )
            await deliver_channel_card(interaction, embed, view=WeatherDashboardView())
            return

        forecast = weather_info["forecast"]
        embed = discord.Embed(
            title=f"{weather_info['icon']} สภาพอากาศ & พยากรณ์วันนี้ • {weather_info['location']}",
            description=f"**ขณะนี้:** {weather_info['condition']} (อุณหภูมิ {weather_info['temperature']} °C / รู้สึก {weather_info['apparent_temperature']} °C)",
            color=discord.Color.from_rgb(14, 165, 233),
            timestamp=datetime.now()
        )
        embed.add_field(name="🔮 พยากรณ์ฝนวันนี้", value=forecast["rain_text"], inline=False)
        embed.add_field(name="☀️ รังสี UV & แดด", value=forecast["uv_text"], inline=False)
        embed.add_field(name="🌡️ อุณหภูมิวันนี้", value=f"ต่ำสุด **{forecast['temp_min']} °C** / สูงสุด **{forecast['temp_max']} °C**", inline=True)
        embed.add_field(name="💧 ความชื้น", value=f"{weather_info['humidity']}%", inline=True)
        embed.add_field(name="💨 ความเร็วลม", value=f"{weather_info['wind_speed']} km/h", inline=True)
        embed.set_footer(text="Open-Meteo Forecast API | อัปเดตล่าสุด")

        await deliver_channel_card(interaction, embed, view=WeatherDashboardView())

    @app_commands.command(name="pm25", description="เช็คค่าฝุ่น PM2.5 และคุณภาพอากาศปัจจุบัน")
    @app_commands.describe(city="ชื่อเมือง หรือ เขต เช่น Bangkok, Lat Phrao, Bang Na, Samut Prakan")
    async def pm25(self, interaction: discord.Interaction, city: str = "Bangkok"):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        aq_info = await fetch_air_quality_report(city)
        if not aq_info:
            embed = discord.Embed(
                title="ไม่พบข้อมูลคุณภาพอากาศ",
                description=f"ไม่สามารถค้นหาข้อมูลดัชนีอากาศสำหรับ `{city}` ได้",
                color=discord.Color.from_rgb(239, 68, 68)
            )
            await deliver_channel_card(interaction, embed, view=WeatherDashboardView())
            return

        embed = build_single_aqi_embed(aq_info)
        await deliver_channel_card(interaction, embed, view=WeatherDashboardView())

async def setup(bot: commands.Bot):
    await bot.add_cog(WeatherCog(bot))