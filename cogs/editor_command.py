# cogs/editor_command.py
import discord
from discord import app_commands
from discord.ext import commands
from helpers import item_parser
from helpers import weapon_class
from helpers import shield_class
import traceback 
import re

# Footers are standard for all messages dependent on data presented. Hence declared globally.
serial_footer = """\n-# Serialization thanks to [Nicnl and InflamedSebi](https://borderlands4-deserializer.nicnl.com/)"""
parts_footer = """\n-# Part information thanks to [this amazing resource](<https://docs.google.com/spreadsheets/d/17LHzPR7BltqgzbJZplr-APhORgT2PTIsV08n4RD3tMw/edit?gid=1385091622#gid=1385091622>)"""

# cogs/editor_command.py

class PrimaryElementSelect(discord.ui.Select):
    def __init__(self, weapon: weapon_class.Weapon, current_primary: str):
        
        # Options from the Weapon class constant
        options = [
            discord.SelectOption(
                label=e, 
                value=e, 
                default=(e == current_primary) # Set default selection
            ) 
            for e in weapon.ELEMENT_NAMES
        ]
        
        super().__init__(
            placeholder="Select Primary Element (Required)...",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        # Store the selection in the parent view
        self.view.primary_selection = self.values[0]
        await interaction.response.defer()

class SecondaryElementSelect(discord.ui.Select):
    def __init__(self, weapon: weapon_class.Weapon, current_secondary: str | None):
        
        # Options start with 'None' (to remove)
        options = [
            discord.SelectOption(label="None", value="None", description="Remove secondary element."),
        ]
        
        # Add all other elements except Kinetic (Kinetic is never a secondary)
        options.extend([
            discord.SelectOption(
                label=e, 
                value=e,
                default=(e == current_secondary)
            ) 
            for e in weapon.ELEMENT_NAMES if e != "Kinetic"
        ])
        
        super().__init__(
            placeholder="Select Secondary Element (Optional)...",
            min_values=0,
            max_values=1,
            options=options,
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        # Store the selection in the parent view. If self.values is empty, it means "None"
        self.view.secondary_selection = self.values[0] if self.values else "None"
        await interaction.response.defer()

class ElementSelectionView(discord.ui.View):
    """
    The ephemeral view for selecting Primary and Secondary elements.
    """
    def __init__(self, weapon: weapon_class.Weapon, cog: commands.Cog, user_id: int, main_message: discord.Message):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.message = None 
        self.main_message = main_message
        self.weapon = weapon
        
        # Get current elements for setting defaults
        # This is safe to call sync as the data is already loaded in self.weapon
        current_primary, current_secondary = self.weapon.get_current_element_names_sync() # Assume a new sync method
        
        # State tracking, initialized to current values
        self.primary_selection = current_primary
        self.secondary_selection = current_secondary
        
        # Add Select Menus
        self.add_item(PrimaryElementSelect(weapon, current_primary))
        self.add_item(SecondaryElementSelect(weapon, current_secondary))
        
        self.embed = discord.Embed(
            title=f"Editing Elements for {weapon.item_name}",
            description=f"Current: {current_primary} / {current_secondary or 'None'}\nSelect new element configuration below."
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey, row=4)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # ... (cancel logic is unchanged) ...
        self.cog.active_editor_sessions.pop(interaction.user.id, None)
        await interaction.response.defer()
        await interaction.delete_original_response()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green, row=4)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 1. Validate selection (Primary is required)
        if not self.primary_selection:
            await interaction.response.send_message("Please select a Primary Element.", ephemeral=True)
            return

        # 2. Release session lock
        self.cog.active_editor_sessions.pop(self.user_id, None)
        await interaction.response.defer()

        # 3. Process new element names
        new_secondary = self.secondary_selection
        if new_secondary == "None":
            new_secondary = None
            
        try:
            # 4. Update the weapon object
            await self.weapon.update_element(self.primary_selection, new_secondary)
            
            # 5. Refresh the main message display
            new_serial = await self.weapon.get_serial()
            new_embed_desc = await self.weapon.get_parts_for_embed()
            
            original_embed = self.main_message.embeds[0]
            original_embed.description = new_embed_desc
            
            await self.main_message.edit(
                content=f"```{new_serial}```\n_ _\n",
                embed=original_embed
            )
        
        except ValueError as e:
            # Catch ValueError from Weapon.update_element (e.g., element ID not found)
            print(f"Element ID error: {e}")
            await interaction.followup.send(
                f"Error: Could not combine those elements. Check if the element combination is valid for this weapon type. ({e})", 
                ephemeral=True
            )
        except Exception as e:
            # Catch all other errors
            print(f"Error during element update: {e}")
            await interaction.followup.send(
                f"An unexpected error occurred: `{e}`", 
                ephemeral=True
            )

        # 6. Delete this ephemeral message
        await interaction.delete_original_response()

class PartSelectionView(discord.ui.View):
    """
    An ephemeral view that now holds a reference to the main public message
    to edit it upon confirmation.
    """
    def __init__(self, weapon: weapon_class.Weapon, part_type: str, cog: commands.Cog, user_id: int, possible_parts: list, main_message: discord.Message):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.message = None
        self.selected_values = []
        
        self.weapon = weapon
        self.part_type = part_type
        self.main_message = main_message 
        self.add_item(PartOptionSelect(weapon, part_type, possible_parts))
        
        self.embed = discord.Embed(
            title=f"Editing: {self.part_type}",
            description=f"Select the new part(s) from the menu, then press 'Confirm'."
        )
    
    @classmethod
    async def create(cls, weapon: weapon_class.Weapon, part_type: str, cog: commands.Cog, user_id: int, main_message: discord.Message):
        """
        Asynchronously fetches and filters possible parts from the DB,
        then creates and returns an instance of the view.
        """
        possible_parts = await item_parser.get_compatible_parts(
            cog.bot.db_pool,
            weapon.manufacturer,
            weapon.type,
            part_type
        )
        
        # (Filtering logic for variants _01, _02)
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
        
        # Pass the main_message to the constructor
        return cls(weapon, part_type, cog, user_id, possible_parts, main_message)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey, row=4)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 1. Release the user's session lock
        self.cog.active_editor_sessions.pop(interaction.user.id, None)
        
        # 2. Delete the ephemeral message
        await interaction.response.defer()
        await interaction.delete_original_response()
        
    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green, row=4)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        
        # 1. Release the session lock
        self.cog.active_editor_sessions.pop(self.user_id, None)
        
        # 2. Acknowledge (ephemerally)
        await interaction.response.defer()
        
        try:
            # 3. Call the new update method on the weapon object
            await self.weapon.update_parts(self.part_type, self.selected_values)
            
            # 4. Get the new, updated data
            new_serial = await self.weapon.get_serial()
            new_embed_desc = await self.weapon.get_parts_for_embed()
            
            # 5. Get the original embed and update it
            original_embed = self.main_message.embeds[0]
            original_embed.description = new_embed_desc
            
            # 6. Edit the *main public message* with the new serial and embed
            await self.main_message.edit(
                content=f"```{new_serial}```\n_ _\n",
                embed=original_embed
            )
        
        except Exception as e:
            # Send a new ephemeral message on error
            print(f"Error during part update: {e}")
            await interaction.followup.send(
                f"An error occurred while updating the part: `{e}`", 
                ephemeral=True
            )

        # 7. Delete this ephemeral message
        await interaction.delete_original_response()

    async def on_timeout(self):
        # ... (unchanged) ...
        pass

    async def on_timeout(self):
        # When this view times out, we only want to remove it from the
        # session dict *if* it is still the active one.
        
        # Get the currently stored message for this user
        current_message = self.cog.active_editor_sessions.get(self.user_id)
        
        # If we have a message and it's the same as the one in the dict,
        # then this timeout is for the active session, and we clear it.
        if self.message and current_message and self.message.id == current_message.id:
            self.cog.active_editor_sessions.pop(self.user_id, None)

