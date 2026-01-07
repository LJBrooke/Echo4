import discord
import re
import logging
from collections import Counter # Import Counter for smarter tag checking
from discord import app_commands
from discord.ext import commands
from helpers import item_parser
from helpers import db_utils
from helpers.creator_engine import CreatorSession

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

        try:
            # --- 1. Deserialize ---
            resp = await item_parser.deserialize(self.bot.session, serial)
            if not resp or 'deserialized' not in resp:
                await interaction.followup.send("❌ Error: Could not deserialize.")
                return
            component_str = str(resp.get('deserialized'))
            
            # --- 2. Parse IDs ---
            try:
                inv_id, item_id, item_p_ids, parent_p_ids = self.parse_component_string(component_str)
            except Exception as e:
                await interaction.followup.send(f"❌ Error parsing: {e}")
                return

            # --- 3. Fetch Balance ---
            balance_data = await item_parser.get_balance(self.bot.db_pool, inv_id, item_id)
            if not balance_data:
                await interaction.followup.send(f"❌ Unknown Item: Inv `{inv_id}` / Item `{item_id}`.")
                return

            # --- 4. Initialize Session ---
            session = CreatorSession(
                user_id=interaction.user.id,
                balance_name=balance_data[0].get('entry_key'),
                balance_data=balance_data,
                db_pool=self.bot.db_pool,
                session=self.bot.session
            )
            await session.initialize() 

            target_item_type = str(session.balance_data.get('item_type'))
            target_parent_type = str(session.balance_data.get('parent_type'))

            loaded_parts = []
            
            async with self.bot.db_pool.acquire() as conn:
                if item_p_ids:
                    q1 = """
                        SELECT * FROM all_parts 
                        LEFT JOIN type_and_manufacturer ON inv = gestalt_type 
                        WHERE serial_index::int = ANY($1::int[]) 
                        AND inv = $2
                    """
                    rows1 = await conn.fetch(q1, item_p_ids, target_item_type)
                    loaded_parts.extend([dict(r) for r in rows1])

                if parent_p_ids:
                    q2 = """
                        SELECT * FROM all_parts 
                        LEFT JOIN type_and_manufacturer ON inv = gestalt_type 
                        WHERE serial_index::int = ANY($1::int[]) 
                        AND inv = $2
                    """
                    rows2 = await conn.fetch(q2, parent_p_ids, target_parent_type)
                    loaded_parts.extend([dict(r) for r in rows2])

            # --- 5. Equip Parts & Fix Unknown ID Check ---
            found_ids = set()
            for p in loaded_parts:
                sid = p['serial_index']
                if sid and str(sid).isdigit():
                    found_ids.add(int(sid))

            all_requested_ids = set(item_p_ids + parent_p_ids)
            unknown_ids = all_requested_ids - found_ids
            
            for part in loaded_parts:
                p_type = part['part_type']
                if p_type in session.slots:
                    session.selections[p_type].append(part)

            # --- 6. Validation Logic ---
            violations = []
            
            # A. Slot Limits (Unchanged)
            for slot in session.slots:
                selected = session.selections[slot]
                count = len(selected)
                rules = session.constraints.get(slot, {})
                max_val = rules.get('max', 1)
                min_val = rules.get('min', 0)
                
                if count > max_val:
                    violations.append(f"**{slot.title()}**: Too many parts ({count}/{max_val}).")
                if count < min_val:
                    violations.append(f"**{slot.title()}**: Missing parts ({count}/{min_val}).")

            # B. Tag Logic (Robust Exclusion Fix)
            # 1. Calculate Global Counts
            current_tags_list = session.get_current_tags()
            global_counts = Counter(current_tags_list)
            current_tags_set = set(current_tags_list)
            
            for slot, parts in session.selections.items():
                for part in parts:
                    p_name = part.get('partname', 'Unknown')
                    
                    # Get this part's specific contributions
                    p_add_list = db_utils.decode_jsonb_list(part.get('addtags'))
                    my_counts = Counter(p_add_list)
                    
                    # Calculate "The Rest of the Build"
                    # logic: Global - Me = Others
                    other_counts = global_counts - my_counts
                    
                    p_exc = set(db_utils.decode_jsonb_list(part.get('exclusiontags')))
                    p_dep = set(db_utils.decode_jsonb_list(part.get('dependencytags')))

                    # Check 1: Exclusions
                    # Logic: If I exclude 'X', 'X' must not exist in 'other_counts'.
                    # This safely ignores self-exclusion while catching duplicates.
                    for exc_tag in p_exc:
                        if other_counts[exc_tag] > 0:
                            violations.append(f"**{p_name}**: Incompatible. Excludes `{exc_tag}` which is present on other parts.")

                    # Check 2: Dependencies (Standard Set Logic)
                    if p_dep and not p_dep.issubset(current_tags_set):
                        missing = list(p_dep - current_tags_set)
                        violations.append(f"**{p_name}**: Missing required tags: `{', '.join(missing)}`.")

            # C. Global Limits (Unchanged)
            for rule in session.global_tag_rules:
                limit = rule['max']
                targets = rule['tags']
                count = sum(1 for t in current_tags_list if t in targets)
                if count > limit:
                    t_names = list(targets)[0]
                    violations.append(f"**Global Limit**: Exceeded `{t_names}` ({count}/{limit}).")
            
            # D. Unknown Parts (Unchanged)
            if unknown_ids:
                 violations.append(f"**Unknown IDs**: {list(unknown_ids)}")

            # --- 7. Build Report ---
            is_legit = (len(violations) == 0)
            status_color = discord.Color.green() if is_legit else discord.Color.red()
            status_text = "✅ LEGITIMATE" if is_legit else "⛔ ILLEGITIMATE"
            
            embed = discord.Embed(title=f"Legitimacy Check: {session.balance_name}", color=status_color)
            embed.add_field(name="Verdict", value=f"{status_text}", inline=False)
            
            if violations:
                error_desc = "\n".join([f"• {v}" for v in violations[:15]])
                if len(violations) > 15: error_desc += f"\n...and {len(violations)-15} more."
                embed.add_field(name="Violations Found", value=error_desc, inline=False)
            
            sorted_tags = sorted(list(current_tags_set))
            if sorted_tags:
                tag_str = ", ".join(sorted_tags)
                if len(tag_str) > 1000: tag_str = tag_str[:997] + "..."
                embed.add_field(name="Active Tags", value=tag_str, inline=False)

            embed.set_footer(text=f"Parts: {len(all_requested_ids)}")
            # embed.set_footer(text=f"Inv: {inv_id} | Item: {item_id} | Parts: {len(all_requested_ids)}")
            
            await interaction.followup.send(embed=embed)

        except Exception as e:
            log.error(f"Legit check failed: {e}", exc_info=True)
            await interaction.followup.send(f"❌ System Error: {str(e)}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(LegitCheckCommand(bot))