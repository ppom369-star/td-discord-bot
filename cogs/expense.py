from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
from database.db_manager import (
    add_transaction,
    get_transactions,
    get_daily_transactions,
    get_month_summary,
    delete_transaction,
    delete_last_transaction,
    get_setting,
    set_setting,
    get_bangkok_now
)
from utils.dashboard import deliver_channel_card

EXPENSE_CHANNEL_ID = 1544579305806241802
HISTORY_CHANNEL_ID = 1544595071175753778

THAI_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
THAI_MONTHS = [
    "", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"
]

CATEGORY_ICONS = {
    "อาหาร": "🍔",
    "เดินทาง": "🚗",
    "ช้อปปิ้ง": "🛍️",
    "สกินแคร์": "🧴",
    "เกม": "🎮",
    "หนังสือ": "📚",
    "บิล": "💡",
    "เงินเดือน": "💼",
    "ทั่วไป": "✨"
}

def get_category_icon(category: str) -> str:
    return CATEGORY_ICONS.get(category.strip(), "✨")

def make_progress_bar(ratio: float, length: int = 8) -> str:
    filled = max(0, min(length, round(ratio * length)))
    return "█" * filled + "░" * (length - filled)

def format_thai_date(date_str: str) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    day_name = THAI_DAYS[dt.weekday()]
    month_name = THAI_MONTHS[dt.month]
    return f"📅 วัน{day_name}ที่ {dt.day} {month_name} {dt.year}"

def build_daily_ledger_embed(items: list, date_str: str) -> discord.Embed:
    lines = []
    income_total = 0.0
    expense_total = 0.0

    for item in items:
        created = str(item.get("created_at", ""))
        time_str = created[11:16] if len(created) >= 16 else "--:--"
        cat = item["category"]
        icon = get_category_icon(cat)
        amt = item["amount"]
        sign = "+" if item["type"] == "income" else "-"

        if item["type"] == "income":
            income_total += amt
        else:
            expense_total += amt

        amt_str = f"{sign}฿{amt:,.2f}"
        note = item.get("note", "").strip()
        if note:
            line = f"#{item['id']} • {time_str} • {icon} {cat} • {note} • {amt_str}"
        else:
            line = f"#{item['id']} • {time_str} • {icon} {cat} • {amt_str}"
        lines.append(line)

    balance = income_total - expense_total
    bal_sign = "+" if balance >= 0 else ""
    summary_line = f"📊 สรุปวันนี้: 🟢 +฿{income_total:,.2f} | 🔴 -฿{expense_total:,.2f} | 💵 คงเหลือ: {bal_sign}฿{balance:,.2f}"

    content = "\n".join(lines) + "\n───────────────────────────\n" + summary_line
    embed_color = discord.Color.from_rgb(16, 185, 129) if balance >= 0 else discord.Color.from_rgb(239, 68, 68)

    embed = discord.Embed(
        title=format_thai_date(date_str),
        description=content,
        color=embed_color
    )
    return embed

async def sync_daily_ledger(bot: commands.Bot, user_id: int, date_str: str):
    channel = bot.get_channel(HISTORY_CHANNEL_ID)
    if not channel:
        try:
            channel = await bot.fetch_channel(HISTORY_CHANNEL_ID)
        except Exception:
            return

    items = get_daily_transactions(user_id, date_str)
    setting_key = f"daily_ledger_{HISTORY_CHANNEL_ID}_{date_str}"
    msg_id_str = get_setting(setting_key)

    if not items:
        if msg_id_str:
            try:
                target_msg = await channel.fetch_message(int(msg_id_str))
                await target_msg.delete()
            except Exception:
                pass
            set_setting(setting_key, "")
        return

    embed = build_daily_ledger_embed(items, date_str)

    target_msg = None
    if msg_id_str:
        try:
            target_msg = await channel.fetch_message(int(msg_id_str))
        except Exception:
            target_msg = None

    if target_msg:
        try:
            await target_msg.edit(embed=embed)
            return
        except Exception:
            pass

    new_msg = await channel.send(embed=embed)
    set_setting(setting_key, str(new_msg.id))