class PartOptionSelect(discord.ui.Select):
    def __init__(self, weapon: weapon_class.Weapon, part_type: str, possible_parts: list):
            
        min_val, max_val = weapon.get_part_limits(part_type)

        options = []
        for part_record in possible_parts:
            # part_record is an asyncpg.Record
            part_id = str(part_record['id'])
            part_str = part_record['part_string']
            
            # Use the generic formatter from item_parser
            pretty_name = item_parser.format_part_name(part_str)
            
            # Use stats for the description, with a fallback
            stats_desc = part_record.get('stats') or "No stat changes"
            # Truncate description to Discord's 100-char limit
            if len(stats_desc) > 100:
                stats_desc = stats_desc[:97] + "..."

            options.append(discord.SelectOption(
                label=pretty_name,
                value=part_id,
                description=stats_desc
            ))
        
        # 3. Handle cases where no parts are found
        is_disabled = False
        if not options:
            options.append(discord.SelectOption(
                label="No alternative parts found",
                value="DISABLED_NO_PARTS",
                description="This part type cannot be changed."
            ))
            # Set min=0, max=1, and disable the menu
            min_val = 0
            max_val = 1 
            is_disabled = True
        else:
            # This is the original capping logic, which is still needed
            max_val = min(max_val, len(options))
            min_val = min(min_val, max_val)
             
        super().__init__(
            placeholder=f"Select {part_type} (Choose {min_val} to {max_val})...",
            min_values=min_val,
            max_values=max_val,
            options=options,
            disabled=is_disabled
        )

    async def callback(self, interaction: discord.Interaction):
        # This is a final action, so we release the session lock
        # We access the cog and user_id from the parent view
        self.view.selected_values = self.values
        
        await interaction.response.defer()

