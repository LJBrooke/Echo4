import os
import discord
from discord import app_commands
from discord.ext import commands

# Load your specific user ID from the .env file.
OWNER_ID = int(os.getenv("OWNER_ID", 0))
# NEW: Load the admin server ID
ADMIN_SERVER_ID = int(os.getenv("ADMIN_SERVER_ID", 0))


class SystemCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # MODIFIED: Added the 'guilds' parameter to restrict this command
    @app_commands.command(name="refresh", description="[Owner Only] Refreshes all cogs and syncs commands.")
    @app_commands.guilds(ADMIN_SERVER_ID)
    async def refresh(self, interaction: discord.Interaction):
        """Refreshes all cogs, reloading code changes."""
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        
        reloaded_cogs = []
        for cog in list(self.bot.extensions.keys()):
            try:
                await self.bot.reload_extension(cog)
                reloaded_cogs.append(cog.split('.')[-1])
            except Exception as e:
                await interaction.followup.send(f"Failed to reload `{cog}`: {e}")
                return
        
        # We sync only to the admin guild for an instant update
        await self.bot.tree.sync(guild=discord.Object(id=ADMIN_SERVER_ID))
        
        await interaction.followup.send(f"✅ Successfully reloaded cogs: `{', '.join(reloaded_cogs)}` and synced commands to the admin server.")

    # MODIFIED: Added the 'guilds' parameter to restrict this command
    @app_commands.command(name="shutdown", description="[Owner Only] Shuts the bot down.")
    @app_commands.guilds(ADMIN_SERVER_ID)
    async def shutdown(self, interaction: discord.Interaction):
        """Shuts the bot down gracefully."""
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return
        
        await interaction.response.send_message("Shutting down...", ephemeral=True)
        await self.bot.close()
        
    # MODIFIED: Added the 'guilds' parameter to restrict this command
    @app_commands.command(name="creator", description="Who builds the Bot?.")
    async def creator(self, interaction: discord.Interaction):
        credits='''**Creator:**
- **Prismatic**

**Contributors**
- **Girthquake**: Filled out Amon information.
- **JoeForLong**: Filled out Rafa information.
- **Ratore**: Filled out Vex information.
        '''
        await interaction.response.send_message(credits)


async def setup(bot: commands.Bot):
    # This check ensures the commands are only added if the ID is set
    if ADMIN_SERVER_ID != 0:
        await bot.add_cog(SystemCommands(bot))
        print("✅ Cog 'SystemCommands' loaded and restricted to the admin server.")
    else:
        print("⚠️ Cog 'SystemCommands' not loaded: ADMIN_SERVER_ID is not set in .env file.")