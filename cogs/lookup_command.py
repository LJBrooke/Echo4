import json
import discord
from cogs.helper_methods import _process_lookup
from discord import app_commands
from discord.ext import commands

# --- Load Data and Prepare Choices ---
try:
    with open('data/Type Database.json', 'r', encoding='utf-8') as f:
        SKILL_DATA = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"Error loading data/data.json for LookupCommand cog: {e}")
    SKILL_DATA = {}

# --- Prepare Autocomplete Choices for all skill names ---
UNIQUE_SKILL_NAMES = sorted(list(set(
    item['name'].strip()
    for items in SKILL_DATA.values()
    for item in items if item.get('name')
)))


# --- Define the Cog Class ---
class LookupCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- Autocomplete Function for the 'name' option ---
    async def skill_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=skill_name, value=skill_name)
            for skill_name in UNIQUE_SKILL_NAMES if current.lower() in skill_name.lower()
        ][:25]
       
    # --- The Slash Command ---
    @app_commands.command(name="lookup", description="Looks up a specific skill by its name.")
    @app_commands.describe(name="The name of the skill or item to look up.")
    @app_commands.autocomplete(name=skill_name_autocomplete)
    async def lookup(self, interaction: discord.Interaction, name: str):
        response, show = _process_lookup(name)

        await interaction.response.send_message(response, ephemeral=show)


# --- Setup Function ---
async def setup(bot: commands.Bot):
    await bot.add_cog(LookupCommand(bot))
    print("✅ Cog 'LookupCommand' loaded.")