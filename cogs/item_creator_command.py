import discord
from discord import app_commands
from discord.ext import commands
from helpers import item_parser
from helpers.creator_engine import CreatorSession
from views.creator_views import CreatorDashboardView
import logging

log = logging.getLogger(__name__)

class CreatorCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.active_editor_sessions = {}
        self.bot = bot
        self.db_pool = bot.db_pool  # Assume bot has a db_pool attribute

    async def balance_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        # Reusing your existing autocomplete from parts_command/item_parser
        return await item_parser.balance_autocomplete(self, interaction, current)

    @app_commands.command(name="create_item", description="Interactively build a new item using the Echo rules engine.")
    @app_commands.describe(balance_file="The game balance file (archetype) to use as a template")
    @app_commands.autocomplete(balance_file=balance_autocomplete)
    async def create_item(self, interaction: discord.Interaction, balance_file: str):
        # 1. Defer immediately
        await interaction.response.defer(ephemeral=False)

        try:
            # 2. Fetch Balance Data
            balance_file = balance_file.split('|')  # Expecting format "BalanceName|InvType"
            balance_data = await item_parser.query_item_balance_explicit(self.db_pool, balance_file[0], balance_file[1])
            
            self.active_editor_sessions[interaction.user.id] = "initializing"
            
            if not balance_data:
                await interaction.followup.send(f"❌ Error: Could not load balance file: `{balance_file}`.", ephemeral=True)
                return

            # 3. Initialize Session
            session = CreatorSession(
                user_id=interaction.user.id,
                balance_name=balance_file,
                balance_data=balance_data,
                db_pool=self.bot.db_pool,
                session=self.bot.session
            )
            
            # 4. Run Preliminary Scan
            # We await this to ensure we have valid slots before rendering
            await session.initialize()

            # DEBUG: Check if we actually found slots
            if not session.active_slots:
                await interaction.followup.send(
                    f"⚠️ **Warning:** No compatible parts found for `{session.item_type}` or `{session.parent_type}`.\n"
                    f"Please check if the `inv` column in your `all_parts` matches these types."
                )
                self.active_editor_sessions.pop(interaction.user.id, None) # Cleanup
                return

            # 5. Send Loading Message (placeholder)
            embed = discord.Embed(
                title=f"Initializing {balance_file}...",
                description="Loading rule set and part databases...",
                color=discord.Color.light_grey()
            )
            msg = await interaction.followup.send(embed=embed)

            # 6. Initialize View with the Message Reference
            # Passing 'msg' allows the view to edit it directly, which is more stable.
            view = CreatorDashboardView(session, self, interaction.user.id, msg)
            
            # 7. Trigger First Render
            await view.update_view(interaction)

        except Exception as e:
            log.error(f"Crash in create_item: {e}", exc_info=True)
            await interaction.followup.send(f"💥 **Critical Error:** {str(e)}", ephemeral=True)
            self.active_editor_sessions.pop(interaction.user.id, None)

async def setup(bot: commands.Bot):
    await bot.add_cog(CreatorCommand(bot))