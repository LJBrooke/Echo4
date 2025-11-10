# cogs/editor_views_shared.py
import logging
import discord
from discord.ext import commands
from helpers import weapon_class, shield_class, repkit_class
from typing import Union

log = logging.getLogger(__name__)

# =============================================================================
# --- SHARED VIEWS ---
# These are the base components used by the other view files.
# =============================================================================

class BaseEditorView(discord.ui.View):
    """
    A base view that handles user validation, session management,
    and message references for all ephemeral editors.
    """
    def __init__(self, cog: commands.Cog, user_id: int, main_message: discord.Message | None, timeout: int = 180):
        super().__init__(timeout=timeout)
        
        self.cog = cog
        
        self.user_id = user_id
        self.main_message = main_message
        self.message = None # The ephemeral message this view is attached to
    
    async def get_cog(self) -> commands.Cog:
        """Helper function to fetch the cog safely."""
        return self.bot.get_cog("EditorCommands")
    
    def _get_bot_ref(self):
        """Helper to safely retrieve the bot reference, handling both Cog and Bot objects."""
        if hasattr(self.cog, 'bot'):
            # self.cog is a Cog instance
            return self.cog.bot
        # self.cog is likely the Bot instance itself
        return self.cog
            
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """
        Ensures that the user interacting is the one who
        initiated the command.
        """
        if interaction.user.id == self.user_id:
            return True
        
        await interaction.response.send_message(
            "This editor isn't for you.", ephemeral=True
        )
        return False

    async def on_timeout(self):
        """
        Clears the user's session lock on timeout.
        """
        self.cog.active_editor_sessions.pop(self.user_id, None)
        
        # Optional: Try to delete the ephemeral message
        if self.message and self.main_message:
            try:
                await self.message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

    async def cancel_and_delete(self, interaction: discord.Interaction):
        
        # 1. ALWAYS: Respond immediately to the interaction
        await interaction.response.defer() 
        
        try:
            if hasattr(self.cog, 'bot'):
                session_host = self.cog.bot
            else:
                session_host = self.cog
            if hasattr(session_host, 'active_editor_sessions'):
                session_host.active_editor_sessions.pop(self.user_id, None)
        except Exception:
            log.debug("Cancel and Delete exception triggered.")
            pass
        await interaction.delete_original_response()
    
    def _build_perk_map(self, unique_id_list: list[str]) -> dict[str, list[int]]:
        """
        Takes a list of 4 'unique_value' strings (or "NONE") and groups
        their *integer IDs* by their 'shield_type' (token).
        """
        # Get the Bot reference, which hosts the shield_perk_lookup cache
        bot_ref = self._get_bot_ref()
            
        perk_map = {"General": [], "Energy": [], "Armour": []}
        
        for unique_val_str in unique_id_list:
            if unique_val_str == "NONE":
                continue
            
            perk_data = bot_ref.shield_perk_lookup.get(unique_val_str)
            
            if not perk_data:
                log.debug(f"Warning: Perk unique_value {unique_val_str} not found in lookup cache.")
                continue
            
            shield_type = perk_data.get('shield_type') 
            perk_id = perk_data.get('id')
            
            if shield_type in perk_map:
                perk_map[shield_type].append(perk_id)
            else:
                log.debug(f"Warning: Perk {unique_val_str} has unknown shield_type '{shield_type}'")
                    
        return perk_map

class LevelModal(discord.ui.Modal, title="Set Item Level"):
    level_input = discord.ui.TextInput(
        label="Item Level (1-50)", 
        placeholder="Enter a number between 1 and 50",
        default="50",
        style=discord.TextStyle.short,
        max_length=2,
        required=True
    )

    def __init__(self, item_object: Union[weapon_class.Weapon, shield_class.Shield, repkit_class.Repkit], main_view: discord.ui.View):
        super().__init__()
        self.item_object = item_object
        self.main_view = main_view
        self.public_message = main_view.message

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer() 
        
        raw_level = self.level_input.value
        try:
            new_level = int(raw_level)
        except ValueError:
            new_level = 50 

        new_level = max(1, min(50, new_level))
        
        try:
            await self.item_object.update_level(new_level)
            new_serial = await self.item_object.get_serial()
            new_embed_desc = await self.item_object.get_parts_for_embed()
            
            original_embed = self.public_message.embeds[0]
            original_embed.description = new_embed_desc
            
            await self.public_message.edit(
                content=f"```{new_serial}```\n_ _\n",
                embed=original_embed
            )
            await interaction.followup.send(f"✅ Level set to **{new_level}**.", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"Error updating level: `{e}`", ephemeral=True)
            log.error(f"Failed to submit level update: \n%s", e, exc_info=True)

