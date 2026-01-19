import asyncpg
import json
import logging
import random
import re
from collections import Counter
from typing import Optional, List, Dict, Any, Tuple
from helpers import db_utils, item_parser

log = logging.getLogger(__name__)

PART_STRUCT_MAPPING = {}

def parse_component_string(component_str: str) -> Tuple[str, str, List[Tuple[int, str]]]:
    """
    Parses the deserialized string using Table Reference Logic.
    
    Format:
    - {y}        -> serial_index=y, serial_inv=inv_type_id (Base Item ID)
    - {x:y}      -> serial_index=y, serial_inv=x
    - {x:[y, z]} -> serial_index=y/z, serial_inv=x

    Returns: (inv_type_id, item_id, List[(part_id, required_serial_inv)])
    """
    if '||' not in component_str:
        raise ValueError("Invalid format: Missing '||' separator.")
        
    first_section = component_str.split('|')[0]
    # The first number is the Inventory ID for the base item (e.g., '50')
    inv_type_id = first_section.split(',')[0].strip()

    parts_block = component_str.split('||')[1]
    if '|' in parts_block:
        parts_block = parts_block.split('|')[0]

    parsed_parts: List[Tuple[int, str]] = []
    
    # Regex finds content inside curly braces: {123} or {1:[123, 456]}
    raw_tokens = re.findall(r'\{((?:[^{}]|\[[^\]]*\])+)\}', parts_block)

    all_ids_ordered = []

    for token in raw_tokens:
        token = token.strip()
        
        # Check for Table Reference: {x:...}
        if ':' in token:
            target_inv_ref, val_part = token.split(':', 1)
            target_inv_ref = target_inv_ref.strip()
            val_part = val_part.strip()
            
            # Clean brackets for list format [x, y]
            clean_val = val_part.replace('[', '').replace(']', '').replace(',', ' ')
            ids = [int(s) for s in clean_val.split() if s.strip().isdigit()]
            
            for pid in ids:
                parsed_parts.append((pid, target_inv_ref))
                all_ids_ordered.append(pid)
        else:
            # Standard format {y} -> Uses the Item's inv_type_id
            clean_val = token.replace('[', '').replace(']', '').replace(',', ' ')
            ids = [int(s) for s in clean_val.split() if s.strip().isdigit()]
            
            for pid in ids:
                parsed_parts.append((pid, inv_type_id))
                all_ids_ordered.append(pid)

    if not all_ids_ordered:
        raise ValueError("No Item ID or Parts found.")

    # Convention: First ID found is the Item/Base ID, remove it from parts list
    item_id = str(all_ids_ordered[0])
    
    # Remove the first occurrence of item_id from parsed_parts to avoid treating base as a part
    for i, (pid, pinv) in enumerate(parsed_parts):
        if str(pid) == item_id:
            parsed_parts.pop(i)
            break

    return inv_type_id, item_id, parsed_parts

