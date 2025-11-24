# cogs/weapon_editor_views.py
import re
import discord
import logging
from discord.ext import commands
from helpers import item_parser, weapon_class
from .editor_views_shared import (
    BaseEditorView, 
    LevelModal, 
    RaritySelectionView
)

log = logging.getLogger(__name__)

class ElementSelectionView(BaseEditorView):
    """
    The ephemeral view for selecting Primary and Secondary elements,
    using decorated components.
    """
    def __init__(self, weapon: weapon_class.Weapon, cog: commands.Cog, user_id: int, main_message: discord.Message):
        super().__init__(cog, user_id, main_message) 
        self.weapon = weapon
        
        current_primary, current_secondary = self.weapon.get_current_element_names_sync()
        
        self.primary_selection = current_primary
        self.secondary_selection = current_secondary
        
        self.embed = discord.Embed(
            title=f"Editing Elements for {weapon.item_name}",
            description=f"Current: {current_primary} / {current_secondary or 'None'}\nSelect new element configuration below."
        )
        
        # Initialize the decorated components with their dynamic options
        self._initialize_components()
        
    def _initialize_components(self):
        """Populates the select menus with their initial options and defaults."""
        
        # --- Primary Element Select ---
        primary_options = [
            discord.SelectOption(
                label=e, 
                value=e, 
                default=(e == self.primary_selection)
            ) 
            for e in self.weapon.ELEMENT_NAMES
        ]
        self.primary_element_select.options = primary_options
        
        # --- Secondary Element Select ---
        secondary_options = [
            discord.SelectOption(
                label="None", 
                value="None", 
                description="Remove secondary element.",
                default=("None" == self.secondary_selection)
            ),
        ]
        secondary_options.extend([
            discord.SelectOption(
                label=e, 
                value=e,
                default=(e == self.secondary_selection)
            ) 
            for e in self.weapon.ELEMENT_NAMES if e != "Kinetic"
        ])
        self.secondary_element_select.options = secondary_options

    @discord.ui.select(
        placeholder="Select Primary Element (Required)...",
        min_values=1,
        max_values=1,
        row=0,
        custom_id="primary_element_select"
    )
    async def primary_element_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.primary_selection = select.values[0]
        await interaction.response.defer()

    @discord.ui.select(
        placeholder="Select Secondary Element (Optional)...",
        min_values=1, # User must re-select "None" or an element
        max_values=1,
        row=1,
        custom_id="secondary_element_select"
    )
    async def secondary_element_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.secondary_selection = select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey, row=4)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cancel_and_delete(interaction)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green, row=4)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if hasattr(self.cog, 'bot'):
            session_host = self.cog.bot
        else:
            session_host = self.cog
            
        if not self.primary_selection:
            await interaction.response.send_message("Please select a Primary Element.", ephemeral=True)
            return

        session_host.active_editor_sessions.pop(self.user_id, None)
        await interaction.response.defer()

        new_secondary = self.secondary_selection
        if new_secondary == "None":
            new_secondary = None
            
        try:
            await self.weapon.update_element(self.primary_selection, new_secondary)
            
            new_serial = await self.weapon.get_serial()
            new_embed_desc = await self.weapon.get_parts_for_embed()
            
            original_embed = self.main_message.embeds[0]
            original_embed.description = new_embed_desc
            
            await self.main_message.edit(
                content=f"```{new_serial}```\n_ _\n",
                embed=original_embed
            )
        
        except ValueError as e:
            log.error("Element ID error: %s", e, exc_info=True)
            await interaction.followup.send(
                f"Error: Could not combine those elements. Check if the element combination is valid for this weapon type. ({e})", 
                ephemeral=True
            )
        except Exception as e:
            log.error("Error during element update: %s", e, exc_info=True)
            await interaction.followup.send(
                f"An unexpected error occurred: `{e}`", 
                ephemeral=True
            )

        await interaction.delete_original_response()
        

