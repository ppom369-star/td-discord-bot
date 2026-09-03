import asyncio
from datetime import datetime, timedelta
import discord
from discord import app_commands
from discord.ext import commands
from database.db_manager import (
    set_pomodoro_session,
    get_pomodoro_session,
    delete_pomodoro_session,
    get_all_active_pomodoro_sessions,
    get_setting,
    set_setting,
    get_bangkok_now
)
from utils.dashboard import deliver_channel_card, DASHBOARD_CHANNELS

SANDBOX_CHANNEL_ID = 1544548171584245860

ACTIVE_POMODORO_TASKS: dict[int, asyncio.Task] = {}

async def update_origin_card(bot: commands.Bot, channel_id: int, embed: discord.Embed, view: discord.ui.View = None):
    channel = bot.get_channel(channel_id)
    if not channel:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception:
            return
    msg_id_str = get_setting(f"channel_card_{channel_id}")
    if msg_id_str:
        try:
            target_msg = await channel.fetch_message(int(msg_id_str))
            await target_msg.edit(embed=embed, view=view)
            return
        except Exception:
            pass
    if channel_id in DASHBOARD_CHANNELS:
        try:
            new_msg = await channel.send(embed=embed, view=view)
            set_setting(f"channel_card_{channel_id}", str(new_msg.id))
        except Exception:
            pass

async def send_sandbox_notification(bot: commands.Bot, content: str, embed: discord.Embed = None, channel_id: int = None):
    target_id = channel_id or SANDBOX_CHANNEL_ID
    channel = bot.get_channel(target_id)
    if not channel:
        try:
            channel = await bot.fetch_channel(target_id)
        except Exception:
            channel = None

    if not channel and target_id != SANDBOX_CHANNEL_ID:
        channel = bot.get_channel(SANDBOX_CHANNEL_ID)

    if channel:
        try:
            await channel.send(content=content, embed=embed)
        except Exception:
            pass

def get_session_config(session: dict | None) -> tuple[int, int, int, int]:
    s = session or {}
    return s.get("work_min", 25), s.get("break_min", 5), s.get("cycles_done", 0), s.get("target_cycles", 4)

def parse_end_time(val) -> datetime:
    now = get_bangkok_now()
    if isinstance(val, datetime):
        dt = val
    elif isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val)
        except Exception:
            return now
    else:
        return now

    if dt.tzinfo is None and now.tzinfo is not None:
        dt = dt.replace(tzinfo=now.tzinfo)
    return dt

def build_pomodoro_embed(session: dict) -> discord.Embed:
    mode = session.get("mode", "work")
    end_dt = parse_end_time(session.get("end_time"))
    unix_ts = int(end_dt.timestamp())
    work_m, break_m, cycles, target = get_session_config(session)

    if mode == "work":
        embed = discord.Embed(
            title="🍅 Pomodoro Focus • กำลังโฟกัสการทำงาน",
            description=(
                f"> 🎯 **รอบโฟกัสที่:** `#{cycles + 1}` / `{target}` รอบ\n"
                f"> ⏰ **สิ้นสุดเวลา:** <t:{unix_ts}:T> (<t:{unix_ts}:R>)\n"
                f"> ⏱️ **การตั้งค่า:** โฟกัส {work_m} นาที | พัก {break_m} นาที | เป้าหมาย {target} ลูป"
            ),
            color=discord.Color.from_rgb(239, 68, 68),
            timestamp=datetime.now()
        )
        embed.set_footer(text="มีสมาธิกับงานชิ้นเดียว | ปิดการแจ้งเตือนรบกวน")
    else:
        remaining = max(0, target - cycles)
        embed = discord.Embed(
            title="☕ Pomodoro Break • ได้เวลาพักสายตา",
            description=(
                f"> 🎉 **ทำสำเร็จไปแล้ว:** `{cycles}` / `{target}` รอบโฟกัส\n"
                f"> ⏰ **พักผ่อนถึงเวลา:** <t:{unix_ts}:T> (<t:{unix_ts}:R>)\n"
                f"> 💡 *ลุกยืดเส้นยืดสาย ดื่มน้ำ หรือพักสายตา (เหลืออีก {remaining} รอบ)*"
            ),
            color=discord.Color.from_rgb(16, 185, 129),
            timestamp=datetime.now()
        )
        embed.set_footer(text="พักสมองให้ปลอดโปร่งเพื่อเติมพลังสำหรับรอบถัดไป")

    return embed