class RaritySelect(discord.ui.Select):
    def __init__(self, item_object: Union[weapon_class.Weapon, shield_class.Shield, repkit_class.Repkit], current_rarity: str):
        options = []

        for name in item_object.EDITABLE_RARITY_MAP.keys():
            options.append(
                discord.SelectOption(
                    label=name, 
                    value=name, 
                    default=(name == current_rarity)
                ) 
            )
        
        log.info(f"!!! LOG D: Rarity loop finished. {len(options)} options created.")

        super().__init__(
            placeholder="Select new Rarity...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
            custom_id="rarity_select"
        )

class RaritySelectionView(BaseEditorView):
    """Ephemeral view for setting Common/Uncommon/Rare/Epic rarity."""
    def __init__(self, item_object: Union[weapon_class.Weapon, shield_class.Shield, repkit_class.Repkit], cog: commands.Cog, user_id: int, main_message: discord.Message):
        super().__init__(cog, user_id, main_message) 
        
        self.item_object = item_object 
        
        current_rarity_token = self.item_object.parts.get("Rarity", ["{95}"])[0] 
        self.selection = self.item_object._get_rarity_string(current_rarity_token)
        
        self.embed = discord.Embed(
            title=f"Editing Rarity for {self.item_object.item_name}",
            # description=f"Current: **{self.selection}**.\nSelect a new Rarity below."
        )
        self._setup_components()
        self.rebuild_ui()
        
    def _setup_components(self):
        # Access the decorated method, forcing the component instance to be created.
        # This is a safe way to ensure self.rarity_select is not a function object.
        _ = self.rarity_select
        
    def rebuild_ui(self):
        
        # Build the options dynamically and set them on the select component
        self.rarity_select.options = []
        for name in self.item_object.EDITABLE_RARITY_MAP.keys():
            self.rarity_select.options.append(
                discord.SelectOption(
                    label=name,
                    value=name,
                    default=(name == self.selection)
                )
            )
        pass
        
    # --- NEW: Use the Decorator Pattern for Select Menu ---
    @discord.ui.select(row=0, custom_id="rarity_select_menu")
    async def rarity_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        # 1. Defer the interaction token first (stable pattern)
        await interaction.response.defer()
        
        # 2. Update the stored state
        self.selection = select.values[0]
        select.placeholder = f"Selected: {self.selection}"
        
        # 3. Update the description for the user
        # self.embed.description = f"Current: **{self.selection}**.\nSelect a new Rarity below."
        self.embed.description = f"Select a new Rarity below."
        
        # 4. Rebuild the components to update the default/placeholder state
        self.rebuild_ui() 

        # 5. FIX: Use followup to edit the message, providing the ID
        await interaction.followup.edit_message(
            self.message.id,
            embed=self.embed, 
            view=self
        )


    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey, row=4)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cancel_and_delete(interaction)

    # cogs/editor_views_shared.py (inside RaritySelectionView)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green, row=4)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        try:
            if hasattr(self.cog, 'bot'):
                session_host = self.cog.bot
            else:
                session_host = self.cog
            if hasattr(session_host, 'active_editor_sessions'):
                session_host.active_editor_sessions.pop(self.user_id, None)
        except Exception:
            pass
            
        try:
            await self.item_object.update_rarity(self.selection)
            
            new_serial = await self.item_object.get_serial()
            new_embed_desc = await self.item_object.get_parts_for_embed()
            new_color = self.item_object.get_rarity_color() 
            
            original_embed = self.main_message.embeds[0]
            original_embed.description = new_embed_desc
            original_embed.color = new_color 
            
            await self.main_message.edit(
                content=f"```{new_serial}```\n_ _\n",
                embed=original_embed
            )
            
            log.debug("Delete original message now.")
            # 3. Delete the ephemeral response
            await interaction.delete_original_response()
        
        except Exception as e:
            await interaction.followup.send(f"Error updating rarity: `{e}`", ephemeral=True)
            # If an error occurred, we still try to delete the message to clear the screen
            try:
                await interaction.delete_original_response() 
            except:
                pass
            log.error("Error confirming rarity update.\n%s", e, exc_info=True)

class ShieldPerkSelect(discord.ui.Select):
    """
    A Select menu for a single perk category.
    (SHARED component used by ShieldPerkEditorView and FirmwareSelectionView)
    """
    def __init__(self, placeholder: str, options: list[discord.SelectOption], row: int):
        
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"perk_select:{placeholder}",
            row=row
        )
        self.custom_id = f"perk_select:{placeholder}"

