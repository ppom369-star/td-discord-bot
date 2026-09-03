import asyncio
import os
import sys
from dotenv import load_dotenv
import discord
from discord import app_commands
from discord.ext import commands
from database.db_manager import init_db, get_database_diagnostics
from keep_alive import start_keep_alive
from cogs.weather import WeatherDashboardView
from cogs.pomodoro import PomodoroControlView, PomodoroFinishedView
from cogs.expense import ExpenseDashboardView
from cogs.fuel import FuelDashboardView
from cogs.todo import TodoDashboardView
from cogs.utility import CommandCenterView

load_dotenv()

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.getenv("PORT", "8080"))
OWNER_USER_ID = int(os.getenv("OWNER_USER_ID", "372796686323417089"))

class TDBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.typing = False
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
            max_messages=None
        )

    async def setup_hook(self):
        init_db()
        print(f"[DB STATUS] {get_database_diagnostics()}", flush=True)
        await start_keep_alive(PORT)
        
        cogs_dir = os.path.join(os.path.dirname(__file__), "cogs")
        for filename in os.listdir(cogs_dir):
            if filename.endswith(".py") and not filename.startswith("__") and filename != "news.py":
                extension_name = f"cogs.{filename[:-3]}"
                try:
                    await self.load_extension(extension_name)
                    print(f"Loaded extension: {extension_name}", flush=True)
                except Exception as err:
                    print(f"Failed to load extension {extension_name}: {err}", file=sys.stderr, flush=True)

        self.add_view(WeatherDashboardView())
        self.add_view(PomodoroControlView())
        self.add_view(PomodoroFinishedView())
        self.add_view(ExpenseDashboardView())
        self.add_view(FuelDashboardView())
        self.add_view(TodoDashboardView())
        self.add_view(CommandCenterView())

        def verify_admin_permission(interaction: discord.Interaction) -> bool:
            if not interaction.guild or not isinstance(interaction.user, discord.Member):
                return False
            perms = interaction.user.guild_permissions
            return (
                interaction.guild.owner_id == interaction.user.id
                or perms.administrator
                or perms.manage_guild
                or perms.manage_channels
            )

        async def global_interaction_check(interaction: discord.Interaction) -> bool:
            if interaction.user.id == OWNER_USER_ID:
                return True

            cmd = interaction.command
            cmd_name = cmd.root_parent.name if (cmd and cmd.root_parent) else (cmd.name if cmd else None)

            if cmd_name == "youtube":
                if not interaction.guild:
                    await interaction.response.send_message("❌ คำสั่งนี้สามารถใช้ได้เฉพาะในเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
                    return False
                if verify_admin_permission(interaction):
                    return True
                await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมิน, ผู้ดูแลห้อง หรือเจ้าของบอท)", ephemeral=True)
                return False

            if cmd_name in ("ai", "ask"):
                sub_cmd = cmd.name if cmd else ""
                if sub_cmd in ("set_channel", "remove_channel"):
                    if not interaction.guild:
                        await interaction.response.send_message("❌ คำสั่งนี้ใช้ได้เฉพาะในเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
                        return False
                    if verify_admin_permission(interaction):
                        return True
                    await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ตั้งค่าห้อง AI (ต้องเป็นแอดมิน)", ephemeral=True)
                    return False
                return True

            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("⛔ ฟังก์ชันนี้เป็นฟังก์ชันส่วนตัวเฉพาะเจ้าของบอทเท่านั้น", ephemeral=True)
            except Exception:
                pass
            return False

        self.tree.interaction_check = global_interaction_check

        @self.tree.error
        async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            err_text = "❌ เกิดข้อผิดพลาดในการประมวลผลคำสั่ง กรุณาลองใหม่อีกครั้ง"
            if isinstance(error, app_commands.CommandOnCooldown):
                err_text = f"⏳ คำสั่งนี้ติด Cooldown กรุณารออีก {error.retry_after:.1f} วินาที"
            elif isinstance(error, app_commands.MissingPermissions):
                err_text = "⛔ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้"

            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(err_text, ephemeral=True)
                else:
                    await interaction.followup.send(err_text, ephemeral=True)
            except Exception:
                pass

        try:
            print("Syncing slash commands globally...", flush=True)
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} slash commands globally.", flush=True)
        except Exception as err:
            print(f"Failed to sync slash commands: {err}", file=sys.stderr, flush=True)

    async def on_ready(self):
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="/today | /weather | /help"
        )
        await self.change_presence(activity=activity, status=discord.Status.online)
        print(f"Bot connected successfully as: {self.user} (ID: {self.user.id})", flush=True)
        print(f"Serving in {len(self.guilds)} guilds.", flush=True)

async def main():
    if not TOKEN:
        print("Error: DISCORD_TOKEN is missing in environment variables.", file=sys.stderr)
        sys.exit(1)

    bot = TDBot()
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by user.")