class LevelModal(discord.ui.Modal, title="Set Weapon Level"):
    level_input = discord.ui.TextInput(
        label="Weapon Level (1-50)",
        placeholder="Enter a number between 1 and 50",
        default="50",
        style=discord.TextStyle.short,
        max_length=2,
        required=True
    )

    def __init__(self, weapon: weapon_class.Weapon, main_view: 'MainEditorView'):
        super().__init__()
        self.weapon = weapon
        self.main_view = main_view # Reference to the public message view

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer() # Acknowledge the modal submission
        
        raw_level = self.level_input.value
        try:
            # Try to convert to int, otherwise default to 50
            new_level = int(raw_level)
        except ValueError:
            new_level = 50 

        # Clamp the value between 1 and 50
        new_level = max(1, min(50, new_level))
        
        try:
            # 1. Update the weapon object
            await self.weapon.update_level(new_level)

            # 2. Get the new, updated data
            new_serial = await self.weapon.get_serial()
            new_embed_desc = await self.weapon.get_parts_for_embed()
            
            # 3. Edit the *main public message*
            original_embed = self.main_view.message.embeds[0]
            original_embed.description = new_embed_desc
            
            await self.main_view.message.edit(
                content=f"```{new_serial}```\n_ _\n",
                embed=original_embed
            )
            
            # 4. Send ephemeral confirmation
            await interaction.followup.send(f"✅ Level set to **{new_level}**.", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"Error updating level: `{e}`", ephemeral=True)

