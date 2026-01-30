# cogs/editor_command.py
import json
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
parts_footer = """\n-# Part information thanks to [this amazing resource](<https://docs.google.com/spreadsheets/d/11TmXyGmIVoDFn4IFNJN1s2HuijSnn_nPZqN3LkDd5TA/edit?gid=1385091622#gid=1385091622>)"""

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
                if record_dict['perk_type'] == 'Firmware':
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

    async def edit_search_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> list[app_commands.Choice[str]]:
        """
        Autocompletes the search_term for /edit_search.
        Prioritizes distinct item_name matches.
        If no item_name matches, it searches for part_string matches.
        """
        choices = []
        
        # For performance, don't run expensive queries on tiny strings
        # If the user has typed 0 characters, show nothing.
        if len(current) == 0:
            return []
            
        # If they have typed 1 or 2 characters, give them a hint.
        if len(current) < 3:
            # Calculate how many more chars are needed
            needed = 3 - len(current)
            # Make the plural 's' dynamic
            char_s = 's' if needed > 1 else ''
            
            return [
                app_commands.Choice(
                    name=f"Keep typing ({needed} more char{char_s})...",
                    value=current # This value is harmless if selected
                )
            ]
            
        search_like = f"%{current}%"

        try:
            # --- Query 1: Find matching item_names (Priority) ---
            query_names = """
                SELECT DISTINCT item_name
                FROM item_edit_history
                WHERE item_name ILIKE $1
                ORDER BY item_name
                LIMIT 25
            """
            name_results = await self.bot.db_pool.fetch(query_names, search_like)

            if name_results:
                for record in name_results:
                    item_name = record['item_name']
                    # Add prefix to name for clarity in UI, value is the actual search term
                    choices.append(app_commands.Choice(name=f"[Item] {item_name}", value=item_name))
                return choices

            # --- Query 2: If no item_names, find matching part_strings ---
            # This query is "broad" - it finds rows where *anything* in the JSON
            # matches. We'll filter for part_string in Python.
            query_parts = """
                SELECT parts_json
                FROM item_edit_history
                WHERE parts_json::text ILIKE $1
                LIMIT 20
            """
            # We limit to 20 rows to keep the post-processing in Python fast
            
            part_results = await self.bot.db_pool.fetch(query_parts, search_like)

            if not part_results:
                return [] # No name matches, no part matches

            found_part_strings = set()
            current_lower = current.lower()

            for record in part_results:
                parts_json_str = record.get('parts_json')
                if not parts_json_str:
                    continue
                    
                try:
                    parts_dict = json.loads(parts_json_str)
                    # Iterate through all part types (e.g., "Body", "Grip")
                    for part_list in parts_dict.values():
                        if not isinstance(part_list, list):
                            continue # Skip non-list values like "Rarity": ["{98}"]
                            
                        # Iterate through all parts in that list
                        for part in part_list:
                            if isinstance(part, dict):
                                part_string = part.get('part_string')
                                # Check if part_string exists and matches the user's input
                                if part_string and current_lower in part_string.lower():
                                    found_part_strings.add(part_string)
                                    
                            if len(found_part_strings) >= 25:
                                break # We have enough choices
                    if len(found_part_strings) >= 25:
                        break
                except json.JSONDecodeError:
                    continue # Skip corrupted JSON in the DB

            # Now build choices from the set of found part strings
            for part_str in found_part_strings:
                # Add prefix to name for clarity in UI
                choices.append(app_commands.Choice(name=f"[Part] {part_str}", value=part_str))
            
            return choices[:25] # Final slice to ensure we don't exceed 25

        except Exception as e:
            log.error(f"Error during edit_search_autocomplete: {e}", exc_info=True)
            return [] # Return empty list on error

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
        # Get the interaction ID to use as a unique session ID
        session_id = str(interaction.id)

        if str(item_type.lower()) == 'shield':
            item_object = await shield_class.Shield.create(
                self.bot.db_pool, 
                self.bot.session, 
                item_serial, 
                deserialized_json,
                item_type_int,
                manufacturer,
                item_type
            )
            editor_view = MainShieldEditorView(self.bot, item_object, interaction.user.id, session_id)
            
        elif str(item_type.lower()) == 'repair_kit':
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
            editor_view = MainRepkitEditorView(self.bot, item_object, interaction.user.id, session_id)

        elif item_type_int < 100: # Assuming < 100 are weapons
            item_type=item_type.replace("riffle", "rifle")
            item_object = await weapon_class.Weapon.create(
                self.bot.db_pool, 
                self.bot.session, 
                item_serial, 
                deserialized_json,
                item_type_int,
                manufacturer,
                item_type
            )
            editor_view = MainWeaponEditorView(self.bot, item_object, interaction.user.id, session_id)
        
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
        embed.url = await item_parser.search_lootlemon(self.bot.db_pool, item_name, "bl4")
        
        current_serial = await item_object.get_serial()
        try:
            current_component_string = item_object.get_component_list()
        except Exception as e:
            current_component_string = {}
        message_content = f"```{current_serial}```\n_ _\n"
        
        try:
            await item_parser.log_item_edit(
                db_pool=self.bot.db_pool,
                session_id=str(interaction.id),  # This is our session ID
                user_id=interaction.user.id,
                edit_type="CREATE",
                item_name=item_object.item_name,
                item_type=item_object.type,
                manufacturer=item_object.manufacturer,
                serial=current_serial,
                component_string=current_component_string,
                parts_json=item_object.parts  # Log the initial parts state
            )
        except Exception as e:
            # Don't fail the command if logging fails
            log.warning(f"Failed to log item 'CREATE' for user {interaction.user.id}: {e}")
            
        send_kwargs = {
            "content": message_content,
            "embed": embed,
            "view": editor_view
        }

        sent_message = await interaction.followup.send(**send_kwargs)
        
        if editor_view:
            editor_view.message = sent_message
    
    async def _query_edit_history(self, interaction: discord.Interaction, edit_type: str, search_term: str, part_filter: Optional[str]) -> Optional[list]:
        """
        Helper 1: Queries the edit history and handles the 'no results' case.
        Returns the list of results or None if no results were found.
        """
        results = await item_parser.query_edit_history(
            db_pool=self.bot.db_pool,
            edit_type=edit_type,
            search_term=search_term,
            part_filter=part_filter
        )

        if not results:
            await interaction.followup.send(f"No results found for `{search_term}`.", ephemeral=True)
            return None
        
        return results

    async def _build_and_send_search_results(self, interaction: discord.Interaction, results: list, search_term: str):
        """
        Helper 2: Builds the results embed and sends it as a followup message.
        """
        embed = discord.Embed(
            title=f"Results for '{search_term}'",
            color=discord.Color.blue()
        )
        
        description_lines = []
        total_results = 0

        for i, record in enumerate(results, 1):
            serial = record.get('serial', 'N/A')
            parts_json_str = record.get('parts_json') # This is a JSON string

            primary_element, secondary_element = None, None
            # Add a header for the result
            result_header = f"**{record.get('item_name', 'Unknown Item')}**:\n```{serial}```"
            
            part_lines = []
            if not parts_json_str:
                part_lines.append("-> *No part data available*")
            else:
                try:
                    parts_dict = json.loads(parts_json_str) # Convert string to dict
                    
                    # Use the PART_ORDER from weapon_class for a logical display
                    for part_type in weapon_class.Weapon.PART_ORDER:
                        part_list = parts_dict.get(part_type, [])
                        
                        for part in part_list:
                            if isinstance(part, dict):
                                part_string = part.get('part_string')
                                if part_string:
                                    part_lines.append(f"-> `{part_string}`")
                            elif isinstance(part, str):
                                # This is a token like '{98}' or '{1:12}'
                                if ":" in part and part[1]=='1': # Check if it's a gun Element
                                    primary_element, secondary_element = await item_parser.query_elements_by_id(self.bot.db_pool, part)
                                else:
                                    part_lines.append(f"-> *Unrecognized Part: {part}*")
                                
                except json.JSONDecodeError:
                    part_lines.append("-> *Error parsing part data*")
            
            if primary_element:
                result_header = result_header + f"\nPrimary Element: {primary_element}"
                if secondary_element:
                    result_header = result_header + f"\nSecondary Element: {secondary_element}"
            # Check if this result + its parts will exceed the embed limit
            # 4096 is the description limit. We check at 4000 to be safe.
            current_desc = "\n".join(description_lines)
            result_block = "\n".join([result_header] + part_lines + ["_ _"]) # _ _ is a spacer
            
            if len(current_desc) + len(result_block) > 4000:
                # We can't add more results.
                embed.set_footer(text=f"Showing {total_results} of {len(results)} results (Embed limit reached).")
                break
            
            # It fits, add it to the description
            description_lines.append(result_block)
            total_results += 1

        embed.description = "\n".join(description_lines)
        await interaction.followup.send(embed=embed)
    
    async def _check_for_clanker(self, interaction: discord.Interaction) -> bool:
        """
        Checks the last 5 messages to see if the user said 'clanker'
        and has not been responded to yet.
        """
        try:
            user_clank_message = None
            bot_clank_response = None

            # Scan the last 5 messages (newest to oldest)
            async for message in interaction.channel.history(limit=10):
                # Find the user's most recent "clanker" message
                if not user_clank_message and message.author.id == interaction.user.id and ("clanker" in message.content.lower().replace(" ", '') or "best" in message.content.lower().replace(" ", '')):
                    user_clank_message = message
                
                # Find the bot's most recent "clanker" response.
                # A clanker response is from the bot, mentions the user,
                # and has NO embeds or components.
                if (not bot_clank_response and
                    message.author.id == self.bot.user.id and
                    interaction.user.mention in message.content and
                    not message.embeds and 
                    not message.components):
                    
                    bot_clank_response = message
                
                # Optimization: if we've found both, we can stop scanning
                if user_clank_message and bot_clank_response:
                    break
            
            # Now, decide whether to trigger the response
            if user_clank_message: # The user has clanked
                if not bot_clank_response: # Bot has not responded at all
                    return True
                else:
                    # Bot has responded. Only trigger if the user's clank is *newer* than the bot's last response.
                    if user_clank_message.created_at > bot_clank_response.created_at:
                        return True
                    # If the user's clank is older, it's been handled.
            
            return False # Default: do not trigger

        except (discord.Forbidden, discord.HTTPException) as e:
            log.warning(f"Could not check for 'clanker' in message history: {e}")
            return False # Proceed normally
        except Exception as e:
            log.error(f"Unexpected error during 'clanker' check: {e}", exc_info=True)
            return False # Proceed normally

    async def _send_clanker_response(self, interaction: discord.Interaction):
        """
        Queries the DB for a clanker response and sends it.
        """
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
                await interaction.followup.send(f"{interaction.user.mention}")
     
    # --- The Slash Command ---
    @app_commands.command(name="deserialize", description="Convert a Bl4 item code to its components")
    @app_commands.describe(serial="Item serial to decode.")
    async def deserialize(self, interaction: discord.Interaction, serial: str):
        response = await item_parser.deserialize(self.bot.session, serial.strip())
        
        log.debug(response)
        message = '**Item:** '+response.get('additional_data') + '\n**Deserialized String:** ```'+str(response.get('deserialized'))+"```"
               
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
        # --- Refactored Clanker Check ---
        if await self._check_for_clanker(interaction):
            await self._send_clanker_response(interaction)
            return # Stop the edit command
                
        try:
            await interaction.response.defer()
            
            item_serial = item_serial.strip()
            
            # --- Block 1: Deserialize and Validate ---
            item_data = await self._deserialize_and_get_item_data(interaction, item_serial)
            if not item_data: return # Error message was sent by the helper
            
            deserialized_json, item_type_int, item_type, manufacturer = item_data
            
            # --- Block 2: Create Item Object and View ---
            object_data = await self._create_item_and_view(
                interaction, item_serial, deserialized_json, 
                item_type_int, item_type, manufacturer
            )
            if not object_data: return # Error message was sent by the helper
                
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

    @app_commands.command(name="edit_search", description="Search the edit history for items and parts.")
    @app_commands.describe(
        search_term="An item name or part name to search for (e.g., 'Stellium', 'MAL_SG.part_barrel_01').",
        part_filter="[Optional] A specific part_string to *also* filter by (e.g., 'MAL_SG.part_grip_01').",
        edit_type="[Optional] Which edit type to show. Defaults to Post Edits."
    )
    @app_commands.choices(
        edit_type=[
            app_commands.Choice(name="Post Edit (Default)", value="FINAL"),
            app_commands.Choice(name="Pre Edit", value="CREATE"),
        ]
    )
    @app_commands.autocomplete(search_term=edit_search_autocomplete)
    async def edit_search(
        self,
        interaction: discord.Interaction,
        search_term: str,
        part_filter: str = None,
        edit_type: str = "FINAL"
    ):
        await interaction.response.defer()

        try:
            # --- Block 1: Query History ---
            results = await self._query_edit_history(
                interaction, edit_type, search_term, part_filter
            )
            if not results: 
                return # Error message was sent by the helper

            # --- Block 2: Build and Send Results ---
            await self._build_and_send_search_results(
                interaction, results, search_term
            )

        except Exception as e:
            log.error(f"Error during /edit_search: {e}", exc_info=True)
            embed = discord.Embed(
                title="💥 Search Crashed",
                color=discord.Color.red(),
                description="An internal error occurred while searching."
            )
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            
# --- Setup Function ---
async def setup(bot: commands.Bot):
    await bot.add_cog(EditorCommands(bot))
    print("✅ Cog 'EditorCommands' loaded.")
