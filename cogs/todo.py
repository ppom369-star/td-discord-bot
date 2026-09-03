import asyncio
import re
import sys
from datetime import datetime, timedelta
import discord
from discord import app_commands
from discord.ext import commands
from database.db_manager import (
    add_todo,
    get_todos,
    mark_todo_done,
    delete_todo,
    add_reminder,
    get_pending_reminders,
    mark_reminder_sent,
    get_bangkok_now
)
from utils.dashboard import deliver_channel_card

SANDBOX_CHANNEL_ID = 1544548171584245860

def parse_duration_string(time_str: str) -> timedelta | None:
    pattern = r"((?P<days>\d+)d)?((?P<hours>\d+)h)?((?P<minutes>\d+)m)?((?P<seconds>\d+)s)?"
    match = re.fullmatch(pattern, time_str.strip().lower())
    if not match or not any(match.groupdict().values()):
        return None
    
    parts = {k: int(v) if v else 0 for k, v in match.groupdict().items()}
    return timedelta(
        days=parts["days"],
        hours=parts["hours"],
        minutes=parts["minutes"],
        seconds=parts["seconds"]
    )

def build_todo_dashboard_embed(user_id: int) -> discord.Embed:
    todos = get_todos(user_id)
    if not todos:
        embed = discord.Embed(
            title="📋 รายการ To-do ประจำตัว",
            description="> 💡 *ยังไม่มีรายการงาน กดปุ่ม [➕ เพิ่มงานใหม่ 📌] ด้านล่างเพื่อเริ่มจดงาน*",
            color=discord.Color.from_rgb(99, 102, 241),
            timestamp=datetime.now()
        )
        embed.set_footer(text="TD Personal Assistant • กดปุ่มด้านล่างเพื่อจัดการงาน")
        return embed

    pending_list = [item for item in todos if item["status"] == "pending"]
    done_list = [item for item in todos if item["status"] == "done"]
    total_tasks = len(todos)
    done_count = len(done_list)
    progress_pct = round((done_count / total_tasks) * 100) if total_tasks > 0 else 0

    embed = discord.Embed(
        title="📋 รายการ To-do ประจำตัว",
        description=f"📊 **ความคืบหน้ารวม:** `{done_count}/{total_tasks}` งานเสร็จสิ้น ({progress_pct}%)",
        color=discord.Color.from_rgb(99, 102, 241),
        timestamp=datetime.now()
    )

    if pending_list:
        lines = [f"`#{item['id']}` ⏳ {item['task']}" for item in pending_list]
        embed.add_field(name=f"📌 งานที่ต้องทำ ({len(pending_list)})", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="📌 งานที่ต้องทำ", value="> ✨ *ไม่มีงานค้าง ยอดเยี่ยมมาก!*", inline=False)

    if done_list:
        lines = [f"`#{item['id']}` ✅ ~~{item['task']}~~" for item in done_list[:5]]
        if len(done_list) > 5:
            lines.append(f"*...และอีก {len(done_list) - 5} รายการที่ปิดงานแล้ว*")
        embed.add_field(name=f"🎉 เสร็จสิ้นแล้ว ({len(done_list)})", value="\n".join(lines), inline=False)

    embed.set_footer(text="กดปุ่มด้านล่างเพื่อเพิ่มงาน ปิดงาน หรือลบงานได้ทันที")
    return embed

class TodoAddModal(discord.ui.Modal, title="เพิ่มงาน To-do ใหม่ 📌"):
    task = discord.ui.TextInput(
        label="ชื่องานหรือเป้าหมายที่ต้องการทำ",
        placeholder="เช่น ซื้อของเข้าบ้าน, ตรวจสอบโค้ด, ออกกำลังกาย",
        required=True,
        max_length=150
    )

    async def on_submit(self, interaction: discord.Interaction):
        task_text = self.task.value.strip()
        try:
            add_todo(interaction.user.id, task_text)
            embed = build_todo_dashboard_embed(interaction.user.id)
            await deliver_channel_card(interaction, embed, view=TodoDashboardView())
        except Exception as err:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ ไม่สามารถเพิ่มงานได้: {err}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ ไม่สามารถเพิ่มงานได้: {err}", ephemeral=True)