class RaritySelect(discord.ui.Select):
    def __init__(self, weapon: weapon_class.Weapon, current_rarity: str):
        
        # Build options from the weapon class constant
        options = [
            discord.SelectOption(
                label=name, 
                value=name, 
                default=(name == current_rarity)
            ) 
            for name in weapon_class.Weapon.EDITABLE_RARITY_MAP.keys()
        ]
        
        super().__init__(
            placeholder="Select new Rarity...",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.selection = self.values[0]
        await interaction.response.defer()

class RaritySelectionView(discord.ui.View):
    """Ephemeral view for setting Common/Uncommon/Rare/Epic rarity."""
    def __init__(self, weapon: weapon_class.Weapon, cog: commands.Cog, user_id: int, main_message: discord.Message):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.message = None
        self.main_message = main_message
        self.weapon = weapon
        
        # Get current rarity name for setting defaults
        current_rarity_token = self.weapon.parts.get("Rarity", ["{95}"])[0]
        current_rarity_name = self.weapon._get_rarity_string(current_rarity_token)
        
        self.selection = current_rarity_name # Initialize with current value
        
        self.add_item(RaritySelect(weapon, current_rarity_name))
        
        self.embed = discord.Embed(
            title=f"Editing Rarity for {weapon.item_name}",
            description=f"Current: **{current_rarity_name}**.\nSelect a new Rarity below."
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey, row=4)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.cog.active_editor_sessions.pop(interaction.user.id, None)
        await interaction.response.defer()
        await interaction.delete_original_response()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green, row=4)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 1. Release session lock
        self.cog.active_editor_sessions.pop(self.user_id, None)
        await interaction.response.defer()

        try:
            # 2. Update the weapon object
            await self.weapon.update_rarity(self.selection)
            
            # 3. Refresh the main message display
            new_serial = await self.weapon.get_serial()
            new_embed_desc = await self.weapon.get_parts_for_embed()
            new_color = self.weapon.get_rarity_color() # Update color!
            
            original_embed = self.main_message.embeds[0]
            original_embed.description = new_embed_desc
            original_embed.color = new_color # Set new color
            
            await self.main_message.edit(
                content=f"```{new_serial}```\n_ _\n",
                embed=original_embed
            )
            
        except Exception as e:
            await interaction.followup.send(f"Error updating rarity: `{e}`", ephemeral=True)

        # 4. Delete this ephemeral message
        await interaction.delete_original_response()
        
class MainEditorView(discord.ui.View):
    """
    The main view with buttons for each part type.
    Attached to the public /edit command response.
    """
    def __init__(self, cog: commands.Cog, weapon: weapon_class.Weapon, user_id: int):
        super().__init__(timeout=300) # 5-minute timeout
        self.weapon = weapon
        self.cog = cog
        self.user_id = user_id
        self.message = None
        
        level_button = discord.ui.Button(
            label=f"Set Level ({weapon.level})", # Display current level
            style=discord.ButtonStyle.blurple,
            custom_id="action_level",
            row=0
        )
        level_button.callback = self.main_button_callback
        self.add_item(level_button)
        
        # --- 2. Add Rarity Button (Conditional) ---
        current_rarity_token = weapon.parts.get("Rarity", ["{95}"])[0]
        current_rarity_name = weapon._get_rarity_string(current_rarity_token)
        
        # Only show button if the current rarity is one of the editable four
        if current_rarity_name in weapon_class.Weapon.EDITABLE_RARITY_MAP:
            rarity_button = discord.ui.Button(
                label=f"Rarity ({current_rarity_name})",
                style=discord.ButtonStyle.blurple,
                custom_id="action_rarity",
                row=0
            )
            rarity_button.callback = self.main_button_callback
            self.add_item(rarity_button)
        
        
        element_button = discord.ui.Button(
            label="Elements",
            style=discord.ButtonStyle.primary, # Distinct color for the element flow
            custom_id="edit_elements" 
        )
        element_button.callback = self.main_button_callback
        self.add_item(element_button)
        
        # --- Add buttons for each part type ---
        # We can dynamically create them based on the weapon's part list
        # to only show buttons for parts that actually exist.
        # We use the PART_ORDER from the weapon class to keep the button order consistent
        for part_type in self.weapon.PART_ORDER:
            # Only add a button if the weapon *has* that part type
            if part_type in self.weapon.parts and self.weapon.parts[part_type]:
                # Skip Body, Rarity and Elements, as those are handled differently
                if part_type in ["Rarity", "Primary Element", "Secondary Element", "Body"]:
                    continue
                
                # Create a button for this part type
                button = discord.ui.Button(
                    label=part_type,
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"edit_part:{part_type}"
                )
                # Assign the single callback to this new button
                button.callback = self.main_button_callback
                self.add_item(button)
        
    async def main_button_callback(self, interaction: discord.Interaction):
        custom_id = interaction.data['custom_id']
        
        # 1. Level Modal (Bypasses Session Lock)
        if custom_id == "action_level":
            modal = LevelModal(self.weapon, self)
            await interaction.response.send_modal(modal)
            return
        
        # 1. Concurrency Check/Override (same as before)
        if interaction.user.id in self.cog.active_editor_sessions:
            old_message = self.cog.active_editor_sessions.pop(interaction.user.id, None)
            if old_message:
                try: await old_message.delete()
                except (discord.NotFound, discord.Forbidden): pass 
        
        await interaction.response.defer(ephemeral=True)
        
        ephemeral_view = None
        
        if custom_id == "action_rarity":
            ephemeral_view = RaritySelectionView(
                self.weapon, self.cog, interaction.user.id, self.message
            )
        
        # 2. Route the click based on custom_id
        if custom_id.startswith("edit_part:"):
            # Existing Part Logic (uses async factory)
            part_type = custom_id.split(':')[-1]
            ephemeral_view = await PartSelectionView.create(
                self.weapon, part_type, self.cog, interaction.user.id, self.message
            )
        
        elif custom_id == "edit_elements":
            # NEW Element Logic (uses synchronous constructor)
            ephemeral_view = ElementSelectionView(
                self.weapon, self.cog, interaction.user.id, self.message
            )
        
        # 3. Send the ephemeral message
        if ephemeral_view:
            new_message = await interaction.followup.send(
                embed=ephemeral_view.embed,
                view=ephemeral_view,
                ephemeral=True
            )
            ephemeral_view.message = new_message
            self.cog.active_editor_sessions[interaction.user.id] = new_message
    
    async def on_timeout(self):
        """Called when the view's 5-minute timer expires."""
        
        # 1. Remove buttons from the main public message
        if self.message: # self.message is the public message this view is attached to
            try:
                await self.message.edit(view=None)
            except (discord.NotFound, discord.Forbidden):
                pass # Message was deleted or permissions lost

        # 2. Find and delete any active ephemeral edit message for this user
        if self.user_id and self.cog:
            # Pop the ephemeral message from the session dict
            ephemeral_message = self.cog.active_editor_sessions.pop(self.user_id, None)
            
            if ephemeral_message:
                try:
                    await ephemeral_message.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass # Ephemeral message was already closed or deleted    
              
