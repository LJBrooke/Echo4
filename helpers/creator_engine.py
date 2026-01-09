import asyncpg
import json
import logging
import random
import re
from collections import Counter
from typing import Optional, List, Dict, Any, Tuple
from helpers import db_utils, item_parser

log = logging.getLogger(__name__)

def parse_component_string(component_str: str) -> Tuple[str, str, List[int], List[int]]:
    """
    Parses the deserialized string.
    Returns: (inv_type_id, item_id, item_specific_ids, parent_specific_ids)
    """
    first_section = component_str.split('|')[0]
    inv_type_id = first_section.split(',')[0].strip()

    if '||' not in component_str:
        raise ValueError("Invalid format: Missing '||' separator.")
        
    parts_block = component_str.split('||')[1]
    if '|' in parts_block:
        parts_block = parts_block.split('|')[0]

    item_specific_ids = []
    parent_specific_ids = []
    raw_tokens = re.findall(r'\{([^}]+)\}', parts_block)
    all_ordered_ids = [] 

    for token in raw_tokens:
        is_parent_type = ':' in token
        if is_parent_type:
            val_part = token.split(':', 1)[1].strip()
        else:
            val_part = token.strip()
        
        val_part = val_part.replace('[', '').replace(']', '')
        sub_ids = []
        for sid in val_part.split():
            if sid.isdigit():
                sub_ids.append(int(sid))
        
        if is_parent_type:
            parent_specific_ids.extend(sub_ids)
        else:
            item_specific_ids.extend(sub_ids)
        all_ordered_ids.extend(sub_ids)

    if not all_ordered_ids:
        raise ValueError("No Item ID or Parts found.")

    item_id = str(all_ordered_ids[0])
    
    # Remove Item ID from the parts list so we don't try to equip the gun to itself
    # Check item specific bucket first
    if item_specific_ids and str(item_specific_ids[0]) == item_id:
        item_specific_ids.pop(0)

    return inv_type_id, item_id, item_specific_ids, parent_specific_ids

