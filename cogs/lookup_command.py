import json
import discord
import asyncpg
from helpers.helper_methods import _process_lookup, get_coms_by_name
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
    def __init__(self, bot: commands.Bot,  db_pool: asyncpg.Pool):
        self.bot = bot
        self.db_pool = db_pool

    # --- Autocomplete Function for the 'name' option ---
    async def com_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=com.get("name"), value=com.get("name"))
            for com in COM_DATA.get("class mods") if current.lower() in com.get("name").lower()
        ][:25]
        
    async def lookup_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocompletes the 'name' argument for the /lookup command."""
        
        # Don't query on an empty string, just return no results
        if not current:
            return []

        # Use a more efficient query for autocomplete:
        # - ILIKE for case-insensitive matching
        # - `current%` (instead of `%current%`) for "starts-with" matching, which is much faster
        #   and more intuitive for autocomplete.
        # - LIMIT 25 is the max Discord allows.
        search_term = f"{current}%"
        query = "SELECT DISTINCT name FROM entities WHERE name ILIKE $1 LIMIT 25;"
        
        choices = []
        try:
            # We don't need a full transaction, just a single connection
            async with self.db_pool.acquire() as conn:
                results = await conn.fetch(query, search_term)
                choices = [
                    app_commands.Choice(name=record['name'], value=record['name'])
                    for record in results
                ]
        except Exception as e:
            # Log the error, but don't crash the autocomplete
            print(f"Autocomplete error: {e}")
            
        return choices
       
    def _format_entity_embed(self, record: asyncpg.Record, tree_id: int | None) -> discord.Embed:
        """
        Takes a single database record and formats it into a rich Discord embed.
        """
        
        # The 'attributes' column is auto-decoded from JSONB into a Python dict
        attributes_raw = record['attributes']

        # asyncpg might return the JSONB as a string instead of auto-decoding.
        # We'll manually parse it if it's a string.
        if isinstance(attributes_raw, str):
            try:
                attributes = json.loads(attributes_raw)
            except json.JSONDecodeError:
                # Fallback for corrupted data
                attributes = {"name": "Error: Corrupted Data"}
        else:
            attributes = attributes_raw
        
        # --- 1. Set Color based on Tree ID ---
        colour = discord.Color.blurple() # Default
        if tree_id is not None:
            # Apply your modulo logic: 1, 4, 7, 10 -> Green
            # 2, 5, 8, 11 -> Blue
            # 3, 6, 9, 12 -> Red
            match tree_id % 3:
                case 1: # 1, 4, 7, 10
                    colour = discord.Color.green()
                case 2: # 2, 5, 8, 11
                    colour = discord.Color.blue()
                case 0: # 3, 6, 9, 12
                    colour = discord.Color.orange()
        
        # Create the base embed with the entity's name
        embed = discord.Embed(
            title=record['name'],
            color=colour
        )

        # 1. Set Description
        if attributes.get('description'):
            # Use the .replace() from our ingestion script to restore newlines
            embed.description = attributes['description'].replace('.\\n', '.\n')

        # 2. Set Author (to show source)
        source_text = record['source_category'].upper()
        if record['char_name']:
            source_text += f" ({record['char_name'].title()})"
        if record['tree_name']:
            source_text += f" - {record['tree_name']}"
        embed.set_author(name=source_text)

        # 3. Set Thumbnail (the "top right bit")
        # This is where we use the extracted icon URL
        icon_url = attributes.get('icon_url')
        if icon_url:
            embed.set_thumbnail(url=icon_url)

        # 4. Add all other attributes as fields
        # These are keys we've already handled in the main embed parts
        RESERVED_KEYS = {'description', 'icon_url', 'damage_effects', 'name', 'condition', 'sub_branch'}
        
        for key, value in attributes.items():
            if key in RESERVED_KEYS or value is None:
                continue
            
            # Format key (e.g., "max_points" -> "Max Points")
            field_name = key.replace('_', ' ').title()
            
            # --- APPLY TIER BRACKETING (Rule 3) ---
            field_value = str(value) # Default
            if key == 'tier':
                try:
                    # Get 0-based tier and context
                    original_tier = int(value)
                    sub_branch = attributes.get('sub_branch')
                    
                    # Rule 1: +1 to all tiers
                    display_tier = original_tier + 1
                    
                    # Rule 2: +3 for side branches
                    if sub_branch in ('left', 'middle', 'right'):
                        display_tier += 3
                        
                    # Rule 3: Bracketing
                    field_value = f"{display_tier}: {sub_branch.title()}"
                except (ValueError, TypeError):
                    field_value = f"[{value}]" # Fallback if tier isn't a number
            # --- END TIER BRACKETING ---
            
            embed.add_field(name=field_name, value=field_value, inline=True)

        # 5. Handle the nested 'damage_effects' (for skills like Decoherence)
        if 'damage_effects' in attributes:
            effects_list = attributes['damage_effects']
            effects_text = []
            
            for effect in effects_list:
                # Use the 'condition' (e.g., "Effect 1") as the name if it exists
                name = effect.get('condition') or effect.get('name', 'Effect')
                dtype = effect.get('damage type', 'N/A')
                dcat = effect.get('damage category', 'N/A')
                if dcat != 'N/A':
                    effects_text.append(f"**{name}**: {dtype} ({dcat})")
                else:
                    effects_text.append(f"**{name}**: {dtype}")
            
            embed.add_field(
                name="Damage Effects", 
                value="\n".join(effects_text), 
                inline=False
            )
            
        return embed
    
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
    @app_commands.command(name="lookup", description="Search for any skill, item, or enhancement.")
    @app_commands.autocomplete(name=lookup_autocomplete)
    @app_commands.describe(
        name="The name of the item to search for.",
        find_coms="Set to True to also find COMs that boost this skill."
    )
    async def lookup(self, interaction: discord.Interaction, name: str, find_coms: bool = False):
        """
        The main slash command logic.
        """
        # Defer response as database queries can take a moment
        await interaction.response.defer(ephemeral=False)
        
        embeds = []
        async with self.db_pool.acquire() as conn:
            # --- 1. Main Entity Search ---
            # This query uses ILIKE for case-insensitive partial matching
            # and joins to get character/tree names.
            search_term = f"%{name}%"
            query = """
                SELECT e.*, c.name as char_name, st.name as tree_name
                FROM entities e
                LEFT JOIN characters c ON e.character_id = c.id
                LEFT JOIN skill_trees st ON e.tree_id = st.id
                WHERE e.name ILIKE $1
                LIMIT 5;
            """
            results = await conn.fetch(query, search_term)

            # --- 2. (Optional) COM Search ---
            com_results = []
            if find_coms:
                # *** ASSUMPTION ***
                # This query assumes your COM entities will have a JSONB attribute
                # named 'boosts' that is an *array of skill names*.
                # e.g., "attributes": {"boosts": ["Decoherence", "A-causality"]}
                com_query = """
                    SELECT name, attributes
                    FROM entities
                    WHERE source_category = 'COM'
                    AND attributes->'boosts' ? $1;
                """
                # We use the *exact name* for this, not the partial search_term
                com_results = await conn.fetch(com_query, name)

            # --- 3. Format the Results ---
            if not results and not com_results:
                await interaction.followup.send(
                    f"Could not find any information for `{name}`.", 
                    ephemeral=True
                )
                return

            # Add COM embed first if it exists
            if com_results:
                com_lines = [f"• **{com['name']}**" for com in com_results]
                com_embed = discord.Embed(
                    title=f"COMs that boost '{name}'",
                    description="\n".join(com_lines),
                    color=discord.Color.orange()
                )
                embeds.append(com_embed)
            
            # Add all main results
            for record in results:
                tree_id = record['tree_id']
                embed = self._format_entity_embed(record, tree_id)
                embeds.append(embed)

        # Send all found embeds (up to 10, Discord's limit)
        await interaction.followup.send(embeds=embeds[:10])

# --- Setup Function ---
async def setup(bot: commands.Bot):
    await bot.add_cog(LookupCommand(bot, bot.db_pool))
    print("✅ Cog 'LookupCommand' loaded.")