# cogs/repkit_editor_view.py
import discord
import logging
from discord.ext import commands
from helpers import repkit_class

# Import the shared views from the new file
from .editor_views_shared import (
    BaseEditorView, 
    LevelModal, 
    RaritySelectionView
)

log = logging.getLogger(__name__)

# =============================================================================
# --- REPKIT-SPECIFIC VIEWS ---
# =============================================================================

class RepkitPerkEditorView(BaseEditorView):
    """
    Ephemeral view for editing the 3 repkit perks.
    Uses 3 dropdowns and a shared pager.
    """
    def __init__(self, repkit: repkit_class.Repkit, cog: commands.Cog, user_id: int, main_message: discord.Message):
        super().__init__(cog, user_id, main_message)
        self.repkit = repkit
        self.bot_ref = self._get_bot_ref()

        self.page = 0
        
        # --- [Cache Placeholder] ---
        # This relies on a 'self.bot_ref.repkit_perk_lists' to be created
        # in editor_command.py, similar to shield_perk_lists
        try:
            self.total_pages = len(self.bot_ref.repkit_perk_lists.get("Perks", [[]]))
        except AttributeError:
            log.warning("Repkit Perk Cache not loaded. Defaulting to 1 page.")
            self.total_pages = 1
        
        # This will store the 'unique_value' (string ID) for each slot
        # e.g., ["105", "100", "86"] or ["105", "NONE", "NONE"]
        self.selections = self._get_current_selections()
        
        self.embed = discord.Embed(
            title=f"Editing Perks for {repkit.item_name}",
            description=f"A repkit can have up to 3 perks. Select perks using the dropdowns."
        )
        self._initialize_decorated_components()
        
    def _initialize_decorated_components(self):
        # 1. Get options for the current page
        current_options = self._get_options_for_page(self.page)
        
        # 2. Set options for all three select menus
        self.perk1_select.options = self._update_options_default(current_options, self.selections[0])
        self.perk2_select.options = self._update_options_default(current_options, self.selections[1])
        self.perk3_select.options = self._update_options_default(current_options, self.selections[2])
        
        # 3. Set initial button labels
        self._update_button_labels()

    def _get_current_selections(self) -> list[str]:
        """
        Gets the string IDs of the first 3 perks.
        """
        # Get flat list of all perk IDs, e.g., [105, 100, 86]
        current_ids = self.repkit._get_current_perk_ids()
        
        # Convert to list of strings
        selections = [str(pid) for pid in current_ids]
        
        # We only support editing 3 perks in this UI
        selections = selections[:3]
        
        # Pad the list with "NONE" up to 3
        if len(selections) < 3:
            selections.extend(["NONE"] * (3 - len(selections)))
            
        return selections
        
    def _get_options_for_page(self, page_index: int) -> list[discord.SelectOption]:
        """
        Builds a "clean" SelectOption list for a given page,
        without any defaults set.
        """
        options = [
            discord.SelectOption(label="None", value="NONE")
        ]
        added_values = {"NONE"}

        try:
            # --- [Cache Placeholder] ---
            # Relies on 'repkit_perk_lists'
            perk_list_page = self.bot_ref.repkit_perk_lists["Perks"][page_index]
        except (AttributeError, IndexError, KeyError):
            perk_list_page = [] 
            
        for perk in perk_list_page:
            # --- [Cache Placeholder] ---
            # Assuming 'unique_value' is set to the string ID during cache load
            unique_val_str = perk.get('unique_value', str(perk.get('id', '')))
            
            if not unique_val_str or unique_val_str in added_values:
                continue
                
            options.append(
                discord.SelectOption(
                    label=perk.get('name', 'Unknown Perk'),
                    value=unique_val_str,
                    description=perk.get('perk_type', None)
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
        
        # If the selected perk wasn't on this page, set "None" as default
        if not found_default and current_selection != "NONE":
            # Find the "None" option and set it to default
            for i, option in enumerate(new_options):
                if option.value == "NONE":
                    new_options[i].default = True
                    break
                    
        return new_options

    def _update_button_labels(self):
        page_label = f"Page {self.page + 1}/{self.total_pages}"
        self.prev_button.label = f"◀ Perks ({page_label})"
        self.prev_button.disabled = (self.total_pages <= 1)
        self.next_button.label = f"Perks ({page_label}) ▶"
        self.next_button.disabled = (self.total_pages <= 1)
        
    # --- DECORATED CALLBACKS ---
    
    # Perk Slot 1
    @discord.ui.select(placeholder="Select Perk 1...", row=0, custom_id="perk_select:0")
    async def perk1_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selections[0] = select.values[0]
        # Re-initialize this specific select to update its default
        current_options = self._get_options_for_page(self.page)
        self.perk1_select.options = self._update_options_default(current_options, self.selections[0])
        await interaction.response.edit_message(view=self)
        
    # Perk Slot 2
    @discord.ui.select(placeholder="Select Perk 2...", row=1, custom_id="perk_select:1")
    async def perk2_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selections[1] = select.values[0]
        current_options = self._get_options_for_page(self.page)
        self.perk2_select.options = self._update_options_default(current_options, self.selections[1])
        await interaction.response.edit_message(view=self)
        
    # Perk Slot 3
    @discord.ui.select(placeholder="Select Perk 3...", row=2, custom_id="perk_select:2")
    async def perk3_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selections[2] = select.values[0]
        current_options = self._get_options_for_page(self.page)
        self.perk3_select.options = self._update_options_default(current_options, self.selections[2])
        await interaction.response.edit_message(view=self)
  
    # Row 3 Pagers
    @discord.ui.button(style=discord.ButtonStyle.grey, custom_id="page_prev", row=3)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        self.page = (self.page - 1) % self.total_pages
        
        # Get new base options
        new_options = self._get_options_for_page(self.page)
        
        # Update all 3 selects
        self.perk1_select.options = self._update_options_default(new_options, self.selections[0])
        self.perk2_select.options = self._update_options_default(new_options, self.selections[1])
        self.perk3_select.options = self._update_options_default(new_options, self.selections[2])
        self._update_button_labels()
        
        await interaction.edit_original_response(embed=self.embed, view=self)

    @discord.ui.button(style=discord.ButtonStyle.grey, custom_id="page_next", row=3)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        self.page = (self.page + 1) % self.total_pages

        new_options = self._get_options_for_page(self.page)
        
        self.perk1_select.options = self._update_options_default(new_options, self.selections[0])
        self.perk2_select.options = self._update_options_default(new_options, self.selections[1])
        self.perk3_select.options = self._update_options_default(new_options, self.selections[2])
        self._update_button_labels()
        
        await interaction.edit_original_response(embed=self.embed, view=self)

    # Row 4 Cancel/Confirm
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
            # Get all selected IDs, filter out "NONE"
            id_list_str = [pid for pid in self.selections if pid != "NONE"]
            
            # Convert to integers
            id_list_int = [int(pid) for pid in id_list_str]
            
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
    def __init__(self, cog: commands.Cog, repkit: repkit_class.Repkit, user_id: int):
        super().__init__(cog, user_id, None, timeout=300) 
        self.repkit = repkit
        
        try:
            # Check if rarity is editable
            is_editable = self.repkit.rarity_name in self.repkit.EDITABLE_RARITY_MAP
        except Exception:
            is_editable = False # Fallback
        
        # Disable the rarity button if not editable (i.e., Legendary)
        self.rarity_button.disabled = not is_editable
        
        # TODO ENABLE WHEN PART SELECTION IS POSSIBLE.
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

    async def on_timeout(self):
        if self.message:
            try: await self.message.edit(view=None)
            except (discord.NotFound, discord.Forbidden): pass
        
        await super().on_timeout()