async def validate_serial(serial: str, db_pool: asyncpg.Pool, session: Any) -> Tuple[bool, List[str], Dict[str, Any]]:
    """
    Validates a serial string against database rules.
    
    Args:
        serial: The encoded string (BL3(...))
        db_pool: Database connection pool
        session: aiohttp session for deserialization
        
    Returns:
        Tuple: (is_legit: bool, violations: list[str], metadata: dict)
        
    Metadata contains: {'inv_id', 'item_id', 'part_count', 'tags': list}
    """
    violations = []
    metadata = {'inv_id': '?', 'item_id': '?', 'part_count': 0, 'tags': []}
    
    try:
        # 1. Deserialize
        resp = await item_parser.deserialize(session, serial)
        if not resp or 'deserialized' not in resp:
            return False, ["Could not deserialize code."], metadata
            
        component_str = str(resp.get('deserialized'))
        
        # 2. Parse
        try:
            inv_id, item_id, item_p_ids, parent_p_ids = parse_component_string(component_str)
            metadata['inv_id'] = inv_id
            metadata['item_id'] = item_id
            metadata['part_count'] = len(item_p_ids) + len(parent_p_ids)
        except Exception as e:
            return False, [f"Parsing Error: {e}"], metadata

        # 3. Fetch Balance
        balance_data = await item_parser.get_balance(db_pool, inv_id, item_id)
        if not balance_data:
            return False, [f"Unknown Item: Inv `{inv_id}` / Item `{item_id}`"], metadata

        # 4. Init Session
        creator = CreatorSession(
            user_id=0, # Dummy ID for validation
            balance_name=balance_data[0].get('entry_key'),
            balance_data=balance_data,
            db_pool=db_pool,
            session=session
        )
        await creator.initialize()
        
        metadata['item_name'] = creator.balance_name

        target_item_type = str(creator.balance_data.get('item_type'))
        target_parent_type = str(creator.balance_data.get('parent_type'))

        # 5. Load Parts
        loaded_parts = []
        async with db_pool.acquire() as conn:
            if item_p_ids:
                q1 = """
                    SELECT * FROM all_parts 
                    LEFT JOIN type_and_manufacturer ON inv = gestalt_type 
                    WHERE serial_index::int = ANY($1::int[]) AND inv = $2
                """
                rows1 = await conn.fetch(q1, item_p_ids, target_item_type)
                loaded_parts.extend([dict(r) for r in rows1])

            if parent_p_ids:
                q2 = """
                    SELECT * FROM all_parts 
                    LEFT JOIN type_and_manufacturer ON inv = gestalt_type 
                    WHERE serial_index::int = ANY($1::int[]) AND inv = $2
                """
                rows2 = await conn.fetch(q2, parent_p_ids, target_parent_type)
                loaded_parts.extend([dict(r) for r in rows2])

        # 6. Equip & Check IDs
        found_ids = set()
        for p in loaded_parts:
            sid = p['serial_index']
            if sid and str(sid).isdigit():
                found_ids.add(int(sid))

        for part in loaded_parts:
            p_type = part['part_type']
            if p_type in creator.slots:
                creator.selections[p_type].append(part)

        # 7. Validation Checks
        
        # A. Slot Limits
        for slot in creator.slots:
            selected = creator.selections[slot]
            count = len(selected)
            rules = creator.constraints.get(slot, {})
            max_val = rules.get('max', 1)
            min_val = rules.get('min', 0)
            
            if count > max_val:
                violations.append(f"**{slot.title()}**: Too many parts ({count}/{max_val}).")
            if count < min_val:
                # Before flagging as missing, check if any parts could actually spawn there
                # given the current tags (dependencies/exclusions).
                possible_parts = await creator.get_parts_status(slot)
                
                # If ANY part is valid, it means the user had a choice but didn't pick it -> Violation.
                # If ALL parts are invalid (valid=False), the slot is forced empty -> Legitimate.
                if any(p['valid'] for p in possible_parts):
                    violations.append(f"**{slot.title()}**: Missing parts ({count}/{min_val}).")
                # violations.append(f"**{slot.title()}**: Missing parts ({count}/{min_val}).")

        # B. Tags (with Counter logic)
        current_tags_list = creator.get_current_tags()
        metadata['tags'] = sorted(list(set(current_tags_list))) # Store for metadata
        
        global_counts = Counter(current_tags_list)
        current_tags_set = set(current_tags_list)
        
        for slot, parts in creator.selections.items():
            for part in parts:
                p_name = part.get('partname', 'Unknown')
                
                p_add_list = db_utils.decode_jsonb_list(part.get('addtags'))
                my_counts = Counter(p_add_list)
                other_counts = global_counts - my_counts
                
                p_exc = set(db_utils.decode_jsonb_list(part.get('exclusiontags')))
                p_dep = set(db_utils.decode_jsonb_list(part.get('dependencytags')))

                for exc_tag in p_exc:
                    if other_counts[exc_tag] > 0:
                        violations.append(f"**{p_name}**: Incompatible. Excludes `{exc_tag}` which is present elsewhere.")

                if p_dep and not p_dep.issubset(current_tags_set):
                    missing = list(p_dep - current_tags_set)
                    violations.append(f"**{p_name}**: Missing required tags: `{', '.join(missing)}`.")

        # C. Global Limits
        for rule in creator.global_tag_rules:
            limit = rule['max']
            targets = rule['tags']
            count = sum(1 for t in current_tags_list if t in targets)
            if count > limit:
                t_names = list(targets)[0]
                violations.append(f"**Global Limit**: Exceeded `{t_names}` ({count}/{limit}).")

        legitimacy = len(violations) == 0
        
        # D. Unknown IDs are not immediately disqualifying, but noted.
        all_requested = set(item_p_ids + parent_p_ids)
        unknown_ids = all_requested - found_ids
        if unknown_ids:
            violations.append(f"**Unknown IDs**: {list(unknown_ids)}")
            
        return legitimacy, violations, metadata

    except Exception as e:
        log.error(f"Validation Exception: {e}", exc_info=True)
        return False, [f"System Error: {str(e)}"], metadata
    
