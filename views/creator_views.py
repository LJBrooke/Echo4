import discord
import logging
from discord import ui
from discord.ext import commands
from helpers.creator_engine import CreatorSession
from .editor_views_shared import BaseEditorView

log = logging.getLogger(__name__)

class CreatorDashboardView(BaseEditorView):
    def __init__(self, session: CreatorSession, cog: commands.Cog, user_id: int, main_message: discord.Message, original_serial: str = None):
        super().__init__(cog, user_id, main_message, timeout=600)
        self.session = session
        
        self.original_serial = original_serial
        self.active_slots = session.active_slots 
        self.current_slot = self.active_slots[0] if self.active_slots else None
        
        self.part_cache = {} 
        
    def build_dashboard_embed(self, final_serial: str = None) -> discord.Embed:
        is_final = final_serial is not None
        if is_final:
            title = f"✅ Finalized: {self.session.balance_name}"
            color = discord.Color.green()
        else:
            title = f"🛠️ Assembly: {self.session.balance_name}"
            color = discord.Color.blue()
            
        embed = discord.Embed(title=title, color=color)

        desc_lines = []
        for slot in self.active_slots:
            parts = self.session.selections.get(slot, [])
            if is_final:
                icon = "🔹"
            else:
                icon = "👉" if slot == self.current_slot else "▪️"
            
            slot_name = slot.replace("_", " ").title()
            
            if parts:
                p_names = ", ".join([f"**{p['partname']}**" for p in parts])
                desc_lines.append(f"{icon} **{slot_name}**: {p_names}")
            else:
                desc_lines.append(f"{icon} **{slot_name}**: *Empty*")
        
        embed.description = "\n".join(desc_lines)
        
        active_tags = self.session.get_current_tags()
        if active_tags:
            from collections import Counter
            counts = Counter(active_tags)
            tag_display = [f"{k} ({v})" if v > 1 else k for k, v in counts.items()]
            embed.add_field(name="Active Tags", value=", ".join(tag_display)[:1024], inline=False)

        if self.original_serial:
            embed.add_field(name="Original Serial", value=f"```\n{self.original_serial}\n```", inline=False)

        if final_serial:
            embed.add_field(name="New Serial Code", value=f"```\n{final_serial}\n```", inline=False)
            embed.set_footer(text="Session Closed. Copy the code above to use in-game.")
        else:
            embed.set_footer(text="Parts list is automatically filtered by your active tags.")
            
        return embed
    
    async def advance_to_next_valid_slot(self):
        """
        Moves self.current_slot to the next slot that REQUIRES user choice.
        Skips slots that have only 1 valid option (presumed auto-filled).
        """
        if not self.current_slot: return

        try:
            current_idx = self.active_slots.index(self.current_slot)
        except ValueError:
            return

        # Iterate through remaining slots
        for next_slot in self.active_slots[current_idx + 1:]:
            parts_data = await self.session.get_parts_status(next_slot)
            valid_candidates = [p for p in parts_data if p['valid']]
            count = len(valid_candidates)
            
            # If > 1, the user has a choice to make. Stop here.
            if count > 1:
                self.current_slot = next_slot
                return
            
            # If count == 1, it was likely auto-selected by initialize()
            # or is forced. We skip it to save the user clicks.
            if count == 1:
                log.debug(f"Auto-skipping slot {next_slot} (Only 1 valid option)")
                continue
            
            # If count == 0, it's empty/invalid, keep searching.

    async def update_view(self, interaction: discord.Interaction):
        try:
            self.clear_items()
            
            slot_options = []
            for s in self.active_slots[:25]: 
                selected_parts = self.session.selections.get(s, [])
                count = len(selected_parts)
                rules = self.session.constraints.get(s, {})
                max_val = rules.get('max', 1)
                
                status = "✅" if count >= 1 else "⚪"
                if max_val > 1: status = f"{count}/{max_val}"

                label = s.replace("_", " ").title()
                
                desc = "Empty"
                if selected_parts:
                    if max_val > 1:
                        from collections import Counter
                        names = [p['partname'] for p in selected_parts]
                        c = Counter(names)
                        desc = ", ".join([f"{k} ({v})" if v > 1 else k for k,v in c.items()])
                    else:
                        names = [p['partname'] for p in selected_parts]
                        desc = ", ".join(names)
                        
                    if len(desc) > 50: desc = desc[:47] + "..."

                slot_options.append(discord.SelectOption(
                    label=label, 
                    value=s, 
                    description=f"{status} {desc}", 
                    default=(s == self.current_slot)
                ))
            
            if slot_options:
                self.add_item(SlotSelect(slot_options))

            if self.current_slot:
                parts_data = await self.session.get_parts_status(self.current_slot)
                parts_data.sort(key=lambda x: (not x['valid'], x['part']['partname']))
                
                self.part_cache = {str(p['part']['serial_index']): p['part'] for p in parts_data}
                
                rules = self.session.constraints.get(self.current_slot, {})
                slot_max = rules.get('max', 1)
                
                current_selection = self.session.selections.get(self.current_slot, [])
                current_ids = [str(p['serial_index']) for p in current_selection]
                
                part_options = []
                seen_indices = set()
                
                for item in parts_data:
                    if len(part_options) >= 25: break

                    p = item['part']
                    p_idx = str(p['serial_index'])
                    
                    if p_idx in seen_indices or not p_idx or p_idx == 'None': continue
                    seen_indices.add(p_idx)
                    
                    is_valid = item['valid']
                    reason = item['reason']
                    label = p['partname'][:100]
                    
                    stats_text = p.get('stats')
                    
                    if not is_valid:
                        label = f"🔒 {label}"
                        desc = f"⛔ {reason}"
                    elif stats_text and stats_text.strip():
                        desc = stats_text[:100]
                    else:
                        tags_list = self.session._parse_tags(p.get('addtags'))
                        if tags_list:
                            t_str = ", ".join(tags_list)
                            desc = f"{p['inv']} | {t_str}"
                        else:
                            desc = f"{p['inv']}"
                            
                    if len(desc) > 100: desc = desc[:97] + "..."

                    is_selected = (p_idx in current_ids)

                    part_options.append(discord.SelectOption(
                        label=label, 
                        value=p_idx, 
                        description=desc, 
                        default=is_selected
                    ))
                
                if part_options:
                    placeholder_text = self.session.get_slot_placeholder(self.current_slot)
                    
                    self.add_item(PartSelect(
                        options=part_options, 
                        placeholder=placeholder_text,
                        max_values=slot_max
                    ))

            self.add_item(FinishButton())
            self.add_item(CancelButton())
            
            embed = self.build_dashboard_embed()

            if self.main_message:
                await self.main_message.edit(embed=embed, view=self)
            else:
                await interaction.edit_original_response(embed=embed, view=self)

        except Exception as e:
            log.error(f"Error updating view: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"⚠️ View Error: {str(e)}", ephemeral=True)
            except:
                pass

class SlotSelect(ui.Select):
    def __init__(self, options):
        super().__init__(
            placeholder="Select Slot to Edit...",
            min_values=1, max_values=1, options=options, row=0
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer() 
        view: CreatorDashboardView = self.view
        view.current_slot = self.values[0]
        await view.update_view(interaction)

class PartSelect(ui.Select):
    def __init__(self, options, placeholder, max_values):
        real_max = min(max_values, len(options), 25)
        super().__init__(
            placeholder=placeholder, 
            min_values=0,
            max_values=real_max, 
            options=options, 
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view: CreatorDashboardView = self.view
        
        selected_parts = []
        for val in self.values:
            part = view.part_cache.get(val)
            if part:
                selected_parts.append(part)
        
        view.session.update_slot_selection(view.current_slot, selected_parts)

        # Logic: If it is a Single-Select slot AND the user selected 1 item,
        # we attempt to auto-advance. (If they selected 0, they just cleared it, so stay.)
        rules = view.session.constraints.get(view.current_slot, {})
        slot_max = rules.get('max', 1)
        
        if slot_max == 1 and len(selected_parts) == 1:
            await view.advance_to_next_valid_slot()

        await view.update_view(interaction)

class FinishButton(ui.Button):
    def __init__(self):
        super().__init__(label="Finalize Item", style=discord.ButtonStyle.green, row=2)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view: CreatorDashboardView = self.view
        
        try:
            final_serial = await view.session.get_serial_string()
            embed = view.build_dashboard_embed(final_serial=final_serial)
            
            if view.main_message:
                await view.main_message.edit(content=None, embed=embed, view=None)
            else:
                await interaction.edit_original_response(content=None, embed=embed, view=None)
            
        except Exception as e:
            log.error(f"Serialization failed: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error generating serial: {str(e)}", ephemeral=True)

class CancelButton(ui.Button):
    def __init__(self):
        super().__init__(label="Cancel", style=discord.ButtonStyle.red, row=2)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content="Item creation cancelled.", view=None, embed=None)