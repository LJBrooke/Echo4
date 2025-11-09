# cogs/shield_editor_view.py
import discord
import traceback
from discord.ext import commands
from helpers import shield_class

# Import the shared views from the new file
from .editor_views_shared import (
    BaseEditorView, 
    LevelModal, 
    RaritySelectionView, 
    FirmwareSelectionView,
    ShieldPerkSelect
)

# =============================================================================
# --- SHIELD-SPECIFIC VIEWS ---
# =============================================================================

class ShieldPerkEditorView(BaseEditorView):
    """
    Ephemeral view for Weaker, Stronger, and Elemental perks.
    """
    def __init__(self, shield: shield_class.Shield, cog: commands.Cog, user_id: int, main_message: discord.Message):
        super().__init__(cog, user_id, main_message)
        self.shield = shield
        self.bot_ref = self._get_bot_ref()

        self.weaker_page = 0
        self.stronger_page = 0
        
        self.weaker_total_pages = len(self.bot_ref.shield_perk_lists.get("Slot_1", [[]]))
        self.stronger_total_pages = len(self.bot_ref.shield_perk_lists.get("Slot_2", [[]]))
        
        self.selections = self._get_current_selections()
        
        self.embed = discord.Embed(
            title=f"Editing Main Perks for {shield.item_name}",
            description=f"Select Weaker, Stronger, and Elemental perks."
        )
        self._initialize_decorated_components()
        
    def _initialize_decorated_components(self):
        # 1. Set initial options for select menus
        self.weaker_select.options = self._get_options_for_page("Weaker Part (Slot 1)", "Slot_1", self.weaker_page)
        self.stronger_select.options = self._get_options_for_page("Stronger Part (Slot 2)", "Slot_2", self.stronger_page)
        self.elemental_select.options = self._get_options_for_page("Elemental Resistance", "Elemental_Resistance", 0)
        
        # 2. Set initial button labels
        self._update_button_labels()

    def _get_current_selections(self) -> dict:
        """
        Finds all 4 currently equipped perks and maps them to their
        'unique_value' (e.g., "1_General") for the dropdown defaults.
        """
        selections = {
            "Weaker Part (Slot 1)": "NONE",
            "Stronger Part (Slot 2)": "NONE",
            "Elemental Resistance": "NONE",
            "Firmware": "NONE"
        }
        
        current_shield_type = self.shield.type
        
        current_id_map = self.shield.get_current_perk_ids_by_type()
        all_ids = current_id_map.get("General", []) + \
                    current_id_map.get("Energy", []) + \
                    current_id_map.get("Armour", [])
        
        checked_ids = set() 
        
        for pid in all_ids:
            if pid in checked_ids:
                continue
            checked_ids.add(pid)

            perk_data_list = self.bot_ref.shield_perk_int_lookup.get(pid)
            if not perk_data_list:
                continue

            for perk_data in perk_data_list:
                
                # Check the shield_type of the perk data itself
                perk_shield_type = self.shield.type
                if (perk_shield_type != current_shield_type and perk_shield_type != 'General'):
                    # This perk data isn't for our shield type (e.g., it's 'Armour'
                    # data for an 'Energy' shield). Skip it.
                    continue
                slot = perk_data.get('slot')
                perk_type = perk_data.get('perk_type')
                unique_value = perk_data['unique_value']

                if slot == 1:
                    selections["Weaker Part (Slot 1)"] = unique_value
                    _, self.weaker_page = self._find_perk_in_cache("Slot_1", unique_value)
                elif slot == 2:
                    selections["Stronger Part (Slot 2)"] = unique_value
                    _, self.stronger_page = self._find_perk_in_cache("Slot_2", unique_value)
                elif perk_type == 'Elemental Resistance':
                    selections["Elemental Resistance"] = unique_value
                elif perk_type == 'Firmware':
                    selections["Firmware"] = unique_value
                
        return selections
        
    def _find_perk_in_cache(self, list_key: str, unique_value: str) -> tuple[bool, int]:
        """Searches the paginated perk_lists cache for a 'unique_value'."""
        paginated_list = self.bot_ref.shield_perk_lists.get(list_key, [])
        for page_index, page in enumerate(paginated_list):
            for perk in page:
                if perk['unique_value'] == unique_value:
                    return True, page_index
        return False, 0

    def _get_options_for_page(self, placeholder: str, list_key: str, page_index: int) -> list[discord.SelectOption]:
        """Builds the SelectOption list using 'unique_value'."""
        current_selection = self.selections[placeholder]
        options = [
            discord.SelectOption(
                label="None", value="NONE", default=(current_selection == "NONE")
            )
        ]
        
        added_values = {"NONE"}

        try:
            perk_list_page = self.bot_ref.shield_perk_lists[list_key][page_index]
        except IndexError:
            perk_list_page = [] 
            
        for perk in perk_list_page:
            unique_val_str = perk['unique_value']
            
            if unique_val_str in added_values or (perk.get("shield_type")!=self.shield.type and perk.get("shield_type")!='General'):
                continue 
            options.append(
                discord.SelectOption(
                    label=perk.get('name', 'Unknown Perk'),
                    value=unique_val_str,
                    # description=perk.get('shield_type', 'Perk'),
                    default=(current_selection == unique_val_str)
                )
            )
            added_values.add(unique_val_str)
            
        return options

    # cogs/shield_editor_view.py (inside ShieldPerkEditorView)

    def _update_button_labels(self):
        # Weaker Pagers
        weaker_label = f"Page {self.weaker_page + 1}/{self.weaker_total_pages}"
        self.weaker_prev_button.label = f"◀ Weaker ({weaker_label})"
        self.weaker_prev_button.disabled = (self.weaker_total_pages <= 1)
        self.weaker_next_button.label = f"Weaker ({weaker_label}) ▶"
        self.weaker_next_button.disabled = (self.weaker_total_pages <= 1)

        # Stronger Pagers
        stronger_label = f"Page {self.stronger_page + 1}/{self.stronger_total_pages}"
        self.stronger_prev_button.label = f"◀ Stronger ({stronger_label})"
        self.stronger_prev_button.disabled = (self.stronger_total_pages <= 1)
        self.stronger_next_button.label = f"Stronger ({stronger_label}) ▶"
        self.stronger_next_button.disabled = (self.stronger_total_pages <= 1)
        
    # --- DECORATED BUTTON CALLBACKS (New implementation to replace manual logic in on_interaction) ---
    
    @discord.ui.select(row=0, custom_id="perk_select:Weaker Part (Slot 1)")
    async def weaker_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        # 1. Update the state
        self.selections["Weaker Part (Slot 1)"] = select.values[0]
        # 2. Acknowledge the interaction without editing the message
        await interaction.response.defer() 
        
    # Stronger Part (Slot 2) - Row 1
    @discord.ui.select(row=1, custom_id="perk_select:Stronger Part (Slot 2)")
    async def stronger_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        # 1. Update the state
        self.selections["Stronger Part (Slot 2)"] = select.values[0]
        # 2. Acknowledge
        await interaction.response.defer()
        
    # Elemental Resistance - Row 2
    @discord.ui.select(row=2, custom_id="perk_select:Elemental Resistance")
    async def elemental_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        # 1. Update the state
        self.selections["Elemental Resistance"] = select.values[0]
        # 2. Acknowledge
        await interaction.response.defer()
  
    # Row 3 Pagers
    @discord.ui.button(style=discord.ButtonStyle.grey, custom_id="page_weaker_prev", row=3)
    async def weaker_prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        self.weaker_page = (self.weaker_page - 1) % self.weaker_total_pages
        new_options = self._get_options_for_page("Weaker Part (Slot 1)", "Slot_1", self.weaker_page)
        self.weaker_select.options = new_options
        self._update_button_labels()

        
        await interaction.edit_original_response(embed=self.embed, view=self)

    @discord.ui.button(style=discord.ButtonStyle.grey, custom_id="page_weaker_next", row=3)
    async def weaker_next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        self.weaker_page = (self.weaker_page + 1) % self.weaker_total_pages
        new_options = self._get_options_for_page("Weaker Part (Slot 1)", "Slot_1", self.weaker_page)
        self.weaker_select.options = new_options
        self._update_button_labels()
        
        await interaction.edit_original_response(embed=self.embed, view=self)

    @discord.ui.button(style=discord.ButtonStyle.grey, custom_id="page_stronger_prev", row=3)
    async def stronger_prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        self.stronger_page = (self.stronger_page - 1) % self.stronger_total_pages
        new_options = self._get_options_for_page("Stronger Part (Slot 2)", "Slot_2", self.stronger_page)
        self.stronger_select.options = new_options
        self._update_button_labels()
        
        await interaction.edit_original_response(embed=self.embed, view=self)

    @discord.ui.button(style=discord.ButtonStyle.grey, custom_id="page_stronger_next", row=3)
    async def stronger_next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        self.stronger_page = (self.stronger_page + 1) % self.stronger_total_pages
        new_options = self._get_options_for_page("Stronger Part (Slot 2)", "Slot_2", self.stronger_page)
        
        self.stronger_select.options = new_options
        self._update_button_labels()
        
        await interaction.edit_original_response(embed=self.embed, view=self)

    # Row 4 Cancel/Confirm
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, custom_id="cancel", row=4)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Using the inherited, robust helper function
        await self.cancel_and_delete(interaction)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green, custom_id="confirm", row=4)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._confirm_selection(interaction)

    async def on_interaction(self, interaction: discord.Interaction):
        custom_id = interaction.data["custom_id"]
        
        # Only handle the Select Menus, as buttons are now handled by decorators
        if custom_id.startswith("perk_select:"):
            placeholder = custom_id.split(":", 1)[1]
            self.selections[placeholder] = interaction.data['values'][0]
            # Defer, as selection does not require a full view rebuild/edit
            await interaction.response.defer() 
            return

        # Let the base class handle any unhandled component types
        await super().on_interaction(interaction)

    async def _confirm_selection(self, interaction: discord.Interaction):
        self.bot_ref.active_editor_sessions.pop(self.user_id, None)
        await interaction.response.defer()

        try:
            weaker_id = self.selections["Weaker Part (Slot 1)"]
            stronger_id = self.selections["Stronger Part (Slot 2)"]
            elemental_id = self.selections["Elemental Resistance"]
            firmware_id = self.selections["Firmware"]
            
            id_list = [weaker_id, stronger_id, elemental_id, firmware_id]
            # FIX: Call the method on the view instance (self)
            perk_map = self._build_perk_map(id_list) 
            
            await self.shield.update_all_perks(perk_map)
            
            new_serial = await self.shield.get_serial()
            new_embed_desc = await self.shield.get_parts_for_embed()
            original_embed = self.main_message.embeds[0]
            original_embed.description = new_embed_desc
            
            await self.main_message.edit(
                content=f"```{new_serial}```\n_ _\n",
                embed=original_embed
            )
        except Exception as e:
            print(f"Error during SHIELD perk update: {e}")
            traceback.print_exc()
            await interaction.followup.send(f"Error updating perks: `{e}`", ephemeral=True)

        # Use the cleaner delete_original_response after deferring the button
        await interaction.delete_original_response()