class CreatorSession:
    """
    Manages the state of a weapon creation session.
    """
    def __init__(self, user_id: int, balance_name: str, balance_data: Any, db_pool: asyncpg.Pool, session: Any):
        self.user_id = user_id
        self.balance_name = balance_name
        self.db_pool = db_pool
        self.session = session
        
        # --- 1. Robust Data Unwrapping ---
        if isinstance(balance_data, list):
            if balance_data:
                self.balance_data = dict(balance_data[0])
            else:
                self.balance_data = {}
                log.error(f"CreatorSession initialized with empty list for {balance_name}")
        elif hasattr(balance_data, 'get'): 
            self.balance_data = dict(balance_data)
        else:
            self.balance_data = {}
            
        self.item_type = balance_data[0].get('item_type')      # e.g., 'jak_sr'
        self.parent_type = balance_data[0].get('parent_type')  # e.g., 'weapon'

        # 2. Part Types (The Slot List)
        raw_pt = self.balance_data.get('parttypes')
        if isinstance(raw_pt, str): raw_pt = json.loads(raw_pt)
        
        self.part_types_config = {}
        if isinstance(raw_pt, list):
            # CASE: ["body", "barrel"] or [{'body':..}]
            if raw_pt and isinstance(raw_pt[0], str):
                self.part_types_config = {k: {} for k in raw_pt}
            else:
                for item in raw_pt:
                    if isinstance(item, dict): self.part_types_config.update(item)
        elif isinstance(raw_pt, dict):
            self.part_types_config = raw_pt

        # 3. Selection Rules
        self.constraints = db_utils.parse_selection_rules(self.balance_data.get('parttypeselectionrules'))
        
        # --- Global Tag Rules ---
        # Format: [ { "max": "2", "tags": [{"licensed": "licensed"}] } ]
        self.global_tag_rules = []
        raw_tag_rules = self.balance_data.get('parttagselectionrules')
        
        # Parse Tags
        if isinstance(raw_tag_rules, str):
            try: raw_tag_rules = json.loads(raw_tag_rules)
            except: raw_tag_rules = []
            
        if isinstance(raw_tag_rules, list):
            for rule in raw_tag_rules:
                if isinstance(rule, dict):
                    try:
                        max_val = int(rule.get('max', 999))
                        # Use existing db_utils to flatten nested dicts in 'tags' list
                        target_tags = set(db_utils.decode_jsonb_list(rule.get('tags')))
                        self.global_tag_rules.append({
                            'max': max_val,
                            'tags': target_tags
                        })
                    except (ValueError, TypeError):
                        continue
        
        # 4. Base Tags
        self.base_tags = db_utils.decode_jsonb_list(self.balance_data.get('basetags'))

        # 5. Slots & Selections
        # We will filter self.slots in an async method later, but init here
        self.slots = list(self.part_types_config.keys())
        self.slots.sort()
        
        # Selections now supports lists for slots with max > 1
        # Format: { "Scope": [part1, part2] } or { "Body": [part1] }
        self.selections: Dict[str, List[Dict[str, Any]]] = {slot: [] for slot in self.slots}

        # Cache for valid slots (populated by preliminary scan)
        self.active_slots = []
        
    async def initialize(self):
        """
        Performs the 'Preliminary Scan' to hide slots that have 0 parts 
        for this inventory type (ignoring tags).
        Must be called after __init__.
        """
        async with self.db_pool.acquire() as conn:
            # Get count of parts per part_type for this item/parent
            query = """
                SELECT part_type, COUNT(*) as c
                FROM all_parts
                WHERE inv = $1 OR inv = $2
                GROUP BY part_type
            """
            rows = await conn.fetch(query, self.item_type, self.parent_type)
        
        valid_types = {r['part_type'] for r in rows if r['c'] > 0}
        
        # Filter slots
        self.active_slots = [s for s in self.slots if s in valid_types]
        
        # Edge case: If a slot is mandated by rules but missing from DB, we might want to keep it visible
        # but for now, we hide what we can't build.
        
    def _parse_tags(self, tag_data: Any) -> List[str]:
        """
        Flattens tags into a LIST of strings, preserving duplicates for count limits.
        Removes redundant dictionary wrappers (e.g. {'tag': 'tag'} -> 'tag').
        """
        parsed = self._parse_json(tag_data, default=[])
        
        cleaned_tags = []

        # 1. Handle List (Standard case)
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    # Extract values: {'unique': 'unique'} -> 'unique'
                    cleaned_tags.extend(str(v) for v in item.values())
                elif isinstance(item, str):
                    cleaned_tags.append(item)
        
        # 2. Handle Single Dict
        elif isinstance(parsed, dict):
            cleaned_tags.extend(str(v) for v in parsed.values())
            
        # 3. Handle Single String
        elif isinstance(parsed, str):
            cleaned_tags.append(parsed)

        return cleaned_tags

    def get_current_tags(self) -> List[str]:
        """
        Aggregates tags from Base + All Selected Parts.
        Returns a LIST to support logic like "Max 2 of Tag X".
        """
        tags = list(self.base_tags)
        for part_list in self.selections.values():
            for part in part_list:
                p_add = db_utils.decode_jsonb_list(part.get('addtags'))
                tags.extend(p_add)
        return tags

    def check_global_tag_limits(self, candidate_part_tags: List[str]) -> tuple[bool, str]:
        """
        Checks if adding a part with specific tags would violate global limits.
        Returns: (Valid Bool, Reason String)
        """
        if not self.global_tag_rules:
            return True, ""
            
        # 1. Calculate Current Counts for Restricted Tags
        current_tags = self.get_current_tags()
        
        for rule in self.global_tag_rules:
            limit = rule['max']
            targets = rule['tags'] # Set of strings e.g. {'licensed'}
            
            # Count how many times ANY target tag appears in current build
            # Note: If a single part has 2 target tags, it counts as 2? 
            # Usually "Max 2 Licensed Parts" implies counting Parts, not Tags. 
            # BUT your data structure is tag-based. 
            # Standard interpretation: Count occurrence of these tags in the final list.
            
            current_count = sum(1 for t in current_tags if t in targets)
            
            # Count how many NEW tags the candidate adds
            new_adds = sum(1 for t in candidate_part_tags if t in targets)
            
            if new_adds > 0:
                if (current_count + new_adds) > limit:
                    # Construct readable reason
                    tag_name = list(targets)[0] if targets else "Restricted"
                    return False, f"Max Limit ({tag_name})"
                    
        return True, ""

    async def get_valid_parts_for_slot(self, slot_name: str) -> List[dict]:
        """
        Fetches all parts for a specific slot that match the Item/Parent INVs,
        then filters them against the current Tag State.
        """
        current_tags_list = self.get_current_tags()
        current_tags_set = set(current_tags_list)
        
        async with self.db_pool.acquire() as conn:
            query = """
                SELECT * FROM all_parts 
                WHERE part_type = $1 
                AND (inv = $2 OR inv = $3)
            """
            print(query, slot_name, self.item_type, self.parent_type)
            rows = await conn.fetch(query, slot_name, self.item_type, self.parent_type)

        valid_parts = []

        for row in rows:
            part = dict(row)
            
            p_dep = set(db_utils.decode_jsonb_list(part.get('dependencytags')))
            p_exc = set(db_utils.decode_jsonb_list(part.get('exclusiontags')))

            # Check Exclusions
            if not p_exc.isdisjoint(current_tags_set):
                continue

            # Check Dependencies
            if p_dep and not p_dep.issubset(current_tags_set):
                continue
            
            valid_parts.append(part)

        return valid_parts

    def _parse_json(self, data: Any, default=None) -> Any:
        """Robustly parses data that might be a JSON string, a Dict/List, or None."""
        if data is None: return default
        if isinstance(data, (dict, list)): return data
        if isinstance(data, str):
            try: return json.loads(data)
            except json.JSONDecodeError: return default
        return default

    def select_part(self, slot_name: str, part_row: Optional[dict]):
        """Updates the state with the new part."""
        self.selections[slot_name] = part_row

    async def get_parts_status(self, slot_name: str) -> List[Dict]:
        """
        Fetches parts, determines selectability, applies name formatting,
        and fetches stats using the item's gestalt_type.
        """
        current_tags_list = self.get_current_tags()
        current_tags_set = set(current_tags_list)
        rules = self.constraints.get(slot_name, {})
        allowed_list = rules.get('allowed_parts') 
        
        async with self.db_pool.acquire() as conn:
            # 1. Fetch Candidates (The parts for the dropdown)
            query = """
                SELECT * FROM all_parts 
                WHERE part_type = $1 AND (inv = $2 OR inv = $3)
            """
            rows = await conn.fetch(query, slot_name, self.item_type, self.parent_type)
            
            # 2. Fetch Stats for the ENTIRE Item Type (Gestalt)
            # We fetch all stats for this weapon type (e.g. all Sniper parts)
            # effectively pre-loading the stats for any part we might find.
            stats_query = """
                SELECT pl.id, pl.stats
                FROM part_list pl
                RIGHT JOIN type_and_manufacturer tam 
                    ON lower(pl.manufacturer) = tam.manufacturer 
                    AND lower(pl.weapon_type) = tam.item_type
                WHERE tam.gestalt_type = $1
            """
            
            try:
                # We use self.item_type (which holds the 'inv' like 'bor_sr')
                stat_rows = await conn.fetch(stats_query, self.item_type)
                
                # Create map: { 12345: "+10% Damage", ... }
                # We filter out rows where ID might be None (artifacts of Right Join)
                stats_map = {r['id']: r['stats'] for r in stat_rows if r['id'] is not None}
            except Exception as e:
                log.warning(f"Failed to fetch stats for slot {slot_name}: {e}")
                stats_map = {}

        results = []

        for row in rows:
            part = dict(row)
            
            # --- CAPTURE RAW NAME FIRST ---
            # Capture BEFORE formatting for Rule Matching
            raw_name = str(part.get('partname', '')) 
            
            # --- APPLY PRETTIFY ---
            formatted = item_parser.format_part_name(raw_name)
            part['partname'] = formatted if formatted else raw_name
            
            # --- INJECT STATS ---
            # Match view_all_parts "serial_index" to part_list "id"
            p_id = part.get('serial_index')
            
            if p_id is not None and str(p_id).isdigit():
                part['stats'] = stats_map.get(int(p_id)) 
            else:
                part['stats'] = None
            
            status = {"part": part, "valid": True, "reason": ""}
            
            # --- PARSE ALL TAGS ---
            p_add = db_utils.decode_jsonb_list(part.get('addtags'))
            p_dep = db_utils.decode_jsonb_list(part.get('dependencytags'))
            p_exc = db_utils.decode_jsonb_list(part.get('exclusiontags'))
            
            identification_tags = p_add + p_dep + p_exc

            # --- RULE MATCHING ---
            if allowed_list is not None:
                match_found = False
                for rule_str in allowed_list:
                    # Match against raw_name (database code)
                    if db_utils.match_rule_part_name(raw_name, identification_tags, rule_str, part['inv']):
                        match_found = True
                        break
                if not match_found:
                    continue 

            # --- TAG VALIDATION ---
            p_dep_set = set(p_dep)
            p_exc_set = set(p_exc)

            if not p_exc_set.isdisjoint(current_tags_set):
                status["valid"] = False
                status["reason"] = "Incompatible (Exclusion)"
            
            elif p_dep_set and not p_dep_set.issubset(current_tags_set):
                status["valid"] = False
                missing = list(p_dep_set - current_tags_set)
                status["reason"] = f"Requires: {', '.join(missing)}"
                
            # --- VALIDATION 2: Global Tag Limits (NEW) ---
            # Only check if passed previous checks
            if status["valid"]:
                is_ok, reason = self.check_global_tag_limits(p_add)
                if not is_ok:
                    status["valid"] = False
                    status["reason"] = reason

            results.append(status)

        return results
    
    async def get_serial_string(self) -> str:
        """
        Constructs the final serial string.
        """
        raw_serials = []
        
        # 1. Base Serial (Item Index)
        base = str(self.balance_data.get('base_part') or '0')
        classification = str(self.balance_data.get('serial_index') or '0')
        raw_serials.append(base)
        
        # 2. Collect Part Serials
        for slot in self.slots:
            selection = self.selections.get(slot)
            
            if isinstance(selection, list):
                # Handle Multi-Select (or single select stored as list)
                for part in selection:
                    if isinstance(part, dict):
                        raw_serials.append(str(part.get('serial_index', '0')))
            
            elif isinstance(selection, dict):
                # Handle Single Object
                raw_serials.append(str(selection.get('serial_index', '0')))
                
            # Note: We simply ignore None/Empty here. 
            # If a slot is empty, we don't add a '0' because we filter them out anyway.

        # 3. Filter '0' and Format
        # Logic: Filter x != '0', then wrap in {x}, then join with space
        final_parts = [f"{{{val}}}" for val in raw_serials if val != '0']
        rand_val = random.randint(1, 9999)
        
        component_parts = " ".join(final_parts)
        full_component_list = f"{classification}, 0, 1, 50| 2, {rand_val} ||{component_parts}"
        
        if hasattr(self, 'session'):
            result = await item_parser.reserialize(self.session, full_component_list)
            full_serial = result.get('serial_b85')
        else:
            # Fallback if session wasn't stored (shouldn't happen with your latest changes)
            full_serial = full_component_list
            log.warning("CreatorSession has no aiohttp session stored. Returning raw string.")

        return full_serial
  
    def toggle_part(self, slot_name: str, part_row: Optional[dict]):
        """
        Toggles selection. 
        If Max=1, replaces. 
        If Max>1, adds/removes.
        """
        rules = self.constraints.get(slot_name, {})
        max_limit = rules.get('max', 1)
        
        current = self.selections[slot_name]

        if part_row is None:
            # Clear all
            self.selections[slot_name] = []
            return

        # Check if already selected (toggle off)
        # Use serial_index as ID
        target_serial = str(part_row['serial_index'])
        existing_index = next((i for i, p in enumerate(current) if str(p['serial_index']) == target_serial), -1)

        if existing_index != -1:
            # Remove it
            current.pop(existing_index)
        else:
            # Add it
            if max_limit == 1:
                self.selections[slot_name] = [part_row]
            else:
                if len(current) < max_limit:
                    current.append(part_row)
                else:
                    # Logic for full: Replace last? Or do nothing?
                    # Usually Shift register: Remove first, add new
                    current.pop(0)
                    current.append(part_row)