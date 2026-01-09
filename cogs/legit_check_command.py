import discord
import re
import logging
from discord import app_commands
from discord.ext import commands
from helpers import creator_engine

log = logging.getLogger(__name__)

class LegitCheckCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def parse_component_string(self, component_str: str) -> tuple[str, str, list[int], list[int]]:
        """
        Parses the deserialized string.
        Returns: (inv_type_id, item_id, item_specific_ids, parent_specific_ids)
        """
        first_section = component_str.split('|')[0]
        inv_type_id = first_section.split(',')[0].strip()

        if '||' not in component_str:
            raise ValueError("Invalid format: Missing '||' separator.")
            
        parts_block = component_str.split('||')[1]
        if '|' in parts_block:
            parts_block = parts_block.split('|')[0]

        item_specific_ids = []
        parent_specific_ids = []
        raw_tokens = re.findall(r'\{([^}]+)\}', parts_block)
        all_ordered_ids = [] 

        for token in raw_tokens:
            is_parent_type = ':' in token
            if is_parent_type:
                val_part = token.split(':', 1)[1].strip()
            else:
                val_part = token.strip()
            
            val_part = val_part.replace('[', '').replace(']', '')
            sub_ids = []
            for sid in val_part.split():
                if sid.isdigit():
                    sub_ids.append(int(sid))
            
            if is_parent_type:
                parent_specific_ids.extend(sub_ids)
            else:
                item_specific_ids.extend(sub_ids)
            all_ordered_ids.extend(sub_ids)

        if not all_ordered_ids:
            raise ValueError("No Item ID or Parts found.")

        item_id = str(all_ordered_ids[0])
        if item_specific_ids and str(item_specific_ids[0]) == item_id:
            item_specific_ids.pop(0)

        return inv_type_id, item_id, item_specific_ids, parent_specific_ids

    @app_commands.command(name="legit_check", description="Analyze a weapon serial to validate it against rule definitions.")
    @app_commands.describe(serial="The item serial to check")
    async def legit_check(self, interaction: discord.Interaction, serial: str):
        await interaction.response.defer(ephemeral=False)

        # CALL THE HELPER
        is_legit, violations, metadata = await creator_engine.validate_serial(
            serial, 
            self.bot.db_pool, 
            self.bot.session
        )

        # BUILD EMBED
        status_color = discord.Color.green() if is_legit else discord.Color.red()
        status_text = "✅ LEGITIMATE" if is_legit else "⛔ ILLEGITIMATE"
        
        item_name = metadata.get('item_name', 'Unknown')
        # Optional: You could fetch the Balance Name (e.g. "Monarch") if you wanted, 
        # but the validator returns raw IDs.
        
        embed = discord.Embed(title=f"Legit Check: {item_name}", color=status_color)
        embed.set_author(name=f"{metadata.get('item_type')}")
        embed.add_field(name="Verdict", value=f"{status_text}", inline=False)
        
        if violations:
            error_desc = "\n".join([f"• {v}" for v in violations[:15]])
            if len(violations) > 15: error_desc += f"\n...and {len(violations)-15} more."
            embed.add_field(name="Violations Found", value=error_desc, inline=False)
        
        tags = metadata.get('tags', [])
        if tags:
            tag_str = ", ".join(tags)
            if len(tag_str) > 1000: tag_str = tag_str[:997] + "..."
            embed.add_field(name="Active Tags", value=tag_str, inline=False)

        inv_id = metadata.get('inv_id', '?')
        p_count = metadata.get('part_count', 0)
        embed.set_footer(text=f"Parts: {p_count}")
        
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(LegitCheckCommand(bot))