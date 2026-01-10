# cogs/repkit_editor_view.py
import discord
import logging
from discord.ext import commands
from helpers import item_parser, repkit_class

# Import the shared views from the new file
from views.editor_views_shared import (
    BaseEditorView, 
    LevelModal, 
    RaritySelectionView
)

log = logging.getLogger(__name__)

# =============================================================================
# --- REPKIT-SPECIFIC VIEWS ---
# =============================================================================

class RepkitFirmwareEditorView(BaseEditorView):
    """
    Ephemeral view for editing the repkit Firmware.
    """
    def __init__(self, repkit: repkit_class.Repkit, cog: commands.Cog, user_id: int, main_message: discord.Message):
        super().__init__(cog, user_id, main_message)
        self.repkit = repkit
        self.bot_ref = self._get_bot_ref()
        
        # This will store the 'unique_value' (string ID) for each slot
        # e.g., {"Firmware": "5", "Type": "105", "Perk1": "86", "Perk2": "NONE", "Nothing": "102"}
        self.selections = self._get_current_selections()
        
        self.embed = discord.Embed(
            title=f"Editing Firmware for {repkit.item_name}",
            description=f"Select a new Firmware perk.\n(Type and other Perks will be preserved.)"
        )
        self._initialize_decorated_components()

    def _initialize_decorated_components(self):
        # Get options for the Firmware dropdown (static, page 0)
        firmware_options = self._get_options_for_page("Firmware", 0)
        self.firmware_select.options = self._update_options_default(firmware_options, self.selections["Firmware"])

    def _get_current_selections(self) -> dict[str, str]:
        """
        Gets the string IDs of the current Firmware, Type, Perks, and Nothing.
        """
        selections = {"Firmware": "NONE", "Type": "NONE", "Perk1": "NONE", "Perk2": "NONE", "Nothing": "NONE"}
        current_ids = self.repkit._get_current_perk_ids() # List[int]
        
        TYPE_PERK_IDS = {103, 104, 105, 106}
        
        # Use a temp list to gather selectable perks
        selectable_perks = []

        for pid in current_ids:
            pid_str = str(pid)
            
            perk_data = self.bot_ref.repkit_perk_lookup.get(pid_str)
            if not perk_data:
                log.warning(f"Repkit perk ID {pid_str} not found in cache. Skipping.")
                continue

            perk_name = perk_data.get('name')

            if 1 <= pid <= 20 or pid==113: # TODO Refactor to a proper generic check.
                selections["Firmware"] = pid_str
            elif pid in TYPE_PERK_IDS:
                selections["Type"] = pid_str
            elif perk_name == 'Nothing':
                selections["Nothing"] = pid_str # Store the "Nothing" perk ID
            else:
                # This is a selectable perk
                selectable_perks.append(pid_str)
        
        # Assign selectable perks to Perk1 and Perk2
        if len(selectable_perks) > 0:
            selections["Perk1"] = selectable_perks[0]
        if len(selectable_perks) > 1:
            selections["Perk2"] = selectable_perks[1]
            
        return selections

    def _get_options_for_page(self, list_key: str, page_index: int) -> list[discord.SelectOption]:
        """
        Builds a "clean" SelectOption list for a given page,
        without any defaults set.
        """
        options = [
            discord.SelectOption(label="None", value="NONE")
        ]
        added_values = {"NONE"}

        try:
            perk_list_page = self.bot_ref.repkit_perk_lists[list_key][page_index]
        except (AttributeError, IndexError, KeyError):
            perk_list_page = [] 
            
        for perk in perk_list_page:
            unique_val_str = perk.get('unique_value', str(perk.get('id', '')))
            
            if not unique_val_str or unique_val_str in added_values:
                continue
                
            options.append(
                discord.SelectOption(
                    label=perk.get('name', 'Unknown Perk'),
                    value=unique_val_str,
                    description=perk.get('description', perk.get('perk_type', None))
                )
            )
            added_values.add(unique_val_str)
            
        return options

    def _update_options_default(self, options: list[discord.SelectOption], current_selection: str) -> list[discord.SelectOption]:
        """
        Takes a "clean" list of options and creates a new list
        with the correct 'default' value set.
        """
        new_options = []
        found_default = False
        
        for option in options:
            is_default = (option.value == current_selection)
            if is_default:
                found_default = True
            new_options.append(
                discord.SelectOption(
                    label=option.label,
                    value=option.value,
                    description=option.description,
                    default=is_default
                )
            )
        
        if not found_default and current_selection != "NONE":
            for option in new_options:
                if option.value == "NONE":
                    option.default = False
                    break
            
            selected_perk_data = self.bot_ref.repkit_perk_lookup.get(current_selection)
            
            if selected_perk_data:
                label = selected_perk_data.get('name', 'Unknown Perk')
                desc = selected_perk_data.get('description', selected_perk_data.get('perk_type', None))
                
                new_options.insert(0, discord.SelectOption(
                    label=label,
                    value=current_selection,
                    description=desc,
                    default=True
                ))
            else:
                new_options.insert(0, discord.SelectOption(
                    label=current_selection,
                    value=current_selection,
                    default=True
                ))
            
            new_options = new_options[:25]
                    
        return new_options

    # --- DECORATED CALLBACKS ---
    
    @discord.ui.select(placeholder="Select Firmware...", row=0, custom_id="repkit_firmware_select")
    async def firmware_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selections["Firmware"] = select.values[0]
        # This list is static, just need to update the default
        current_options = self._get_options_for_page("Firmware", 0)
        self.firmware_select.options = self._update_options_default(current_options, self.selections["Firmware"])
        await interaction.response.edit_message(view=self)

    # Row 3 Cancel/Confirm
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, custom_id="cancel", row=3)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cancel_and_delete(interaction)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green, custom_id="confirm", row=3)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._confirm_selection(interaction)

    async def _confirm_selection(self, interaction: discord.Interaction):
        self.bot_ref.active_editor_sessions.pop(self.user_id, None)
        await interaction.response.defer()

        try:
            # Read Firmware, Type, Perks, and Nothing
            id_list_str = [
                self.selections["Firmware"],
                self.selections["Type"],
                self.selections["Perk1"],
                self.selections["Perk2"],
                self.selections["Nothing"]
            ]
            id_list_str_filtered = [pid for pid in id_list_str if pid != "NONE"]
            
            # Convert to integers
            id_list_int = [int(pid) for pid in id_list_str_filtered]
            
            # Use the repkit class method to update
            await self.repkit.update_all_perks(id_list_int)
            
            # Regenerate serial and embed
            new_serial = await self.repkit.get_serial()
            new_embed_desc = await self.repkit.get_parts_for_embed()
            original_embed = self.main_message.embeds[0]
            original_embed.description = new_embed_desc
            
            await self.main_message.edit(
                content=f"```{new_serial}```\n_ _\n",
                embed=original_embed
            )
        except Exception as e:
            log.error("Error during REPKIT firmware update: %s", e, exc_info=True)
            await interaction.followup.send(f"Error updating firmware: `{e}`", ephemeral=True)

        await interaction.delete_original_response()

