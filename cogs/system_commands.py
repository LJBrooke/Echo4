import os
import discord
from discord import app_commands
from discord.ext import commands
from helpers import sync_parts

# Load your specific user ID from the .env file.
OWNER_ID = int(os.getenv("OWNER_ID", 0))
# NEW: Load the admin server ID
ADMIN_SERVER_ID = int(os.getenv("ADMIN_SERVER_ID", 0))


class SystemCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
    @app_commands.command(name="sync_sheet", description="[Owner Only] Force-sync the Google Sheet with the database.")
    @commands.is_owner()
    async def sync_part_sheet(self, interaction: discord.Interaction):
        """
        Runs the Google Sheet sync process.
        """
        try:
            # Failsafe for commands.is_owner() not working.
            if interaction.user.id != OWNER_ID:
                await interaction.response.send_message("You do not have permission to use this command. If you have found old data please report it to Prismatic.", ephemeral=True)
            
            # Defer the response, as this will take several seconds
            await interaction.response.defer(ephemeral=True)
            
            # Call the helper function, passing the bot's session and db_pool
            status_message = await sync_parts.sync_part_sheet(
                session=self.bot.session,
                db_pool=self.bot.db_pool
            )
            await interaction.followup.send(status_message, ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

    @sync_part_sheet.error
    async def on_sync_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Error handler for the sync command"""
        if isinstance(error, app_commands.NotOwner):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        else:
            print(f"Error in sync command: {error}")
            if interaction.response.is_done():
                await interaction.followup.send("An unknown error occurred.", ephemeral=True)
            else:
                await interaction.response.send_message("An unknown error occurred.", ephemeral=True)
                
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
        
    @app_commands.command(name="credits", description="Who builds the Bot?")
    async def creadits(self, interaction: discord.Interaction):
        credits='''**Bot Developer:**
- **Prismatic**

**Contributors**
- **Girthquake**: Filled out Amon information and endless support promoting this bot.
- **JoeForLong**: Filled out Rafa information.
- **Ratore**: Filled out Vex information.
        '''
        await interaction.response.send_message(credits)

    @app_commands.command(name="news", description="Borderlands 4 Update Notes.")
    async def updates(self, interaction: discord.Interaction):
        updates='''[The latest Borderlands 4 Patch notes can be found here](https://borderlands.2k.com/borderlands-4/update-notes/)
        '''
        await interaction.response.send_message(updates)


async def setup(bot: commands.Bot):
    # This check ensures the commands are only added if the ID is set
    if ADMIN_SERVER_ID != 0:
        await bot.add_cog(SystemCommands(bot))
        print("✅ Cog 'SystemCommands' loaded and restricted to the admin server.")
    else:
        print("⚠️ Cog 'SystemCommands' not loaded: ADMIN_SERVER_ID is not set in .env file.")