async def validate_serial(serial: str, db_pool: asyncpg.Pool, session: Any) -> Tuple[bool, List[str], Dict[str, Any]]:
    """
    Validates a serial string by strictly checking (serial_index, serial_inv) pairs
    and ensuring the resulting parts belong to allowed inventory types.
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
            inv_type_id, item_id, parsed_parts = parse_component_string(component_str)
            metadata['inv_id'] = inv_type_id
            metadata['item_id'] = item_id
            metadata['part_count'] = len(parsed_parts)
        except Exception as e:
            return False, [f"Parsing Error: {e}"], metadata

        # 3. Fetch Balance (The Recursive SQL Result)
        balance_data = await item_parser.get_balance(db_pool, inv_type_id, item_id)
        if not balance_data:
            return False, [f"Unknown Item: Inv `{inv_type_id}` / Item `{item_id}`"], metadata

        # 4. Determine Valid Inventory Types (Whitelist)
        row = balance_data[0]
        item_type = row.get('item_type')
        parent_types = row.get('parent_type') or []
        child_types = row.get('child_types') or []
        
        # Fallback for data types
        if not isinstance(parent_types, list): parent_types = [str(parent_types)] if parent_types else []
        if not isinstance(child_types, list): child_types = [str(child_types)] if child_types else []
        
        # Valid Scopes: The part must belong to one of these text names
        valid_inv_scopes = set([item_type] + parent_types + child_types)

        # 5. Init Session
        creator = CreatorSession(
            user_id=0,
            balance_name=row.get('entry_key'),
            balance_data=balance_data,
            base_serial_inv_id=inv_type_id, # Pass the numeric ID
            db_pool=db_pool,
            session=session
        )
        await creator.initialize(auto_select=False)
        
        metadata['item_name'] = creator.balance_name
        metadata['item_type'] = str(creator.item_type)

        # 6. Bulk Load Parts
        # We need to query: WHERE (serial_index, serial_inv) IN (parsed_parts)
        # We use UNNEST to pass arrays of IDs and Invs matching index-wise.
        loaded_parts = []
        
        if parsed_parts:
            req_ids = [int(p[0]) for p in parsed_parts]
            req_invs = [int(p[1]) for p in parsed_parts]
            
            async with db_pool.acquire() as conn:
                # UPDATED: Explicit casts to resolve "operator does not exist: text = integer"
                q_fetch = """
                    SELECT p.* FROM all_parts p
                    JOIN unnest($1::int[], $2::int[]) AS req(idx, sinv) 
                        ON p.serial_index::int = req.idx AND p.serial_inv = req.sinv
                """
                log.debug(f"Bulk validating {len(parsed_parts)} parts.")
                rows = await conn.fetch(q_fetch, req_ids, req_invs)
                loaded_parts = [dict(r) for r in rows]

        # 7. Equip & Validate
        
        # Track which requested (ID, Inv) pairs we actually found
        found_map = { (int(p['serial_index']), str(p['serial_inv'])): p for p in loaded_parts }
        
        for req_id, req_inv in parsed_parts:
            part = found_map.get((req_id, req_inv))
            
            # Check A: Did we find the part in the specific table ref?
            if not part:
                violations.append(f"**Missing Part**: ID `{req_id}` not found in Table Ref `{req_inv}`.")
                continue

            # Check B: Is the part's Actual Inventory Type allowed for this Item?
            real_inv_type = part.get('inv')
            if real_inv_type not in valid_inv_scopes:
                violations.append(f"**{part.get('partname')}**: Invalid Source. Source `{real_inv_type}` is not in allowed types for this item.")
                continue

            # Equip
            p_type = part.get('part_type')
            if p_type in creator.slots:
                creator.selections[p_type].append(part)
        
        # 8. Standard Logic Checks (Limits, Tags)
        
        # A. Slot Limits
        for slot in creator.slots:
            selected = creator.selections[slot]
            count = len(selected)
            rules = creator.constraints.get(slot, {})
            max_val = rules.get('max', 1)
            min_val = rules.get('min', 1)
            
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
        return legitimacy, violations, metadata

    except Exception as e:
        log.error(f"Validation Exception: {e}", exc_info=True)
        return False, [f"System Error: {str(e)}"], metadata
    
class CreatorSession:
    def __init__(self, user_id: int, balance_name: str, balance_data: Any, db_pool: asyncpg.Pool, session: Any, base_serial_inv_id: str = "0"):
        self.user_id = user_id
        self.balance_name = balance_name
        self.db_pool = db_pool
        self.session = session
        self.base_serial_inv_id = base_serial_inv_id # The numeric ID (e.g. '50')
        
        if isinstance(balance_data, list):
            self.balance_data = dict(balance_data[0]) if balance_data else {}
        elif hasattr(balance_data, 'get'): 
            self.balance_data = dict(balance_data)
        else:
            self.balance_data = {}
            
        self.item_type = self.balance_data.get('item_type')      
        
        # Load Hierarchy Types
        self.parent_types = self.balance_data.get('parent_type') or []
        if not isinstance(self.parent_types, list): self.parent_types = [str(self.parent_types)]
        
        self.child_types = self.balance_data.get('child_types') or []
        if not isinstance(self.child_types, list): self.child_types = [str(self.child_types)]
        
        # Create Whitelist of Valid Inventory Names
        # If child_types is empty, include item_type.
        if not self.child_types and self.item_type:
             self.child_types = [self.item_type]

        self.valid_inv_types = list(set([self.item_type] + self.parent_types + self.child_types))

        # Config Loading...
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

        # --- FIX: Parse and Sanitize parttypeselectionrules ---
        raw_rules = self.balance_data.get('parttypeselectionrules')

        # 1. Ensure it is a Dictionary
        if isinstance(raw_rules, str):
            try:
                raw_rules = json.loads(raw_rules)
            except Exception:
                raw_rules = {}
        
        if not isinstance(raw_rules, dict):
            raw_rules = {}

        # 2. Recursive Sanitizer: Handles both Flat and Nested "Pairs" structures
        # targets keys 'parts' or 'allowed_parts' anywhere in the JSON tree.
        def sanitize_rules_data(data):
            if isinstance(data, dict):
                for k, v in data.items():
                    # Check for keys that hold part lists
                    if k in ['parts', 'allowed_parts'] and isinstance(v, list):
                        new_list = []
                        for item in v:
                            if isinstance(item, str):
                                # Fix: Convert plain string (even empty "") to dict object
                                new_list.append({'part': item})
                            else:
                                new_list.append(item)
                        data[k] = new_list
                    else:
                        # Continue recursion
                        sanitize_rules_data(v)
            elif isinstance(data, list):
                for item in data:
                    sanitize_rules_data(item)

        sanitize_rules_data(raw_rules)

        self.constraints = db_utils.parse_selection_rules(raw_rules)
        # -----------------------------------------------------------
        
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
        self.slots = list(self.part_types_config.keys())
        self.selections: Dict[str, List[Dict[str, Any]]] = {slot: [] for slot in self.slots}
        self.active_slots = []
        
    async def initialize(self, auto_select: bool = True):
        """
        Preliminary Scan.
        Updated to strictly filter by serial_inv to avoid cross-contamination.
        """
        async with self.db_pool.acquire() as conn:
            # UPDATED: Group by serial_inv too.
            query = """
                SELECT part_type, inv, serial_inv, COUNT(*) as c
                FROM all_parts
                WHERE inv = ANY($1::text[])
                GROUP BY part_type, inv, serial_inv
            """
            log.debug(f"Initializing Session. Valid Invs: {self.valid_inv_types}")
            rows = await conn.fetch(query, self.valid_inv_types)
            
            valid_slots = set()
            single_candidate_slots = []
            
            # Map part types to their counts *if* they match the correct serial_inv
            slot_candidates = {}

            for r in rows:
                p_type = r['part_type']
                p_inv = r['inv']
                # Cast to string for safe comparison
                p_serial_inv = str(r['serial_inv']) 
                
                # Check 1: Does this part belong to the expected Table Ref for this slot?
                expected_ref = PART_STRUCT_MAPPING.get(p_type, self.base_serial_inv_id)
                if p_serial_inv != expected_ref:
                    # Skip parts that happen to have the same name/inv but wrong table ID
                    continue

                if p_type not in slot_candidates:
                    slot_candidates[p_type] = 0
                slot_candidates[p_type] += r['c']

            for s, count in slot_candidates.items():
                if count > 0:
                    valid_slots.add(s)
                    if count == 1:
                        single_candidate_slots.append(s)

            self.active_slots = [s for s in self.slots if s in valid_slots]

            if auto_select and single_candidate_slots:
                # To auto-select, we must respect the table references
                for slot in single_candidate_slots:
                    parts = await self.get_parts_status(slot)
                    # get_parts_status does strict checking now
                    valid_p = [p['part'] for p in parts if p['valid']]
                    if len(valid_p) == 1:
                        self.selections[slot] = valid_p

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

    async def get_parts_status(self, slot_name: str) -> List[Dict]:
        """
        Fetches parts for a slot using strictly mapped Table Ref IDs (serial_inv).
        AND validates that the parts come from allowed Inventory Types (inv).
        """
        log.debug(f"--- FETCHING PARTS FOR SLOT: {slot_name} ---")
        
        current_tags_list = self.get_current_tags()
        current_tags_set = set(current_tags_list)
        rules = self.constraints.get(slot_name, {})
        allowed_list = rules.get('allowed_parts') 
        
        # DETERMINE TARGET SERIAL_INV
        mapped_ref = PART_STRUCT_MAPPING.get(slot_name)
        if mapped_ref:
            target_serial_inv = mapped_ref
            log.debug(f"Slot {slot_name} uses Mapped Ref: {target_serial_inv}")
        else:
            target_serial_inv = self.base_serial_inv_id
            log.debug(f"Slot {slot_name} uses Base Ref: {target_serial_inv}")

        async with self.db_pool.acquire() as conn:
            # STRICT QUERY with CASTS:
            # 1. Matches part_type
            # 2. Matches serial_inv (casted to text to match Python string)
            # 3. Matches allowed Inventory Types (inv)
            query = """
                SELECT * FROM all_parts 
                WHERE part_type = $1 
                AND serial_inv = $2 
                AND inv = ANY($3::text[])
            """
            rows = await conn.fetch(query, slot_name, target_serial_inv, self.valid_inv_types)
            log.debug(f"Query returned {len(rows)} parts.")
            
            stats_map = {}
            if mapped_ref is None: 
                # Standard Item logic for stats
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
                except Exception: pass

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
                        match_found = True
                        break
                if not match_found:
                    continue 

            p_dep_set = set(p_dep)
            p_exc_set = set(p_exc)

            # 2. Exclusion Check
            if not p_exc_set.isdisjoint(current_tags_set):
                status["valid"] = False
                status["reason"] = "Incompatible (Exclusion)"
            
            # 3. Dependency Check
            elif p_dep_set and not p_dep_set.issubset(current_tags_set):
                status["valid"] = False
                missing = list(p_dep_set - current_tags_set)
                status["reason"] = f"Requires: {', '.join(missing)}"
                
            # 4. Global Tag Limits
            if status["valid"]:
                is_ok, reason = self.check_global_tag_limits(p_add)
                if not is_ok:
                    status["valid"] = False
                    status["reason"] = reason

            results.append(status)

        return results
    
    async def get_serial_string(self) -> str:
        """
        Constructs the final serial string using Table Reference buckets.
        """
        base = str(self.balance_data.get('base_part') or '0')
        classification = str(self.balance_data.get('serial_index') or '0')
        
        # We group parts by their required Table Reference ID
        # Map: serial_inv -> list of IDs
        buckets: Dict[str, List[str]] = {}
        
        # Initialize default bucket (Base Item ID)
        buckets[self.base_serial_inv_id] = []
        
        for slot in self.slots:
            selection = self.selections.get(slot)
            if not selection: continue
            
            if isinstance(selection, dict): parts_list = [selection]
            else: parts_list = selection
            
            # Determine which bucket these parts belong to
            mapped_ref = PART_STRUCT_MAPPING.get(slot)
            target_bucket = mapped_ref if mapped_ref else self.base_serial_inv_id
            
            if target_bucket not in buckets:
                buckets[target_bucket] = []

            for p in parts_list:
                sid = str(p.get('serial_index', '0'))
                if sid != '0':
                    buckets[target_bucket].append(sid)

        # Build Token Strings
        part_tokens = []
        
        # 1. Handle Default Bucket (Unstructured {id})
        default_ids = buckets.get(self.base_serial_inv_id, [])
        for pid in default_ids:
            part_tokens.append(f"{{{pid}}}")
            
        # 2. Handle Structured Buckets ({ref:[ids]})
        for ref, ids in buckets.items():
            if ref == self.base_serial_inv_id: continue # Already handled
            if not ids: continue
            
            if len(ids) == 1:
                part_tokens.append(f"{{{ref}:{ids[0]}}}")
            else:
                joined_ids = ", ".join(ids)
                part_tokens.append(f"{{{ref}:[{joined_ids}]}}")

        all_tokens = []
        if base != '0':
            all_tokens.append(f"{{{base}}}")
        all_tokens.extend(part_tokens)
        
        rand_val = random.randint(1, 9999)
        component_parts = " ".join(all_tokens)
        
        # Inv Type ID goes into the prefix
        full_component_list = f"{self.base_serial_inv_id}, {classification}, 0, 1, 50| 2, {rand_val} ||{component_parts}"
        
        if hasattr(self, 'session'):
            result = await item_parser.reserialize(self.session, full_component_list)
            full_serial = result.get('serial_b85')
        else:
            full_serial = full_component_list
            log.warning("CreatorSession has no aiohttp session stored. Returning raw string.")

        return full_serial
  
    def update_slot_selection(self, slot_name: str, part_rows: List[dict]):
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
        rules = self.constraints.get(slot_name, {})
        min_val = rules.get('min', 0)
        max_val = rules.get('max', 1)
        return f"Select {slot_name} to add [{min_val}-{max_val}]"