import json
import discord
from discord import app_commands
from discord.ext import commands

# --- Load Data and Prepare Choices (Self-contained within the cog file) ---
try:
    with open('data/Type Database.json', 'r', encoding='utf-8') as f:
        SKILL_DATA = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"Error loading data.json for FindCommand cog: {e}")
    SKILL_DATA = {}

UNIQUE_DAMAGE_TYPES = sorted(list(set(
    item['damage type'].lower().strip()
    for items in SKILL_DATA.values()
    for item in items if item.get('damage type')
)))
UNIQUE_SOURCES = sorted(list(SKILL_DATA.keys()))


# --- Define the Cog Class ---
# A cog is a class that inherits from commands.Cog.
class FindCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- Autocomplete Functions (now methods of the class) ---
    async def damage_type_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=dt, value=dt)
            for dt in UNIQUE_DAMAGE_TYPES if current.lower() in dt.lower()
        ][:25]

    async def source_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=source, value=source)
            for source in UNIQUE_SOURCES if current.lower() in source.lower()
        ][:25]

    # --- The Slash Command (now a method of the class) ---
    # The decorator changes from @bot.tree.command to @app_commands.command
    @app_commands.command(name="find", description="Finds items by their damage type.")
    @app_commands.describe(
        damage_type="The damage type you want to search for.",
        source="Optional: Restrict the search to only this source (e.g., COM, Harlowe)."
    )
    @app_commands.autocomplete(damage_type=damage_type_autocomplete, source=source_autocomplete)
    async def find(self, interaction: discord.Interaction, damage_type: str, source: str = None):
        """The main logic for the find command, same as before."""
        results = {}
        search_area = {source: SKILL_DATA[source]} if source and source in SKILL_DATA else SKILL_DATA
        if not source and damage_type.lower().strip()=='soup':
            search_area.pop('Amon', None)
            search_area.pop('Harlowe', None)
            search_area.pop('Rafa', None)
            search_area.pop('Vex', None)
            
        for parent_key, items in search_area.items():
            matching_items = [
                item['name'] for item in items
                if item.get('damage type') and item['damage type'].lower().strip() == damage_type.lower().strip()
            ]
            if matching_items:
                results[parent_key] = matching_items

        if not results:
            await interaction.response.send_message(f"No items found with damage type: `{damage_type}`.", ephemeral=True)
            return

        response_lines = [f"🔎 Results for damage type: **{damage_type.title()}**"]
        if source:
            response_lines.append(f"Filtered by source: **{source}**")
        elif not source and damage_type.lower().strip()=='soup':
            response_lines.append(f"\nTo see VH specific Soup, please filter by VH. \nApologies from DCLP. \n_DCLP=Discord Character Limit Police_")
        response_lines.append("-" * 20)

        for parent_key, names in results.items():
            response_lines.append(f"**# {parent_key}**")
            for name in names:
                response_lines.append(f"- {name}")
            response_lines.append("")

        final_response = "\n".join(response_lines)
        if len(final_response) > 2000:
            final_response = final_response[:1975] + "\n... (results truncated)"
        
        await interaction.response.send_message(final_response)


# --- Setup Function ---
# This special function is called when the cog is loaded.
async def setup(bot: commands.Bot):
    await bot.add_cog(FindCommand(bot))
    print("✅ Cog 'FindCommand' loaded.")