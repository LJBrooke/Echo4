# cogs/editor_command.py
import discord
import logging
from discord import app_commands
from discord.ext import commands
from typing import Union, Tuple, Optional


# Helpers
from helpers import item_parser
from helpers import weapon_class
from helpers import shield_class
from helpers import repkit_class

# Views
from .weapon_editor_view import MainWeaponEditorView
from .shield_editor_view import MainShieldEditorView
from .repkit_editor_view import MainRepkitEditorView

log = logging.getLogger(__name__)

# Footers are standard for all messages dependent on data presented. Hence declared globally.
serial_footer = """\n-# Serialization thanks to [Nicnl and InflamedSebi](https://borderlands4-deserializer.nicnl.com/)"""
parts_footer = """\n-# Part information thanks to [this amazing resource](<https://docs.google.com/spreadsheets/d/17LHzPR7BltqgzbJZplr-APhORgT2PTIsV08n4RD3tMw/edit?gid=1385091622#gid=1385091622>)"""

# =============================================================================
# --- MAIN COG ---
# This class contains all slash commands and the core logic.
# =============================================================================

class EditorCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        if not hasattr(self.bot, 'active_editor_sessions'):
            self.bot.active_editor_sessions = {}
                   
        self.bot.shield_perk_lists = {}
        self.bot.shield_perk_lookup = {}
        self.bot.shield_perk_int_lookup = {}
        
        self.bot.repkit_perk_lists = {}
        self.bot.repkit_perk_lookup = {}
    
    async def cog_load(self):
        """
        This function is called by discord.py when the cog is loaded.
        It's the perfect place for async setup.
        """
        self.manufacturer_options = ["Daedalus", "Jakobs", "Maliwan", "Order", "Ripper", "Tediore", "Torgue", "Vladof"]
        self.weapon_type_options = ["Assault Rifle", "Pistol", "SMG", "Shotgun", "Sniper"]
        self.part_type_options = ["Barrel", "Barrel Accessory", "Body", "Body Accessory", "Foregrip", "Grip", "Magazine", "Manufacturer Part", "Scope", "Scope Accessory", "Stat Modifier", "Underbarrel", "Underbarrel Accessory"]    
        
        await self.load_shield_perk_cache()
        log.info("✅ Shield Perk Cache loaded.")
        
        await self.load_repkit_perk_cache()
        log.info("✅ Repkit Perk Cache loaded.")
        
    # Add this function after load_shield_perk_cache

    async def load_repkit_perk_cache(self):
        """
        Queries all repkit perks and builds cache structures.
        1. repkit_perk_lists:
            - ["Firmware"]: Static list of firmware perks (1-20)
            - ["Type"]: Static list of type perks (103-106)
            - ["Perks"]: Paginated list of other perks (21-97, no "Nothing")
        2. repkit_perk_lookup: A dict mapping perk_id (str) -> {perk_data}
        """
        PAGE_SIZE = 24
        TYPE_PERK_IDS = {103, 104, 105, 106}

        self.bot.repkit_perk_lists.clear()
        self.bot.repkit_perk_lookup.clear()

        self.bot.repkit_perk_lists = {"Firmware": [], "Type": [], "Perks": []}

        query = "SELECT id, name, perk_type, description FROM repkit_parts"

        try:
            all_perk_records = await self.bot.db_pool.fetch(query)

            firmware_perks = []
            type_perks = []
            other_perks = []

            for record in all_perk_records:
                record_dict = dict(record)
                perk_id = record_dict['id']
                perk_name = record_dict.get('name', '')

                # Unlike shields, unique_value can just be the string of the ID
                unique_value = str(perk_id)
                record_dict['unique_value'] = unique_value 

                # Add to universal lookup
                self.bot.repkit_perk_lookup[unique_value] = record_dict
                
                # --- Categorize Perks ---
                if 1 <= perk_id <= 20:
                    firmware_perks.append(record_dict)
                elif perk_id in TYPE_PERK_IDS:
                    type_perks.append(record_dict)
                elif 21 <= perk_id <= 97 and perk_name != 'Nothing':
                    other_perks.append(record_dict)

            # Sort Firmware perks by name
            firmware_perks.sort(key=lambda p: p['name'])
            self.bot.repkit_perk_lists["Firmware"] = [firmware_perks] # Single page

            # Sort Type perks by ID
            type_perks.sort(key=lambda p: p['id'])
            self.bot.repkit_perk_lists["Type"] = [type_perks] # Single page

            # Sort other perks by name
            other_perks.sort(key=lambda p: p['name'])

            # Paginate the "Perks" list
            for i in range(0, len(other_perks), PAGE_SIZE):
                self.bot.repkit_perk_lists["Perks"].append(other_perks[i:i + PAGE_SIZE])

            if not self.bot.repkit_perk_lists["Perks"]:
                self.bot.repkit_perk_lists["Perks"] = [[]] # Ensure at least one empty page

        except Exception as e:
            log.info(f"❌ FAILED TO LOAD REPKIT PERK CACHE ")
            log.error("Repkit Cache Error: %s", e, exc_info=True)
            self.bot.repkit_perk_lists = {}
            self.bot.repkit_perk_lookup = {}

    async def load_shield_perk_cache(self):
        """
        Queries all shield perks and builds two cache structures:
        1. shield_perk_lists: Paginated lists for UI dropdowns.
        2. shield_perk_lookup: A dict mapping perk_id -> {perk_data}
        """
        PAGE_SIZE = 24
        
        self.bot.shield_perk_lists.clear()
        self.bot.shield_perk_lookup.clear()
        self.bot.shield_perk_int_lookup.clear()
        
        self.bot.shield_perk_lists = {
            "Slot_1": [],
            "Slot_2": [],
            "Elemental_Resistance": [],
            "Firmware": []
        }
        
        query = "SELECT id, name, perk_type, shield_type, slot FROM shield_parts"
        
        try:
            all_perk_records = await self.bot.db_pool.fetch(query)
            
            slot_1_perks, slot_2_perks, elemental_perks, firmware_perks = [], [], [], []

            for record in all_perk_records:
                record_dict = dict(record)
                perk_id = record_dict['id']
                shield_type = record_dict.get('shield_type') 

                unique_value = f"{perk_id}_{shield_type}"
                record_dict['unique_value'] = unique_value 

                self.bot.shield_perk_lookup[unique_value] = record_dict
                
                if perk_id not in self.bot.shield_perk_int_lookup:
                    self.bot.shield_perk_int_lookup[perk_id] = []
                self.bot.shield_perk_int_lookup[perk_id].append(record_dict)
                
                slot, perk_type = record_dict.get('slot'), record_dict.get('perk_type')

                if slot == 1:
                    slot_1_perks.append(record_dict)
                elif slot == 2:
                    slot_2_perks.append(record_dict)
                elif perk_type == 'Elemental Resistance':
                    elemental_perks.append(record_dict)
                elif perk_type == 'Firmware':
                    firmware_perks.append(record_dict)

            for perk_list in [slot_1_perks, slot_2_perks, elemental_perks, firmware_perks]:
                perk_list.sort(key=lambda p: p['name'])

            for i in range(0, len(slot_1_perks), PAGE_SIZE):
                self.bot.shield_perk_lists["Slot_1"].append(slot_1_perks[i:i + PAGE_SIZE])
            for i in range(0, len(slot_2_perks), PAGE_SIZE):
                self.bot.shield_perk_lists["Slot_2"].append(slot_2_perks[i:i + PAGE_SIZE])
            
            self.bot.shield_perk_lists["Elemental_Resistance"] = [elemental_perks]
            self.bot.shield_perk_lists["Firmware"] = [firmware_perks]
            
            for key in ["Slot_1", "Slot_2"]:
                if not self.bot.shield_perk_lists[key]:
                    self.bot.shield_perk_lists[key] = [[]]
                
        except Exception as e:
            log.info(f"❌ FAILED TO LOAD SHIELD PERK CACHE ")
            log.error("Shield Cache Error: %s", e, exc_info=True)
            self.bot.shield_perk_cache = {}
            self.bot.shield_perk_lookup = {}
                   
    async def manufacturer_autocomplete(self, 
        interaction: discord.Interaction, 
        current: str
    ) -> list[app_commands.Choice[str]]:
        
        choices = [
            app_commands.Choice(name=m, value=m) 
            for m in self.manufacturer_options if current.lower() in m.lower()
        ]
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
        # --- EDIT COMMAND HELPER METHODS ---

    async def _deserialize_and_get_item_data(self, interaction: discord.Interaction, item_serial: str) -> Optional[Tuple[dict, int, str, str]]:
        """
        Helper 1: Deserializes the serial and queries the item's base data.
        Sends an error and returns None on failure.
        """
        deserialized_json = await item_parser.deserialize(self.bot.session, item_serial)
        item_str = deserialized_json.get('deserialized')

        if not item_str:
            await interaction.followup.send(
                "Error: Could not deserialize this serial. It might be invalid.",
                ephemeral=True
            )
            return None

        try:
            base_aspect, _ = item_str.split('||')
            base = base_aspect.split('|')[0]
            item_type_int_str = base.split(', ')[0]
            item_type_int = int(item_type_int_str)
        except (ValueError, IndexError) as e:
            log.warning("Failed to parse base_aspect from item_str: %s", item_str, exc_info=True)
            await interaction.followup.send(
                "Error: Could not parse the deserialized item string. The serial may be malformed.",
                ephemeral=True
            )
            return None

        item_type, manufacturer = await item_parser.query_type(self.bot.db_pool, item_type_int)

        if not item_type:
            await interaction.followup.send(
                f"Error: Unknown item type ID: `{item_type_int}`. Cannot edit.",
                ephemeral=True
            )
            return None
            
        return (deserialized_json, item_type_int, item_type, manufacturer)

    async def _create_item_and_view(self, interaction: discord.Interaction, item_serial: str, deserialized_json: dict, item_type_int: int, item_type: str, manufacturer: str) -> Optional[Tuple[Union[weapon_class.Weapon, shield_class.Shield], discord.ui.View]]:
        """
        Helper 2: Creates the appropriate item object (Weapon/Shield) and its
        corresponding editor view. Returns None if the item type is unsupported.
        """
        item_object = None
        editor_view = None

        if item_type.lower() == 'shield':
            item_object = await shield_class.Shield.create(
                self.bot.db_pool, 
                self.bot.session, 
                item_serial, 
                deserialized_json,
                item_type_int,
                manufacturer,
                item_type
            )
            editor_view = MainShieldEditorView(self.bot, item_object, interaction.user.id)
            
        if item_type.lower() == 'repair_kit':
            item_type='repkit' # For terminology consistenty and to avoid confusion.
            item_object = await repkit_class.Repkit.create(
                self.bot.db_pool, 
                self.bot.session, 
                item_serial, 
                deserialized_json,
                item_type_int,
                manufacturer,
                item_type
            )
            editor_view = MainRepkitEditorView(self.bot, item_object, interaction.user.id)

        elif item_type_int < 100: # Assuming < 100 are weapons
            item_object = await weapon_class.Weapon.create(
                self.bot.db_pool, 
                self.bot.session, 
                item_serial, 
                deserialized_json,
                item_type_int,
                manufacturer,
                item_type
            )
            editor_view = MainWeaponEditorView(self.bot, item_object, interaction.user.id)
        
        else:
            await interaction.followup.send(
                f"Sorry, item type '{item_type}' is not supported for editing.",
                ephemeral=True
            )
            return None
            
        return (item_object, editor_view)

    async def _build_and_send_editor_response(self, interaction: discord.Interaction, item_object: Union[weapon_class.Weapon, shield_class.Shield, repkit_class.Repkit], editor_view: discord.ui.View):
        """
        Helper 3: Builds the embed and sends the final response
        message with the editor view.
        """
        item_name = item_object.item_name
        part_list_string = await item_object.get_parts_for_embed()
        item_color = item_object.get_rarity_color()
        
        embed = discord.Embed(
            title=f"{item_name}",
            description=part_list_string,
            color=item_color
        )
        
        message_content = f"```{await item_object.get_serial()}```\n_ _\n"
        
        send_kwargs = {
            "content": message_content,
            "embed": embed,
            "view": editor_view
        }

        sent_message = await interaction.followup.send(**send_kwargs)
        
        if editor_view:
            editor_view.message = sent_message
     
    # --- The Slash Command ---
    @app_commands.command(name="deserialize", description="Convert a Bl4 item code to its components")
    @app_commands.describe(serial="Item serial to decode.")
    async def deserialize(self, interaction: discord.Interaction, serial: str):
        response = await item_parser.deserialize(self.bot.session, serial.strip())
        
        log.debug(response)
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
    @app_commands.describe(item_serial="Item serial")
    async def edit(self, interaction: discord.Interaction, item_serial: str):
        # --- Clanker Check (Last 5 Messages) ---
        trigger_clanker_response = False
        try:
            user_clank_message = None
            bot_clank_response = None

            # Scan the last 5 messages (newest to oldest)
            async for message in interaction.channel.history(limit=5):
                # Find the user's most recent "clanker" message
                if not user_clank_message and message.author.id == interaction.user.id and "clanker" in message.content.lower():
                    user_clank_message = message
                
                # Find the bot's most recent "clanker" response
                # Heuristic: It's from the bot, part of an 'edit' interaction, and mentions the user.
                if not bot_clank_response and message.author.id == self.bot.user.id and message.interaction and message.interaction.name == 'edit' and interaction.user.mention in message.content:
                    bot_clank_response = message
                
                # Optimization: if we've found both, we can stop scanning
                if user_clank_message and bot_clank_response:
                    break
            
            # Now, decide whether to trigger the response
            if user_clank_message: # The user has clanked
                if not bot_clank_response: # Bot has not responded at all
                    trigger_clanker_response = True
                else:
                    # Bot has responded. Only trigger if the user's clank is *newer* than the bot's last response.
                    if user_clank_message.created_at > bot_clank_response.created_at:
                        trigger_clanker_response = True
                    # If the user's clank is older, it's been handled. trigger_clanker_response remains False.

        except (discord.Forbidden, discord.HTTPException) as e:
            log.warning(f"Could not check for 'clanker' in message history: {e}")
            pass # Proceed normally
        except Exception as e:
            log.error(f"Unexpected error during 'clanker' check: {e}", exc_info=True)
            pass # Proceed normally

        if trigger_clanker_response:
            # --- Clanker Flow ---
            try:
                # We need item_parser for this new function
                response_text = await item_parser.query_clanker_response(self.bot.db_pool)
                await interaction.response.send_message(f"{interaction.user.mention} {response_text}")
            except Exception as e:
                log.error(f"Failed to send 'clanker' response: {e}", exc_info=True)
                # Try to send a fallback response
                try:
                    await interaction.response.send_message(f"{interaction.user.mention} You said the word!", ephemeral=True)
                except discord.InteractionResponded:
                    await interaction.followup.send(f"{interaction.user.mention} You said the word!", ephemeral=True)
            return # Stop the edit command
                
        try:
            await interaction.response.defer()
            
            item_serial = item_serial.strip()
            
            # --- Block 1: Deserialize and Validate ---
            item_data = await self._deserialize_and_get_item_data(interaction, item_serial)
            if not item_data:
                return # Error message was sent by the helper
            
            deserialized_json, item_type_int, item_type, manufacturer = item_data
            
            # --- Block 2: Create Item Object and View ---
            object_data = await self._create_item_and_view(
                interaction, item_serial, deserialized_json, 
                item_type_int, item_type, manufacturer
            )
            if not object_data:
                return # Error message was sent by the helper
                
            item_object, editor_view = object_data
            
            # --- Block 3: Build and Send Response ---
            await self._build_and_send_editor_response(interaction, item_object, editor_view)
            
        except Exception as e:
            log.error("--- EDIT COMMAND CRASHED ---\n%s", e, exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="💥 Command Crashed",
                        color=discord.Color.red(),
                        description="An internal error occurred."
                    )
                )
            else:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="💥 Command Crashed",
                        color=discord.Color.red(),
                        description="An internal error occurred."
                    )
                )

    # --- The Slash Command ---
    @app_commands.command(name="parts", description="Filter possible parts")
    @app_commands.describe(manufacturer="The Weapon Manufacturer")
    @app_commands.describe(weapon_type="What type of weapon do you parts for want?")
    @app_commands.describe(part_type="Which part type do you want?")
    @app_commands.autocomplete(
        manufacturer=manufacturer_autocomplete,
        weapon_type=weapon_type_autocomplete,
        part_type=part_type_autocomplete
    )
    async def parts(self, interaction: discord.Interaction, manufacturer: str, weapon_type: str, part_type: str):
        message = await item_parser.possible_parts_driver(
            db_pool=self.bot.db_pool,
            manufacturer=manufacturer,
            weapon_type=weapon_type,
            part_type=part_type
        )
        message = message+parts_footer
        await interaction.response.send_message(content=message)
        
        
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
