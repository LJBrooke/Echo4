import discord
import asyncpg
import json
from discord import app_commands
from discord.ext import commands

class LookupCommand(commands.Cog):
    def __init__(self, bot: commands.Bot, db_pool: asyncpg.Pool):
        self.bot = bot
        self.db_pool = db_pool

    async def lookup_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """Autocompletes the 'name' argument."""
        if not current:
            return []
        
        search_term = f"{current}%"
        # We query for names that start with the input
        query = "SELECT DISTINCT name FROM entities WHERE name ILIKE $1 LIMIT 25;"
        
        choices = []
        try:
            async with self.db_pool.acquire() as conn:
                results = await conn.fetch(query, search_term)
                choices = [
                    app_commands.Choice(name=record['name'], value=record['name'])
                    for record in results
                ]
        except Exception as e:
            print(f"Autocomplete error: {e}")
            
        return choices

    # --- FORMATTER 1: CLASS MODS ---
    def _format_class_mod_embed(self, record: asyncpg.Record, attributes: dict) -> discord.Embed:
        """
        Specialized embed formatting for Class Mods.
        Handles: Rarity colors, Red Text, Boosted Skills, and Drop Info.
        """
        # 1. Determine Color based on Rarity (Defaulting to Orange if unknown)
        rarity = attributes.get('rarity', 'Common')
        color_map = {
            'Legendary': discord.Color.orange(),
            'Epic': discord.Color.purple(),
            'Purple': discord.Color.purple(),
            'Rare': discord.Color.blue(),
            'Uncommon': discord.Color.green(),
            'Common': discord.Color.light_grey()
        }
        color = color_map.get(rarity, discord.Color.orange())

        # 2. Build Base Embed
        embed = discord.Embed(
            title=record['name'],
            color=color,
            url=attributes.get('lootlemon') # Link title to Lootlemon if available
        )
        

        # 3. Author: "Class Mod • Character Name"
        char_name = record.get('char_name')
        author_text = "Class Mod"
        if char_name:
            author_text += f" • {char_name.title()}"
        embed.set_author(name=author_text)

        thumbnail_url='https://cdn.prod.website-files.com/5ff36780a1084987868ce198/68e22a55c2e072fddfb3b422_Harlowe.avif'
        if char_name.title()=='Amon':
            thumbnail_url='https://cdn.prod.website-files.com/5ff36780a1084987868ce198/68e22a5db725b2d289f4f526_Amon.avif'
        elif char_name.title()=='Rafa':
            thumbnail_url='https://cdn.prod.website-files.com/5ff36780a1084987868ce198/68e22a4d705bce252742b8a9_Rafa.avif'
        elif char_name.title()=='Vex':
            thumbnail_url='https://cdn.prod.website-files.com/5ff36780a1084987868ce198/68e22a40a94f8477fe7d1c2e_Vex.avif'
        embed.set_thumbnail(url=thumbnail_url)
        
        # 4. Description: Red Text (in italics for flavor)
        if attributes.get('red_text'):
            embed.description = f"*{attributes['red_text']}*"

        # 5. Skills List (Formatted as bullet points)
        if attributes.get('skills'):
            skills = attributes['skills']
            if isinstance(skills, list):
                value = "\n".join([f"• {s}" for s in skills])
                embed.add_field(name="Skills Boosted", value=value, inline=False)

        # 6. Specific Class Mod Stats
        if attributes.get('fixed_stat'):
            embed.add_field(name="Fixed Stat", value=attributes['fixed_stat'], inline=True)

        if attributes.get('passive_count'):
            embed.add_field(name="Passives", value=str(attributes['passive_count']), inline=True)

        if attributes.get('drop_location'):
            embed.add_field(name="Drop Source", value=attributes['drop_location'], inline=True)

        # 7. Notes
        if attributes.get('skill_notes'):
            embed.add_field(name="Notes", value=attributes['skill_notes'], inline=False)
            
        return embed

    # --- FORMATTER 2: SKILLS & GENERAL ENTITIES ---
    def _format_skill_embed(self, record: asyncpg.Record, tree_id: int | None, attributes: dict) -> discord.Embed:
        """
        Standard formatting for Skills, Enhancements, and generic items.
        """
        # 1. Set Color based on Tree ID (Modulo logic)
        color = discord.Color.dark_grey()
        if tree_id is not None:
            match tree_id % 3:
                case 1: color = discord.Color.green()
                case 2: color = discord.Color.blue()
                case 0: color = discord.Color.red()
        
        embed = discord.Embed(title=record['name'], color=color)

        # 2. Description
        if attributes.get('description'):
            embed.description = attributes['description'].replace('.\\n', '.\n')

        # 3. Author (Source Category + Character/Tree)
        source_text = record['source_category'].upper()
        if record['char_name']:
            source_text += f" ({record['char_name'].title()})"
        if record['tree_name']:
            source_text += f" - {record['tree_name']}"
        embed.set_author(name=source_text)

        # 4. Thumbnail
        if attributes.get('icon_url'):
            embed.set_thumbnail(url=attributes['icon_url'])

        # 5. Dynamic Attributes Loop
        # Keys to exclude from the generic field loop because they are handled elsewhere
        RESERVED_KEYS = {'description', 'icon_url', 'damage_effects', 'name', 'condition', 'sub_branch'}
        
        for key, value in attributes.items():
            if key in RESERVED_KEYS or value is None:
                continue
            
            field_name = key.replace('_', ' ').title()
            
            # Logic for formatted Tiers
            field_value = str(value)
            if key == 'tier':
                try:
                    original_tier = int(value)
                    sub_branch = attributes.get('sub_branch')
                    display_tier = original_tier + 1
                    if sub_branch in ('left', 'middle', 'right'):
                        display_tier += 3
                    field_value = f"[{display_tier}]"
                except (ValueError, TypeError):
                    field_value = f"[{value}]"
            
            embed.add_field(name=field_name, value=field_value, inline=True)

        # 6. Damage Effects (for complex skills)
        if 'damage_effects' in attributes:
            effects_list = attributes['damage_effects']
            effects_text = []
            
            for effect in effects_list:
                name = effect.get('condition') or effect.get('name', 'Effect')
                
                # Build details string (e.g., "Gun Damage, Soup")
                details_parts = []
                if effect.get('damage type'): details_parts.append(effect['damage type'])
                if effect.get('damage category'): details_parts.append(effect['damage category'])
                
                details_str = f" ({', '.join(details_parts)})" if details_parts else ""
                effects_text.append(f"**{name}**{details_str}")
            
            embed.add_field(name="Damage Effects", value="\n".join(effects_text), inline=False)
            
        return embed

    # --- MAIN DISPATCHER ---
    def _format_entity_embed(self, record: asyncpg.Record, tree_id: int | None) -> discord.Embed:
        """
        Routes the record to the correct formatter based on source_category.
        """
        # 1. Safe JSON Parsing
        attributes_raw = record['attributes']
        if isinstance(attributes_raw, str):
            try:
                attributes = json.loads(attributes_raw)
            except json.JSONDecodeError:
                attributes = {"name": "Error: Corrupted Data"}
        else:
            attributes = attributes_raw

        # 2. Dispatch Logic
        source = record['source_category']
        
        # You can add more 'if' blocks here if you add new types (like 'Shield' or 'Gun')
        if source == 'Class Mod':
            return self._format_class_mod_embed(record, attributes)
        else:
            # Fallback for Skills, Action Skills, Augments, Enhancements, etc.
            return self._format_skill_embed(record, tree_id, attributes)

    @app_commands.command(name="lookup", description="Search for any skill, item, or enhancement.")
    @app_commands.describe(
        name="The name of the item to search for.",
        type="[Optional] Restrict search types",
        find_coms="[Skills only] Set to True to also find COMs that boost this skill."
    )
    @app_commands.autocomplete(name=lookup_autocomplete)
    @app_commands.choices(
        type=[
            app_commands.Choice(name="Action Skill", value="Action Skill"),
            app_commands.Choice(name="Augment", value="Augment"),
            app_commands.Choice(name="Capstone", value="Capstone"),
            app_commands.Choice(name="Class Mod", value="Class Mod"),
            app_commands.Choice(name="Enhacnement", value="Enhacnement"),
            app_commands.Choice(name="Firmware", value="Firmware"),
            app_commands.Choice(name="Skill", value="Skill"),
        ]
    )
    async def lookup(self, interaction: discord.Interaction, name: str, type:str ='%', find_coms: bool = False):
        await interaction.response.defer(ephemeral=False)
        
        embeds = []
        async with self.db_pool.acquire() as conn:
            # 1. Main Entity Search
            search_term = f"%{name}%"
            results=''
            if type != '%':
                query = """
                    SELECT e.*, c.name as char_name, st.name as tree_name
                    FROM entities e
                    LEFT JOIN characters c ON e.character_id = c.id
                    LEFT JOIN skill_trees st ON e.tree_id = st.id
                    WHERE e.name ILIKE $1 and lower(e.source_category) = lower($2)
                    LIMIT 5;
                """
                results = await conn.fetch(query, search_term, type)
            else:
                query = """
                    SELECT e.*, c.name as char_name, st.name as tree_name
                    FROM entities e
                    LEFT JOIN characters c ON e.character_id = c.id
                    LEFT JOIN skill_trees st ON e.tree_id = st.id
                    WHERE e.name ILIKE $1
                    LIMIT 5;
                """
                results = await conn.fetch(query, search_term)

            # 2. Optional COM Search (Finding COMs that boost the searched skill)
            com_results = []
            if find_coms:
                com_query = """
                    SELECT name, attributes
                    FROM entities
                    WHERE source_category = 'Class Mod'
                    AND attributes->'skills' ? $1;
                """
                com_results = await conn.fetch(com_query, name)

            # 3. Return Results
            if not results and not com_results:
                await interaction.followup.send(f"Could not find any information for `{name}`.", ephemeral=True)
                return
            
            # Display Main Results using the Dispatcher
            for record in results:
                tree_id = record['tree_id']
                embed = self._format_entity_embed(record, tree_id)
                embeds.append(embed)

            # Display COMs first (if any)
            if com_results:
                com_lines = [f"• **{com['name']}**" for com in com_results]
                com_embed = discord.Embed(
                    title=f"COMs that boost '{name}'",
                    description="\n".join(com_lines),
                    color=discord.Color.orange()
                )
                embeds.append(com_embed)

        await interaction.followup.send(embeds=embeds[:10])

# Helper for loading the cog
async def setup(bot: commands.Bot):
    if not hasattr(bot, 'db_pool'):
        print("Error: bot.db_pool not found.")
        return
    await bot.add_cog(LookupCommand(bot, bot.db_pool))