import json
import discord
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
    @app_commands.command(name="lookup", description="Looks up a specific item by its exact name.")
    @app_commands.describe(name="The full name of the skill or item to look up.")
    @app_commands.autocomplete(name=skill_name_autocomplete)
    async def lookup(self, interaction: discord.Interaction, name: str):

        found_item = None
        source_key = None # MODIFIED: Add a variable to store the source

        # Search through all data to find the matching item
        for parent_key, items in SKILL_DATA.items():
            for item in items:
                if item.get('name', '').lower().strip() == name.lower().strip():
                    found_item = item
                    source_key = parent_key # NEW: Store the source key when a match is found
                    break
            if found_item:
                break

        # --- Format and Send the Response ---
        if not found_item:
            await interaction.response.send_message(f"Could not find an item named `{name}`.", ephemeral=True)
            return

        response_lines = [f"🔎 Results for search: **{found_item.get('name')}**", "\n**# Skill Details**"]

        # NEW: Add the source to the output
        if source_key:
            response_lines.append(f"- **Source**: {source_key}")

        for key, value in found_item.items():
            if value is not None:
                formatted_key = key.replace('_', ' ').title()
                response_lines.append(f"- **{formatted_key}**: {value}")

        await interaction.response.send_message("\n".join(response_lines))


# --- Setup Function ---
async def setup(bot: commands.Bot):
    await bot.add_cog(LookupCommand(bot))
    print("✅ Cog 'LookupCommand' loaded.")