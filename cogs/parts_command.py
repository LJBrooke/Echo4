import discord
import asyncpg
import json  # <--- FIXED: Added missing import
from discord import app_commands
from discord.ext import commands

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

    def _format_entity_embed(self, record):
        stats = record['stats']
        # JSON handling now works because import json is present
        if isinstance(stats, str):
            stats = json.loads(stats)

        embed = discord.Embed(
            title=record['part_name'],
            color=discord.Color.fuchsia() 
        )
        
        p_type = record['part_type'].split(" ")[0] if record['part_type'] else "General"
        embed.set_author(name=p_type)

        field_count = 0
        for key, value in stats.items():
            if field_count >= 25:
                embed.set_footer(text="...more stats hidden (Discord limit reached)")
                break

            if isinstance(value, dict):
                sub_stats = []
                for sub_k, sub_v in value.items():
                    sub_stats.append(f"**{sub_k}:** {sub_v}")
                
                content_str = "\n".join(sub_stats)
                if len(content_str) > 1024:
                    content_str = content_str[:1020] + "..."
                if not content_str: 
                    content_str = "None"

                embed.add_field(name=key, value=content_str, inline=False)
            else:
                embed.add_field(name=key, value=str(value), inline=True)
            
            field_count += 1

        return embed

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

            for record in results:
                embed = self._format_entity_embed(record)
                embeds.append(embed)

        await interaction.followup.send(embeds=embeds[:10])

async def setup(bot: commands.Bot):
    if not hasattr(bot, 'db_pool'):
        print("Error: bot.db_pool not found.")
        return
    await bot.add_cog(PartCommand(bot, bot.db_pool))