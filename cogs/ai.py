import os
import json
import asyncio
import re
import urllib.parse
from datetime import datetime, timedelta
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from database.db_manager import (
    add_ai_chat_message,
    get_ai_chat_history,
    clear_ai_chat_history,
    get_setting,
    set_setting,
    get_bangkok_now
)
from utils.ai_tools import execute_ai_tool

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
FALLBACK_MODELS = [
    "gemini-3.8-flash",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-pro-latest"
]

def build_system_instruction() -> str:
    now = get_bangkok_now()
    now_str = f"วัน{now.strftime('%A')}ที่ {now.strftime('%d/%m/%Y')} (พ.ศ. {now.year + 543}) เวลา {now.strftime('%H:%M')} น."
    return f"""คุณคือผู้ช่วย AI อัจฉริยะประจำตัวบน Discord (TD Bot)
บริบทเวลาปัจจุบัน: วันนี้คือ{now_str} (ปี ค.ศ. {now.year} / พ.ศ. {now.year + 543})
คุณรอบรู้ เข้าใจภาษาไทยเป็นอย่างดี สุภาพ เป็นกันเอง และมีความรู้ความเข้าใจในระบบและคำสั่งทั้งหมดของบอทอย่างลึกซึ้ง

ระบบและเครื่องมือที่คุณสามารถเรียกใช้งานได้ (Internal Tools):
1. get_fuel_price: เช็คราคาน้ำมันวันนี้และแนวโน้มการปรับราคาพรุ่งนี้ (Gasohol 95, 91, E20, Diesel, Premium 98) จาก Bangchak API โดยตรง ไม่ต้องมี parameters
2. youtube_add: เพิ่มช่อง YouTube เข้าสู่ระบบแจ้งเตือนคลิปใหม่และ Shorts (args: {{"channel_url_or_id": "URL หรือ ID ช่อง"}})
   *หมายเหตุ: หากผู้ใช้บอกให้เพิ่มช่อง YouTube แต่ยังไม่ได้ระบุลิงก์หรือ ID ช่อง ให้ตอบถามขอลิงก์ใน "reply" โดยไม่ต้องเรียก tool*
3. youtube_list: ดูรายชื่อช่อง YouTube ทั้งหมดที่เซิร์ฟเวอร์นี้ติดตาม
4. youtube_remove: ลบช่อง YouTube ออกจากการติดตาม (args: {{"channel_id_or_title": "ID หรือชื่อช่อง"}})
5. get_weather: ดูสภาพอากาศ อุณหภูมิ และพยากรณ์ฝน (args: {{"city": "ชื่อเมือง เช่น Bangkok, Chiang Mai, Lat Phrao"}})
6. get_air_quality: ตรวจสอบค่าฝุ่น PM2.5 และดัชนี AQI พร้อมคำแนะนำสุขภาพ (args: {{"city": "ชื่อเมือง"}})
7. get_daily_briefing: สรุปภาพรวมยามเช้า (สภาพอากาศบ้าน/ที่ทำงาน, งาน To-do ค้าง, ราคาน้ำมัน)
8. get_crypto_price: เช็คราคาเหรียญคริปโตเคอร์เรนซี (args: {{"coin": "เช่น btc, eth, sol, doge"}})
9. get_exchange_rate: คำนวณอัตราแลกเปลี่ยนเงินตรา (args: {{"from_currency": "USD", "to_currency": "THB", "amount": 100}})
10. record_expense: บันทึกรายรับ/รายจ่าย (args: {{"type": "expense" หรือ "income", "amount": 100.0, "category": "อาหาร"|"เดินทาง"|"ช้อปปิ้ง"|"สกินแคร์"|"เกม"|"หนังสือ"|"บิล"|"เงินเดือน"|"ทั่วไป", "note": "รายละเอียด"}})
11. get_expense_summary: สรุปยอดรายรับ-รายจ่าย ประจำเดือนปัจจุบัน
12. add_todo: เพิ่มงานที่ต้องทำใน To-do (args: {{"task": "ข้อความงาน"}})
13. get_todo_list: ดูรายการสิ่งที่ต้องทำ (args: {{"status": "pending"|"done"|"all"}})
14. complete_todo: เช็คงาน To-do ว่าทำเสร็จแล้ว (args: {{"todo_id": 1}})
15. delete_todo: ลบงาน To-do (args: {{"todo_id": 1}})
16. set_reminder: ตั้งเวลาเตือนความจำ (args: {{"time_str": "เช่น 10m, 30m, 1h", "message": "ข้อความที่จะเตือน"}})
17. add_memo: บันทึกโน้ตสั้น (args: {{"title": "หัวข้อ", "content": "เนื้อหา"}})
18. get_memos: ดูโน้ตที่บันทึกไว้
19. get_system_status: เช็คสถานะระบบของบอท (Uptime, RAM, Latency)
20. stream_follow: ติดตามสตรีมเมอร์ Twitch (args: {{"channel_login": "ชื่อช่อง"}})
21. stream_list: ดูรายชื่อ Twitch ที่ติดตาม
22. stream_unfollow: ยกเลิกติดตาม Twitch (args: {{"channel_login": "ชื่อช่อง"}})
23. search_web: ค้นหาข้อมูลอินเทอร์เน็ตสดๆ จากภายนอก ข่าวสาร บุคคลสำคัญ เหตุการณ์ปัจจุบัน หรือเรื่องทั่วไปที่อาจเปลี่ยนแปลงตามกาลเวลา (args: {{"query": "คำค้นหาที่สั้นกระชับ ตรงประเด็น"}})

โครงสร้าง JSON ที่คุณต้องส่งกลับเท่านั้น:
{{
  "tool_calls": [
    {{
      "tool": "ชื่อเครื่องมือ",
      "args": {{ ... }}
    }}
  ],
  "reply": "ข้อความตอบกลับผู้ใช้ หรือคำตอบสุดท้าย หรือข้อความสอบถามข้อมูลเพิ่มเติม"
}}

กฎเหล็กสำคัญ:
1. หากคำถามตรงกับเครื่องมือระบบ ให้เรียกเครื่องมือนั้นเสมอ ห้ามเรียก search_web:
   - ราคาน้ำมัน: "get_fuel_price"
   - สภาพอากาศ/ฝน: "get_weather"
   - ฝุ่น PM2.5: "get_air_quality"
   - ราคาคริปโต: "get_crypto_price"
   - อัตราแลกเปลี่ยนเงิน: "get_exchange_rate"
   - รายรับรายจ่าย: "record_expense" หรือ "get_expense_summary"
   - สิ่งที่ต้องทำ (To-do): "add_todo" หรือ "get_todo_list"
2. ข้อห้ามเด็ดขาด (ห้ามเรียก search_web):
   - คำถามความรู้ทั่วไป, วิทยาศาสตร์, ข้อเท็จจริงทั่วไป, การแพทย์เบื้องต้น
   - การให้คำแนะนำหรือวิเคราะห์สกินแคร์ (เช่น รูทีนสำหรับผิวมัน, ส่วนผสม Niacinamide, Retinol, Ceramide) เนื่องจากคุณมีความรู้เรื่องนี้อย่างลึกซึ้งอยู่แล้ว
   - การแปลภาษา, เขียนโปรแกรม/โค้ด, คำนวณคณิตศาสตร์, แต่งกลอน, คิดแคปชัน
   - การทักทาย, ชวนคุยทั่วไป, หรือคำถามต่อเนื่องที่บริบทเดิมมีคำตอบอยู่แล้ว
   ในกรณีเหล่านี้ ให้ส่ง "tool_calls": [] และตอบกลับใน "reply" ทันที เพื่อความรวดเร็วสูงสุด
3. อนุญาตให้เรียก "search_web" เฉพาะกรณีเหล่านี้เท่านั้น:
   - ข้อมูลสดที่มีเงื่อนไขเวลาชัดเจน (เช่น "วันนี้", "ล่าสุด", "ปี 2568/2026", "เมื่อวาน")
   - ข้อมูลราคาตั๋วเครื่องบิน, ราคาบัตรคอนเสิร์ต, วันเปิดจองบัตร, ผังคอนเสิร์ต
   - ข่าวด่วน, ผลการแข่งขันล่าสุด, ผู้ดำรงตำแหน่งในปัจจุบัน (เช่น นายกฯ, ผู้ว่าฯ, CEO)
4. เมื่อสร้าง query สำหรับ "search_web" ให้ใช้คีย์เวิร์ดสั้นกระชับ ตรงประเด็น (เช่น "ตั๋วเครื่องบิน ญี่ปุ่น สงกรานต์", "OpenAI CEO", "ผลบอลพรีเมียร์ลีกล่าสุด") ห้ามใส่คำฟุ่มเฟือย
5. หากมี [ผลลัพธ์จากเครื่องมือระบบ หรือ การค้นหาเว็บสดๆ] ส่งมาให้ ให้นำข้อมูลนั้นมาเป็นข้อเท็จจริงสูงสุด (Ground Truth) ในการตอบคำถาม ห้ามตอบขัดแย้งกับผลลัพธ์สดที่ได้เด็ดขาด และห้ามใช้ข้อมูลเก่าจากความจำของตนเองหากผลการค้นหาให้ข้อมูลที่เป็นปัจจุบันกว่า หากผลการค้นหาแจ้งว่า error หรือหาไม่พบ ให้ตอบว่าไม่สามารถค้นหาข้อมูลได้ในขณะนี้และแนะนำให้ลองใหม่อีกครั้ง ห้ามเดาหรือแต่งข้อมูลขึ้นเองเด็ดขาด
"""

