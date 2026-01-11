import asyncpg
import json
import logging
import random
import re
from collections import Counter
from typing import Optional, List, Dict, Any, Tuple
from helpers import db_utils, item_parser

log = logging.getLogger(__name__)

# --- CONFIGURATION ---
# Associates a Part Type (slot name) with a specific Structure Key (the 'x' in {x:y}).
# Any part type listed here will:
# 1. Be formatted as {Key:[ID, ID]} in the serial.
# 2. Be queried exclusively from the PARENT inventory type (parent_type).
# Part types NOT listed here will use standard {ID} formatting and ITEM inventory type.
PART_STRUCT_MAPPING = {
    "body_ele": "1", 
    "secondary_ele": "1"
}

def parse_component_string(component_str: str) -> Tuple[str, str, List[int], List[int]]:
    """
    Parses the deserialized string.
    Handles standard {id} and structured {key:val} or {key:[v1, v2]} formats.
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
    all_ordered_ids = [] 

    raw_tokens = re.findall(r'\{((?:[^{}]|\[[^\]]*\])+)\}', parts_block)

    for token in raw_tokens:
        token = token.strip()
        is_parent_type = ':' in token
        
        sub_ids = []
        
        if is_parent_type:
            _, val_part = token.split(':', 1)
            val_part = val_part.strip()
            clean_val = val_part.replace('[', '').replace(']', '').replace(',', ' ')
            
            for sid in clean_val.split():
                if sid.strip().isdigit():
                    sub_ids.append(int(sid))
        else:
            clean_val = token.replace('[', '').replace(']', '') 
            for sid in clean_val.split():
                if sid.strip().isdigit():
                    sub_ids.append(int(sid))
        
        if is_parent_type:
            parent_specific_ids.extend(sub_ids)
        else:
            item_specific_ids.extend(sub_ids)
        all_ordered_ids.extend(sub_ids)

    if not all_ordered_ids:
        raise ValueError("No Item ID or Parts found.")

    item_id = str(all_ordered_ids[0])
    
    if item_specific_ids and str(item_specific_ids[0]) == item_id:
        item_specific_ids.pop(0)

    return inv_type_id, item_id, item_specific_ids, parent_specific_ids

async def validate_serial(serial: str, db_pool: asyncpg.Pool, session: Any) -> Tuple[bool, List[str], Dict[str, Any]]:
    """
    Validates a serial string against database rules.
    """
    violations = []
    metadata = {'inv_id': '?', 'item_id': '?', 'part_count': 0, 'tags': []}
    
    try:
        resp = await item_parser.deserialize(session, serial)
        if not resp or 'deserialized' not in resp:
            return False, ["Could not deserialize code."], metadata
            
        component_str = str(resp.get('deserialized'))
        
        try:
            inv_id, item_id, item_p_ids, parent_p_ids = parse_component_string(component_str)
            metadata['inv_id'] = inv_id
            metadata['item_id'] = item_id
            metadata['part_count'] = len(item_p_ids) + len(parent_p_ids)
        except Exception as e:
            return False, [f"Parsing Error: {e}"], metadata

        balance_data = await item_parser.get_balance(db_pool, inv_id, item_id)
        if not balance_data:
            return False, [f"Unknown Item: Inv `{inv_id}` / Item `{item_id}`"], metadata

        creator = CreatorSession(
            user_id=0,
            balance_name=balance_data[0].get('entry_key'),
            balance_data=balance_data,
            db_pool=db_pool,
            session=session
        )
        await creator.initialize()
        
        metadata['item_name'] = creator.balance_name

        target_item_type = str(creator.balance_data.get('item_type'))
        target_parent_type = str(creator.balance_data.get('parent_type'))
        metadata['item_type'] = target_item_type

        loaded_parts = []
        async with db_pool.acquire() as conn:
            all_requested = item_p_ids + parent_p_ids
            if all_requested:
                q = """
                    SELECT * FROM all_parts 
                    LEFT JOIN type_and_manufacturer ON inv = gestalt_type 
                    WHERE serial_index::int = ANY($1::int[])
                """
                log.debug(f"Validating Serial - Loading Parts for IDs: {all_requested}")
                rows = await conn.fetch(q, all_requested)
                loaded_parts = [dict(r) for r in rows]

        found_ids = set()
        for p in loaded_parts:
            sid = p['serial_index']
            if sid and str(sid).isdigit():
                found_ids.add(int(sid))

        for part in loaded_parts:
            p_type = part['part_type']
            p_inv = part.get('inv')
            
            struct_key = PART_STRUCT_MAPPING.get(p_type)
            if struct_key:
                if p_inv != target_parent_type:
                    violations.append(f"**{part.get('partname')}**: Invalid Source. Expected Parent Type `{target_parent_type}`, got `{p_inv}`.")
                    continue
            else:
                if p_inv != target_item_type:
                    violations.append(f"**{part.get('partname')}**: Invalid Source. Expected Item Type `{target_item_type}`, got `{p_inv}`.")
                    continue

            if p_type in creator.slots:
                creator.selections[p_type].append(part)
        
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
                possible_parts = await creator.get_parts_status(slot)
                if any(p['valid'] for p in possible_parts):
                    violations.append(f"**{slot.title()}**: Missing parts ({count}/{min_val}).")

        # B. Tags
        current_tags_list = creator.get_current_tags()
        metadata['tags'] = sorted(list(set(current_tags_list)))
        
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
        
        all_requested_set = set(all_requested)
        unknown_ids = all_requested_set - found_ids
        if unknown_ids:
            violations.append(f"**Unknown IDs**: {list(unknown_ids)}")
            
        return legitimacy, violations, metadata

    except Exception as e:
        log.error(f"Validation Exception: {e}", exc_info=True)
        return False, [f"System Error: {str(e)}"], metadata
    
class CreatorSession:
    def __init__(self, user_id: int, balance_name: str, balance_data: Any, db_pool: asyncpg.Pool, session: Any):
        self.user_id = user_id
        self.balance_name = balance_name
        self.db_pool = db_pool
        self.session = session
        
        if isinstance(balance_data, list):
            self.balance_data = dict(balance_data[0]) if balance_data else {}
        elif hasattr(balance_data, 'get'): 
            self.balance_data = dict(balance_data)
        else:
            self.balance_data = {}
            
        self.item_type = balance_data[0].get('item_type')      
        self.parent_type = balance_data[0].get('parent_type')

        raw_pt = self.balance_data.get('parttypes')
        if isinstance(raw_pt, str): raw_pt = json.loads(raw_pt)
        
        self.part_types_config = {}
        if isinstance(raw_pt, list):
            if raw_pt and isinstance(raw_pt[0], str):
                self.part_types_config = {k: {} for k in raw_pt}
            else:
                for item in raw_pt:
                    if isinstance(item, dict): self.part_types_config.update(item)
        elif isinstance(raw_pt, dict):
            self.part_types_config = raw_pt

        self.constraints = db_utils.parse_selection_rules(self.balance_data.get('parttypeselectionrules'))
        
        self.global_tag_rules = []
        raw_tag_rules = self.balance_data.get('parttagselectionrules')
        
        if isinstance(raw_tag_rules, str):
            try: raw_tag_rules = json.loads(raw_tag_rules)
            except: raw_tag_rules = []
            
        if isinstance(raw_tag_rules, list):
            for rule in raw_tag_rules:
                if isinstance(rule, dict):
                    try:
                        max_val = int(rule.get('max', 999))
                        target_tags = set(db_utils.decode_jsonb_list(rule.get('tags')))
                        self.global_tag_rules.append({'max': max_val, 'tags': target_tags})
                    except (ValueError, TypeError): continue
        
        self.base_tags = db_utils.decode_jsonb_list(self.balance_data.get('basetags'))

        # Slot order from balance_data
        self.slots = list(self.part_types_config.keys())
        
        self.selections: Dict[str, List[Dict[str, Any]]] = {slot: [] for slot in self.slots}
        self.active_slots = []
        
    async def initialize(self):
        """
        Performs the 'Preliminary Scan'.
        Determines active slots and Auto-Selects parts if they are the only option.
        """
        async with self.db_pool.acquire() as conn:
            query = """
                SELECT part_type, inv, COUNT(*) as c
                FROM all_parts
                WHERE inv = $1 OR inv = $2
                GROUP BY part_type, inv
            """
            log.debug(f"Initializing CreatorSession for Item Type: {self.item_type}, Parent Type: {self.parent_type}")
            rows = await conn.fetch(query, self.item_type, self.parent_type)
            
            valid_slots = set()
            single_candidate_slots = []

            for r in rows:
                p_type = r['part_type']
                p_inv = r['inv']
                count = r['c']
                
                struct_key = PART_STRUCT_MAPPING.get(p_type)
                
                is_valid_source = False
                if struct_key:
                    if p_inv == self.parent_type: is_valid_source = True
                else:
                    if p_inv == self.item_type: is_valid_source = True
                
                if is_valid_source and count > 0:
                    valid_slots.add(p_type)
                    if count == 1:
                        single_candidate_slots.append(p_type)

            self.active_slots = [s for s in self.slots if s in valid_slots]

            if single_candidate_slots:
                fetch_q = "SELECT * FROM all_parts WHERE part_type = ANY($1::text[]) and inv = ANY($2::text[])"
                log.debug(f"Auto-selecting parts for slots: {single_candidate_slots}")
                p_rows = await conn.fetch(fetch_q, single_candidate_slots, [self.item_type, self.parent_type])

                for row in p_rows:
                    p_type = row['part_type']
                    p_inv = row['inv']
                    
                    struct_key = PART_STRUCT_MAPPING.get(p_type)
                    target_inv = self.parent_type if struct_key else self.item_type

                    if p_inv == target_inv:
                        self.selections[p_type] = [dict(row)]

    def _parse_tags(self, tag_data: Any) -> List[str]:
        parsed = self._parse_json(tag_data, default=[])
        cleaned_tags = []
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    cleaned_tags.extend(str(v) for v in item.values())
                elif isinstance(item, str):
                    cleaned_tags.append(item)
        elif isinstance(parsed, dict):
            cleaned_tags.extend(str(v) for v in parsed.values())
        elif isinstance(parsed, str):
            cleaned_tags.append(parsed)
        return cleaned_tags

    def get_current_tags(self) -> List[str]:
        tags = list(self.base_tags)
        for part_list in self.selections.values():
            for part in part_list:
                p_add = db_utils.decode_jsonb_list(part.get('addtags'))
                tags.extend(p_add)
        return tags

    def check_global_tag_limits(self, candidate_part_tags: List[str]) -> tuple[bool, str]:
        if not self.global_tag_rules: return True, ""
        current_tags = self.get_current_tags()
        for rule in self.global_tag_rules:
            limit = rule['max']
            targets = rule['tags'] 
            current_count = sum(1 for t in current_tags if t in targets)
            new_adds = sum(1 for t in candidate_part_tags if t in targets)
            if new_adds > 0:
                if (current_count + new_adds) > limit:
                    tag_name = list(targets)[0] if targets else "Restricted"
                    return False, f"Max Limit ({tag_name})"
        return True, ""

    def _parse_json(self, data: Any, default=None) -> Any:
        if data is None: return default
        if isinstance(data, (dict, list)): return data
        if isinstance(data, str):
            try: return json.loads(data)
            except json.JSONDecodeError: return default
        return default

    def select_part(self, slot_name: str, part_row: Optional[dict]):
        self.selections[slot_name] = part_row

    async def get_parts_status(self, slot_name: str) -> List[Dict]:
        """
        Fetches parts with extensive DEBUG logging to trace filtering.
        """
        log.debug(f"--- FETCHING PARTS FOR SLOT: {slot_name} ---")
        
        current_tags_list = self.get_current_tags()
        current_tags_set = set(current_tags_list)
        rules = self.constraints.get(slot_name, {})
        allowed_list = rules.get('allowed_parts') 
        
        struct_key = PART_STRUCT_MAPPING.get(slot_name)
        if struct_key:
            target_inv = self.parent_type
            log.debug(f"Slot {slot_name} mapped to Key {struct_key}. Using PARENT Type: {target_inv}")
        else:
            target_inv = self.item_type
            log.debug(f"Slot {slot_name} is Standard. Using ITEM Type: {target_inv}")

        async with self.db_pool.acquire() as conn:
            query = "SELECT * FROM all_parts WHERE part_type = $1 AND inv = $2"
            log.debug(f"Executing DB Query for parts in slot '{slot_name}' with inv '{target_inv}'")
            rows = await conn.fetch(query, slot_name, target_inv)
            log.debug(f"DB Query returned {len(rows)} raw rows for {slot_name} (inv={target_inv})")
            
            stats_map = {}
            if target_inv == self.item_type:
                # Primary Table: Fetch stats normally
                stats_query = """
                    SELECT pl.id, pl.stats
                    FROM part_list pl
                    RIGHT JOIN type_and_manufacturer tam 
                        ON lower(pl.manufacturer) = tam.manufacturer 
                        AND lower(pl.weapon_type) = tam.item_type
                    WHERE tam.gestalt_type = $1
                """
                try:
                    stat_rows = await conn.fetch(stats_query, self.item_type)
                    stats_map = {r['id']: r['stats'] for r in stat_rows if r['id'] is not None}
                except Exception as e:
                    log.warning(f"Failed to fetch stats: {e}")
            else:
                # Secondary (Parent) Table: Do NOT fetch stats to avoid ID overlap
                # TODO: Insert function call here to fetch stats for Parent Type parts when available.
                # currently, we leave stats_map empty so parts get 'None' stats.
                log.debug(f"Skipping stats fetch for Parent Type parts in slot {slot_name} to prevent overlap.")

        results = []

        for row in rows:
            part = dict(row)
            raw_name = str(part.get('partname', '')) 
            formatted = item_parser.format_part_name(raw_name)
            part['partname'] = formatted if formatted else raw_name
            
            p_id = part.get('serial_index')
            if p_id is not None and str(p_id).isdigit():
                part['stats'] = stats_map.get(int(p_id)) 
            else:
                part['stats'] = None
            
            status = {"part": part, "valid": True, "reason": ""}
            
            p_add = db_utils.decode_jsonb_list(part.get('addtags'))
            p_dep = db_utils.decode_jsonb_list(part.get('dependencytags'))
            p_exc = db_utils.decode_jsonb_list(part.get('exclusiontags'))
            
            identification_tags = p_add + p_dep + p_exc

            # 1. Allowed Parts List Check
            if allowed_list is not None:
                match_found = False
                for rule_str in allowed_list:
                    if db_utils.match_rule_part_name(raw_name, identification_tags, rule_str, part['inv']):
                        log.debug(f"Part '{raw_name}' matches allowed rule '{rule_str}'.")
                        match_found = True
                        break
                if not match_found:
                    log.debug(f"Part '{raw_name}' filtered: Not in allowed_list.")
                    continue 

            p_dep_set = set(p_dep)
            p_exc_set = set(p_exc)

            # 2. Exclusion Check
            if not p_exc_set.isdisjoint(current_tags_set):
                status["valid"] = False
                status["reason"] = "Incompatible (Exclusion)"
                log.debug(f"Part '{raw_name}' INVALID: Exclusion conflict with tags {p_exc_set.intersection(current_tags_set)}")
            
            # 3. Dependency Check
            elif p_dep_set and not p_dep_set.issubset(current_tags_set):
                status["valid"] = False
                missing = list(p_dep_set - current_tags_set)
                status["reason"] = f"Requires: {', '.join(missing)}"
                log.debug(f"Part '{raw_name}' INVALID: Missing dependency {missing}")
                
            # 4. Global Tag Limits
            if status["valid"]:
                is_ok, reason = self.check_global_tag_limits(p_add)
                if not is_ok:
                    status["valid"] = False
                    status["reason"] = reason
                    log.debug(f"Part '{raw_name}' INVALID: Global Limit {reason}")

            results.append(status)

        log.debug(f"--- SLOT {slot_name} FINISHED. {len(results)} parts returned. ---")
        return results
    
    async def get_serial_string(self) -> str:
        """
        Constructs the final serial string, respecting Structured Keys.
        """
        base = str(self.balance_data.get('base_part') or '0')
        classification = str(self.balance_data.get('serial_index') or '0')
        
        part_tokens = []
        for slot in self.slots:
            selection = self.selections.get(slot)
            if not selection: continue
            
            if isinstance(selection, dict): parts_list = [selection]
            else: parts_list = selection
            
            ids = [str(p.get('serial_index', '0')) for p in parts_list]
            ids = [i for i in ids if i != '0']
            if not ids: continue
            
            struct_key = PART_STRUCT_MAPPING.get(slot)
            if struct_key:
                if len(ids) == 1:
                    part_tokens.append(f"{{{struct_key}:{ids[0]}}}")
                else:
                    joined_ids = ", ".join(ids)
                    part_tokens.append(f"{{{struct_key}:[{joined_ids}]}}")
            else:
                for i in ids:
                    part_tokens.append(f"{{{i}}}")

        all_tokens = []
        if base != '0':
            all_tokens.append(f"{{{base}}}")
        all_tokens.extend(part_tokens)
        
        rand_val = random.randint(1, 9999)
        component_parts = " ".join(all_tokens)
        
        full_component_list = f"{classification}, 0, 1, 50| 2, {rand_val} ||{component_parts}"
        
        if hasattr(self, 'session'):
            result = await item_parser.reserialize(self.session, full_component_list)
            full_serial = result.get('serial_b85')
        else:
            full_serial = full_component_list
            log.warning("CreatorSession has no aiohttp session stored. Returning raw string.")

        return full_serial
  
    def update_slot_selection(self, slot_name: str, part_rows: List[dict]):
        """
        Updates the selection for a slot using a list of parts (Multi-Select compatible).
        Replaces the current selection. Truncates if exceeds max limit.
        """
        rules = self.constraints.get(slot_name, {})
        max_limit = rules.get('max', 1)
        
        if not part_rows:
            self.selections[slot_name] = []
            return

        if len(part_rows) > max_limit:
            self.selections[slot_name] = part_rows[:max_limit]
        else:
            self.selections[slot_name] = part_rows

    def get_slot_placeholder(self, slot_name: str) -> str:
        """
        Returns the formatted placeholder string for the UI.
        Example: "Select body_acc to add [2-3]"
        """
        rules = self.constraints.get(slot_name, {})
        min_val = rules.get('min', 0)
        max_val = rules.get('max', 1)
        
        return f"Select {slot_name} to add [{min_val}-{max_val}]"