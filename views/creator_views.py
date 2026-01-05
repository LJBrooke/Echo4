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
        # Use the pre-calculated active slots
        self.active_slots = session.active_slots 
        self.current_slot = self.active_slots[0] if self.active_slots else None
        
        self.part_cache = {} 
        
    def build_dashboard_embed(self, final_serial: str = None) -> discord.Embed:
        """
        Helper method to construct the dashboard embed.
        Centralizes logic for Editing, Finalizing, and future 'Original Serial' display.
        """
        is_final = final_serial is not None
        
        # 1. Title & Color
        if is_final:
            title = f"✅ Finalized: {self.session.balance_name}"
            color = discord.Color.green()
        else:
            title = f"🛠️ Assembly: {self.session.balance_name}"
            color = discord.Color.blue()
            
        embed = discord.Embed(title=title, color=color)

        # 2. Description (Slots & Parts)
        desc_lines = []
        for slot in self.active_slots:
            parts = self.session.selections.get(slot, [])
            
            # Icon Logic:
            # If finalized, just use a static bullet.
            # If editing, point to the active slot.
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
        
        # 3. Active Tags Field
        active_tags = self.session.get_current_tags()
        if active_tags:
            from collections import Counter
            counts = Counter(active_tags)
            tag_display = [f"{k} ({v})" if v > 1 else k for k, v in counts.items()]
            embed.add_field(name="Active Tags", value=", ".join(tag_display)[:1024], inline=False)

        # 4. Original Serial Field (For Edit Mode)
        if self.original_serial:
            embed.add_field(
                name="Original Serial", 
                value=f"```\n{self.original_serial}\n```", 
                inline=False
            )

        # 5. Final Serial Field (For Finished State)
        if final_serial:
            embed.add_field(
                name="New Serial Code", 
                value=f"```\n{final_serial}\n```", 
                inline=False
            )
            embed.set_footer(text="Session Closed. Copy the code above to use in-game.")
        else:
            embed.set_footer(text="Parts list is automatically filtered by your active tags.")
            
        return embed
    
    async def advance_to_next_valid_slot(self):
        """
        Moves self.current_slot to the next slot in the list that has 
        at least one valid (selectable) part given current tags.
        """
        if not self.current_slot: return

        try:
            current_idx = self.active_slots.index(self.current_slot)
        except ValueError:
            return

        # Iterate through all SUBSEQUENT slots
        # We start at current_idx + 1
        for next_slot in self.active_slots[current_idx + 1:]:
            
            # Check if this slot has ANY valid options given current tags
            # We reuse the engine's check logic
            parts_data = await self.session.get_parts_status(next_slot)
            
            # If at least one part is VALID (not locked by tags), we stop here
            if any(item['valid'] for item in parts_data):
                self.current_slot = next_slot
                return

    async def update_view(self, interaction: discord.Interaction):
        try:
            self.clear_items()
            
            # --- 1. Slot Selector ---
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

            # --- 2. Part Selector ---
            if self.current_slot:
                parts_data = await self.session.get_parts_status(self.current_slot)
                
                # Sort: Valid first, then by name
                parts_data.sort(key=lambda x: (not x['valid'], x['part']['partname']))
                
                # Rebuild Cache (Dictionary naturally handles dupes by keeping last one)
                self.part_cache = {str(p['part']['serial_index']): p['part'] for p in parts_data}
                
                part_options = []
                rules = self.session.constraints.get(self.current_slot, {})
                max_val = rules.get('max', 1)
                
                # Option to clear slot (Single Select only)
                if max_val == 1:
                    part_options.append(discord.SelectOption(
                        label="[ CLEAR SLOT ]", value="REMOVE", emoji="🚫"
                    ))

                current_ids = [str(p['serial_index']) for p in self.session.selections.get(self.current_slot, [])]
                
                seen_indices = set()
                
                # Iterate through ALL data, but stop when we hit 25 options
                for item in parts_data:
                    if len(part_options) >= 25: break
                    p = item['part']
                    p_idx = str(p['serial_index'])
                    
                    if p_idx in seen_indices or not p_idx or p_idx == 'None': continue
                    seen_indices.add(p_idx)
                    
                    is_valid = item['valid']
                    reason = item['reason']
                    label = p['partname'][:100] # Now using Prettified Name
                    
                    # --- NEW DESCRIPTION LOGIC ---
                    # Priority 1: Use Stats if available
                    # Priority 2: Use just Tag List
                    # Priority 3: Fallback to inv code
                    tag_str = "<No Tags>"
                    stats_text = p.get('stats')
                    tags_list = self.session._parse_tags(p.get('addtags'))
                    if tags_list: tag_str = ", ".join(tags_list)
                    
                    if not is_valid:
                        label = f"🔒 {label}"
                        desc = f"⛔ {reason}"
                    elif stats_text and stats_text.strip():
                        # Use the stats!
                        desc = f"{stats_text} | {tag_str}"[:100]
                    else:
                        # Fallback to tags or inv
                        
                        if tags_list:
                            desc = f"{p['inv']} | {tag_str}"[:100]
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
                
                # Configure Component
                actual_max = min(max_val, len(part_options))
                actual_max = max(1, actual_max)
                
                if part_options:
                    self.add_item(PartSelect(part_options, max_values=actual_max))

            # --- Buttons ---
            self.add_item(FinishButton())
            self.add_item(CancelButton())
            
            # --- Embed ---
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

# --- Components ---

class SlotSelect(ui.Select):
    def __init__(self, options):
        super().__init__(
            placeholder="Select Slot to Edit...",
            min_values=1, max_values=1, options=options, row=0
        )

    async def callback(self, interaction: discord.Interaction):
        # Must acknowledge interaction immediately to prevent "Interaction Failed"
        await interaction.response.defer() 
        view: CreatorDashboardView = self.view
        view.current_slot = self.values[0]
        await view.update_view(interaction)

class PartSelect(ui.Select):
    def __init__(self, options, max_values=1):
        super().__init__(
            placeholder="Select Component(s)...", 
            min_values=0 if max_values > 1 else 1, 
            max_values=max_values, options=options, row=1
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view: CreatorDashboardView = self.view
        
        # 1. Update Session
        if "REMOVE" in self.values:
            view.session.toggle_part(view.current_slot, None)
        else:
            new_selection = []
            for val in self.values:
                part = view.part_cache.get(val)
                if part: new_selection.append(part)
            view.session.selections[view.current_slot] = new_selection
        
        # 2. Advance to Next Valid Slot (Logic Added Here)
        await view.advance_to_next_valid_slot()

        # 3. Refresh UI
        await view.update_view(interaction)

class FinishButton(ui.Button):
    def __init__(self):
        super().__init__(label="Finalize Item", style=discord.ButtonStyle.green, row=2)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view: CreatorDashboardView = self.view
        
        try:
            final_serial = await view.session.get_serial_string()
            
            # USE HELPER TO BUILD FINAL EMBED
            # We pass final_serial, which triggers the Green Color + Code Block
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