class PomodoroSetupModal(discord.ui.Modal, title="ตั้งค่ารอบเวลา Pomodoro ⏱️"):
    work_min = discord.ui.TextInput(
        label="เวลาทำงาน / โฟกัส (นาที)",
        default="25",
        placeholder="เช่น 25",
        required=True,
        max_length=3
    )
    break_min = discord.ui.TextInput(
        label="เวลาพักสายตา (นาที)",
        default="5",
        placeholder="เช่น 5",
        required=True,
        max_length=3
    )
    loops = discord.ui.TextInput(
        label="จำนวนรอบ / ลูปเป้าหมาย (รอบ)",
        default="4",
        placeholder="เช่น 4",
        required=True,
        max_length=2
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            w = int(self.work_min.value.strip())
            b = int(self.break_min.value.strip())
            l = int(self.loops.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ กรุณากรอกตัวเลขจำนวนเต็มที่ถูกต้อง", ephemeral=True)
            return

        w = max(1, min(180, w))
        b = max(1, min(60, b))
        l = max(1, min(20, l))

        end_time = get_bangkok_now() + timedelta(minutes=w)
        try:
            set_pomodoro_session(interaction.user.id, interaction.channel_id, "work", end_time, w, b, 0, l)
            start_pomodoro_task(interaction.client, interaction.user.id)
            session = get_pomodoro_session(interaction.user.id)
            embed = build_pomodoro_embed(session)
            await deliver_channel_card(interaction, embed, view=PomodoroControlView())
        except Exception as err:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ ไม่สามารถเริ่ม Pomodoro ได้: {err}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ ไม่สามารถเริ่ม Pomodoro ได้: {err}", ephemeral=True)

class PomodoroFinishedView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="ตั้งค่าและเริ่มรอบใหม่ ⚙️", style=discord.ButtonStyle.success, custom_id="btn_pomo_setup_new", row=0)
    async def setup_new_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PomodoroSetupModal())

    @discord.ui.button(label="เริ่มด่วน 25/5m (4 ลูป) ⚡", style=discord.ButtonStyle.primary, custom_id="btn_pomo_quick_start", row=0)
    async def quick_start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        end_time = get_bangkok_now() + timedelta(minutes=25)
        set_pomodoro_session(interaction.user.id, interaction.channel_id, "work", end_time, 25, 5, 0, 4)
        start_pomodoro_task(interaction.client, interaction.user.id)
        session = get_pomodoro_session(interaction.user.id)
        embed = build_pomodoro_embed(session)
        await deliver_channel_card(interaction, embed, view=PomodoroControlView())

    @discord.ui.button(label="กลับหน้า Command Center 🎛️", style=discord.ButtonStyle.secondary, custom_id="btn_pomo_back_cmd", row=0)
    async def back_to_cmd_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        from cogs.utility import build_command_center_embed, CommandCenterView
        embed = build_command_center_embed(interaction.client)
        await deliver_channel_card(interaction, embed, view=CommandCenterView())

class PomodoroControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="เริ่มรอบถัดไป 🎯", style=discord.ButtonStyle.success, custom_id="btn_pomo_next")
    async def next_work_round(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        session = get_pomodoro_session(interaction.user.id)
        work_m, break_m, cycles, target = get_session_config(session)
        end_time = get_bangkok_now() + timedelta(minutes=work_m)
        set_pomodoro_session(interaction.user.id, interaction.channel_id, "work", end_time, work_m, break_m, cycles, target)
        start_pomodoro_task(interaction.client, interaction.user.id)
        new_session = get_pomodoro_session(interaction.user.id)
        embed = build_pomodoro_embed(new_session)
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="พักสายตาก่อน ☕", style=discord.ButtonStyle.secondary, custom_id="btn_pomo_break")
    async def take_break(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        session = get_pomodoro_session(interaction.user.id)
        work_m, break_m, cycles, target = get_session_config(session)
        end_time = get_bangkok_now() + timedelta(minutes=break_m)
        set_pomodoro_session(interaction.user.id, interaction.channel_id, "break", end_time, work_m, break_m, cycles, target)
        start_pomodoro_task(interaction.client, interaction.user.id)
        new_session = get_pomodoro_session(interaction.user.id)
        embed = build_pomodoro_embed(new_session)
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="จบเซสชัน ⏹️", style=discord.ButtonStyle.danger, custom_id="btn_pomo_stop")
    async def stop_session(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        session = get_pomodoro_session(interaction.user.id)
        _, _, cycles, target = get_session_config(session)
        stop_pomodoro_task(interaction.user.id)
        delete_pomodoro_session(interaction.user.id)

        embed = discord.Embed(
            title="🏁 จบการทำงานแบบ Pomodoro",
            description=(
                f"> 🎉 **ยอดเยี่ยมมาก!** วันนี้คุณทำสำเร็จไปทั้งหมด `{cycles}/{target}` รอบโฟกัส\n"
                f"> เลือกเริ่มต้นรอบใหม่หรือแตะปุ่มด้านล่างเพื่อดำเนินการต่อได้ทันที"
            ),
            color=discord.Color.from_rgb(99, 102, 241),
            timestamp=datetime.now()
        )
        await interaction.edit_original_response(embed=embed, view=PomodoroFinishedView())

def stop_pomodoro_task(user_id: int):
    task = ACTIVE_POMODORO_TASKS.pop(user_id, None)
    if task and not task.done():
        task.cancel()

def start_pomodoro_task(bot: commands.Bot, user_id: int):
    stop_pomodoro_task(user_id)
    ACTIVE_POMODORO_TASKS[user_id] = asyncio.create_task(run_pomodoro_lifecycle(bot, user_id))

async def run_pomodoro_lifecycle(bot: commands.Bot, user_id: int):
    try:
        while True:
            session = get_pomodoro_session(user_id)
            if not session:
                break

            c_id = session["channel_id"]
            mode = session.get("mode")
            work_m, break_m, cycles, target = get_session_config(session)
            end_val = session.get("end_time")
            end_time = parse_end_time(end_val)
            now = get_bangkok_now()
            wait_sec = max((end_time - now).total_seconds(), 0.0)

            if wait_sec > 0:
                await asyncio.sleep(wait_sec)

            session = get_pomodoro_session(user_id)
            if not session:
                break

            if mode == "work":
                new_cycles = cycles + 1
                if new_cycles >= target:
                    delete_pomodoro_session(user_id)
                    total_work_time = target * work_m
                    embed = discord.Embed(
                        title="🏆 ยินดีด้วย! บรรลุเป้าหมาย Pomodoro ครบทั้งหมดแล้ว",
                        description=(
                            f"> 🎖️ **ทำสำเร็จตามเป้าหมาย:** `{target}/{target}` รอบโฟกัส ({total_work_time} นาที)\n"
                            f"> 💆‍♂️ สมองทำงานได้อย่างเต็มประสิทธิภาพแล้ว ถึงเวลาพักผ่อนยาวหรือเสร็จสิ้นภารกิจของวันนี้!"
                        ),
                        color=discord.Color.from_rgb(234, 179, 8),
                        timestamp=datetime.now()
                    )
                    await update_origin_card(bot, c_id, embed=embed, view=PomodoroFinishedView())
                    await send_sandbox_notification(
                        bot,
                        content=f"🎉 <@{user_id}> **ยินดีด้วย! คุณทำงานครบเป้าหมาย {target}/{target} รอบโฟกัสเรียบร้อยแล้ว! 🏆**",
                        embed=embed,
                        channel_id=c_id
                    )
                    break
                else:
                    break_end = get_bangkok_now() + timedelta(minutes=break_m)
                    set_pomodoro_session(user_id, c_id, "break", break_end, work_m, break_m, new_cycles, target)
                    updated_s = get_pomodoro_session(user_id)

                    embed = build_pomodoro_embed(updated_s)
                    view = PomodoroControlView()
                    await update_origin_card(bot, c_id, embed=embed, view=view)
                    await send_sandbox_notification(
                        bot,
                        content=f"🔔 <@{user_id}> **ครบเวลาโฟกัสรอบที่ {new_cycles}/{target} แล้ว!** ได้เวลาพักสายตา {break_m} นาที ☕",
                        embed=embed,
                        channel_id=c_id
                    )
            elif mode == "break":
                work_end = get_bangkok_now() + timedelta(minutes=work_m)
                next_cycle = cycles + 1
                set_pomodoro_session(user_id, c_id, "work", work_end, work_m, break_m, cycles, target)
                updated_s = get_pomodoro_session(user_id)

                embed = build_pomodoro_embed(updated_s)
                view = PomodoroControlView()
                await update_origin_card(bot, c_id, embed=embed, view=view)
                await send_sandbox_notification(
                    bot,
                    content=f"⚡ <@{user_id}> **หมดเวลาพักแล้ว!** ระบบเริ่มนับเวลาโฟกัสรอบที่ `{next_cycle}/{target}` อัตโนมัติ ({work_m} นาที) ลุยต่อกันเลย! 💪",
                    embed=embed,
                    channel_id=c_id
                )
    except asyncio.CancelledError:
        pass
    finally:
        ACTIVE_POMODORO_TASKS.pop(user_id, None)

class PomodoroCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        asyncio.create_task(self.recover_pomodoro_sessions())

    def cog_unload(self):
        for task in list(ACTIVE_POMODORO_TASKS.values()):
            task.cancel()
        ACTIVE_POMODORO_TASKS.clear()

    async def recover_pomodoro_sessions(self):
        await self.bot.wait_until_ready()
        sessions = get_all_active_pomodoro_sessions()
        for s in sessions:
            u_id = s["user_id"]
            start_pomodoro_task(self.bot, u_id)

    pomodoro_group = app_commands.Group(name="pomodoro", description="นาฬิกาโฟกัสการทำงานแบบ Pomodoro 25/5 นาที")

    @pomodoro_group.command(name="start", description="เริ่มรอบโฟกัสการทำงานพร้อมกำหนดจำนวนลูป")
    @app_commands.describe(
        work="เวลาทำงานต่อรอบ (นาที) เช่น 25",
        break_time="เวลาพักสายตาต่อรอบ (นาที) เช่น 5",
        loops="จำนวนรอบ (ลูป) ที่ต้องการทำ เช่น 4"
    )
    async def pomodoro_start(self, interaction: discord.Interaction, work: int = 25, break_time: int = 5, loops: int = 4):
        if not interaction.response.is_done():
            await interaction.response.defer()
        end_time = get_bangkok_now() + timedelta(minutes=work)
        set_pomodoro_session(interaction.user.id, interaction.channel_id, "work", end_time, work, break_time, 0, loops)
        start_pomodoro_task(self.bot, interaction.user.id)
        session = get_pomodoro_session(interaction.user.id)
        embed = build_pomodoro_embed(session)
        await deliver_channel_card(interaction, embed, view=PomodoroControlView())

    @pomodoro_group.command(name="stop", description="หยุดและจบเซสชัน Pomodoro ปัจจุบัน")
    async def pomodoro_stop(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        session = get_pomodoro_session(interaction.user.id)
        if not session:
            embed = discord.Embed(
                title="ℹ️ ไม่พบเซสชันที่กำลังทำงาน",
                description="คุณยังไม่ได้เริ่มเซสชัน Pomodoro ใช้ `/pomodoro start` เพื่อเริ่มรอบโฟกัส",
                color=discord.Color.light_grey()
            )
            await deliver_channel_card(interaction, embed)
            return

        cycles = session.get("cycles_done", 0)
        target = session.get("target_cycles", 4)
        stop_pomodoro_task(interaction.user.id)
        delete_pomodoro_session(interaction.user.id)
        embed = discord.Embed(
            title="🏁 ยุติเซสชัน Pomodoro",
            description=f"> ทำสำเร็จไปทั้งหมด `{cycles}/{target}` รอบโฟกัส บันทึกข้อมูลเรียบร้อยแล้ว",
            color=discord.Color.from_rgb(99, 102, 241),
            timestamp=datetime.now()
        )
        await deliver_channel_card(interaction, embed)

    @pomodoro_group.command(name="status", description="ดูสถานะเวลาโฟกัสปัจจุบัน")
    async def pomodoro_status(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        session = get_pomodoro_session(interaction.user.id)
        if not session:
            embed = discord.Embed(
                title="ℹ️ ยังไม่มีเซสชันที่เริ่มไว้",
                description="พิมพ์ `/pomodoro start` เพื่อเริ่มนาฬิกาโฟกัส",
                color=discord.Color.light_grey()
            )
            await deliver_channel_card(interaction, embed)
            return

        embed = build_pomodoro_embed(session)
        await deliver_channel_card(interaction, embed, view=PomodoroControlView())

async def setup(bot: commands.Bot):
    await bot.add_cog(PomodoroCog(bot))
