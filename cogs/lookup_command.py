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
        # 1. Initialize a list to store all matching items, not just one.
        found_items = []
        
        # Pre-process the search name once to be more efficient
        search_name = name.lower().strip()

        # 2. Search through all data without breaking after the first match.
        for parent_key, items in SKILL_DATA.items():
            for item in items:
                # 3. Use the 'in' operator for substring search.
                if search_name in item.get('name', '').lower().strip():
                    # Add a dictionary containing both the item and its source to our list.
                    found_items.append({'item': item, 'source': parent_key})

        # --- Format and Send the Response ---

        # 4. Check if the list of found items is empty.
        if not found_items:
            await interaction.response.send_message(f"Could not find any item containing `{name}`.", ephemeral=True)
            return

        # 5. Build the response message.
        # Start with a summary of how many results were found.
        response_lines = [f"🔎 Found **{len(found_items)}** results for: **{name}**"]

        # Loop through each match you found.
        for match in found_items:
            item_data = match['item']
            source_key = match['source']

            # Add a separator and a main header for each item for clarity.
            response_lines.append("\n---")
            response_lines.append(f"**# {item_data.get('name')}**")
            
            # Add the source.
            response_lines.append(f"- **Source**: {source_key}")

            # Add all other details from the item's dictionary.
            for key, value in item_data.items():
                # Skip the 'name' key since we already used it in the header.
                if key != 'name' and value is not None:
                    formatted_key = key.replace('_', ' ').title()
                    response_lines.append(f"- **{formatted_key}**: {value}")

        final_response = "\n".join(response_lines)
        
        # Note: Discord messages have a 2000 character limit. 
        # If the combined result is too long, you might need to implement pagination.
        if len(final_response) > 2000:
            final_response = final_response[:1990] + "\n... (truncated)"

        await interaction.response.send_message(final_response)


# --- Setup Function ---
async def setup(bot: commands.Bot):
    await bot.add_cog(LookupCommand(bot))
    print("✅ Cog 'LookupCommand' loaded.")