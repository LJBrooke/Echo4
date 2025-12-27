import discord
import asyncpg
import json
from discord import app_commands
from discord.ext import commands
from helpers.item_parser import query_unique_balance_files, query_item_balance

class PaginationView(discord.ui.View):
    def __init__(self, pages: list[list[discord.Embed]], interaction: discord.Interaction):
        super().__init__(timeout=180)
        self.pages = pages
        self.interaction = interaction
        self.current_page = 0
        self.total_pages = len(pages)
        self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = (self.current_page == 0)
        self.next_button.disabled = (self.current_page == self.total_pages - 1)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.gray, emoji="⬅️")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await self.update_message(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.gray, emoji="➡️")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await self.update_message(interaction)

    async def update_message(self, interaction: discord.Interaction):
        # Get the list of embeds for the current page
        current_embeds = self.pages[self.current_page]
        
        # Update the footer of the LAST embed in the group to show page info
        # We clone it so we don't permanently modify the stored embed if we go back/forth
        last_embed = current_embeds[-1]
        
        # We can't actually copy() and modify easily without reconstructing, 
        # so we just modify the footer text directly. 
        # (It's a visual state, so overwriting is usually fine).
        existing_footer = last_embed.footer.text or ""
        if "Page" not in existing_footer: 
            # Simple check to prevent duplicate "Page X/Y" strings
            last_embed.set_footer(text=f"{existing_footer} | Page {self.current_page + 1}/{self.total_pages}".strip(" |"))

        await interaction.response.edit_message(embeds=current_embeds, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.interaction.edit_original_response(view=self)
        except:
            pass
        
class PartCommand(commands.Cog):
    def __init__(self, bot: commands.Bot, db_pool: asyncpg.Pool):
        self.bot = bot
        self.db_pool = db_pool

    async def type_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        # Retrieve the state of other fields
        current_name_filter = interaction.namespace.data_name
        is_deep = interaction.namespace.deep_search  # check if the flag is enabled

        async with self.db_pool.acquire() as conn:
            # 1. DEEP SEARCH LOGIC
            if is_deep:
                # If filtering by name, we need types of parts that match the name OR contain the key
                if current_name_filter:
                    query = """
                        SELECT DISTINCT part_type 
                        FROM weapon_parts 
                        WHERE part_type ILIKE $1 
                        AND (
                            part_name ILIKE $2
                            OR EXISTS (
                                SELECT 1 FROM jsonb_each(stats) 
                                WHERE key ILIKE $2 AND jsonb_typeof(value) = 'object'
                            )
                        )
                        ORDER BY part_type ASC
                        LIMIT 25
                    """
                    results = await conn.fetch(query, f"%{current}%", f"%{current_name_filter}%")
                else:
                    # No name filter, just standard types
                    query = """
                        SELECT DISTINCT part_type 
                        FROM weapon_parts 
                        WHERE part_type ILIKE $1
                        ORDER BY part_type ASC
                        LIMIT 25
                    """
                    results = await conn.fetch(query, f"%{current}%")

            # 2. STANDARD LOGIC (Default)
            else:
                if current_name_filter:
                    query = """
                        SELECT DISTINCT part_type 
                        FROM weapon_parts 
                        WHERE part_type ILIKE $1 AND part_name ILIKE $2
                        ORDER BY part_type ASC
                        LIMIT 25
                    """
                    results = await conn.fetch(query, f"%{current}%", f"%{current_name_filter}%")
                else:
                    query = """
                        SELECT DISTINCT part_type 
                        FROM weapon_parts 
                        WHERE part_type ILIKE $1
                        ORDER BY part_type ASC
                        LIMIT 25
                    """
                    results = await conn.fetch(query, f"%{current}%")

        return [
            app_commands.Choice(name=r['part_type'][:100], value=r['part_type'][:100]) 
            for r in results if r['part_type']
        ]

    async def name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        current_type_filter = interaction.namespace.data_type
        is_deep = interaction.namespace.deep_search

        async with self.db_pool.acquire() as conn:
            # 1. DEEP SEARCH LOGIC
            if is_deep:
                # We use a UNION to combine Main Part Names + Nested Keys
                # We use specific LIMITs on the subqueries to ensure we get a mix of results
                
                type_clause = "AND part_type ILIKE $2" if current_type_filter else ""
                args = [f"%{current}%"]
                if current_type_filter:
                    args.append(f"%{current_type_filter}%")

                query = f"""
                    (
                        -- Standard Part Names
                        SELECT part_name 
                        FROM weapon_parts 
                        WHERE part_name ILIKE $1 {type_clause}
                        LIMIT 15
                    )
                    UNION
                    (
                        -- Nested Keys (Only Objects)
                        SELECT DISTINCT key as part_name
                        FROM weapon_parts, jsonb_each(stats)
                        WHERE key ILIKE $1 
                        AND jsonb_typeof(value) = 'object'
                        {type_clause}
                        LIMIT 10
                    )
                    LIMIT 25
                """
                results = await conn.fetch(query, *args)

            # 2. STANDARD LOGIC (Default)
            else:
                if current_type_filter:
                    query = """
                        SELECT part_name 
                        FROM weapon_parts 
                        WHERE part_name ILIKE $1 AND part_type ILIKE $2
                        ORDER BY part_name ASC
                        LIMIT 25
                    """
                    results = await conn.fetch(query, f"%{current}%", f"%{current_type_filter}%")
                else:
                    query = """
                        SELECT part_name 
                        FROM weapon_parts 
                        WHERE part_name ILIKE $1
                        ORDER BY part_name ASC
                        LIMIT 25
                    """
                    results = await conn.fetch(query, f"%{current}%")

        return [
            app_commands.Choice(name=r['part_name'][:100], value=r['part_name'][:100]) 
            for r in results if r['part_name']
        ]
    
    async def balance_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        async with self.db_pool.acquire() as conn:
            query = """
                SELECT DISTINCT
                    regexp_replace(entry_key, '^comp_[0-9]+_[^_]+_', '') AS variant_name,
                    entry_key
                FROM inv_comp
                WHERE 
                    entry_key ~ '^comp_[0-9]+_[^_]+_' 
                    AND entry_key ILIKE $1 
                    AND substring(entry_key FROM '^comp_[0-9]+_[^_]+_(.*)$') ~ '[a-zA-Z]'
                ORDER BY variant_name ASC
                LIMIT 25;
            """
            # Add wildcards ONLY here in Python
            results = await conn.fetch(query, f"%{current}%")

        return [
            app_commands.Choice(name=r['variant_name'][:100], value=r['entry_key'][:100]) 
            for r in results if r['variant_name']
        ]

    def _format_entity_embed(self, record) -> list[discord.Embed]:
        stats = record['stats']
        if isinstance(stats, str):
            stats = json.loads(stats)

        # List to hold the split embeds
        generated_embeds = []

        # Initialize the first embed
        current_embed = discord.Embed(
            title=record['part_name'],
            color=discord.Color.fuchsia(),
            url='https://borderlands.be/complete_parts_viewer.html'
        )
        
        p_type = record['part_type'] if record['part_type'] else "General"
        if len(p_type)>256: current_embed.set_author(name=p_type[:250]+'...')
        else: current_embed.set_author(name=p_type)

        field_count = 0
        
        # Helper to push current embed and start a new one
        def start_new_embed():
            nonlocal current_embed, field_count
            generated_embeds.append(current_embed)
            current_embed = discord.Embed(
                title=f"{record['part_name']} (Cont.)",
                color=discord.Color.fuchsia(),
                url='https://borderlands.be/complete_parts_viewer.html'
            )
            current_embed.set_author(name=p_type)
            field_count = 0

        for key, value in stats.items():
            # Max 25 fields per embed (Discord Limit)
            if field_count >= 25:
                start_new_embed()

            # --- Formatting Logic ---
            if isinstance(value, dict):
                sub_stats = []
                for sub_k, sub_v in value.items():
                    sub_stats.append(f"**{sub_k}:** {sub_v}")
                
                content_str = "\n".join(sub_stats)
                if len(content_str) > 1024:
                    content_str = content_str[:1020] + "..."
                if not content_str: content_str = "None"

                current_embed.add_field(name=key, value=content_str, inline=False)
            else:
                current_embed.add_field(name=key, value=str(value), inline=True)
            
            field_count += 1

            # --- Splitting Logic ---
            # User Rule: Cut off after the first item that takes us past 1500 chars
            if len(current_embed) > 1500:
                start_new_embed()

        # Append the final embed (if it has fields or is the only one)
        if len(current_embed.fields) > 0 or len(generated_embeds) == 0:
            generated_embeds.append(current_embed)

        return generated_embeds

    # --- Main Command ---
    @app_commands.command(name="balance", description="View item part rules.")
    @app_commands.describe(
        item_name="The name of the item to search for."
    )
    @app_commands.autocomplete(item_name=balance_autocomplete)
    async def balance(self, interaction: discord.Interaction, item_name: str):
        await interaction.response.defer(ephemeral=False)
        
        # 1. Fetch Data
        item_results = await query_item_balance(self.db_pool, item_name)
        
        if not item_results:
            await interaction.followup.send(f"No balance data found for `{item_name}`.")
            return

        row = item_results[0]
        
        # 2. Extract Basic Values
        entry_key = row.get('entry_key', item_name)
        max_prefixes = row.get('maxnumprefixes')
        max_suffixes = row.get('maxnumsuffixes')
        
        # 3. Start Building the Message
        lines = []
        lines.append(f"# Balance info for {entry_key}:")
        lines.append("") 

        if max_prefixes is not None:
            lines.append(f"**maxnumprefixes:** {max_prefixes}")
        
        if max_suffixes is not None:
            lines.append(f"**maxnumsuffixes:** {max_suffixes}")
        
        lines.append("")

        # 4. Helper to format lists/JSON
        def format_section(title, data):
            if not data or data == 'null':
                return
            
            # Ensure we have a python object
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    return 
            
            lines.append(f"## {title}")
            
            # CASE A: List
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        for v in item.values():
                            lines.append(f"  - {v}")
                    else:
                        lines.append(f"  - {item}")
            
            # CASE B: Dictionary (The complex rules)
            elif isinstance(data, dict):
                if "pairs" in data:
                    # Sort by the category name
                    sorted_pairs = sorted(data["pairs"].values(), key=lambda x: x.get("key", ""))
                    
                    for pair_data in sorted_pairs:
                        category = pair_data.get("key", "Unknown Category")
                        val_obj = pair_data.get("value", {})
                        
                        # --- NEW LOGIC: Check for partcount ---
                        part_count = val_obj.get("partcount")
                        count_str = ""
                        
                        if part_count:
                            # Default to '?' if min/max are missing in the JSON
                            p_min = part_count.get("min", "0") # Usually defaults to 0 if missing
                            p_max = part_count.get("max", "?")
                            count_str = f" [{p_min}-{p_max}]"
                        
                        lines.append(f"  - **{category}{count_str}**:")
                        
                        # Drill down to parts
                        parts_list = val_obj.get("parts", [])
                        if parts_list:
                            for part_obj in parts_list:
                                part_name = part_obj.get("part", "Unknown Part")
                                lines.append(f"    - `{part_name}`")
                        else:
                            lines.append("    - (No parts listed)")

                else:
                    for k, v in data.items():
                        lines.append(f"  - **{k}:** {v}")
            
            lines.append("")

        # 5. Add Sections
        format_section("Basetags", row.get('basetags'))
        format_section("Possible Part Types", row.get('parttypes'))
        format_section("Part Type Selection Rules", row.get('parttypeselectionrules'))
        format_section("Part Tag Selection Rules", row.get('parttagselectionrules'))

        # 6. Send
        final_message = "\n".join(lines)
        if len(final_message) > 2000:
            final_message = final_message[:1990] + "\n... (truncated)"
            
        await interaction.followup.send(final_message)
    
    # --- Main Command ---
    @app_commands.command(name="examine", description="View base component vectors.")
    @app_commands.describe(
        data_name="The name of the item to search for.",
        data_type="[Optional] Restrict search types",
        deep_search="[Optional] Search inside nested JSON objects (Default: False)"
    )
    @app_commands.autocomplete(data_name=name_autocomplete)
    @app_commands.autocomplete(data_type=type_autocomplete)
    async def examine(self, interaction: discord.Interaction, data_name: str, data_type: str = None, deep_search: bool = False):
        await interaction.response.defer(ephemeral=False)
        
        async with self.db_pool.acquire() as conn:
            name_param = f"%{data_name}%"
            type_param = f"%{data_type}%" if data_type else None

            # --- Query Construction ---
            if deep_search:
                # UNION Query: Get standard matches AND nested matches
                # We rename columns in the second half to make them look like standard parts
                
                # Base WHERE clause for type filtering
                type_filter_sql = "AND part_type ILIKE $2" if data_type else ""
                
                query = f"""
                    -- 1. Standard Top-Level Matches
                    SELECT part_name, part_type, stats, 1 as match_priority
                    FROM weapon_parts
                    WHERE part_name ILIKE $1 {type_filter_sql}

                    UNION ALL

                    -- 2. Nested Key Matches (Deep Search)
                    SELECT 
                        key as part_name, 
                        -- Contextualize: "ParentName (ParentType)"
                        part_name || ' (' || part_type || ')' as part_type, 
                        value as stats,
                        2 as match_priority
                    FROM weapon_parts, jsonb_each(stats)
                    WHERE key ILIKE $1 
                    {type_filter_sql}
                    -- Only treat nested OBJECTS as searchable parts (avoids "Damage: 10" becoming a part)
                    AND jsonb_typeof(value) = 'object' 

                    ORDER BY match_priority, part_name
                    LIMIT 50;
                """
                
                args = [name_param]
                if data_type:
                    args.append(type_param)
                
                results = await conn.fetch(query, *args)
                
            else:
                # Standard Search Only
                if data_type:
                    query = """
                        SELECT part_name, part_type, stats
                        FROM weapon_parts
                        WHERE part_name ILIKE $1 AND part_type ILIKE $2
                        LIMIT 50;
                    """
                    results = await conn.fetch(query, name_param, type_param)
                else:
                    query = """
                        SELECT part_name, part_type, stats
                        FROM weapon_parts
                        WHERE part_name ILIKE $1
                        LIMIT 50;
                    """
                    results = await conn.fetch(query, name_param)

            if not results:
                msg = f"No results found for **{data_name}**."
                if deep_search:
                    msg += " (Deep search was active)"
                await interaction.followup.send(msg, ephemeral=True)
                return

            # --- Embed Generation & Chunking ---
            all_embeds = []
            for record in results:
                embed_parts = self._format_entity_embed(record)
                all_embeds.extend(embed_parts)

            pages = []
            current_page_embeds = []
            current_char_count = 0
            
            SOFT_LIMIT = 1000 
            HARD_LIMIT = 5800
            MAX_EMBEDS = 10

            for embed in all_embeds:
                embed_len = len(embed)
                
                is_over_soft = (current_char_count + embed_len > SOFT_LIMIT) and len(current_page_embeds) > 0
                is_over_hard = (current_char_count + embed_len > HARD_LIMIT)
                is_max_count = len(current_page_embeds) >= MAX_EMBEDS

                if is_over_soft or is_over_hard or is_max_count:
                    pages.append(current_page_embeds)
                    current_page_embeds = []
                    current_char_count = 0
                
                current_page_embeds.append(embed)
                current_char_count += embed_len

            if current_page_embeds:
                pages.append(current_page_embeds)

            if len(pages) == 1:
                await interaction.followup.send(embeds=pages[0])
            else:
                view = PaginationView(pages, interaction)
                first_page_embeds = pages[0]
                last_embed = first_page_embeds[-1]
                existing = last_embed.footer.text or ""
                last_embed.set_footer(text=f"{existing} | Page 1/{len(pages)}".strip(" |"))
                
                await interaction.followup.send(embeds=first_page_embeds, view=view)

async def setup(bot: commands.Bot):
    if not hasattr(bot, 'db_pool'):
        print("Error: bot.db_pool not found.")
        return
    await bot.add_cog(PartCommand(bot, bot.db_pool))