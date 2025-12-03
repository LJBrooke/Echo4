import discord
import asyncpg
import json
from discord import app_commands
from discord.ext import commands

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
        current_name_filter = interaction.namespace.data_name
        
        async with self.db_pool.acquire() as conn:
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

        # FIXED: Slice name and value to 100 chars to meet Discord API limits
        return [
            app_commands.Choice(name=r['part_type'].split(" ")[0][:100], value=r['part_type'][:100]) 
            for r in results if r['part_type']
        ]

    async def name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        current_type_filter = interaction.namespace.data_type

        async with self.db_pool.acquire() as conn:
            if current_type_filter:
                query = """
                    SELECT DISTINCT part_name 
                    FROM weapon_parts 
                    WHERE part_name ILIKE $1 AND part_type ILIKE $2
                    ORDER BY part_name ASC
                    LIMIT 25
                """
                results = await conn.fetch(query, f"%{current}%", f"%{current_type_filter}%")
            else:
                query = """
                    SELECT DISTINCT part_name 
                    FROM weapon_parts 
                    WHERE part_name ILIKE $1
                    ORDER BY part_name ASC
                    LIMIT 25
                """
                results = await conn.fetch(query, f"%{current}%")

        # FIXED: Slice name and value to 100 chars to meet Discord API limits
        return [
            app_commands.Choice(name=r['part_name'][:100], value=r['part_name'][:100]) 
            for r in results if r['part_name']
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
            color=discord.Color.fuchsia()
        )
        
        p_type = record['part_type'] if record['part_type'] else "General"
        current_embed.set_author(name=p_type)

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

    @app_commands.command(name="examine", description="View base component vectors.")
    @app_commands.describe(
        data_name="The name of the item to search for.",
        data_type="[Optional] Restrict search types"
    )
    @app_commands.autocomplete(data_name=name_autocomplete)
    @app_commands.autocomplete(data_type=type_autocomplete)
    async def examine(self, interaction: discord.Interaction, data_name: str, data_type: str = None):
        await interaction.response.defer(ephemeral=False)
        
        embeds = []
        async with self.db_pool.acquire() as conn:
            # We wrap inputs in % to allow for partial matching and to match
            # the behavior of the autocomplete functions.
            name_param = f"%{data_name}%"

            if data_type:
                type_param = f"%{data_type}%"
                query = """
                    SELECT part_name, part_type, stats
                    FROM weapon_parts
                    WHERE part_name ILIKE $1 AND part_type ILIKE $2
                    LIMIT 10;
                """
                results = await conn.fetch(query, name_param, type_param)
            else:
                query = """
                    SELECT part_name, part_type, stats
                    FROM weapon_parts
                    WHERE part_name ILIKE $1
                    LIMIT 10;
                """
                results = await conn.fetch(query, name_param)

            if not results:
                # Add a helpful error message showing what we searched for
                search_context = f"Name: `{data_name}`"
                if data_type:
                    search_context += f", Type: `{data_type}`"
                
                await interaction.followup.send(
                    f"No results found for {search_context}. \n*Try selecting an option from the autocomplete list explicitly.*", 
                    ephemeral=True
                )
                return

            # 1. Generate ALL embeds first
            all_embeds = []
            for record in results:
                # _format_entity_embed now returns a LIST of embeds
                embed_parts = self._format_entity_embed(record)
                all_embeds.extend(embed_parts)

            # 2. Smart Chunking Logic
            pages = []
            current_page_embeds = []
            current_char_count = 0
            
            SOFT_LIMIT = 1000  # User preference
            HARD_LIMIT = 5800  # Discord limit (6000), leaving buffer for metadata
            MAX_EMBEDS = 10    # Discord limit per message

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

            # 3. Send Logic
            if len(pages) == 1:
                await interaction.followup.send(embeds=pages[0])
            else:
                view = PaginationView(pages, interaction)
                # Initialize footer for page 1
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