# helpers/shield_class.py
import discord
import re
from helpers import item_parser

class Shield:
    """Represents the BL4 Shield item being edited."""
    
    # Map of shield perk keys to their part_type names
    SHIELD_PART_KEYS = {
        "237": "Armour",
        "246": "General",
        "248": "Energy"
    }
    
    # Define the serialization order
    PART_ORDER = [
        "Rarity",
        "UniquePart", # This is the Shield "Body"
        "General",
        "Energy",
        "Armour"
    ]

    EDITABLE_RARITY_MAP = {
        "Common": "1",
        "Uncommon": "2",
        "Rare": "3",
        "Epic": "4",
    }
    
    PART_TYPE_TO_KEY = {v: k for k, v in SHIELD_PART_KEYS.items()}

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
        self.rarity_name = "Unknown"
        self.manufacturer = ""
        self.unique_perk = None
        self.firmware_id = None
        
        # Shield-specific part structure
        self.parts = {
            "Rarity": [],
            "UniquePart": [],
            "General": [],
            "Energy": [],
            "Armour": []
        }
        self.additional_data = ""
        self.item_name = "Unknown Shield"

    @classmethod
    async def create(cls, db_pool, session, initial_serial: str, deserialized_json: dict, item_type_int: int, manufacturer: str, item_type: str):
        """
        Asynchronously creates and initializes a Shield instance
        from pre-deserialized data.
        """
        # First, create the "empty" instance using the synchronous __init__
        shield = cls(db_pool, session, initial_serial)
        
        # Now, perform all async operations and populate the instance
        try:
            shield.item_str = deserialized_json.get('deserialized')
            shield.additional_data = deserialized_json.get('additional_data', '')
            
            # 1. --- Parse Base Aspect (Identical to Weapon) ---
            base_aspect, part_aspect = shield.item_str.split('||')
            base = base_aspect.split('|')[0]
            shield.skin_data = '|'.join(base_aspect.split('|')[1:])
            # We already have item_type_int, but we still need to parse level
            _, base_0, base_1, shield.level = base.split(', ')
            parts_string = part_aspect.split('|')[0]
            shield.extra = '|'.join(part_aspect.split('|')[1:])

            # --- ASSIGN PRE-FETCHED DATA ---
            shield.item_type_int = item_type_int
            shield.type = item_type
            shield.manufacturer = manufacturer
            
            # 2. --- Parse Part Aspect (Shield-Specific Logic) ---
            all_part_tokens = re.findall(r"\{[^}]+\}", parts_string)

            simple_part_ids_int = [] 
            
            for token in all_part_tokens:
                inner_token = token[1:-1]
                
                if ":" in inner_token:
                    try:
                        key, value = inner_token.split(":", 1)
                        part_type = cls.SHIELD_PART_KEYS.get(key)
                        
                        if part_type:
                            shield.parts[part_type].append(token)
                            if part_type!='General': shield.type = part_type
                        else:
                            print(f"Warning: Unknown shield part key {key} in token {token}")
                    except Exception as e:
                        print(f"Warning: Could not parse perk token {token}: {e}")
                
                else:
                    try:
                        simple_part_ids_int.append(int(inner_token))
                    except ValueError:
                        print(f"Warning: Non-integer simple part {token}")

            # 3. --- Separate Rarity from UniquePart ---
            part_list_results = await item_parser.query_part_list(
                shield.db_pool, shield.manufacturer, shield.type, simple_part_ids_int
            )
            
            returned_ids = {part['id'] for part in part_list_results}
            
            shield.parts["Rarity"] = [
                "{"+str(p)+"}" for p in simple_part_ids_int if int(p) not in returned_ids
            ]
            
            shield.parts["UniquePart"] = [
                shield._process_part_record(part) for part in part_list_results
            ]

            rarity_list = shield.parts.get("Rarity", [])
            if rarity_list:
                shield.rarity_name = shield._get_rarity_string(rarity_list[0])
            if shield.rarity_name!='Legendary':
                shield.item_name = manufacturer.title() + " Shield"
            else:
                response = await item_parser.query_unique_shield(db_pool, shield.manufacturer, int(shield.parts["Rarity"][1][1:-1]))
                try:
                    shield.item_name = response[0].get('shield_name', 'Unknown Shield')
                    shield.unique_perk = response[0].get('unique_perk', 'Unknown Perk')
                except Exception as e:
                    shield.item_name = "Unknown Shield"
                    shield.unique_perk = "Unknown Perk"
                
            return shield
            
        except Exception as e:
            print(f"Error during Shield.create: {e}")
            raise e

    async def get_serial(self) -> str:
        """
        Reconstructs the full component string in the exact required order
        for serialization.
        """       
        return str((await item_parser.reserialize(self.session, self.get_component_list())).get('serial_b85')+' ')

    async def get_perks(self) -> dict[str, list[dict]]:
        """
        Queries the DB for the full data of all equipped perks.
        
        Returns:
            A dict mapping part_type to a list of perk data dicts.
            e.g. {"General": [{'id': 7, 'name': 'Baker', 'perk_type': 'Firmware'}]}
        """
        perk_data_map = {"General": [], "Energy": [], "Armour": []}
        
        for part_type in perk_data_map.keys():
            tokens = self.parts.get(part_type, []) # e.g., ['{248:[7 27]}']
            
            all_perk_ids_for_type = []
            for token in tokens:
                _, perk_ids = self._parse_perk_token(token) # e.g., [7, 27]
                if perk_ids:
                    all_perk_ids_for_type.extend(perk_ids)
            
            if not all_perk_ids_for_type:
                continue
                
            try:
                # This now returns a list of dicts, e.g. [{'id': 7, 'name': 'Baker', ...}]
                perk_records = await item_parser.query_shield_perks(
                    self.db_pool, part_type, all_perk_ids_for_type
                )
                
                # We need to convert the asyncpg.Record objects to standard dicts
                # to make them easier to work with (e.g., for JSON serialization if needed)
                perk_data_map[part_type] = [dict(record) for record in perk_records]
                
            except Exception as e:
                print(f"Warning: Could not query shield perks. {e}")
                # Add a fallback for display
                perk_data_map[part_type] = [{'id': 0, 'name': f"Perk IDs: {all_perk_ids_for_type} (Query failed)", 'perk_type': 'Error'}]

        return perk_data_map

    async def get_parts_for_embed(self) -> str:
        """
        Generates a formatted, indented string list of all current parts
        for an embed.
        """
        display_lines = []
        firmware = None
        # --- 1. Rarity and Level ---
        
        display_lines.append(f"**Level:** {self.level}")
        display_lines.append(f"**Shield Type:** {self.type}")
        if self.unique_perk is not None:
            display_lines.append(f"**Unique Perk:** {self.unique_perk.title()}")

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
        # Call our updated get_perks method
        perk_data_map = await self.get_perks()
        
        display_lines.append(f"**\nParts:**")
        for part_type, perk_list in perk_data_map.items():
            if perk_list:
                # perk_list is now a list of dicts
                for perk_data in perk_list:
                    additional=''
                    # Get the name and perk_type
                    perk_name = perk_data.get('name', 'Unknown Perk')
                    perk_type = perk_data.get('perk_type', 'Perk') # Fallback to 'Perk'
                    if perk_type =='Firmware': firmware = perk_name
                    # Add the perk type in backticks for nice formatting
                    else: 
                        if perk_type!='Perk': additional = perk_type
                        display_lines.append(f"-> {perk_name} {additional}")
        
        if firmware is not None: 
            display_lines.append(f"\n**Firmware:** _{firmware}_")
        
        return "\n".join(display_lines)

    def get_current_perk_ids_by_type(self) -> dict[str, list[int]]:
        """
        Parses all perk tokens and returns a map of perk IDs,
        grouped by the part_type (which corresponds to the token key).
        
        Returns:
            {'General': [1, 22, 27], 'Energy': [16], 'Armour': []}
        """
        id_map = {"General": [], "Energy": [], "Armour": []}
        
        for part_type in id_map.keys():
            tokens = self.parts.get(part_type, []) # e.g., ['{248:[7 27]}']
            
            if not tokens:
                continue
            
            # Use the existing parser
            # We assume one token per part_type, e.g. '{248:[7 27]}'
            _, perk_ids = self._parse_perk_token(tokens[0]) 
            if perk_ids:
                id_map[part_type] = perk_ids
                
        return id_map

    async def update_all_perks(self, perk_map: dict[str, list[int]]):
        """
        Rebuilds all three perk tokens from scratch based on a
        grouping of perk IDs.
        
        perk_map = {
            'General': [7, 27, 25],
            'Energy': [16],
            'Armour': []
        }
        """
        
        # 1. Clear all existing perk parts
        self.parts["General"] = []
        self.parts["Energy"] = []
        self.parts["Armour"] = []

        # 2. Loop over the map and build each token
        for part_type, id_list in perk_map.items():
            # Skip if no IDs for this type
            if not id_list:
                continue

            # Get the token key (e.g., '246' for 'General')
            token_key = self.PART_TYPE_TO_KEY.get(part_type)
            if not token_key:
                print(f"Warning: No token key found for part_type {part_type}")
                continue
            
            try:
                # Sort IDs for a consistent token
                int_ids = sorted([int(pid) for pid in id_list])
                
                # Create the string, e.g., "7 25 27"
                ids_str = ' '.join(str(i) for i in int_ids)
                
                # Format the new token, e.g., {246:[7 25 27]}
                new_token = f"{{{token_key}:[{ids_str}]}}"
                
                # Assign the new token
                self.parts[part_type] = [new_token]
                print(f"New Token set: {new_token}")
                
            except ValueError:
                raise ValueError(f"Invalid perk ID found for type {part_type}.")
            except Exception as e:
                print(f"Error building token for {part_type}: {e}")
                raise e
                
    async def update_perks(self, perk_type: str, new_perk_ids: list[str]):
        """
        Updates the shield's perk list for a given type (General, Energy, Armour).
        'new_perk_ids' is a list of perk ID strings, e.g., ['7', '27'].
        """
        key = self.PART_TYPE_TO_KEY.get(perk_type)
        if not key:
            raise ValueError(f"Invalid shield perk type: {perk_type}")

        # If the list is empty, user wants to remove all perks of this type
        if not new_perk_ids:
            self.parts[perk_type] = []
            print(f"Cleared perks for type: {perk_type}")
            return

        # We must convert the string IDs back to integers for sorting/joining
        try:
            # Sort IDs to ensure a consistent token, e.g. [7, 27] not [27, 7]
            int_ids = sorted([int(pid) for pid in new_perk_ids])
            
            # Re-create the string list, e.g., "7 27"
            ids_str = ' '.join(str(i) for i in int_ids)
            
            # Format the new token, e.g., {248:[7 27]}
            new_token = f"{{{key}:[{ids_str}]}}"
            
            # Shields (unlike weapons) store perks as one token per type
            self.parts[perk_type] = [new_token]
            print(f"Updated perks for {perk_type} to: {new_token}")
            
        except ValueError:
            raise ValueError("Perk IDs must be numbers.")
        except Exception as e:
            print(f"Error updating perks: {e}")
            raise e

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
            case 1: return "Common"
            case 2: return "Uncommon"
            case 3: return "Rare"
            case 4: return "Epic"
            case _: return "Legendary"
            
    def _process_part_record(self, part_data: dict) -> dict:
        """
        Processes a single raw part record from the DB.
        (Copied from Weapon class)
        """
        
        processed_part = {
            'id': part_data['id'],
            'part_string': part_data['part_string'],
            'part_type': part_data['part_type'],
            'stats': part_data.get('stats', {})
        }
        
        variant_match = re.search(r"_(\d{2})", part_data['part_string'])
        if variant_match:
            processed_part['variant'] = variant_match.group(1)
            
        return processed_part
    
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

    def get_current_perk_ids_by_type(self) -> dict[str, list[int]]:
        """
        Parses all perk tokens and returns a map of perk IDs.
        This is a SYNCHRONOUS helper for building the UI.
        
        Returns:
            {'General': [1, 22, 27], 'Energy': [16], 'Armour': []}
        """
        id_map = {"General": [], "Energy": [], "Armour": []}
        
        for part_type in id_map.keys():
            tokens = self.parts.get(part_type, []) # e.g., ['{248:[7 27]}']
            
            if not tokens:
                continue
            
            # Use the existing parser
            # We assume one token per part_type, e.g. '{248:[7 27]}'
            _, perk_ids = self._parse_perk_token(tokens[0]) 
            if perk_ids:
                id_map[part_type] = perk_ids
                
        return id_map

    def get_component_list(self) -> str:
        """
        Reconstructs the full component string in the exact required order
        for serialization. Returns the raw component string.
        """
        
        all_part_tokens = []
        
        for part_type in self.PART_ORDER:
            parts_for_type = self.parts.get(part_type, [])
            if not parts_for_type:
                continue

            # Rarity and Perks are stored as raw tokens (e.t., '{9}', '{246:25}')
            if part_type in ["Rarity", "General", "Energy", "Armour"]:
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
        
        return component_string