def build_expense_dashboard_embed(user_id: int) -> discord.Embed:
    summary = get_month_summary(user_id)
    recent = get_transactions(user_id, limit=5)

    now = get_bangkok_now()
    month_str = now.strftime("%m/%Y")

    balance = summary["balance"]
    bal_sign = "+" if balance >= 0 else ""
    embed_color = discord.Color.from_rgb(16, 185, 129) if balance >= 0 else discord.Color.from_rgb(239, 68, 68)

    embed = discord.Embed(
        title=f"💰 บัญชีรายรับ-รายจ่าย • ประจำเดือน {month_str}",
        description=(
            f"> 📈 **รายรับสะสม:** `+฿{summary['total_income']:,.2f}`\n"
            f"> 📉 **รายจ่ายสะสม:** `-฿{summary['total_expense']:,.2f}`\n"
            f"> 💵 **คงเหลือสุทธิ:** **{bal_sign}฿{balance:,.2f}**\n\n"
            f"📅 **วันนี้ใช้ไป:** `฿{summary['today_expense']:,.2f}` ({summary['today_count']} รายการ)"
        ),
        color=embed_color,
        timestamp=now
    )

    categories = summary["categories"]
    total_exp = summary["total_expense"]
    if categories and total_exp > 0:
        cat_lines = []
        sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)
        for cat, amt in sorted_cats[:6]:
            ratio = amt / total_exp
            pct = round(ratio * 100)
            bar = make_progress_bar(ratio, 8)
            icon = get_category_icon(cat)
            cat_lines.append(f"{icon} **{cat}:** `{bar}` ฿{amt:,.2f} ({pct}%)")
        embed.add_field(name="📊 สัดส่วนค่าใช้จ่ายเดือนนี้", value="\n".join(cat_lines), inline=False)
    else:
        embed.add_field(name="📊 สัดส่วนค่าใช้จ่ายเดือนนี้", value="> 💡 *ยังไม่มีรายการรายจ่ายในเดือนนี้*", inline=False)

    if recent:
        rec_lines = []
        for item in recent:
            icon = get_category_icon(item["category"])
            sign = "+" if item["type"] == "income" else "-"
            note_str = f" • {item['note']}" if item["note"] else ""
            rec_lines.append(f"`#{item['id']}` {icon} **{item['category']}**{note_str} (**{sign}฿{item['amount']:,.2f}**)")
        embed.add_field(name="📝 5 รายการล่าสุด", value="\n".join(rec_lines), inline=False)
    else:
        embed.add_field(name="📝 รายการล่าสุด", value="> 💡 *ยังไม่มีรายการบันทึก กดปุ่มด้านล่างเพื่อเริ่มจด*", inline=False)

    embed.set_footer(text="กดปุ่มด้านล่างเพื่อบันทึกหรือพิมพ์ /spend <ยอด> <หมวด> [โน้ต]")
    return embed