class RepkitPerkEditorView(BaseEditorView):
    """
    Ephemeral view for editing the repkit Type and Perk(s).
    Shows 1 or 2 perk dropdowns based on repkit rarity.
    """
    def __init__(self, repkit: repkit_class.Repkit, cog: commands.Cog, user_id: int, main_message: discord.Message):
        super().__init__(cog, user_id, main_message)
        self.repkit = repkit
        self.bot_ref = self._get_bot_ref()
        self.page = 0
        self.is_epic = (self.repkit.rarity_name == "Epic")
        
        # Perk list is paginated, Type list is not
        try:
            self.total_pages = len(self.bot_ref.repkit_perk_lists.get("Perks", [[]]))
        except AttributeError:
            log.warning("Repkit Perk Cache not loaded. Defaulting to 1 page.")
            self.total_pages = 1
        
        # This will store the 'unique_value' (string ID) for each slot
        # e.g., {"Firmware": "5", "Type": "105", "Perk1": "86", "Perk2": "96", "Nothing": "102"}
        self.selections = self._get_current_selections()
        
        self.embed = discord.Embed(
            title=f"Editing Perks for {repkit.item_name}",
            description=f"Select a Repkit Type and one additional Perk.\n(Firmware and placeholder perks are not editable here and will be preserved.)"
        )
        if self.is_epic:
            self.embed.description = f"Select a Repkit Type and up to two additional Perks.\n(Firmware and placeholder perks are not editable here and will be preserved.)"
        
        # Call this *before* _initialize_decorated_components
        self._setup_layout() 
        self._initialize_decorated_components()
        
    def _setup_layout(self):
        """Hides Perk 2 and moves buttons up if not Epic."""
        if not self.is_epic:
            # Remove the second perk dropdown
            self.remove_item(self.perk2_select)
            # Move other items up
            self.prev_button.row = 2
            self.next_button.row = 2
            self.cancel_button.row = 3
            self.confirm_button.row = 3
            
    def _initialize_decorated_components(self):
        # 1. Get options for the Type dropdown (static, page 0)
        type_options = self._get_options_for_page("Type", 0)
        self.type_select.options = self._update_options_default(type_options, self.selections["Type"])

        # 2. Get options for the Perk dropdown (paginated)
        perk_options = self._get_options_for_page("Perks", self.page)
        self.perk1_select.options = self._update_options_default(perk_options, self.selections["Perk1"])
        
        # 3. Handle Epic perk dropdown
        if self.is_epic:
            self.perk2_select.options = self._update_options_default(perk_options, self.selections["Perk2"])
        
        # 4. Set initial button labels
        self._update_button_labels()

    def _get_current_selections(self) -> dict[str, str]:
        """
        Gets the string IDs of the current Firmware, Type, Perks, and Nothing.
        """
        selections = {"Firmware": "NONE", "Type": "NONE", "Perk1": "NONE", "Perk2": "NONE", "Nothing": "NONE"}
        current_ids = self.repkit._get_current_perk_ids() # List[int]
        
        TYPE_PERK_IDS = {103, 104, 105, 106}

        # Use a temp list to gather selectable perks
        selectable_perks = []

        for pid in current_ids:
            pid_str = str(pid)
            
            perk_data = self.bot_ref.repkit_perk_lookup.get(pid_str)
            if not perk_data:
                log.warning(f"Repkit perk ID {pid_str} not found in cache. Skipping.")
                continue

            perk_name = perk_data.get('name')

            if 1 <= pid <= 20:
                selections["Firmware"] = pid_str
            elif pid in TYPE_PERK_IDS:
                selections["Type"] = pid_str
            elif perk_name == 'Nothing':
                selections["Nothing"] = pid_str
            else:
                # This is a selectable perk
                selectable_perks.append(pid_str)
        
        # Assign selectable perks to Perk1 and Perk2
        if len(selectable_perks) > 0:
            selections["Perk1"] = selectable_perks[0]
        if len(selectable_perks) > 1:
            selections["Perk2"] = selectable_perks[1]
                
        return selections
        
    def _get_options_for_page(self, list_key: str, page_index: int) -> list[discord.SelectOption]:
        """
        Builds a "clean" SelectOption list for a given page,
        without any defaults set.
        """
        options = [
            discord.SelectOption(label="None", value="NONE")
        ]
        added_values = {"NONE"}

        try:
            perk_list_page = self.bot_ref.repkit_perk_lists[list_key][page_index]
        except (AttributeError, IndexError, KeyError):
            perk_list_page = [] 
            
        for perk in perk_list_page:
            unique_val_str = perk.get('unique_value', str(perk.get('id', '')))
            
            if not unique_val_str or unique_val_str in added_values:
                continue
                
            options.append(
                discord.SelectOption(
                    label=perk.get('name', 'Unknown Perk'),
                    value=unique_val_str,
                    description=perk.get('description', perk.get('perk_type', None))
                )
            )
            added_values.add(unique_val_str)
            
        return options

    def _update_options_default(self, options: list[discord.SelectOption], current_selection: str) -> list[discord.SelectOption]:
        """
        Takes a "clean" list of options and creates a new list
        with the correct 'default' value set.
        
        FIX: If the selection is not on this page, it is added
        to the top of the list as the default.
        """
        new_options = []
        found_default = False
        
        for option in options:
            is_default = (option.value == current_selection)
            if is_default:
                found_default = True
            new_options.append(
                discord.SelectOption(
                    label=option.label,
                    value=option.value,
                    description=option.description,
                    default=is_default
                )
            )
        
        # --- BUG FIX ---
        # If the selected perk wasn't on this page, add it
        if not found_default and current_selection != "NONE":
            # 1. Un-set the "None" default
            for option in new_options:
                if option.value == "NONE":
                    option.default = False
                    break
            
            # 2. Get the data for the selected perk
            selected_perk_data = self.bot_ref.repkit_perk_lookup.get(current_selection)
            
            if selected_perk_data:
                label = selected_perk_data.get('name', 'Unknown Perk')
                desc = selected_perk_data.get('description', selected_perk_data.get('perk_type', None))
                
                new_options.insert(0, discord.SelectOption(
                    label=label,
                    value=current_selection,
                    description=desc,
                    default=True
                ))
            else:
                # Fallback if perk not in cache (shouldn't happen)
                new_options.insert(0, discord.SelectOption(
                    label=current_selection,
                    value=current_selection,
                    default=True
                ))
            
            # 3. --- FIX for 26 options ---
            # Trim the list to 25 if it's now too long
            new_options = new_options[:25]
                    
        return new_options

    def _update_button_labels(self):
        page_label = f"Page {self.page + 1}/{self.total_pages}"
        self.prev_button.label = f"◀ Perks ({page_label})"
        self.prev_button.disabled = (self.total_pages <= 1)
        self.next_button.label = f"Perks ({page_label}) ▶"
        self.next_button.disabled = (self.total_pages <= 1)
        
    # --- DECORATED CALLBACKS ---
    
    # Repkit Type
    @discord.ui.select(placeholder="Select Repkit Type...", row=0, custom_id="repkit_type_select")
    async def type_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selections["Type"] = select.values[0]
        # This list is static, just need to update the default
        current_options = self._get_options_for_page("Type", 0)
        self.type_select.options = self._update_options_default(current_options, self.selections["Type"])
        await interaction.response.edit_message(view=self)
        
    # Repkit Perk 1
    @discord.ui.select(placeholder="Select Perk 1...", row=1, custom_id="repkit_perk1_select")
    async def perk1_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selections["Perk1"] = select.values[0]
        # This list is paginated, need to update defaults for current page
        current_options = self._get_options_for_page("Perks", self.page)
        self.perk1_select.options = self._update_options_default(current_options, self.selections["Perk1"])
        await interaction.response.edit_message(view=self)

    # Repkit Perk 2 (Epic Only)
    @discord.ui.select(placeholder="Select Perk 2... (Epic Only)", row=2, custom_id="repkit_perk2_select")
    async def perk2_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selections["Perk2"] = select.values[0]
        # This list is paginated, need to update defaults for current page
        current_options = self._get_options_for_page("Perks", self.page)
        self.perk2_select.options = self._update_options_default(current_options, self.selections["Perk2"])
        await interaction.response.edit_message(view=self)
  
    # Row 3 Pagers (default, moved by _setup_layout if needed)
    @discord.ui.button(style=discord.ButtonStyle.grey, custom_id="page_prev", row=3)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        self.page = (self.page - 1) % self.total_pages
        
        # Get new base options for the perk dropdown
        new_options = self._get_options_for_page("Perks", self.page)
        
        # Update perk select(s)
        self.perk1_select.options = self._update_options_default(new_options, self.selections["Perk1"])
        if self.is_epic:
            self.perk2_select.options = self._update_options_default(new_options, self.selections["Perk2"])
            
        self._update_button_labels()
        
        await interaction.edit_original_response(embed=self.embed, view=self)

    @discord.ui.button(style=discord.ButtonStyle.grey, custom_id="page_next", row=3)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        self.page = (self.page + 1) % self.total_pages

        # Get new base options for the perk dropdown
        new_options = self._get_options_for_page("Perks", self.page)
        
        # Update perk select(s)
        self.perk1_select.options = self._update_options_default(new_options, self.selections["Perk1"])
        if self.is_epic:
            self.perk2_select.options = self._update_options_default(new_options, self.selections["Perk2"])

        self._update_button_labels()
        
        await interaction.edit_original_response(embed=self.embed, view=self)

    # Row 4 Cancel/Confirm (default, moved by _setup_layout if needed)
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, custom_id="cancel", row=4)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cancel_and_delete(interaction)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green, custom_id="confirm", row=4)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._confirm_selection(interaction)

    async def _confirm_selection(self, interaction: discord.Interaction):
        self.bot_ref.active_editor_sessions.pop(self.user_id, None)
        await interaction.response.defer()

        try:
            # Read Firmware, Type, Perks, and Nothing
            id_list_str = [
                self.selections["Firmware"],
                self.selections["Type"],
                self.selections["Perk1"],
                self.selections["Perk2"],
                self.selections["Nothing"]
            ]
            id_list_str_filtered = [pid for pid in id_list_str if pid != "NONE"]
            
            # Convert to integers
            id_list_int = [int(pid) for pid in id_list_str_filtered]
            
            # Use the repkit class method to update
            await self.repkit.update_all_perks(id_list_int)
            
            # Regenerate serial and embed
            new_serial = await self.repkit.get_serial()
            new_embed_desc = await self.repkit.get_parts_for_embed()
            original_embed = self.main_message.embeds[0]
            original_embed.description = new_embed_desc
            
            await self.main_message.edit(
                content=f"```{new_serial}```\n_ _\n",
                embed=original_embed
            )
        except Exception as e:
            log.error("Error during REPKIT perk update: %s", e, exc_info=True)
            await interaction.followup.send(f"Error updating perks: `{e}`", ephemeral=True)

        await interaction.delete_original_response()

