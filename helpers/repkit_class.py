# helpers/repkit_class.py
import discord
import logging
import re
from helpers import item_parser
from typing import List, Dict, Any
log = logging.getLogger(__name__)

class Repkit:
    """Represents the BL4 Repkit item being edited."""
    
    # The part key for repkit perks
    REPKIT_PART_KEY = "243"
    
    # The fixed part ID for the repkit type
    TYPE_DENOMINATION_ID = "2"
    
    # Define the serialization order
    PART_ORDER = [
        "Rarity",
        "TypeDenomination",
        "UniquePart",
        "Perks"
    ]

    # Map of editable rarity names to their part IDs
    EDITABLE_RARITY_MAP = {
        "Common": "1",
        "Uncommon": "2",
        "Rare": "3",
        "Epic": "4",
        "Epic": "6"
    }
    
    # 1. A synchronous and minimal __init__
    def __init__(self, db_pool, session, initial_serial: str):
        self.db_pool = db_pool
        self.session = session
        self.original_serial = initial_serial.strip()
        
        # Initialize attributes that will be populated by the 'create' method
        self.item_str = ""
        self.skin_data = "" # Stores data like '| 2, 1132'
        self.item_type_int = 0
        self.level = 0
        self.extra = "" # Stores data after the final '|' in part_aspect
        self.type = "Repkit"
        self.rarity_name = "Unknown"
        self.manufacturer = ""
        self.unique_perk = None
        self.repkit_effect = ""
        
        # Repkit-specific part structure
        self.parts = {
            "Rarity": [],           # e.g., ['{7}']
            "TypeDenomination": [], # e.g., ['{2}']
            "UniquePart": [],       # e.g., ['{1}']
            "Perks": []             # e.g., ['{243:[105 100 86]}', '{243:[96 5]}']
        }
        self.additional_data = ""
        self.item_name = "Unknown Repkit"

    @classmethod
    async def create(cls, db_pool, session, initial_serial: str, deserialized_json: dict, item_type_int: int, manufacturer: str, item_type: str):
        """
        Asynchronously creates and initializes a Repkit instance
        from pre-deserialized data.
        """
        repkit = cls(db_pool, session, initial_serial)
        
        try:
            repkit.item_str = deserialized_json.get('deserialized')
            repkit.additional_data = deserialized_json.get('additional_data', '')
            
            # 1. --- Parse Base Aspect ---
            base_aspect, part_aspect = repkit.item_str.split('||')
            base = base_aspect.split('|')[0]
            repkit.skin_data = '|'.join(base_aspect.split('|')[1:]) # e.g., ' 2, 1132' or ' 9, 1| 2, 720'
            
            _, base_0, base_1, repkit.level = base.split(', ')
            parts_string = part_aspect.split('|')[0]
            repkit.extra = '|'.join(part_aspect.split('|')[1:]) # Data after final '|'

            # --- ASSIGN PRE-FETCHED DATA ---
            repkit.item_type_int = item_type_int
            repkit.type = item_type
            repkit.manufacturer = manufacturer
            
            # 2. --- Parse Part Aspect (Repkit-Specific Logic) ---
            all_part_tokens = re.findall(r"\{[^}]+\}", parts_string)

            log.debug(f'Part tokens: {str(all_part_tokens)}')
            
            simple_part_tokens = []
            
            for token in all_part_tokens:
                if f"{cls.REPKIT_PART_KEY}:" in token:
                    # This is a perk token, e.g., {243:[105 100 86]}
                    repkit.parts["Perks"].append(token)
                else:
                    # This is a simple token
                    simple_part_tokens.append(token)

            log.debug(f'Simple tokens: {str(simple_part_tokens)}')
            # 3. --- Separate Rarity, Type, and UniquePart ---
            repkit.parts["Rarity"].append(simple_part_tokens.pop(0)) # Rarity first.
            repkit.parts["TypeDenomination"].append(simple_part_tokens.pop(0)) # Type second.
            for token in simple_part_tokens:
                repkit.parts["UniquePart"].append(token) # All that is left???
                # if token == f"{{{cls.TYPE_DENOMINATION_ID}}}":
                #     repkit.parts["TypeDenomination"].append(token)
                # elif token == "{1}": # Legendary part ID
                #     repkit.parts["UniquePart"].append(token)
                # else:
                #     # Assume any other simple token is Rarity
                #     repkit.parts["Rarity"].append(token)
            log.debug(f'Organized Parts: {str(repkit.parts)}')

            # 4. --- Set Name and Rarity ---
            rarity_list = repkit.parts.get("Rarity", [])
            if rarity_list:
                repkit.rarity_name = repkit._get_rarity_string(rarity_list[0])
            
            if repkit.rarity_name != 'Legendary':
                repkit.item_name = f"{manufacturer.title()} Repkit"
            else:
                # Legendary repkits use {1} for their ID
                unique_id = 1
                
                # --- [DB Placeholder] ---
                # This is where you would call item_parser.query_unique_repkit
                # For now, we'll use placeholder logic.
                try:
                    # This function needs to be created in item_parser.py
                    response = await item_parser.query_unique_repkit(
                        db_pool, 
                        repkit.manufacturer, 
                        unique_id
                    )
                    if response:
                        repkit.item_name = response[0].get('repkit_name', 'Legendary Repkit')
                        repkit.unique_perk = response[0].get('unique_perk')
                        repkit.repkit_effect = response[0].get('repkit_effect')
                    else:
                        repkit.item_name = "Legendary Repkit (Unknown)"
                except AttributeError:
                    # Fallback if item_parser.query_unique_repkit doesn't exist yet
                    repkit.item_name = "Legendary Repkit (DB-TODO)"
                    repkit.unique_perk = "Unique Perk (DB-TODO)"
                    repkit.repkit_effect = "Unique Effect (DB-TODO)"
                
            return repkit
            
        except Exception as e:
            print(f"Error during Repkit.create: {e}")
            raise e

    async def get_serial(self) -> str:
        """
        Reconstructs the full component string in the exact required order
        for serialization. Returns the item serial.
        """
    
        return (await item_parser.reserialize(self.session, self.get_component_list())).get('serial_b85')

    def _get_current_perk_ids(self) -> List[int]:
        """
        Parses all perk tokens and returns a single flat list of all perk IDs.
        e.g. ['{243:[106 102]}', '{243:[96 5]}'] -> [106, 102, 96, 5]
        """
        all_ids = []
        for token in self.parts.get("Perks", []):
            ids = self._parse_perk_token(token)
            if ids:
                all_ids.extend(ids)
        return all_ids

    async def get_perks(self) -> List[Dict[str, Any]]:
        """
        Queries the DB for the full data of all equipped perks.
        
        Returns:
            A list of perk data dicts.
            e.g. [{'id': 105, 'name': 'Perk A', 'perk_type': 'Type 1'}]
        """
        all_perk_ids = self._get_current_perk_ids()
        if not all_perk_ids:
            return []
            
        try:
            # --- [DB Placeholder] ---
            # This function needs to be created in item_parser.py
            # It should query the 'repkit_parts' table
            perk_records = await item_parser.query_repkit_perks(
                self.db_pool, all_perk_ids
            )
            
            # Convert asyncpg.Record objects to standard dicts
            return [dict(record) for record in perk_records]
            
        except AttributeError:
            # Fallback if item_parser.query_repkit_perks doesn't exist yet
            return [{'id': pid, 'name': f"Perk ID {pid} (DB-TODO)", 'perk_type': 'Perk'} for pid in all_perk_ids]
        except Exception as e:
            print(f"Warning: Could not query repkit perks. {e}")
            return [{'id': 0, 'name': f"Perk IDs: {all_perk_ids} (Query failed)", 'perk_type': 'Error'}]

    async def get_parts_for_embed(self) -> str:
        """
        Generates a formatted, indented string list of all current parts
        for an embed.
        """
        display_lines = [f"**Level:** {self.level}"]

        if self.unique_perk:
            display_lines.append(f"**Unique Perk:** {self.unique_perk.title()}")
        if self.repkit_effect:
            display_lines.append(f"**Effect:** {self.repkit_effect}")

        # --- Get Perks ---
        perk_data_list = await self.get_perks()
        
        display_lines.append(f"**\nParts:**")
        if not perk_data_list:
            display_lines.append("-> None")
        else:
            firmware = 'None'
            for perk_data in reversed(perk_data_list):
                perk_name = perk_data.get('name', 'Unknown Perk')
                perk_type = perk_data.get('perk_type', 'Perk')
                perk_desc = perk_data.get('description', 'Perk')
                
                if perk_name != 'Nothing' and perk_type!= 'Firmware':
                    line = f"-> {perk_name} ({perk_desc})"
                    # if perk_type != 'Perk':
                    #     line += f" ({perk_type})"
                    display_lines.append(line)
                elif perk_type == 'Firmware':
                    firmware = str(perk_name)
        
        display_lines.append(f"\n**Firmware:** {firmware}")
        return "\n".join(display_lines)

    async def update_all_perks(self, new_perk_ids: List[int]):
        """
        Rebuilds the perk token from scratch based on a
        flat list of new perk IDs.
        """
        
        # 1. Clear all existing perk parts
        self.parts["Perks"] = []

        # 2. Skip if no IDs are provided
        if not new_perk_ids:
            return
            
        try:
            # 3. Sort IDs for a consistent token
            int_ids = sorted([int(pid) for pid in new_perk_ids])
            
            # 4. Create the string, e.g., "105 100 86"
            ids_str = ' '.join(str(i) for i in int_ids)
            
            # 5. Format the new token, e.g., {243:[105 100 86]}
            new_token = f"{{{self.REPKIT_PART_KEY}:[{ids_str}]}}"
            
            # 6. Assign the new token
            self.parts["Perks"] = [new_token]
            print(f"New Repkit Token set: {new_token}")
            
        except ValueError:
            raise ValueError(f"Invalid perk ID found for Repkit.")
        except Exception as e:
            print(f"Error building token for Repkit: {e}")
            raise e

    async def update_rarity(self, new_rarity_name: str):
        rarity_id = self.EDITABLE_RARITY_MAP.get(new_rarity_name)
        if not rarity_id:
            raise ValueError(f"Invalid rarity name: {new_rarity_name}")
        
        # Repkits only have one rarity token
        self.parts["Rarity"] = [f"{{{rarity_id}}}"]
        self.rarity_name = new_rarity_name
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
        
        # Repkit Rarity IDs
        match rarity_id:
            case 1: return "Common"
            case 2: return "Uncommon"
            case 3: return "Rare"
            case 4: return "Epic"
            case 6: return "Epic"
            case _: return "Legendary"
            
    def _parse_perk_token(self, token: str) -> List[int]:
        """
        Parses a perk token like '{243:[105 100 86]}' or '{243:105}'
        Returns: [105, 100, 86] or [105]
        """
        try:
            inner_token = token[1:-1] # '243:[105 100 86]'
            key, value_str = inner_token.split(":", 1) # key='243', value_str='[105 100 86]'
            
            # Clean the value string: '[105 100 86]' -> '105 100 86' or '105' -> '105'
            value_str_cleaned = value_str.strip("[]")
            
            # Split by space and convert to int
            ids_int = [int(i) for i in value_str_cleaned.split()]
            
            return ids_int
        
        except Exception as e:
            print(f"Error parsing repkit perk token {token}: {e}")
            return []
        
    def get_component_list(self) -> str:
        """
        Reconstructs the full component string in the exact required order
        for serialization. Returns the raw component string.
        """
        all_part_tokens = []
        
        # 1. Get all perks and rebuild the single perk token
        all_perk_ids = self._get_current_perk_ids()
        
        # Clear existing perk parts
        self.parts["Perks"] = []
        if all_perk_ids:
            # Sort IDs and create the new unified token
            int_ids = sorted([int(pid) for pid in all_perk_ids])
            ids_str = ' '.join(str(i) for i in int_ids)
            new_token = f"{{{self.REPKIT_PART_KEY}:[{ids_str}]}}"
            self.parts["Perks"] = [new_token]

        # 2. Add all parts in the correct order
        for part_type in self.PART_ORDER:
            all_part_tokens.extend(self.parts.get(part_type, []))

        # 3. Create the space-separated part string
        part_string = ' '.join(all_part_tokens)
        
        # 4. Reconstruct the full component string
        base_aspect = f"{self.item_type_int}, 0, 1, {self.level}|{self.skin_data}"
        part_aspect = f"{part_string}|{self.extra}"
        
        component_string = f"{base_aspect}||{part_aspect}" # Note: No space before ||
        
        return component_string