class TodoDoneModal(discord.ui.Modal, title="ปิดงาน To-do ที่ทำเสร็จแล้ว ✅"):
    task_id = discord.ui.TextInput(
        label="รหัส ID ของงานที่เสร็จแล้ว",
        placeholder="เช่น 1, 2, 3 (ดูจากเลข #ID ในการ์ด)",
        required=True,
        max_length=8
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            tid = int(self.task_id.value.strip().replace("#", ""))
        except ValueError:
            await interaction.response.send_message("❌ กรุณากรอกรหัส ID เป็นตัวเลข", ephemeral=True)
            return
        try:
            mark_todo_done(tid, interaction.user.id)
            embed = build_todo_dashboard_embed(interaction.user.id)
            await deliver_channel_card(interaction, embed, view=TodoDashboardView())
        except Exception as err:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ ไม่สามารถปิดงานได้: {err}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ ไม่สามารถปิดงานได้: {err}", ephemeral=True)

class TodoDeleteModal(discord.ui.Modal, title="ลบงาน To-do ออกจากลิสต์ 🗑️"):
    task_id = discord.ui.TextInput(
        label="รหัส ID ของงานที่ต้องการลบ",
        placeholder="เช่น 1, 2, 3 (ดูจากเลข #ID ในการ์ด)",
        required=True,
        max_length=8
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            tid = int(self.task_id.value.strip().replace("#", ""))
        except ValueError:
            await interaction.response.send_message("❌ กรุณากรอกรหัส ID เป็นตัวเลข", ephemeral=True)
            return
        try:
            delete_todo(tid, interaction.user.id)
            embed = build_todo_dashboard_embed(interaction.user.id)
            await deliver_channel_card(interaction, embed, view=TodoDashboardView())
        except Exception as err:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ ไม่สามารถลบงานได้: {err}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ ไม่สามารถลบงานได้: {err}", ephemeral=True)

class TodoDashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="เพิ่มงานใหม่ 📌", style=discord.ButtonStyle.success, custom_id="btn_todo_add")
    async def add_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TodoAddModal())

    @discord.ui.button(label="ปิดงานที่เสร็จ ✅", style=discord.ButtonStyle.primary, custom_id="btn_todo_done")
    async def done_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TodoDoneModal())

    @discord.ui.button(label="ลบงาน 🗑️", style=discord.ButtonStyle.danger, custom_id="btn_todo_delete")
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TodoDeleteModal())

    @discord.ui.button(label="รีเฟรช 🔄", style=discord.ButtonStyle.secondary, custom_id="btn_todo_refresh")
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        embed = build_todo_dashboard_embed(interaction.user.id)
        await interaction.edit_original_response(embed=embed, view=self)

ACTIVE_REMIND_TASKS: dict[int, asyncio.Task] = {}

def start_reminder_task(bot: commands.Bot, reminder_id: int, user_id: int, message: str, delay_seconds: float):
    old = ACTIVE_REMIND_TASKS.pop(reminder_id, None)
    if old and not old.done():
        old.cancel()
    ACTIVE_REMIND_TASKS[reminder_id] = asyncio.create_task(
        run_reminder_worker(bot, reminder_id, user_id, message, delay_seconds)
    )

async def run_reminder_worker(bot: commands.Bot, reminder_id: int, user_id: int, message: str, delay_seconds: float):
    try:
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

        channel = bot.get_channel(SANDBOX_CHANNEL_ID)
        if not channel:
            try:
                channel = await bot.fetch_channel(SANDBOX_CHANNEL_ID)
            except Exception as e:
                print(f"[REMIND] Cannot fetch sandbox channel: {e}", file=sys.stderr, flush=True)
                channel = None

        embed = discord.Embed(
            title="⏰ แจ้งเตือนครบกำหนดเวลา!",
            description=message,
            color=discord.Color.gold(),
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"TD Reminder System • #{reminder_id}")

        sent_successfully = False
        if channel:
            try:
                await channel.send(content=f"🔔 <@{user_id}> **แจ้งเตือนครบเวลา!**", embed=embed)
                sent_successfully = True
            except Exception as e:
                print(f"[REMIND] Error sending to channel: {e}", file=sys.stderr, flush=True)

        if not sent_successfully:
            try:
                user = bot.get_user(user_id) or await bot.fetch_user(user_id)
                if user:
                    await user.send(embed=embed)
                    sent_successfully = True
            except Exception as e:
                print(f"[REMIND] Error sending to DM: {e}", file=sys.stderr, flush=True)

        mark_reminder_sent(reminder_id)
        print(f"[REMIND] Delivered reminder #{reminder_id} successfully", flush=True)
    except asyncio.CancelledError:
        pass
    except Exception as err:
        print(f"[REMIND] Error delivering reminder #{reminder_id}: {err}", file=sys.stderr, flush=True)
    finally:
        ACTIVE_REMIND_TASKS.pop(reminder_id, None)

class TodoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        asyncio.create_task(self.recover_reminders())

    def cog_unload(self):
        for task in list(ACTIVE_REMIND_TASKS.values()):
            task.cancel()
        ACTIVE_REMIND_TASKS.clear()

    async def recover_reminders(self):
        await self.bot.wait_until_ready()
        pending = get_pending_reminders()
        now = get_bangkok_now()
        print(f"[REMIND RECOVERY] Found {len(pending)} pending reminders", flush=True)
        for item in pending:
            r_id = item["id"]
            u_id = item["user_id"]
            msg = item["message"]
            remind_at_val = item.get("remind_at") or item.get("due_time")
            delay = 0.0
            if remind_at_val:
                try:
                    if isinstance(remind_at_val, str):
                        remind_at = datetime.fromisoformat(remind_at_val)
                    else:
                        remind_at = remind_at_val

                    if remind_at.tzinfo is None:
                        remind_at = remind_at.replace(tzinfo=now.tzinfo)

                    delay = max((remind_at - now).total_seconds(), 0.0)
                except Exception as ex:
                    print(f"[REMIND RECOVERY] Parse date error for #{r_id}: {ex}", flush=True)
                    delay = 0.0

            start_reminder_task(self.bot, r_id, u_id, msg, delay)

    todo_group = app_commands.Group(name="todo", description="จัดการรายการสิ่งที่ต้องทำ (To-do List)")

    @todo_group.command(name="add", description="เพิ่มรายการงานใหม่")
    @app_commands.describe(task="ข้อความงานที่ต้องการทำ")
    async def todo_add(self, interaction: discord.Interaction, task: str):
        if not interaction.response.is_done():
            await interaction.response.defer()
        add_todo(interaction.user.id, task)
        embed = build_todo_dashboard_embed(interaction.user.id)
        await deliver_channel_card(interaction, embed, view=TodoDashboardView())

    @todo_group.command(name="list", description="ดูรายการงานทั้งหมด")
    async def todo_list(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        embed = build_todo_dashboard_embed(interaction.user.id)
        await deliver_channel_card(interaction, embed, view=TodoDashboardView())

    @todo_group.command(name="done", description="ทำเครื่องหมายว่าเสร็จแล้ว")
    @app_commands.describe(task_id="รหัส ID ของงานที่ต้องการปิด")
    async def todo_done(self, interaction: discord.Interaction, task_id: int):
        if not interaction.response.is_done():
            await interaction.response.defer()
        mark_todo_done(task_id, interaction.user.id)
        embed = build_todo_dashboard_embed(interaction.user.id)
        await deliver_channel_card(interaction, embed, view=TodoDashboardView())

    @todo_group.command(name="delete", description="ลบรายการงานทิ้ง")
    @app_commands.describe(task_id="รหัส ID ของงานที่ต้องการลบ")
    async def todo_delete(self, interaction: discord.Interaction, task_id: int):
        if not interaction.response.is_done():
            await interaction.response.defer()
        delete_todo(task_id, interaction.user.id)
        embed = build_todo_dashboard_embed(interaction.user.id)
        await deliver_channel_card(interaction, embed, view=TodoDashboardView())

    @app_commands.command(name="remind", description="ตั้งเวลาแจ้งเตือนล่วงหน้า")
    @app_commands.describe(
        time="ระยะเวลา เช่น 10m (10 นาที), 1h (1 ชั่วโมง), 2h30m, 1d (1 วัน)",
        message="ข้อความที่ต้องการให้แจ้งเตือน"
    )
    async def remind(self, interaction: discord.Interaction, time: str, message: str):
        if not interaction.response.is_done():
            await interaction.response.defer()
        duration = parse_duration_string(time)
        if not duration or duration.total_seconds() <= 0:
            embed = discord.Embed(
                title="⚠️ รูปแบบเวลาไม่ถูกต้อง",
                description="กรุณาระบุเวลาในรูปแบบ เช่น `10m` (10 นาที), `2h` (2 ชั่วโมง), `1h30m`, `30s`",
                color=discord.Color.red(),
                timestamp=get_bangkok_now()
            )
            await deliver_channel_card(interaction, embed)
            return

        remind_at = get_bangkok_now() + duration
        reminder_id = add_reminder(
            user_id=interaction.user.id,
            channel_id=SANDBOX_CHANNEL_ID,
            due_time=remind_at,
            message=message
        )

        start_reminder_task(
            bot=self.bot,
            reminder_id=reminder_id,
            user_id=interaction.user.id,
            message=message,
            delay_seconds=duration.total_seconds()
        )

        unix_timestamp = int(remind_at.timestamp())
        embed = discord.Embed(
            title="⏰ ตั้งเวลาแจ้งเตือนเรียบร้อยแล้ว",
            description=f"จะแจ้งเตือน: **{message}**\nเวลาเป้าหมาย: <t:{unix_timestamp}:F> (<t:{unix_timestamp}:R>)\n*(ระบบจะส่งการแจ้งเตือนไปที่ห้อง `sandbox`)*",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"Reminder ID: #{reminder_id}")
        await deliver_channel_card(interaction, embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(TodoCog(bot))