class MainRepkitEditorView(BaseEditorView):
    """
    The main view for repkits, using decorated methods.
    """
    def __init__(self, cog: commands.Cog, repkit: repkit_class.Repkit, user_id: int, session_id: str):
        super().__init__(cog, user_id, None, timeout=300) 
        self.repkit = repkit
        self.session_id = session_id
        
        try:
            # Check if rarity is editable
            is_editable = self.repkit.rarity_name in self.repkit.EDITABLE_RARITY_MAP
        except Exception:
            is_editable = False # Fallback
        
        # Disable the rarity button if not editable (i.e., Legendary)
        self.rarity_button.disabled = not is_editable
        
        self.parts_button.disabled = False
        

    async def _handle_ephemeral_launch(self, interaction: discord.Interaction, ephemeral_view: BaseEditorView):
        
        if hasattr(self.cog, 'bot'):
            session_host = self.cog.bot
        else:
            session_host = self.cog
            
        # 1. Session cleanup
        try:
            if interaction.user.id in session_host.active_editor_sessions:
                old_message = session_host.active_editor_sessions.pop(interaction.user.id, None)
                if old_message:
                    await old_message.delete()
        except Exception:
            pass
        
        # 2. Defer interaction
        await interaction.response.defer(ephemeral=True)

        if not self.message:
            await interaction.followup.send("Error: Main message reference not found.", ephemeral=True)
            return

        await self._clean_embeds()
        
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
            log.error("!!! FATAL LOG: REPKIT VIEW LAUNCH CRASH !!! Error: %s", e, exc_info=True)
            session_host.active_editor_sessions.pop(interaction.user.id, None)
            await interaction.followup.send(f"An internal error occurred: `{e}`", ephemeral=True)

    # --- BUTTON CALLBACKS ---

    @discord.ui.button(label="Check Legitimacy", style=discord.ButtonStyle.green, custom_id="action_legit", row=0)
    async def legit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        legit_embed = await self.get_legitimacy_embed(await self.repkit.get_serial())
        if self.message:
            try:
                current_embeds = self.message.embeds
                # Append the report to existing embeds
                await self.message.edit(embeds=current_embeds + [legit_embed])
            except (discord.NotFound, discord.Forbidden):
                pass
        return

    @discord.ui.button(label="Set Level", style=discord.ButtonStyle.blurple, custom_id="action_level", row=0)
    async def level_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # This one handles the modal immediately
        modal = LevelModal(self.repkit, self) 
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Rarity", style=discord.ButtonStyle.blurple, custom_id="action_rarity", row=0)
    async def rarity_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RaritySelectionView(self.repkit, self.cog, interaction.user.id, self.message)
        await self._handle_ephemeral_launch(interaction, view)
    
    @discord.ui.button(label="Change Perks", style=discord.ButtonStyle.green, custom_id="edit_perks", row=1)
    async def parts_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RepkitPerkEditorView(self.repkit, self.cog, interaction.user.id, self.message)
        await self._handle_ephemeral_launch(interaction, view)
        
    @discord.ui.button(label="Firmware", style=discord.ButtonStyle.secondary, custom_id="edit_firmware", row=1)
    async def firmware_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RepkitFirmwareEditorView(self.repkit, self.cog, interaction.user.id, self.message)
        await self._handle_ephemeral_launch(interaction, view)
        
    async def on_timeout(self):
        
        try:
            if hasattr(self.cog, 'bot'):
                bot_ref = self.cog.bot
            else:
                bot_ref = self.cog
            
            # Get the final state of the item
            final_serial = await self.repkit.get_serial()
            final_component_string = self.repkit.get_component_list()

            await item_parser.log_item_edit(
                db_pool=bot_ref.db_pool,
                session_id=self.session_id,  # Use the stored session ID
                user_id=self.user_id,
                edit_type="FINAL",
                item_name=self.repkit.item_name,
                item_type=self.repkit.type,
                manufacturer=self.repkit.manufacturer,
                serial=final_serial,
                component_string=final_component_string,
                parts_json=self.repkit.parts  # Log the final parts state
            )
            log.info(f"Successfully logged 'Final Item' for session {self.session_id}, user {self.user_id}")
            
            legit_embed = await self.get_legitimacy_embed(final_serial)
            
            if self.message:
                try:
                    current_embeds = self.message.embeds
                    # Append the report to existing embeds
                    await self.message.edit(embeds=current_embeds + [legit_embed], view=None)
                except (discord.NotFound, discord.Forbidden):
                    pass
            
        except Exception as e:
            log.error(f"Failed to log 'Final Item' event for session {self.session_id}: {e}", exc_info=True)
            if self.message:
                try: await self.message.edit(view=None)
                except (discord.NotFound, discord.Forbidden): pass
        
        await super().on_timeout()