class ExpenseModal(discord.ui.Modal):
    def __init__(self, category: str = "อาหาร"):
        self.category = category
        icon = get_category_icon(category)
        super().__init__(title=f"บันทึกรายจ่าย • {icon} {category}")
        self.amount = discord.ui.TextInput(
            label="จำนวนเงิน (บาท)",
            placeholder="เช่น 65 หรือ 120.50",
            required=True,
            max_length=10
        )
        self.note = discord.ui.TextInput(
            label="รายละเอียด/โน้ต (ไม่บังคับ)",
            placeholder="เช่น ข้าวมันไก่, สตีมเกม, ครีมกันแดด",
            required=False,
            max_length=100
        )
        self.add_item(self.amount)
        self.add_item(self.note)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = float(self.amount.value.replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message("❌ กรุณากรอกจำนวนเงินเป็นตัวเลข เช่น `65` หรือ `150.50`", ephemeral=True)
            return

        today_str = get_bangkok_now().strftime("%Y-%m-%d")
        note_text = self.note.value.strip()

        try:
            add_transaction(interaction.user.id, "expense", amt, self.category, note_text)
            embed = build_expense_dashboard_embed(interaction.user.id)
            await deliver_channel_card(interaction, embed, view=ExpenseDashboardView(current_category=self.category))
            await sync_daily_ledger(interaction.client, interaction.user.id, today_str)
        except Exception as err:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ ไม่สามารถบันทึกรายจ่ายได้: {err}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ ไม่สามารถบันทึกรายจ่ายได้: {err}", ephemeral=True)

class IncomeModal(discord.ui.Modal, title="บันทึกรายรับ 💰"):
    def __init__(self):
        super().__init__()
        self.amount = discord.ui.TextInput(
            label="จำนวนเงิน (บาท)",
            placeholder="เช่น 35000 หรือ 1500",
            required=True,
            max_length=10
        )
        self.note = discord.ui.TextInput(
            label="ที่มารายรับ / โน้ต (ไม่บังคับ)",
            placeholder="เช่น เงินเดือนประจำ, โบนัส, ฟรีแลนซ์, ขายของ",
            required=False,
            max_length=100
        )
        self.add_item(self.amount)
        self.add_item(self.note)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = float(self.amount.value.replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message("❌ กรุณากรอกจำนวนเงินเป็นตัวเลข เช่น `35000`", ephemeral=True)
            return

        today_str = get_bangkok_now().strftime("%Y-%m-%d")
        note_text = self.note.value.strip()
        cat = "เงินเดือน"
        for candidate in ["โบนัส", "ฟรีแลนซ์", "ขายของ", "ลงทุน", "เงินเดือน"]:
            if candidate in note_text:
                cat = candidate
                break

        try:
            add_transaction(interaction.user.id, "income", amt, cat, note_text)
            embed = build_expense_dashboard_embed(interaction.user.id)
            await deliver_channel_card(interaction, embed, view=ExpenseDashboardView())
            await sync_daily_ledger(interaction.client, interaction.user.id, today_str)
        except Exception as err:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ ไม่สามารถบันทึกรายรับได้: {err}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ ไม่สามารถบันทึกรายรับได้: {err}", ephemeral=True)

class ExpenseCategorySelect(discord.ui.Select):
    def __init__(self, selected_category: str = "อาหาร"):
        options = [
            discord.SelectOption(label="อาหาร & เครื่องดื่ม", emoji="🍔", value="อาหาร", default=(selected_category == "อาหาร")),
            discord.SelectOption(label="เดินทาง & น้ำมัน", emoji="🚗", value="เดินทาง", default=(selected_category == "เดินทาง")),
            discord.SelectOption(label="ช้อปปิ้ง & ของใช้", emoji="🛍️", value="ช้อปปิ้ง", default=(selected_category == "ช้อปปิ้ง")),
            discord.SelectOption(label="สกินแคร์", emoji="🧴", value="สกินแคร์", default=(selected_category == "สกินแคร์")),
            discord.SelectOption(label="เกม & เอนเตอร์เทน", emoji="🎮", value="เกม", default=(selected_category == "เกม")),
            discord.SelectOption(label="หนังสือ & พัฒนาตนเอง", emoji="📚", value="หนังสือ", default=(selected_category == "หนังสือ")),
            discord.SelectOption(label="บิล & ค่าใช้จ่าย", emoji="💡", value="บิล", default=(selected_category == "บิล")),
            discord.SelectOption(label="ทั่วไป / อื่นๆ", emoji="✨", value="ทั่วไป", default=(selected_category == "ทั่วไป"))
        ]
        super().__init__(
            placeholder="📂 เลือกหมวดหมู่ล่วงหน้าเพื่อจด...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="select_expense_category",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        chosen = self.values[0] if self.values else "อาหาร"
        view = ExpenseDashboardView(current_category=chosen)
        embed = build_expense_dashboard_embed(interaction.user.id)
        await interaction.edit_original_response(embed=embed, view=view)

class ExpenseDashboardView(discord.ui.View):
    def __init__(self, current_category: str = "อาหาร"):
        super().__init__(timeout=None)
        self.current_category = current_category
        self.add_item(ExpenseCategorySelect(selected_category=current_category))

    @discord.ui.button(label="บันทึกรายจ่าย 💸", style=discord.ButtonStyle.danger, custom_id="btn_expense_add", row=1)
    async def add_expense_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ExpenseModal(category=self.current_category))

    @discord.ui.button(label="บันทึกรายรับ 💰", style=discord.ButtonStyle.success, custom_id="btn_income_add", row=1)
    async def add_income_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(IncomeModal())

    @discord.ui.button(label="ลบล่าสุด 🗑️", style=discord.ButtonStyle.secondary, custom_id="btn_expense_undo", row=1)
    async def undo_last_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        deleted = delete_last_transaction(interaction.user.id)
        embed = build_expense_dashboard_embed(interaction.user.id)
        await interaction.edit_original_response(embed=embed, view=self)
        if deleted:
            await sync_daily_ledger(interaction.client, interaction.user.id, deleted["date"])

    @discord.ui.button(label="รีเฟรช 🔄", style=discord.ButtonStyle.primary, custom_id="btn_expense_refresh", row=1)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        embed = build_expense_dashboard_embed(interaction.user.id)
        await interaction.edit_original_response(embed=embed, view=self)
        today_str = datetime.now().strftime("%Y-%m-%d")
        await sync_daily_ledger(interaction.client, interaction.user.id, today_str)

class ExpenseCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    expense_group = app_commands.Group(name="expense", description="ระบบสมุดบันทึกรายรับ-รายจ่ายส่วนตัว")

    @expense_group.command(name="card", description="แสดงการ์ดสมุดบัญชีรายรับ-รายจ่ายประจำเดือน")
    async def expense_card(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        embed = build_expense_dashboard_embed(interaction.user.id)
        await deliver_channel_card(interaction, embed, view=ExpenseDashboardView())
        today_str = datetime.now().strftime("%Y-%m-%d")
        await sync_daily_ledger(self.bot, interaction.user.id, today_str)

    @expense_group.command(name="delete", description="ลบรายการบันทึกตามรหัส ID")
    @app_commands.describe(item_id="รหัส ID ของรายการที่ต้องการลบ เช่น 12")
    async def expense_delete(self, interaction: discord.Interaction, item_id: int):
        if not interaction.response.is_done():
            await interaction.response.defer()
        deleted = delete_transaction(item_id, interaction.user.id)
        embed = build_expense_dashboard_embed(interaction.user.id)
        await deliver_channel_card(interaction, embed, view=ExpenseDashboardView())
        if deleted:
            await sync_daily_ledger(self.bot, interaction.user.id, deleted["date"])

    @expense_group.command(name="list", description="ดูรายการประวัติบันทึกรายรับ-รายจ่ายย้อนหลังแบบเต็มจำนวน")
    @app_commands.describe(limit="จำนวนรายการที่ต้องการดู (เช่น 20 หรือ 50 รายการ)")
    async def expense_list(self, interaction: discord.Interaction, limit: int = 20):
        await interaction.response.defer(ephemeral=True)
        fetch_limit = min(50, max(1, limit))
        items = get_transactions(interaction.user.id, limit=fetch_limit)
        if not items:
            await interaction.followup.send("ℹ️ ยังไม่มีประวัติการบันทึกรายการใดๆ", ephemeral=True)
            return

        lines = []
        for item in items:
            icon = get_category_icon(item["category"])
            sign = "+" if item["type"] == "income" else "-"
            amt = item["amount"]
            note_str = f" • {item['note']}" if item["note"] else ""
            date_str = item.get("date", "")
            lines.append(f"`#{item['id']}` `{date_str}` {icon} **{item['category']}**{note_str} (**{sign}฿{amt:,.2f}**)")

        embed = discord.Embed(
            title=f"📜 ประวัติบันทึกรายรับ-รายจ่าย ({len(items)} รายการล่าสุด)",
            description="\n".join(lines),
            color=discord.Color.from_rgb(99, 102, 241),
            timestamp=datetime.now()
        )
        embed.set_footer(text="ใช้คำสั่ง /expense delete <id> เพื่อลบรายการที่ระบุ")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @expense_group.command(name="sync", description="ซิงค์อัปเดตการ์ดสมุดบัญชีรายวันในห้องประวัติรับจ่าย")
    async def expense_sync(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        today_str = get_bangkok_now().strftime("%Y-%m-%d")
        await sync_daily_ledger(self.bot, interaction.user.id, today_str)
        await interaction.followup.send("✅ ซิงค์ข้อมูลลงห้อง `ประวัติรับจ่าย` เรียบร้อยแล้ว", ephemeral=True)

    @app_commands.command(name="spend", description="บันทึกรายจ่ายด่วน")
    @app_commands.describe(
        amount="จำนวนเงิน เช่น 65 หรือ 120",
        category="หมวดหมู่ค่าใช้จ่าย",
        note="รายละเอียดเพิ่มเติม เช่น ข้าวมันไก่"
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="🍔 อาหาร", value="อาหาร"),
        app_commands.Choice(name="🚗 เดินทาง", value="เดินทาง"),
        app_commands.Choice(name="🛍️ ช้อปปิ้ง", value="ช้อปปิ้ง"),
        app_commands.Choice(name="🧴 สกินแคร์", value="สกินแคร์"),
        app_commands.Choice(name="🎮 เกม", value="เกม"),
        app_commands.Choice(name="📚 หนังสือ", value="หนังสือ"),
        app_commands.Choice(name="💡 บิล/ค่าใช้จ่าย", value="บิล"),
        app_commands.Choice(name="✨ ทั่วไป", value="ทั่วไป")
    ])
    async def spend(
        self,
        interaction: discord.Interaction,
        amount: float,
        category: app_commands.Choice[str] = None,
        note: str = ""
    ):
        if not interaction.response.is_done():
            await interaction.response.defer()
        cat_val = category.value if category else "อาหาร"
        today_str = get_bangkok_now().strftime("%Y-%m-%d")
        add_transaction(interaction.user.id, "expense", amount, cat_val, note)
        embed = build_expense_dashboard_embed(interaction.user.id)
        await deliver_channel_card(interaction, embed, view=ExpenseDashboardView())
        await sync_daily_ledger(self.bot, interaction.user.id, today_str)

    @app_commands.command(name="income", description="บันทึกรายรับด่วน")
    @app_commands.describe(
        amount="จำนวนเงิน เช่น 35000",
        category="หมวดหมู่รายรับ",
        note="รายละเอียดเพิ่มเติม เช่น เงินเดือนประจำเดือน"
    )
    async def income(
        self,
        interaction: discord.Interaction,
        amount: float,
        category: str = "เงินเดือน",
        note: str = ""
    ):
        if not interaction.response.is_done():
            await interaction.response.defer()
        today_str = get_bangkok_now().strftime("%Y-%m-%d")
        add_transaction(interaction.user.id, "income", amount, category, note)
        embed = build_expense_dashboard_embed(interaction.user.id)
        await deliver_channel_card(interaction, embed, view=ExpenseDashboardView())
        await sync_daily_ledger(self.bot, interaction.user.id, today_str)

async def setup(bot: commands.Bot):
    await bot.add_cog(ExpenseCog(bot))