# --- Define the Cog Class ---
class EditorCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_editor_sessions = {}
    
    async def cog_load(self):
        """
        This function is called by discord.py when the cog is loaded.
        It's the perfect place for async setup.
        """
        self.manufacturer_options = ["Daedalus", "Jakobs", "Maliwan", "Order", "Ripper", "Tediore", "Torgue", "Vladof"]
        self.weapon_type_options = ["Assault Rifle", "Pistol", "SMG", "Shotgun", "Sniper"]
        self.part_type_options = ["Barrel", "Barrel Accessory", "Body", "Body Accessory", "Foregrip", "Grip", "Magazine", "Manufacturer Part", "Scope", "Scope Accessory", "Stat Modifier", "Underbarrel", "Underbarrel Accessory"]    
            
    async def manufacturer_autocomplete(self, 
        interaction: discord.Interaction, 
        current: str
    ) -> list[app_commands.Choice[str]]:
        
        # Filter the cached list based on the user's typing
        choices = [
            app_commands.Choice(name=m, value=m) 
            for m in self.manufacturer_options if current.lower() in m.lower()
        ]
        # Return up to 25 choices (Discord's limit)
        return choices[:25]

    async def weapon_type_autocomplete(self, 
        interaction: discord.Interaction, 
        current: str
    ) -> list[app_commands.Choice[str]]:
        
        choices = [
            app_commands.Choice(name=wt, value=wt) 
            for wt in self.weapon_type_options if current.lower() in wt.lower()
        ]
        return choices[:25]

    async def part_type_autocomplete(self, 
        interaction: discord.Interaction, 
        current: str
    ) -> list[app_commands.Choice[str]]:
        
        choices = [
            app_commands.Choice(name=pt, value=pt) 
            for pt in self.part_type_options if current.lower() in pt.lower()
        ]
        return choices[:25]
          
    # --- The Slash Command ---
    @app_commands.command(name="deserialize", description="Convert a Bl4 item code to its components")
    @app_commands.describe(serial="Item serial to decode.")
    async def deserialize(self, interaction: discord.Interaction, serial: str):
        response = await item_parser.deserialize(self.bot.session, serial.strip())
        
        print(response)
        message = '**Item:** '+response.get('additional_data') + '\n**Deserialized String:** ```'+response.get('deserialized')+"```"
               
        message = message+parts_footer
        await interaction.response.send_message(content=message)

    # --- The Slash Command ---
    @app_commands.command(name="serialize", description="Encode a Bl4 item string to its serial value")
    @app_commands.describe(serial="Item string to serialize.")
    async def serialize(self, interaction: discord.Interaction, serial: str):
        response = await item_parser.reserialize(self.bot.session, serial.strip())
        
        message = '**Item:** '+response.get('additional_data') + '\n**Serialized String:** ```'+response.get('serial_b85')+"```"
        
        message = message+serial_footer
        await interaction.response.send_message(content=message)
    
    # --- The Slash Command ---
    @app_commands.command(name="inspect", description="Show weapon parts associated with a serial or component list")
    @app_commands.describe(weapon_id="weapon serial or component list")
    async def inspect(self, interaction: discord.Interaction, weapon_id: str):
        message = await item_parser.part_list_driver(
            session=self.bot.session,
            db_pool=self.bot.db_pool,
            item_code=weapon_id
        )
        message = message+serial_footer+parts_footer
        await interaction.response.send_message(content=message)

    @app_commands.command(name="edit", description="Edit the parts on your gun or shield!")
    @app_commands.describe(weapon_serial="Item serial")
    async def edit(self, interaction: discord.Interaction, weapon_serial: str):
        try:
            await interaction.response.defer()
            
            # --- STEP 1: Deserialize and Get Type (as you requested) ---
            
            # 1. Deserialize the item
            deserialized_json = await item_parser.deserialize(self.bot.session, weapon_serial.strip())
            item_str = deserialized_json.get('deserialized')

            if not item_str:
                await interaction.followup.send(
                    "Error: Could not deserialize this serial. It might be invalid.",
                    ephemeral=True
                )
                return

            # 2. Parse the item_type_int from the string
            # '24, 0, 1, 50|...' -> '24'
            base_aspect, _ = item_str.split('||')
            base, _ = base_aspect.split('|')
            item_type_int_str, _, _, _ = base.split(', ')
            item_type_int = int(item_type_int_str)

            # 3. Query the item type
            item_type, manufacturer = await item_parser.query_type(self.bot.db_pool, item_type_int)

            if not item_type:
                await interaction.followup.send(
                    f"Error: Unknown item type ID: `{item_type_int}`. Cannot edit.",
                    ephemeral=True
                )
                return

            # --- STEP 2: Route to the correct Class and View ---
            
            item_object = None
            editor_view = None

            if item_type.lower() == 'shield':
                # --- SHIELD PATH ---
                item_object = await shield_class.Shield.create(
                    self.bot.db_pool, 
                    self.bot.session, 
                    weapon_serial.strip(), 
                    deserialized_json,
                    item_type_int,
                    manufacturer,
                    item_type
                )
                
                # TODO: We need to create a 'MainShieldEditorView'
                # For now, we'll just send the "inspect" embed without edit buttons
                # editor_view = MainShieldEditorView(self, item_object, interaction.user.id)

            elif item_type_int < 100: # Your logic for weapons
                # --- WEAPON PATH ---
                item_object = await weapon_class.Weapon.create(
                    self.bot.db_pool, 
                    self.bot.session, 
                    weapon_serial.strip(), 
                    deserialized_json,
                    item_type_int,
                    manufacturer,
                    item_type
                )
                # Use the existing MainEditorView for weapons
                editor_view = MainEditorView(self, item_object, interaction.user.id)
            
            else:
                await interaction.followup.send(
                    f"Sorry, item type '{item_type}' is not supported for editing.",
                    ephemeral=True
                )
                return

            # --- STEP 3: Send the response ---
            
            item_name = item_object.item_name
            part_list_string = await item_object.get_parts_for_embed()
            item_color = item_object.get_rarity_color()
            
            embed = discord.Embed(
                title=f"{item_name}",
                description=part_list_string,
                color=item_color
            )
            
            message_content = f"```{await item_object.get_serial()}```\n_ _\n"
            
            # Send the message. If editor_view is None (e.g., for shields),
            # it will send a non-interactive message.
            # --- STEP 3: Send the response ---
            
            item_name = item_object.item_name
            part_list_string = await item_object.get_parts_for_embed()
            item_color = item_object.get_rarity_color()
            
            embed = discord.Embed(
                title=f"{item_name}",
                description=part_list_string,
                color=item_color
            )
            
            message_content = f"```{await item_object.get_serial()}```\n_ _\n"

            # Create the payload as a dict
            send_kwargs = {
                "content": message_content,
                "embed": embed
            }
            
            # Only add the 'view' key if editor_view is not None
            if editor_view:
                send_kwargs["view"] = editor_view

            # Send the message by unpacking the kwargs dict
            sent_message = await interaction.followup.send(**send_kwargs)
            
            # If we created a view, assign the message to it
            if editor_view:
                editor_view.message = sent_message
            
            # If we created a view, assign the message to it
            if editor_view:
                editor_view.message = sent_message

        except Exception as e:
            # (Your existing robust error handling)
            error_traceback = traceback.format_exc()
            print("--- EDIT COMMAND CRASHED ---")
            print(error_traceback)
            print("----------------------------")
            
            await interaction.followup.send(
                embed=discord.Embed(
                    title="💥 Command Crashed",
                    color=discord.Color.red(),
                    description=f"An error occurred:\n```\n{error_traceback[:1900]}\n```"
                )
            )

    # --- The Slash Command ---
    @app_commands.command(name="element_id", description="Fetch the part id for elements on a gun")
    @app_commands.describe(primary_element="The Primary or only element on your gun")
    @app_commands.describe(secondary_element="The element you can switch to if the gun has the option, otherwise 'None'")
    @app_commands.describe(maliwan="Is this a Maliwan gun?")
    @app_commands.choices(
        primary_element=[
            app_commands.Choice(name="Corrosive", value="Corrosive"),
            app_commands.Choice(name="Cryo", value="Cryo"),
            app_commands.Choice(name="Fire", value="Fire"),
            app_commands.Choice(name="Radiation", value="Radiation"),
            app_commands.Choice(name="Shock", value="Shock"),
        ],
        secondary_element=[
            app_commands.Choice(name="None", value="None"),
            app_commands.Choice(name="Corrosive", value="Corrosive"),
            app_commands.Choice(name="Cryo", value="Cryo"),
            app_commands.Choice(name="Fire", value="Fire"),
            app_commands.Choice(name="Radiation", value="Radiation"),
            app_commands.Choice(name="Shock", value="Shock"),
        ],
        maliwan=[
            app_commands.Choice(name="No", value='False'),
            app_commands.Choice(name="Yes", value='True'),
        ]
    )
    async def get_element_id(self, interaction: discord.Interaction, primary_element: str, secondary_element: str, maliwan: str):
        if maliwan == 'True' and secondary_element!="None": underbarrel=True
        else: underbarrel=False
        message = await item_parser.query_element_id(
            db_pool=self.bot.db_pool,
            primary=primary_element,
            secondary=secondary_element,
            underbarrel=underbarrel
        )
        message = f"Primary Element: {primary_element}\nSecondary Element: {secondary_element}\nMaliwan: {str(underbarrel)}\n\n**Element ID:** {message}\n{parts_footer}"
        await interaction.response.send_message(content=message)
         
# --- Setup Function ---
async def setup(bot: commands.Bot):
    await bot.add_cog(EditorCommands(bot))
    print("✅ Cog 'EditorCommands' loaded.")