class FirmwareSelectionView(BaseEditorView):
    """
    Ephemeral view for Firmware.
    """
    def __init__(self, shield: shield_class.Shield, cog: commands.Cog, user_id: int, main_message: discord.Message):
        super().__init__(cog, user_id, main_message)
        self.shield = shield
        
        self.selections = self._get_current_selections()
                
        log.debug(f"Firmware Set: {self.selections['Firmware']}")
        
        self.embed = discord.Embed(
            title=f"Editing Firmware for {shield.item_name}",
            description=f"Select a new Firmware perk."
        )
        
        self._initialize_decorated_components()
        
    def _initialize_decorated_components(self):
        """Sets the initial options for the decorated select menu."""
        
        # FIX: Pass the placeholder string "Firmware", not the ID
        initial_options = self._get_options_for_page("Firmware", "Firmware", 0)
        
        # Access the decorated method instance and set its options property
        self.firmware_select.options = initial_options

    def _get_current_selections(self) -> dict:
        """Finds all 4 currently equipped perks and maps them."""
        # ... (This method is fine, no changes needed) ...
        bot_ref = self._get_bot_ref()
        selections = {
            "Weaker Part (Slot 1)": "NONE",
            "Stronger Part (Slot 2)": "NONE",
            "Elemental Resistance": "NONE",
            "Firmware": "NONE"
        }
        current_id_map = self.shield.get_current_perk_ids_by_type()
        
        all_ids = current_id_map.get("General", []) + \
                    current_id_map.get("Energy", []) + \
                    current_id_map.get("Armour", [])
        
        checked_ids = set()
        
        current_shield_type = self.shield.type # e.g., "Energy"
        
        for pid in all_ids:
            if pid in checked_ids:
                continue
            checked_ids.add(pid)
            
            # This relies on the cog having the cache
            perk_data_list = bot_ref.shield_perk_int_lookup.get(pid)
            if not perk_data_list:
                continue
                
            for perk_data in perk_data_list:
                # Check the shield_type of the perk data itself
                perk_shield_type = perk_data.get('shield_type')
                if (perk_shield_type != current_shield_type and perk_shield_type != 'General'):
                    # This perk data isn't for our shield type (e.g., it's 'Armour'
                    # data for an 'Energy' shield). Skip it.
                    continue
                slot, perk_type = perk_data.get('slot'), perk_data.get('perk_type')
                unique_value = perk_data['unique_value']
                
                if slot == 1:
                    selections["Weaker Part (Slot 1)"] = unique_value
                elif slot == 2:
                    selections["Stronger Part (Slot 2)"] = unique_value
                elif perk_type == 'Elemental Resistance':
                    selections["Elemental Resistance"] = unique_value
                elif perk_type == 'Firmware':
                    selections["Firmware"] = unique_value
        return selections
        
    def _get_options_for_page(self, placeholder: str, list_key: str, page_index: int) -> list[discord.SelectOption]:
        """Builds the SelectOption list using 'unique_value'."""
        bot_ref = self._get_bot_ref()
        
        # FIX: Get the current value from the self.selections dict
        #      using the placeholder key, just like in ShieldPerkEditorView
        current_unique_value = self.selections.get(placeholder, "NONE")
        
        options = [
            discord.SelectOption(
                label="None", 
                value="NONE", 
                # FIX: Check if the current selection is "NONE"
                default=(current_unique_value == "NONE")
            )
        ]
        
        added_values = {"NONE"}

        try:
            # This relies on the cog having the cache
            perk_list_page = bot_ref.shield_perk_lists[list_key][page_index]
        except IndexError:
            perk_list_page = [] 
            
        for perk in perk_list_page:
            unique_val_str = perk['unique_value']
            
            if unique_val_str in added_values:
                continue
                
            options.append(
                discord.SelectOption(
                    label=perk.get('name', 'Unknown Perk'),
                    value=unique_val_str,
                    default=(current_unique_value == unique_val_str)
                )
            )
            added_values.add(unique_val_str)
            
        return options
               
    @discord.ui.select(row=0, custom_id="perk_select:Firmware")
    async def firmware_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        
        selected_id = select.values[0]
        
        # 1. FIX: Update the canonical state in self.selections
        self.selections["Firmware"] = selected_id
        
        # 2. Look up the user-facing name for display in the embed
        selected_name = "None"
        if selected_id != "NONE":
            bot_ref = self._get_bot_ref()
            perk_data = bot_ref.shield_perk_lookup.get(selected_id)
            if perk_data:
                selected_name = perk_data.get('name', selected_id)
            else:
                selected_name = selected_id # Fallback

        select.placeholder = f"{selected_name}"
        
        # 4. Re-initialize to update the options list (which sets default=True based on the ID)
        self._initialize_decorated_components()

        await interaction.response.edit_message(embed=self.embed, view=self)
        
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
            # 5. FIX: Read all values from self.selections
            weaker_id = self.selections["Weaker Part (Slot 1)"]
            stronger_id = self.selections["Stronger Part (Slot 2)"]
            elemental_id = self.selections["Elemental Resistance"]
            firmware_id = self.selections["Firmware"]
            
            id_list = [weaker_id, stronger_id, elemental_id, firmware_id]
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
            log.error("Error during SHIELD firmware update:\n%s", e, exc_info=True)
            await interaction.followup.send(f"Error updating firmware: `{e}`", ephemeral=True)

        await interaction.delete_original_response()