class MainShieldEditorView(BaseEditorView):
    """
    The main view for shields, using decorated methods for stability.
    """
    def __init__(self, cog: commands.Cog, shield: shield_class.Shield, user_id: int):
        # Pass all necessary context to the BaseEditorView
        super().__init__(cog, user_id, None, timeout=300) 
        self.shield = shield
        
        try:
            current_rarity_token = self.shield.parts.get("Rarity", ["{95}"])[0]
            current_rarity_name = self.shield._get_rarity_string(current_rarity_token)
        except Exception:
            current_rarity_name = "Unknown" # Fallback in case of error
        
        # 2. Check the condition: The rarity name must be a key in the editable map
        is_editable = current_rarity_name in self.shield.EDITABLE_RARITY_MAP
        
        # 3. Access the decorated button instance and set its disabled state
        #    Disable the button if the rarity is NOT editable.
        self.rarity_button.disabled = not is_editable
        

    # Helper method for common logic: session cleanup, defer, and launch
    async def _handle_ephemeral_launch(self, interaction: discord.Interaction, ephemeral_view: BaseEditorView):
        
        if hasattr(self.cog, 'bot'):
            session_host = self.cog.bot # This is the Bot
        else:
            session_host = self.cog
            
        # 1. Session cleanup (must happen before defer)
        try:
            if interaction.user.id in session_host.active_editor_sessions:
                old_message = session_host.active_editor_sessions.pop(interaction.user.id, None)
                if old_message:
                    await old_message.delete()
        except Exception:
            # Non-fatal: Continue even if cleanup fails
            pass
        
        # 2. Defer interaction (must happen now to avoid "Interaction failed")
        await interaction.response.defer(ephemeral=True)

        if not self.message:
            await interaction.followup.send("Error: Main message reference not found.", ephemeral=True)
            return

        # 3. Launch the view
        try:
            new_message = await interaction.followup.send(
                embed=ephemeral_view.embed,
                view=ephemeral_view,
                ephemeral=True
            )
            ephemeral_view.message = new_message
            session_host.active_editor_sessions[interaction.user.id] = new_message
        except Exception as e:
            error_traceback = traceback.format_exc()
            print(f"!!! FATAL LOG: SHIELD VIEW LAUNCH CRASH !!! Error: {e}")
            print(error_traceback)
            session_host.active_editor_sessions.pop(interaction.user.id, None)
            await interaction.followup.send(f"An internal error occurred: `{e}`", ephemeral=True)

    # --- BUTTON CALLBACKS ---

    @discord.ui.button(label="Set Level", style=discord.ButtonStyle.blurple, custom_id="action_level", row=0)
    async def level_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # This one handles the modal immediately
        modal = LevelModal(self.shield, self) 
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Rarity", style=discord.ButtonStyle.blurple, custom_id="action_rarity", row=0)
    async def rarity_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # This calls the helper method to handle defer/launch
        view = RaritySelectionView(self.shield, self.cog, interaction.user.id, self.message)
        await self._handle_ephemeral_launch(interaction, view)
        
    @discord.ui.button(label="Change Parts", style=discord.ButtonStyle.green, custom_id="edit_main_perks", row=1)
    async def parts_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ShieldPerkEditorView(self.shield, self.cog, interaction.user.id, self.message)
        await self._handle_ephemeral_launch(interaction, view)
        
    @discord.ui.button(label="Change Firmware", style=discord.ButtonStyle.secondary, custom_id="edit_firmware", row=1)
    async def firmware_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # This calls the helper method to handle defer/launch
        view = FirmwareSelectionView(self.shield, self.cog, interaction.user.id, self.message)
        await self._handle_ephemeral_launch(interaction, view)

    async def on_timeout(self):
        if self.message:
            try: await self.message.edit(view=None)
            except (discord.NotFound, discord.Forbidden): pass
        
        await super().on_timeout()