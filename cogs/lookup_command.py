import json
import discord
from cogs.helper_methods import _process_lookup, get_coms_by_name
from cogs.builds_command import BuildView
from discord import app_commands
from discord.ext import commands

# --- Load Data and Prepare Choices ---
try:
    with open('data/Type Database.json', 'r', encoding='utf-8') as f:
        SKILL_DATA = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"Error loading data/data.json for LookupCommand cog: {e}")
    SKILL_DATA = {}

try:
    with open('data/Gear.json', 'r', encoding='utf-8') as f:
        COM_DATA = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"Error loading data/Gear.json for Class Mod information: {e}")
    COM_DATA = {}

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
    async def com_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=com.get("name"), value=com.get("name"))
            for com in COM_DATA.get("class mods") if current.lower() in com.get("name").lower()
        ][:25]
        
    # --- Autocomplete Function for the 'name' option ---
    async def skill_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=skill_name, value=skill_name)
            for skill_name in UNIQUE_SKILL_NAMES if current.lower() in skill_name.lower()
        ][:25]
       
    # --- The Slash Command ---
    @app_commands.command(name="com", description="Search Class Mods")
    @app_commands.describe(name="Which Class Mod do you want information on?")
    @app_commands.autocomplete(name=com_name_autocomplete)
    async def com_search(self, interaction: discord.Interaction, name: str):
        response, vault_hunter, show = get_coms_by_name(name, COM_DATA)
        view = BuildView(self, vault_hunter, name)

        await interaction.response.send_message(response, view=view, ephemeral=show)
       
    # --- The Slash Command ---
    # Choices does not support bool, hence the use of an int.
    @app_commands.command(name="lookup", description="Looks up a specific skill/item by its name.")
    @app_commands.describe(name="The name of the skill or item to look up.",
                           com="Include Class mods with this skill, defaults to No.")
    @app_commands.autocomplete(name=skill_name_autocomplete)
    @app_commands.choices(com=[
        app_commands.Choice(name="Yes", value=1),
        app_commands.Choice(name="No", value=0)
    ])
    async def lookup(self, interaction: discord.Interaction, name: str, com: int = 0):
        response, show = _process_lookup(name, com, SKILL_DATA, COM_DATA)

        await interaction.response.send_message(response, ephemeral=show)


# --- Setup Function ---
async def setup(bot: commands.Bot):
    await bot.add_cog(LookupCommand(bot))
    print("✅ Cog 'LookupCommand' loaded.")