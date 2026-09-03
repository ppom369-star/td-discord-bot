import discord
from database.db_manager import get_setting, set_setting

DASHBOARD_CHANNELS = {
    1544563713548488765: "help",
    1544548008786530374: "daily_brief",
    1544548048837808278: "commands",
    1544548130404573204: "quick_notes",
    1544579305806241802: "expense",
    1544575570380197888: "fuel"
}

async def deliver_channel_card(
    interaction: discord.Interaction,
    embed: discord.Embed,
    view: discord.ui.View = None
):
    channel = interaction.channel
    is_dashboard = isinstance(channel, discord.TextChannel) and channel.id in DASHBOARD_CHANNELS

    if not is_dashboard:
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, view=view)
        else:
            await interaction.edit_original_response(content=None, embed=embed, view=view)
        return

    setting_key = f"channel_card_{channel.id}"
    msg_id_str = get_setting(setting_key)

    is_component_or_modal = interaction.type in (
        discord.InteractionType.component,
        discord.InteractionType.modal_submit
    )

    if is_component_or_modal and interaction.message:
        if not interaction.response.is_done():
            try:
                await interaction.response.edit_message(content=None, embed=embed, view=view)
            except Exception:
                try:
                    await interaction.message.edit(content=None, embed=embed, view=view)
                    await interaction.response.defer()
                except Exception:
                    pass
        else:
            try:
                await interaction.message.edit(content=None, embed=embed, view=view)
            except Exception:
                pass
        set_setting(setting_key, str(interaction.message.id))
        return

    target_msg = None
    if msg_id_str:
        try:
            target_msg = await channel.fetch_message(int(msg_id_str))
        except Exception:
            target_msg = None

    if target_msg:
        try:
            await target_msg.edit(embed=embed, view=view)
            if not interaction.response.is_done():
                try:
                    await interaction.response.defer(ephemeral=True)
                except Exception:
                    pass
            return
        except Exception:
            target_msg = None

    if not interaction.response.is_done():
        await interaction.response.send_message(embed=embed, view=view)
    else:
        await interaction.edit_original_response(content=None, embed=embed, view=view)

    try:
        orig = await interaction.original_response()
        set_setting(setting_key, str(orig.id))
    except Exception:
        pass
