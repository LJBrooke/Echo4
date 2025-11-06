# helpers/shield_class.py
import discord
import re
from helpers import item_parser

class Shield:
    """Represents the BL4 Shield item being edited."""
    
    # Map of shield perk keys to their part_type names
    SHIELD_PART_KEYS = {
        "237": "Armor",
        "246": "General",
        "248": "Energy"
    }
    
    # Define the serialization order
    PART_ORDER = [
        "Rarity",
        "UniquePart", # This is the Shield "Body"
        "General",
        "Energy",
        "Armor"
    ]

    EDITABLE_RARITY_MAP = {
        "Common": "95",
        "Uncommon": "96",
        "Rare": "97",
        "Epic": "98"
    }

    # 1. A synchronous and minimal __init__
    def __init__(self, db_pool, session, initial_serial: str):
        self.db_pool = db_pool
        self.session = session
        self.original_serial = initial_serial.strip()
        
        # Initialize attributes that will be populated by the 'create' method
        self.item_str = ""
        self.skin_data = ""
        self.item_type_int = 0
        self.level = 0
        self.extra = ""
        self.type = ""
        self.manufacturer = ""
        
        # Shield-specific part structure
        self.parts = {
            "Rarity": [],
            "UniquePart": [],
            "General": [],
            "Energy": [],
            "Armor": []
        }
        self.additional_data = ""
        self.item_name = "Unknown Shield"

    @classmethod
    async def create(cls, db_pool, session, initial_serial: str):
        """
        Asynchronously creates and initializes a Shield instance.
        """
        # First, create the "empty" instance using the synchronous __init__
        shield = cls(db_pool, session, initial_serial)
        
        # Now, perform all async operations and populate the instance
        try:
            derialized_json = await item_parser.deserialize(shield.session, shield.original_serial)
            shield.item_str = derialized_json.get('deserialized')
            shield.additional_data = derialized_json.get('additional_data', '')
            
            # 1. --- Parse Base Aspect (Identical to Weapon) ---
            base_aspect, part_aspect = shield.item_str.split('||')
            base, shield.skin_data = base_aspect.split('|')
            if shield.additional_data and '"' in shield.additional_data:
                parts = shield.additional_data.split('"')
                if len(parts) > 1:
                    shield.item_name = parts[1]
            
            shield.item_type_int, base_0, base_1, shield.level = base.split(', ')
            parts_string, shield.extra = part_aspect.split('|')
            
            shield.type, shield.manufacturer = await item_parser.query_type(
                shield.db_pool, int(shield.item_type_int)
            )

            # 2. --- Parse Part Aspect (Shield-Specific Logic) ---
            
            # This regex finds *all* tokens, including complex ones
            # e.g., ['{9}', '{8}', '{246:25}', '{248:[7 27]}']
            all_part_tokens = re.findall(r"\{[^}]+\}", parts_string)

            simple_part_ids_int = [] # To store simple IDs like 9, 8
            
            for token in all_part_tokens:
                inner_token = token[1:-1] # e.g., '9', '8', '246:25', '248:[7 27]'
                
                if ":" in inner_token:
                    # This is a perk token, e.g., '246:25'
                    try:
                        key, value = inner_token.split(":", 1)
                        part_type = cls.SHIELD_PART_KEYS.get(key)
                        
                        if part_type:
                            # Store the *raw token* (e.g., '{246:25}')
                            shield.parts[part_type].append(token)
                        else:
                            print(f"Warning: Unknown shield part key {key} in token {token}")
                    except Exception as e:
                        print(f"Warning: Could not parse perk token {token}: {e}")
                
                else:
                    # This is a simple token, e.g., '9' or '8'
                    try:
                        simple_part_ids_int.append(int(inner_token))
                    except ValueError:
                        print(f"Warning: Non-integer simple part {token}")

            # 3. --- Separate Rarity from UniquePart ---
            # (Identical logic to Weapon)
            
            # Query the simple part IDs against the parts table
            part_list_results = await item_parser.query_part_list(
                shield.db_pool, shield.manufacturer, shield.type, simple_part_ids_int
            )
            
            returned_ids = {part['id'] for part in part_list_results}
            
            # Rarity tokens are the ones NOT found in the parts table
            shield.parts["Rarity"] = [
                "{"+str(p)+"}" for p in simple_part_ids_int if int(p) not in returned_ids
            ]
            
            # UniqueParts are the ones that WERE found
            # We can reuse _process_part_record, it's generic enough
            shield.parts["UniquePart"] = [
                shield._process_part_record(part) for part in part_list_results
            ]

            return shield
            
        except Exception as e:
            print(f"Error during Shield.create: {e}")
            raise e

    async def get_serial(self) -> str:
        """
        Reconstructs the full component string in the exact required order
        for serialization.
        """
        
        all_part_tokens = []
        
        for part_type in self.PART_ORDER:
            parts_for_type = self.parts.get(part_type, [])
            if not parts_for_type:
                continue

            # Rarity and Perks are stored as raw tokens (e.t., '{9}', '{246:25}')
            if part_type in ["Rarity", "General", "Energy", "Armor"]:
                all_part_tokens.extend(parts_for_type)
            
            # UniquePart is stored as a list of dicts
            elif part_type == "UniquePart":
                part_tokens = [f"{{{part['id']}}}" for part in parts_for_type]
                all_part_tokens.extend(part_tokens)

        # 3. Create the space-separated part string
        part_string = ' '.join(all_part_tokens)
        
        # 4. Reconstruct the full component string
        base_aspect = f"{self.item_type_int}, 0, 1, {self.level}|{self.skin_data}"
        part_aspect = f"{part_string}|{self.extra}"
        
        component_string = f"{base_aspect}|| {part_aspect}"
        
        return (await item_parser.reserialize(self.session, component_string)).get('serial_b85')

    def _parse_perk_token(self, token: str) -> tuple[str, list[int]]:
        """
        Parses a perk token like '{248:[7 27]}'
        Returns: ('Energy', [7, 27])
        """
        try:
            inner_token = token[1:-1] # '248:[7 27]'
            key, value_str = inner_token.split(":", 1) # key='248', value_str='[7 27]'
            
            part_type = self.SHIELD_PART_KEYS.get(key) # 'Energy'
            
            # Clean the value string: '[7 27]' -> '7 27' or '25' -> '25'
            value_str_cleaned = value_str.strip("[]")
            
            # Split by space and convert to int: '7 27' -> ['7', '27'] -> [7, 27]
            ids_int = [int(i) for i in value_str_cleaned.split()]
            
            return part_type, ids_int
        
        except Exception as e:
            print(f"Error parsing perk token {token}: {e}")
            return "Unknown", []

    async def get_perks_for_display(self) -> dict[str, list[str]]:
        """
        Queries the DB for the names of all equipped perks.
        
        **Requires a new function in item_parser:**
        `query_shield_perks(db_pool, part_type: str, perk_ids: list[int])`
        which should return a list of perk name strings.
        """
        display_perks = {"General": [], "Energy": [], "Armor": []}
        
        for part_type in display_perks.keys():
            tokens = self.parts.get(part_type, []) # e.g., ['{248:[7 27]}']
            
            for token in tokens:
                _, perk_ids = self._parse_perk_token(token) # e.g., [7, 27]
                if not perk_ids:
                    continue
                
                try:
                    # --- YOU WILL NEED TO IMPLEMENT THIS FUNCTION ---
                    perk_names = await item_parser.query_shield_perks(
                        self.db_pool, part_type, perk_ids
                    )
                    # This function should look at the 'General' table for ID 7
                    # and the 'General' table for ID 27, and return
                    # ['Baker', 'Utility 20%/10%']
                    #
                    # You can use the tables you provided to build this query.
                    
                    display_perks[part_type].extend(perk_names)
                    
                except Exception as e:
                    # Handle case where item_parser.query_shield_perks doesn't exist yet
                    print(f"Warning: Could not query shield perks. {e}")
                    # Fallback to just showing the IDs
                    display_perks[part_type].append(f"Perk IDs: {perk_ids} (Query failed)")

        return display_perks

    async def get_parts_for_embed(self) -> str:
        """
        Generates a formatted, indented string list of all current parts
        for an embed.
        """
        display_lines = []

        # --- 1. Rarity and Level ---
        rarity_list = self.parts.get("Rarity", [])
        rarity_name = "Unknown"
        if rarity_list:
            rarity_name = self._get_rarity_string(rarity_list[0])
        
        display_lines.append(f"**Rarity:** {rarity_name}")
        display_lines.append(f"**Level:** {self.level}")

        # --- 2. Unique Part (Body) ---
        unique_parts = self.parts.get("UniquePart", [])
        if unique_parts:
            display_lines.append(f"**\nShield Body:**")
            for p in unique_parts:
                part_str = p.get('part_string', 'N/A')
                part_stat = p.get('stats', '')
                
                # We can reuse the weapon part formatter
                pretty_name = item_parser.format_part_name(part_str)
                
                line = f"-> `{pretty_name}`"
                if part_stat:
                    line += f" : {part_stat}"
                display_lines.append(line)

        # --- 3. Perks ---
        perk_map = await self.get_perks_for_display()
        
        for part_type, perks in perk_map.items():
            if perks:
                display_lines.append(f"**\n{part_type} Perks:**")
                for perk_name in perks:
                    display_lines.append(f"-> {perk_name}")
        
        return "\n".join(display_lines)

    # --- Reusable Helper Methods (Copied from Weapon) ---
    # These methods are generic and can be used by both classes.

    async def update_rarity(self, new_rarity_name: str):
        rarity_id = self.EDITABLE_RARITY_MAP.get(new_rarity_name)
        if not rarity_id:
            raise ValueError(f"Invalid rarity name: {new_rarity_name}")
        self.parts["Rarity"] = [f"{{{rarity_id}}}"]
        print(f"Rarity updated to: {new_rarity_name}")

    async def update_level(self, new_level: int):
        new_level = int(new_level)
        self.level = str(new_level) 
        if not 1 <= new_level <= 50:
            self.level = '50'
        print(f"Level updated to: {new_level}")
    
    def get_rarity_color(self) -> discord.Color:
        rarity_list = self.parts.get("Rarity", [])
        if not rarity_list:
            return discord.Color.default()
        
        rarity_name = self._get_rarity_string(rarity_list[0])
        
        match rarity_name:
            case "Common": return discord.Color.default()
            case "Uncommon": return discord.Color.green()
            case "Rare": return discord.Color.blue()
            case "Epic": return discord.Color.purple()
            case "Legendary": return discord.Color.orange()
            case _: return discord.Color.default()
            
    def _get_rarity_string(self, rarity_token: str) -> str:
        try:
            rarity_id = int(rarity_token[1:-1])
        except (ValueError, IndexError):
            return "Unknown"
        
        match rarity_id:
            case 95: return "Common"
            case 96: return "Uncommon"
            case 97: return "Rare"
            case 98: return "Epic"
            case _: return "Legendary"
            
    def _get_true_part_type(self, part_string: str, db_part_type: str) -> str:
        """
        Re-classifies 'Manufacturer Part' entries.
        (Copied from Weapon class, may need adjustment for shields
         if they also use 'Manufacturer Part' for other things)
        """
        if db_part_type != "Manufacturer Part":
            return db_part_type
        
        # Add shield-specific rules here if needed
        if ".part_shield_" in part_string:
            return "Body Accessory" # This is a weapon rule, but harmless
            
        # Fallback
        return "Stat Modifier"

    def _process_part_record(self, part_data: dict) -> dict:
        """
        Processes a single raw part record from the DB.
        (Copied from Weapon class)
        """
        db_part_type = part_data['part_type']
        part_string = part_data['part_string']
        
        true_part_type = self._get_true_part_type(part_string, db_part_type)
        
        processed_part = {
            'id': part_data['id'],
            'part_string': part_data['part_string'],
            'part_type': true_part_type,
            'stats': part_data.get('stats', {})
        }
        
        variant_match = re.search(r"_(\d{2})", part_string)
        if variant_match:
            processed_part['variant'] = variant_match.group(1)
            
        return processed_part