async def call_gemini_api(session: aiohttp.ClientSession, user_prompt: str, history: list[dict] = None, tool_context: str = "") -> dict | None:
    if not GEMINI_API_KEY:
        return {"error": "ไม่พบ GEMINI_API_KEY ในไฟล์ .env"}

    contents = []
    if history:
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg["content"]}]
            })

    current_text = user_prompt
    if tool_context:
        current_text += f"\n\n[ผลลัพธ์จากเครื่องมือระบบ หรือ การค้นหาเว็บสดๆ]:\n{tool_context}\n\n(นำข้อมูลสดด้านบนมาตอบผู้ใช้เป็นภาษาไทยอย่างกระชับ สุภาพ ถูกต้อง ชัดเจน ห้ามใช้ข้อมูลเก่าจากความจำตนเองเด็ดขาด)"

    contents.append({
        "role": "user",
        "parts": [{"text": current_text}]
    })

    payload = {
        "system_instruction": {
            "parts": [{"text": build_system_instruction()}]
        },
        "contents": contents,
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1
        }
    }

    last_error = None
    for model_name in FALLBACK_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        try:
            async with session.post(url, json=payload, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text_res = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        try:
                            return json.loads(text_res)
                        except json.JSONDecodeError:
                            cleaned = re.sub(r"^```json\s*", "", text_res.strip(), flags=re.MULTILINE)
                            cleaned = re.sub(r"^```\s*$", "", cleaned.strip(), flags=re.MULTILINE)
                            return json.loads(cleaned)
                elif resp.status in (429, 503, 404):
                    last_error = f"Model {model_name} returned status {resp.status}"
                    await asyncio.sleep(0.5)
                    continue
                else:
                    err_txt = await resp.text()
                    last_error = f"HTTP {resp.status}: {err_txt}"
        except asyncio.TimeoutError:
            last_error = f"Timeout on {model_name}"
        except Exception as e:
            last_error = str(e)

    return {"error": last_error or "ไม่สามารถเชื่อมต่อ Gemini API ได้"}

def is_user_admin(user: discord.User | discord.Member, guild: discord.Guild | None) -> bool:
    owner_id = int(os.getenv("OWNER_USER_ID", "372796686323417089"))
    if user.id == owner_id:
        return True
    if not guild or not isinstance(user, discord.Member):
        return False
    perms = user.guild_permissions
    return guild.owner_id == user.id or perms.administrator or perms.manage_guild or perms.manage_channels

def extract_tool_calls(ai_data: dict) -> list[dict]:
    raw_calls = ai_data.get("tool_calls") or ai_data.get("actions") or []
    tool_calls = []
    for call in raw_calls:
        if not isinstance(call, dict) or "tool" not in call:
            continue
        t_name = call["tool"]
        t_args = call.get("args") or {k: v for k, v in call.items() if k not in ("tool", "reply")}
        tool_calls.append({"tool": t_name, "args": t_args})
    return tool_calls

def split_message_chunks(text: str, chunk_size: int = 1900) -> list[str]:
    if len(text) <= 2000:
        return [text]
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

async def process_ai_interaction(
    bot: commands.Bot,
    user: discord.User | discord.Member,
    prompt: str,
    guild: discord.Guild | None = None,
    channel: discord.abc.Messageable | None = None
) -> str:
    context = {
        "bot": bot,
        "user_id": user.id,
        "user": user,
        "guild": guild,
        "channel": channel,
        "is_admin": is_user_admin(user, guild)
    }

    history = get_ai_chat_history(user_id=user.id, max_messages=10, timeout_minutes=30)

    async with aiohttp.ClientSession() as session:
        ai_data = await call_gemini_api(session, prompt, history)
        if not ai_data or "error" in ai_data:
            err_msg = ai_data.get("error", "ไม่สามารถประมวลผลได้") if ai_data else "ไม่สามารถประมวลผลได้"
            return f"⚠️ **AI ไม่สามารถประมวลผลได้:** `{err_msg}`\nกรุณาลองใหม่อีกครั้งครับ"

        tool_calls = extract_tool_calls(ai_data)
        if not tool_calls:
            reply_text = ai_data.get("reply", "ดำเนินการเรียบร้อยแล้วครับ")
            add_ai_chat_message(user_id=user.id, role="user", content=prompt)
            add_ai_chat_message(user_id=user.id, role="model", content=reply_text)
            return reply_text

        tool_results = []
        for call in tool_calls:
            tool_name = call.get("tool")
            args = call.get("args", {})
            result = await execute_ai_tool(tool_name, args, context)
            tool_results.append({"tool": tool_name, "result": result})

        if len(tool_calls) == 1 and tool_calls[0].get("tool") == "search_web":
            search_res = tool_results[0].get("result")
            if isinstance(search_res, dict) and ("error" in search_res or not search_res.get("results")):
                reply_text = "ขออภัยครับ ไม่สามารถค้นหาข้อมูลได้ในขณะนี้ กรุณาลองใหม่อีกครั้งครับ"
                add_ai_chat_message(user_id=user.id, role="user", content=prompt)
                add_ai_chat_message(user_id=user.id, role="model", content=reply_text)
                return reply_text

        tool_json = json.dumps(tool_results, ensure_ascii=False)
        second_ai_data = await call_gemini_api(session, prompt, history, tool_context=tool_json)
        reply_text = (second_ai_data or {}).get("reply") or ai_data.get("reply") or "ดำเนินการตามคำสั่งของระบบเรียบร้อยแล้วครับ"

    add_ai_chat_message(user_id=user.id, role="user", content=prompt)
    add_ai_chat_message(user_id=user.id, role="model", content=reply_text)
    return reply_text

class AICog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    ai_group = app_commands.Group(name="ai", description="จัดการและสั่งงานผู้ช่วย AI อัจฉริยะ (Google Gemini)")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        setting_key = f"ai_chat_channel_{message.guild.id}"
        ai_channel_id = get_setting(setting_key) or get_setting("ai_chat_channel_id")
        if not ai_channel_id or str(message.channel.id) != ai_channel_id:
            return

        if message.content.startswith("/") or message.content.startswith("!"):
            return

        prompt = message.content.strip()
        if not prompt:
            return

        async with message.channel.typing():
            response_text = await process_ai_interaction(
                bot=self.bot,
                user=message.author,
                prompt=prompt,
                guild=message.guild,
                channel=message.channel
            )

        chunks = split_message_chunks(response_text)
        await message.reply(chunks[0], mention_author=False)
        for chunk in chunks[1:]:
            await message.channel.send(chunk)

    @ai_group.command(name="set_channel", description="กำหนดห้องแชทเฉพาะสำหรับคุยกับ AI โดยไม่ต้องพิมพ์คำสั่ง /")
    @app_commands.describe(channel="ห้อง Text Channel ที่ต้องการตั้งเป็นห้องคุย AI")
    async def ai_set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.guild:
            await interaction.response.send_message("❌ คำสั่งนี้สามารถใช้ได้เฉพาะในเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
            return

        setting_key = f"ai_chat_channel_{interaction.guild_id}"
        set_setting(setting_key, str(channel.id))
        embed = discord.Embed(
            title="✅ ตั้งค่าห้องแชท AI เรียบร้อย",
            description=(
                f"ตั้งค่าห้อง {channel.mention} เป็นห้องสนทนา AI ประจำเซิร์ฟเวอร์นี้เรียบร้อยแล้ว!\n"
                f"💡 *สมาชิกสามารถพิมพ์คุยหรือสั่งงานในห้องนี้ได้ทันที โดยไม่ต้องพิมพ์คำสั่ง `/`*"
            ),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @ai_group.command(name="remove_channel", description="ยกเลิกห้องแชทเฉพาะ AI (กลับไปใช้คำสั่ง /ask แทน)")
    async def ai_remove_channel(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("❌ คำสั่งนี้สามารถใช้ได้เฉพาะในเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
            return

        setting_key = f"ai_chat_channel_{interaction.guild_id}"
        set_setting(setting_key, "")
        embed = discord.Embed(
            title="🗑️ ยกเลิกห้องแชท AI เรียบร้อย",
            description="ยกเลิกห้องแชทอัตโนมัติของเซิร์ฟเวอร์นี้แล้ว หลังจากนี้ต้องพิมพ์คำสั่ง `/ask` หรือ `/ai chat` เท่านั้น",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed)

    @ai_group.command(name="chat", description="คุยกับ AI สามารถสั่งการและสอบถามข้อมูลของระบบบอทได้")
    @app_commands.describe(prompt="พิมพ์สิ่งที่คุณต้องการสั่งหรือสอบถาม เช่น 'ราคาน้ำมันวันนี้' หรือ 'เพิ่มช่อง youtube https://...'")
    async def ai_chat(self, interaction: discord.Interaction, prompt: str):
        if not interaction.response.is_done():
            await interaction.response.defer()

        response_text = await process_ai_interaction(
            bot=self.bot,
            user=interaction.user,
            prompt=prompt,
            guild=interaction.guild,
            channel=interaction.channel
        )

        for chunk in split_message_chunks(response_text):
            await interaction.followup.send(chunk)

    @ai_group.command(name="clear", description="ล้างประวัติการสนทนากับ AI ทั้งหมดเพื่อเริ่มคุยหัวข้อใหม่")
    async def ai_clear(self, interaction: discord.Interaction):
        count = clear_ai_chat_history(interaction.user.id)
        await interaction.response.send_message(
            f"🧠 **ล้างความจำบทสนทนาเรียบร้อยแล้ว** (ลบประวัติไป {count} ข้อความ) เริ่มคุยหัวข้อใหม่ได้ทันทีครับ!",
            ephemeral=True
        )

    @app_commands.command(name="ask", description="คุยกับผู้ช่วย AI ด่วน (คำสั่งย่อของ /ai chat)")
    @app_commands.describe(prompt="คำถามหรือคำสั่งที่ต้องการ เช่น 'ราคาน้ำมันวันนี้' หรือ 'สรุปข่าวเด่น'")
    async def ask_short(self, interaction: discord.Interaction, prompt: str):
        await self.ai_chat.callback(self, interaction, prompt)

async def setup(bot: commands.Bot):
    await bot.add_cog(AICog(bot))
