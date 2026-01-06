# helpers/weapon_class.py
import discord
import re
from helpers import item_parser
import logging

# Get a logger for this specific module
log = logging.getLogger(__name__)

class Weapon:
    """Represents the BL4 item being edited."""
    
    PART_ORDER = [
        "Rarity",           
        "Body", 
        "Body Accessory", 
        "Primary Element", 
        "Barrel", 
        "Barrel Accessory", 
        "Magazine",         
        "Scope",
        "Scope Accessory",  
        "Grip", 
        "Underbarrel",
        "Foregrip",
        "Stat Modifier",
        "Secondary Element"  
    ]
    
    DEFAULT_PART_LIMITS = {
        "Body": (1, 1),
        "Body Accessory": (1, 4),
        "Primary Element": (1, 1),
        "Barrel": (1, 1),
        "Barrel Accessory": (1, 4),
        "Magazine": (1, 2),
        "Scope": (1, 1),
        "Scope Accessory": (1, 2),
        "Grip": (1, 1),
        "Underbarrel": (0, 2),
        "Foregrip": (0, 1),
        "Stat Modifier": (0, 2),
        "Secondary Element": (0, 1)
        # Rarity not included yet, may include it +Legendary select later.
    }
    
    EDITABLE_RARITY_MAP = {
        "Common": "95",
        "Uncommon": "96",
        "Rare": "97",
        "Epic": "98"
    }
    
    ACCESSORY_MAP = {
        "Barrel": "Barrel Accessory",
        "Scope": "Scope Accessory",
        "Body": "Body Accessory"
    }
    
    ELEMENT_NAMES = ["Kinetic", "Fire", "Corrosive", "Shock", "Cryo", "Radiation"]
    DEFAULT_PRIMARY_ELEMENT = "Kinetic"
    
    # 1. A synchronous and minimal __init__
    def __init__(self, db_pool, session, initial_serial: str):
        self.db_pool = db_pool
        self.session = session
        self.original_serial = initial_serial.strip()
        
        self.primary_element_name = self.DEFAULT_PRIMARY_ELEMENT
        self.secondary_element_name = None
        # Initialize attributes that will be populated by the 'create' method
        self.item_str = ""
        self.skin_data = ""
        self.item_type_int = 0
        self.level = 0
        self.extra = ""
        self.type = ""
        self.manufacturer = ""
        self.primary_element_token = []
        self.secondary_element_tokens = []
        self.parts = {}
        self.rarity_tokens = {}
        self.current_part_type = 'Body'
        self.additional_data = ""
        self.item_name = "Unknown Item"

    @classmethod
    async def create(cls, db_pool, session, initial_serial: str, deserialized_json: dict, item_type_int: int, manufacturer: str, item_type: str):        
        """
        Asynchronously creates and initializes a Weapon instance.
        """
        log.info("Creating new Weapon instance for item type %s (%s)", item_type_int, manufacturer)
        # First, create the "empty" instance using the synchronous __init__
        weapon = cls(db_pool, session, initial_serial)
        
        # Now, perform all async operations and populate the instance
        try:            
            weapon.item_str = deserialized_json.get('deserialized')
            weapon.additional_data = deserialized_json.get('additional_data', '')
            base_aspect, part_aspect = weapon.item_str.split('||')
            base, weapon.skin_data = base_aspect.split('|')
            if weapon.additional_data and '"' in weapon.additional_data:
                parts = weapon.additional_data.split('"')
                if len(parts) > 1:
                    weapon.item_name = parts[1]
            
            # We already have item_type_int, but we still need to parse level
            _, base_0, base_1, weapon.level = base.split(', ')
            parts_string = part_aspect.split('|')[0]
            weapon.extra = part_aspect.split('|')[1:]
                        
            all_part_tokens = re.findall(r"\{[\d:]+\}", parts_string)
            
            element_tokens = [p for p in all_part_tokens if ':' in p]
            weapon.primary_element_token = [element_tokens[0]] if element_tokens else []
            weapon.secondary_element_tokens = element_tokens[1:]
            
            regular_part_tokens = [int(p[1:-1]) for p in all_part_tokens if ':' not in p]
            
            # --- ASSIGN PRE-FETCHED DATA ---
            weapon.item_type_int = item_type_int
            weapon.type = item_type.replace('_',' ')
            weapon.manufacturer = manufacturer
            
            log.debug("Querying part list from DB for %s %s", weapon.manufacturer, weapon.type)
            part_list_results = await item_parser.query_part_list(
                weapon.db_pool, weapon.manufacturer, weapon.type, regular_part_tokens
            )
            
            returned_ids = {part['id'] for part in part_list_results}
            weapon.rarity_tokens = [
                "{"+str(p)+"}" for p in regular_part_tokens if int(p) not in returned_ids
            ]
            
            # Call the synchronous helper methods
            weapon._build_structured_parts(part_list_results)
            
            weapon.parts["Rarity"] = weapon.rarity_tokens
            weapon.parts["Primary Element"] = weapon.primary_element_token
            weapon.parts["Secondary Element"] = weapon.secondary_element_tokens
            
            weapon.primary_element_name, weapon.secondary_element_name = await weapon.get_current_element_names()
            
            log.info("Successfully created Weapon instance for %s", weapon.item_name)
            # Return the fully populated instance
            return weapon
            
        except Exception as e:
            log.error("Failed to create Weapon instance during create(): %s", e, exc_info=True)
            raise e

    async def get_serial(self) -> str:
        log.debug("Reserializing weapon to get new serial...")
        serial_dict = await item_parser.reserialize(self.session, self.get_component_list())
        return str(serial_dict.get('serial_b85')+' ')

    async def get_current_element_names(self) -> tuple[str, str | None]:
        """
        Fetches the primary and secondary element names for display
        by querying the two element tokens.
        Returns: (primary_name, secondary_name or None)
        """
        log.debug("Querying current element names from tokens...")
        primary_token_list = self.parts.get("Primary Element", [])
        secondary_token_list = self.parts.get("Secondary Element", [])
        
        # --- 1. Get Primary Name from Primary Token ---
        if primary_token_list:
            primary_token = primary_token_list[0]
            # We only care about the primary_element field from this token
            primary_name, _ = await item_parser.query_elements_by_id(self.db_pool, primary_token)
        else:
            primary_name = self.DEFAULT_PRIMARY_ELEMENT
            log.debug("No primary element token found. Using default: %s", self.DEFAULT_PRIMARY_ELEMENT)

        # --- 2. Get Secondary Name from Secondary Token ---
        secondary_name = None
        if secondary_token_list:
            secondary_token = secondary_token_list[0]
            # We query the secondary token, which contains the info for the dual-element gun.
            # We are safe to use the secondary_element field here.
            _, secondary_name = await item_parser.query_elements_by_id(self.db_pool, secondary_token)
        
        log.debug("Element names resolved: Primary=%s, Secondary=%s", primary_name, secondary_name)
        return primary_name or self.DEFAULT_PRIMARY_ELEMENT, secondary_name

    async def get_parts_for_embed(self) -> str:
        """
        Generates a formatted, indented string list of all current parts
        for an embed, with priority fields at the top.
        """
        log.debug("Generating parts list for embed display.")
        display_lines = []

        rarity_list = self.parts.get("Rarity", [])
        # ... (Rarity logic) ...

        display_lines.append(f"**Level:** {self.level}")
        
        # --- NEW ELEMENT DISPLAY LOGIC ---
        primary_name, secondary_name = await self.get_current_element_names()

        line_to_append = f"**Element:** {primary_name}"
        if secondary_name: 
            line_to_append += f"/{secondary_name}"
        
        display_lines.append(line_to_append)
        # --- 2. Define Display Order for Remaining Parts ---
        REMAINING_PART_ORDER = [
            "Body", 
            "Body Accessory", 
            "Barrel", 
            "Barrel Accessory", 
            "Magazine",         
            "Scope",
            "Scope Accessory",  
            "Grip", 
            "Underbarrel",
            "Foregrip",
            "Stat Modifier"
        ]

        # --- 3. Add Formatted Part List ---
        for part_type in REMAINING_PART_ORDER:
            if part_type!='Body':
                parts_list = self.parts.get(part_type, [])
                if not parts_list:
                    continue
                
                # Add the heading
                display_lines.append(f"**\n{part_type}:**")
                
                # All others are lists of dicts
                for p in parts_list:
                    part_str = p.get('part_string', 'N/A')
                    part_stat = p.get('stats', '')
                    
                    pretty_name = item_parser.format_part_name(part_str)
                    
                    display_lines.append(f"-> `{pretty_name}` : {part_stat}")
        
        return "\n".join(display_lines)

    async def update_parts(self, part_type: str, new_part_ids_str: list[str]): 
        """
        Asynchronously updates the parts list for a given part_type
        with a new list of part IDs and automatically updates accessories
        if a base part variant is changed.
        """
        log.info("Updating parts for type: %s with %s new part(s)", part_type, len(new_part_ids_str))
        
        # 1. Capture the OLD variant before update
        old_part_data = self.parts.get(part_type, [{}])[0] if self.parts.get(part_type) else {}
        old_variant = old_part_data.get('variant')

        is_base_part = part_type in self.ACCESSORY_MAP

        # 2. PERFORM THE MAIN PART UPDATE
        if not new_part_ids_str:
            self.parts[part_type] = []
            new_processed_parts = []
        else:
            # Fetch and process new parts
            new_part_ids_int = [int(pid) for pid in new_part_ids_str]
            part_list_results = await item_parser.query_part_list(self.db_pool, self.manufacturer, self.type, new_part_ids_int)
            new_processed_parts = [self._process_part_record(part_data) for part_data in part_list_results]
            self.parts[part_type] = new_processed_parts

        # 3. ACCESSORY AUTO-UPDATE LOGIC
        if is_base_part:
            # Get the NEW variant after update
            new_variant = new_processed_parts[0].get('variant') if new_processed_parts else None
            
            # Only proceed if the variant has changed (e.g., '01' -> '02')
            if old_variant != new_variant:
                log.info("Base part variant changed from '%s' to '%s'. Checking for accessory updates.", old_variant, new_variant)
                
                accessory_type = self.ACCESSORY_MAP[part_type]
                updated_accessories = []
                
                # Check all currently equipped accessories of the corresponding type
                for equipped_accessory in self.parts.get(accessory_type, []):
                    
                    # Check if the equipped accessory is the OLD variant.
                    # Accessories with variant=None (wildcards) are skipped.
                    if equipped_accessory.get('variant') == old_variant and old_variant is not None:
                        log.debug("Accessory %s matches old variant '%s'. Attempting to find new variant '%s'.", equipped_accessory['part_string'], old_variant, new_variant)
                        
                        # a. Construct the new part string based on the new variant
                        part_string = equipped_accessory['part_string']
                        
                        if new_variant:
                            # Replace old variant in string with new variant
                            # e.g., '...barrel_01_a' -> '...barrel_02_a'
                            new_part_string = part_string.replace(f"_{old_variant}", f"_{new_variant}")
                        else:
                            # The new base part is a wildcard (no variant). 
                            # We keep the old accessory, even if it has a variant, as per your rule.
                            # We do not change its string or lookup a new ID.
                            log.debug("New base part is a wildcard. Keeping original accessory: %s", part_string)
                            updated_accessories.append(equipped_accessory)
                            continue

                        # b. Query the DB for the new accessory part data
                        log.debug("Querying DB for new accessory string: %s", new_part_string)
                        new_accessory_data = await item_parser.query_part_by_string(
                            self.db_pool, self.manufacturer, self.type, new_part_string
                        )

                        if new_accessory_data:
                            # Found the new variant part! Replace the old one.
                            log.debug("Found matching new accessory: %s", new_accessory_data['part_string'])
                            updated_accessories.append(self._process_part_record(new_accessory_data))
                        else:
                            # New variant part not found (e.g., 'Barrel Accessory 02' doesn't exist).
                            # We skip the accessory, effectively removing it.
                            log.warning("Could not find accessory variant %s. Accessory removed.", new_part_string)
                    
                    else:
                        # Accessory is either a wildcard (no variant) or doesn't match the old variant. Keep it.
                        log.debug("Accessory %s is a wildcard or did not match old variant. Keeping it.", equipped_accessory['part_string'])
                        updated_accessories.append(equipped_accessory)

                # 4. Overwrite the old accessory list with the new, updated list
                self.parts[accessory_type] = updated_accessories
                log.info("Accessory auto-update complete. Final %s count: %s", accessory_type, len(updated_accessories))

        log.info("Completed part update for %s", part_type)

    async def update_element(self, new_primary_name: str, new_secondary_name: str | None):
        """
        Updates the primary and optional secondary element tokens in two separate slots.
        new_secondary_name = None means remove the secondary element.
        """
        log.info("Updating elements: Primary=%s, Secondary=%s", new_primary_name, new_secondary_name)
        
        # 1. Determine Maliwan flag (affects the dual-element token ID lookup)
        # --- LOGIC CORRECTION ---
        # Original was: not self.manufacturer.lower() == 'maliwan'
        # This set the flag to False for Maliwan, which seems incorrect.
        is_not_maliwan_flag = not (self.manufacturer.lower() == 'maliwan')
        log.debug("Manufacturer is '%s'. Setting Maliwan flag to: %s", self.manufacturer, is_not_maliwan_flag)

        # 2. Lookup the token for the PRIMARY ELEMENT SLOT (Base element token)
        # This token is always (Primary, Secondary=null, Maliwan=False)
        log.debug("Querying primary-only element token for: %s", new_primary_name)
        primary_token = await item_parser.query_element_id(
            self.db_pool, 
            new_primary_name, 
            None,      # Secondary is always None for the primary slot
            False      # Maliwan is always False for the primary slot
        )
        
        if not primary_token:
            log.error("Could not find a Primary-Only element ID for %s", new_primary_name)
            raise ValueError(f"Could not find a Primary-Only element ID for {new_primary_name}. (DB error)")

        # 3. Handle the SECONDARY ELEMENT SLOT (Dual-element token)
        secondary_token = None
        if new_secondary_name and new_secondary_name.lower() != 'none':
            log.debug("Querying dual-element token for: %s + %s (Maliwan=%s)", new_primary_name, new_secondary_name, is_not_maliwan_flag)
            
            # The dual-element token queries (Primary, Secondary, Maliwan)
            secondary_token = await item_parser.query_element_id(
                self.db_pool, 
                new_primary_name, 
                new_secondary_name, 
                is_not_maliwan_flag
            )
            
            if not secondary_token:
                log.error("Could not find dual-element ID for %s + %s (Maliwan=%s)", new_primary_name, new_secondary_name, is_not_maliwan_flag)
                raise ValueError(f"Could not find dual-element ID for {new_primary_name} + {new_secondary_name} (Maliwan={is_not_maliwan_flag}).")
        
        self.primary_element_name = new_primary_name
        self.secondary_element_name = new_secondary_name
        # 4. Update the stored parts
        self.parts["Primary Element"] = [primary_token]
        self.parts["Secondary Element"] = [secondary_token] if secondary_token else []

        log.info("Element parts updated successfully.")
    
    async def update_rarity(self, new_rarity_name: str):
        """
        Updates the weapon's rarity token based on the selected name.
        """
        log.info("Updating rarity to %s", new_rarity_name)
        rarity_id = self.EDITABLE_RARITY_MAP.get(new_rarity_name)
        if not rarity_id:
            # Should not happen with the provided options
            log.error("Invalid rarity name provided: %s", new_rarity_name)
            raise ValueError(f"Invalid rarity name: {new_rarity_name}")

        rarity_token = f"{{{rarity_id}}}"
        log.debug("Rarity token set to %s", rarity_token)
        
        # Rarity is stored as a list of one token
        self.parts["Rarity"] = [rarity_token]

    async def update_level(self, new_level: int):
        """
        Updates the weapon's level attribute.
        """
        log.info("Updating level to %s", new_level)
        # Level validation is typically done in the modal, but useful to keep here
        new_level = int(new_level)
        self.level = str(new_level) 
        
        if not 1 <= new_level <= 50:
            self.level = '50'
            log.warning("Invalid level %s provided. Clamping to 50.", new_level)
            #  raise ValueError("Level must be between 1 and 50.")
        # Store as string for consistency with how it's used in base_aspect
    
    def get_current_element_names_sync(self) -> tuple[str, str | None]:
        """
        Returns the stored primary and secondary element names.
        Safe for use in synchronous View.__init__.
        """
        return self.primary_element_name, self.secondary_element_name
             
    def get_part_limits(self, part_type: str) -> tuple[int, int]:
        """
        Gets the (min, max) selection limits for a given part type.
        
        This can be overridden by edge-case logic later,
        but for now, it returns the class defaults.
        """
        # Default to (1, 1) if a part type is missing from the list
        return self.DEFAULT_PART_LIMITS.get(part_type, (1, 1))
    
    def get_base_part_variant_for_accessory(self, accessory_part_type: str) -> str | None:
        """
        Finds the base part for a given accessory type and returns its 'variant'
        (e.g., '01', '02', or None).
        """
        log.debug("Checking base variant for accessory type: %s", accessory_part_type)
        base_part_type = None
        
        # 1. Define the relationship between accessories and their base
        if accessory_part_type == "Barrel Accessory":
            base_part_type = "Barrel"
        elif accessory_part_type == "Scope Accessory":
            base_part_type = "Scope"
        elif accessory_part_type == "Body Accessory":
            base_part_type = "Body"
        # Add other mappings here if needed (e.g., Magazine Accessory -> Magazine)

        if not base_part_type:
            # This part type doesn't have a base, so no filtering is needed.
            log.debug("Part type has no base. No filtering needed.")
            return None

        # 2. Get the currently equipped base part
        equipped_base_parts = self.parts.get(base_part_type, [])
        if not equipped_base_parts:
            # No base part is equipped (e.g., a weapon with no scope)
            # In this case, we shouldn't filter.
            log.debug("No base part (%s) is equipped. No filtering needed.", base_part_type)
            return None
        
        # 3. Get the part's stored variant (e.g., '01', '02', or None)
        # We assume the first part in the list is the equipped one.
        base_part_data = equipped_base_parts[0]
        variant = base_part_data.get('variant')
        log.debug("Found base part. Variant is: %s", variant)
        return variant
    
    def get_current_embed(self) -> discord.Embed:
        """Generates the current display for the item state."""
        # Use self.data to build a nice embed showing all parts/stats
        embed = discord.Embed(title="Current Item Build", description=f"Serial: {self.original_serial[:15]}...")
        # ... logic to populate embed from self.data ...
        return embed
    
    def get_rarity_color(self) -> discord.Color:
        """Gets the discord.Color associated with the weapon's rarity."""
        rarity_list = self.parts.get("Rarity", [])
        
        if not rarity_list:
            return discord.Color.default() # Default color if no rarity
        
        # rarity_list[0] is the token, e.g., '{98}'
        rarity_name = self._get_rarity_string(rarity_list[0])
        
        match rarity_name:
            # discord.Color.default() is the standard "white" embed color
            case "Common": return discord.Color.default()
            case "Uncommon": return discord.Color.green()
            case "Rare": return discord.Color.blue()
            case "Epic": return discord.Color.purple()
            case "Legendary": return discord.Color.orange()
            case _: return discord.Color.default()

    def get_component_list(self) -> str:
        """
        Reconstructs the full component string in the exact required order
        for serialization.
        """
        log.debug("Reconstructing component string for serialization.")
        
        # 1. Define the required order of part types (The blueprint)
        # This list defines the *slots* in the component string.
        PART_ORDER = [
            "Rarity",
            "Body", 
            "Body Accessory", 
            "Primary Element",
            "Barrel", 
            "Barrel Accessory", 
            "Magazine",         
            "Scope",
            "Scope Accessory",  
            "Grip", 
            "Foregrip",
            "Underbarrel",
            "Stat Modifier",
            "Secondary Element"
        ]
        
        # 2. Extract and sequence the Part IDs (tokens)
        all_part_tokens = []
        
        for part_type in PART_ORDER:
            # Get the list of parts for this type from our structured dict
            parts_for_type = self.parts.get(part_type, [])
            
            if not parts_for_type:
                continue # Skip if this part type is empty

            if part_type in ["Rarity", "Primary Element", "Secondary Element"]:
                # Elements are already stored as tokens (e.g., "{1:5}")
                all_part_tokens.extend(parts_for_type)
            else:
                # Regular parts are dicts. We need to extract their ID
                # and format it as a token (e.g., "{2}")
                # We use part['id'] because that is the key from the DB
                # that matches the original token {id}
                part_tokens = [f"{{{part['id']}}}" for part in parts_for_type]
                all_part_tokens.extend(part_tokens)

        # 3. Create the space-separated part string
        part_string = ' '.join(all_part_tokens)
                
        # 4. Reconstruct the full component string
        base_aspect = f"{self.item_type_int}, 0, 1, {self.level}|{self.skin_data}"
        part_aspect = f"{part_string}|{'|'.join(self.extra)}"
        
        component_string = f"{base_aspect}|| {part_aspect}"
        
        log.debug("Reconstructed Component String: %s", component_string)
        
        return component_string
           
    def _get_true_part_type(self, part_string: str, db_part_type: str) -> str:
        """
        Re-classifies 'Manufacturer Part' entries based on their part_string
        to determine their *true* functional part type.
        """
        # If the type is not 'Manufacturer Part', we trust it.
        if db_part_type != "Manufacturer Part":
            return db_part_type
        
        log.debug("Re-classifying 'Manufacturer Part' with string: %s", part_string)
        
        # --- Re-classification Logic ---
        # Based on your table, we check substrings in the part_string
        
        if ".part_shield_" in part_string:
            # e.g., "JAK_SR.part_shield_default"
            log.debug("Re-classified as: Body Accessory")
            return "Body Accessory"
            
        if ".part_mag_torgue_" in part_string:
            # e.g., "JAK_SR.part_mag_torgue_normal"
            log.debug("Re-classified as: Magazine")
            return "Magazine"
            
        if ".part_barrel_licensed_" in part_string:
            # e.g., "JAK_SR.part_barrel_licensed_ted"
            log.debug("Re-classified as: Barrel Accessory")
            return "Barrel Accessory"
            
        if ".part_secondary_ammo_" in part_string:
            # e.g., "JAK_SR.part_secondary_ammo_smg"
            # This acts as a stat modifier
            log.debug("Re-classified as: Stat Modifier")
            return "Stat Modifier"
            
        # Fallback for any 'Manufacturer Part' we don't have a rule for
        log.debug("Fell back to: Stat Modifier")
        return "Stat Modifier"

    def _build_structured_parts(self, part_list_results: list[dict]):
        """
        Ingests the *initial* raw part list from the DB and
        populates self.parts.
        """
        log.debug("Building structured parts dictionary from %s raw DB results.", len(part_list_results))
        # 1. Initialize self.parts with all possible part type keys
        self.parts = {
            "Rarity": [], "Body": [], "Body Accessory": [], "Barrel": [],
            "Barrel Accessory": [], "Magazine": [], "Scope": [],
            "Scope Accessory": [], "Grip": [], "Underbarrel": [],
            "Foregrip": [], "Stat Modifier": [], "Primary Element": [],
            "Secondary Element": []
        }
        
        # 2. Process each part using the new helper
        for part_data in part_list_results:
            processed_part = self._process_part_record(part_data)
            true_part_type = processed_part['part_type']
            
            # 3. Add the processed part to the correct list
            if true_part_type in self.parts:
                self.parts[true_part_type].append(processed_part)
            else:
                # Fallback for an unhandled part type
                log.warning("Unhandled part type %s for part string %s. Placing in 'Unhandled'.", true_part_type, processed_part['part_string'])
                if 'Unhandled' not in self.parts:
                    self.parts['Unhandled'] = []
                self.parts['Unhandled'].append(processed_part)
                   
    def _get_rarity_string(self, rarity_token: str) -> str:
        """Converts a rarity token like '{98}' into its display name."""
        try:
            # Extract the number: '{98}' -> '98' -> 98
            rarity_id = int(rarity_token[1:-1])
        except (ValueError, IndexError):
            log.warning("Could not parse rarity token: %s", rarity_token, exc_info=True)
            return "Unknown" # Fallback for malformed tokens

        match rarity_id:
            case 95:
                return "Common"
            case 96:
                return "Uncommon"
            case 97:
                return "Rare"
            case 98:
                return "Epic"
            case _:
                return "Legendary"
    
    def _process_part_record(self, part_data: dict) -> dict:
        """
        Processes a single raw part record from the DB into the
        structured dictionary format used by self.parts.
        """
        log.debug("Processing raw part record: %s", part_data.get('part_string', 'N/A'))
        db_part_type = part_data['part_type']
        part_string = part_data['part_string']
        
        # 1. Get the "true" part type
        true_part_type = self._get_true_part_type(part_string, db_part_type)
        
        # 2. Build the final part dictionary to store
        processed_part = {
            'id': part_data['id'],
            'part_string': part_data['part_string'],
            'part_type': true_part_type,
            'stats': part_data.get('stats', {})
        }
        
        # 3. Handle the _01, _02 variant logic
        variant_match = re.search(r"_(\d{2})", part_string)
        part_variant = None
        if variant_match:
            part_variant = variant_match.group(1) # Get '01', '02', etc.
        
        if part_variant:
            log.debug("Found variant: %s", part_variant)
            processed_part['variant'] = part_variant
            
        return processed_part