class PartSelectionView(BaseEditorView):
    """
    An ephemeral view for part selection, using decorated components.
    """
    def __init__(self, weapon: weapon_class.Weapon, part_type: str, cog: commands.Cog, user_id: int, possible_parts: list, main_message: discord.Message):
        super().__init__(cog, user_id, main_message)
        self.selected_values = [] # Default to empty
        
        self.weapon = weapon
        self.part_type = part_type
        
        self.embed = discord.Embed(
            title=f"Editing: {self.part_type}",
            description=f"Select the new part(s) from the menu, then press 'Confirm'."
        )
        
        # Initialize the decorated select menu
        self._initialize_components(possible_parts)
    
    @classmethod
    async def create(cls, weapon: weapon_class.Weapon, part_type: str, cog: commands.Cog, user_id: int, main_message: discord.Message):
        """Factory method to asynchronously fetch parts before initializing."""
        
        # FIX: Replicate the logic from _get_bot_ref() to safely get the bot
        if hasattr(cog, 'bot'):
            # cog is a Cog instance
            bot_ref = cog.bot
        else:
            # cog is likely the Bot instance itself
            bot_ref = cog
            
        possible_parts = await item_parser.get_compatible_parts(
            bot_ref.db_pool,  # <-- Use the safe bot_ref
            weapon.manufacturer,
            weapon.type,
            part_type
        )
        
        base_variant = weapon.get_base_part_variant_for_accessory(part_type)
        if base_variant:
            filtered_list = []
            for part in possible_parts:
                part_string = part['part_string']
                variant_match = re.search(r"_(\d{2})", part_string)
                part_variant = variant_match.group(1) if variant_match else None
                if part_variant == base_variant or part_variant is None:
                    filtered_list.append(part)
            possible_parts = filtered_list
        
        return cls(weapon, part_type, cog, user_id, possible_parts, main_message)

    def _initialize_components(self, possible_parts: list):
        """Configures the decorated part_select menu."""
        
        min_val, max_val = self.weapon.get_part_limits(self.part_type)

        options = []
        for part_record in possible_parts:
            part_id = str(part_record['id'])
            part_str = part_record['part_string']
            
            pretty_name = item_parser.format_part_name(part_str)
            
            stats_desc = part_record.get('stats') or "No stat changes"
            if len(stats_desc) > 100:
                stats_desc = stats_desc[:97] + "..."

            options.append(discord.SelectOption(
                label=pretty_name,
                value=part_id,
                description=stats_desc
            ))
        
        is_disabled = False
        if not options:
            options.append(discord.SelectOption(
                label="No alternative parts found",
                value="DISABLED_NO_PARTS",
                description="This part type cannot be changed."
            ))
            min_val = 0
            max_val = 1 
            is_disabled = True
        else:
            max_val = min(max_val, len(options))
            min_val = min(min_val, max_val)
        
        # Configure the decorated select menu instance
        self.part_option_select.placeholder = f"Select {self.part_type} (Choose {min_val} to {max_val})..."
        self.part_option_select.min_values = min_val
        self.part_option_select.max_values = max_val
        self.part_option_select.options = options
        self.part_option_select.disabled = is_disabled

    @discord.ui.select(row=0, custom_id="part_option_select")
    async def part_option_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_values = select.values
        await interaction.response.defer()
        
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey, row=4)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cancel_and_delete(interaction)
        
    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green, row=4)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if hasattr(self.cog, 'bot'):
            session_host = self.cog.bot
        else:
            session_host = self.cog
        session_host.active_editor_sessions.pop(self.user_id, None)
        await interaction.response.defer()
        
        try:
            await self.weapon.update_parts(self.part_type, self.selected_values)
            
            new_serial = await self.weapon.get_serial()
            new_embed_desc = await self.weapon.get_parts_for_embed()
            
            original_embed = self.main_message.embeds[0]
            original_embed.description = new_embed_desc
            
            await self.main_message.edit(
                content=f"```{new_serial}```\n_ _\n",
                embed=original_embed
            )
        
        except Exception as e:
            log.error("Error during part update: %s", e, exc_info=True)
            await interaction.followup.send(
                f"An error occurred while updating the part: `{e}`", 
                ephemeral=True
            )
        await interaction.delete_original_response()


class MainWeaponEditorView(BaseEditorView):
    """
    The main view with buttons for each part type.
    Attached to the public /edit command response.
    
    FIX: This view now uses the "manual callback" pattern from
    'old editor.py' to solve interaction timeouts. It does NOT use
    decorators or the on_interaction override.
    """
    def __init__(self, cog: commands.Cog, weapon: weapon_class.Weapon, user_id: int, session_id: str):
        # Initialize the BaseEditorView
        super().__init__(cog, user_id, None, timeout=300) 
        self.weapon = weapon
        self.session_id = session_id
        
        # --- 1. Manually create and add Level Button ---
        level_button = discord.ui.Button(
            label=f"Set Level ({weapon.level})", 
            style=discord.ButtonStyle.blurple,
            custom_id="action_level",
            row=0
        )
        level_button.callback = self.main_button_callback
        self.add_item(level_button)
        
        # --- 2. Manually create and add Rarity Button (Conditional) ---
        current_rarity_token = weapon.parts.get("Rarity", ["{95}"])[0]
        current_rarity_name = weapon._get_rarity_string(current_rarity_token)
        
        if current_rarity_name in weapon_class.Weapon.EDITABLE_RARITY_MAP:
            rarity_button = discord.ui.Button(
                label=f"Rarity ({current_rarity_name})",
                style=discord.ButtonStyle.blurple,
                custom_id="action_rarity",
                row=0
            )
            rarity_button.callback = self.main_button_callback
            self.add_item(rarity_button)
        
        # --- 3. Manually create and add Elements Button ---
        element_button = discord.ui.Button(
            label="Elements",
            style=discord.ButtonStyle.primary, 
            custom_id="edit_elements",
            row=0
        )
        element_button.callback = self.main_button_callback
        self.add_item(element_button)
        
        # --- 4. Manually create and add Dynamic Part Buttons ---
        for part_type in self.weapon.PART_ORDER:
            if part_type in self.weapon.parts and (self.weapon.parts[part_type] or part_type=="Underbarrel" or part_type=="Stat Modifier"):
                if part_type in ["Rarity", "Primary Element", "Secondary Element", "Body"]:
                    continue
                
                part_button = discord.ui.Button(
                    label=part_type,
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"edit_part:{part_type}"
                )
                # Assign the same, single callback
                part_button.callback = self.main_button_callback
                self.add_item(part_button)

    async def main_button_callback(self, interaction: discord.Interaction):
        """
        A single, monolithic callback to handle all button clicks,
        based on the 'old editor.py' pattern.
        """
        custom_id = interaction.data['custom_id']
        
        # 1. Handle Level Modal (which handles its own response)
        if custom_id == "action_level":
            modal = LevelModal(self.weapon, self)
            await interaction.response.send_modal(modal)
            return

        # 2. Handle Session Cleanup
        if hasattr(self.cog, 'bot'): session_host = self.cog.bot
        else: session_host = self.cog
            
        if interaction.user.id in session_host.active_editor_sessions:
            old_message = session_host.active_editor_sessions.pop(interaction.user.id, None)
            if old_message:
                try: await old_message.delete()
                except (discord.NotFound, discord.Forbidden): pass 
        
        # 3. DEFER - This is the crucial step. Defer *before* any slow async logic.
        await interaction.response.defer(ephemeral=True)
        
        if not self.message:
            await interaction.followup.send("Error: Main message reference not found.", ephemeral=True)
            return

        # 4. Route to the correct ephemeral view
        ephemeral_view = None
        try:
            if custom_id == "action_rarity":
                ephemeral_view = RaritySelectionView(
                    self.weapon, self.cog, interaction.user.id, self.message
                )
            
            elif custom_id.startswith("edit_part:"):
                part_type = custom_id.split(':')[-1]
                # This is the slow async call that caused the timeout.
                # It is now safely after the defer.
                ephemeral_view = await PartSelectionView.create(
                    self.weapon, part_type, self.cog, interaction.user.id, self.message
                )
            
            elif custom_id == "edit_elements":
                ephemeral_view = ElementSelectionView(
                    self.weapon, self.cog, interaction.user.id, self.message
                )
            
            # 5. Launch the new view
            if ephemeral_view:
                new_message = await interaction.followup.send(
                    embed=ephemeral_view.embed,
                    view=ephemeral_view,
                    ephemeral=True
                )
                ephemeral_view.message = new_message # Give view a ref to its own msg
                session_host.active_editor_sessions[interaction.user.id] = new_message
        
        except Exception as e:
            # Catch errors during view creation
            session_host.active_editor_sessions.pop(interaction.user.id, None)
            log.error("Error creating ephemeral view: %s", e, exc_info=True)
            await interaction.followup.send(f"An error occurred: `{e}`", ephemeral=True)
 
    async def on_timeout(self):
        """
        Custom timeout for the main view:
        1. Disable buttons on the main message.
        2. Call the base on_timeout to clear any active sessions.
        """
        try:
            if hasattr(self.cog, 'bot'):
                bot_ref = self.cog.bot
            else:
                bot_ref = self.cog
            
            # Get the final state of the item
            final_serial = await self.weapon.get_serial()
            final_component_string = self.weapon.get_component_list()

            await item_parser.log_item_edit(
                db_pool=bot_ref.db_pool,
                session_id=self.session_id,  # Use the stored session ID
                user_id=self.user_id,
                edit_type="FINAL",
                item_name=self.weapon.item_name,
                item_type=self.weapon.type,
                manufacturer=self.weapon.manufacturer,
                serial=final_serial,
                component_string=final_component_string,
                parts_json=self.weapon.parts  # Log the final parts state
            )
            log.info(f"Successfully logged 'Final Item' for session {self.session_id}, user {self.user_id}")
            
        except Exception as e:
            log.error(f"Failed to log 'Final Item' event for session {self.session_id}: {e}", exc_info=True)
            # Don't prevent the rest of the timeout logic from running
            
        if self.message: 
            try:
                await self.message.edit(view=None)
            except (discord.NotFound, discord.Forbidden):
                pass
        
        # Call the BaseEditorView.on_timeout()
        await super().on_timeout()