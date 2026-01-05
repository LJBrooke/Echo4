import json
import logging
import re
from typing import Any, List, Dict, Union

log = logging.getLogger(__name__)

log = logging.getLogger(__name__)

def encode_jsonb(data: Any) -> str:
    """
    Formats a Python object (List/Dict) into a JSON string that Postgres 
    can accept for JSONB columns.
    
    Usage: 
        await conn.execute("UPDATE table SET tags = $1", encode_jsonb(['a', 'b']))
    """
    if data is None:
        return '[]'
    try:
        return json.dumps(data)
    except (TypeError, ValueError):
        log.error(f"Failed to encode data to JSONB: {data}")
        return '[]'

def decode_jsonb_list(data: Any, flatten_redundant_dicts: bool = True) -> List[str]:
    """
    Robustly parses data from Postgres JSONB columns.
    
    1. Handles Strings (JSON encoded), Lists (Asyncpg decoded), or None.
    2. If flatten_redundant_dicts is True, it cleans up the 
       [{'tag': 'tag'}, 'tag2'] structure into ['tag', 'tag2'].
    """
    if data is None:
        return []

    # 1. Decode JSON String if necessary
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return []

    # 2. Ensure we have a list to iterate over
    if isinstance(data, dict):
        # Edge case: Data is just {'tag': 'tag'}
        items = [data]
    elif isinstance(data, list):
        items = data
    else:
        # Primitives (int, plain str that wasn't json)
        items = [data]

    cleaned_list = []

    # 3. Flatten and Clean
    for item in items:
        if flatten_redundant_dicts and isinstance(item, dict):
            # Extract values: {'unique': 'unique'} -> 'unique'
            cleaned_list.extend(str(v) for v in item.values())
        elif isinstance(item, (str, int, float, bool)):
            cleaned_list.append(str(item))
            
    return cleaned_list

def parse_selection_rules(rules_data: Any) -> Dict[str, Dict]:
    """
    Parses the 'parttypeselectionrules' JSON structure.
    
    Input format:
    { "pairs": { "random_id": { "key": "barrel", "value": { "parts": [...], "partcount": {...} } } } }
    
    Output format:
    {
       "barrel": {
           "min": 1,
           "max": 1,
           "allowed_parts": ["part_barrel_01_Stray", ...] (or None if no restriction)
       },
       ...
    }
    """
    if not rules_data:
        return {}
    
    # Handle string/dict conversion
    if isinstance(rules_data, str):
        try:
            rules_data = json.loads(rules_data)
        except:
            return {}
            
    pairs = rules_data.get('pairs', {})
    parsed_rules = {}

    for pair_obj in pairs.values():
        slot_name = pair_obj.get('key')
        val = pair_obj.get('value', {})
        
        if not slot_name:
            continue

        # 1. Parse Counts
        count_data = val.get('partcount', {})
        # User requested default to 1 if missing
        min_val = int(count_data.get('min', 1))
        max_val = int(count_data.get('max', 1))

        # 2. Parse Allow List
        allowed_parts = None
        raw_parts = val.get('parts') # List of {"part": "name"} objects
        if raw_parts:
            allowed_parts = [item.get('part') for item in raw_parts if item.get('part')]

        parsed_rules[slot_name] = {
            "min": min_val,
            "max": max_val,
            "allowed_parts": allowed_parts
        }
        
    return parsed_rules

def match_rule_part_name(db_partname: str, db_tags: List[str], rule_part_string: str, inv: str) -> bool:
    """
    Matches a Rule String (e.g. 'part_barrel_01_Stray') against a DB Row.
    
    Logic:
    1. Replace 'part' in rule with 'inv'.
    2. Check if DB name matches exactly.
    3. If not, check if Rule contains DB name + specific Tag suffix.
    """
    # Normalize inputs
    db_partname = db_partname.lower()
    rule_part_string = rule_part_string.lower()
    inv = inv.lower()

    # print("Matching Rule Part Name:")
    # print(f"  DB Part Name: {db_partname}") 
    # print(f"  DB Tags: {db_tags}")
    # print(f"  Rule Part String: {rule_part_string}")
    # print(f"  Inv: {inv}")
    # 1. Construct Expected Basic Name
    # "part_mag_01" -> "bor_sr_mag_01"
    # "part_barrel_01_stray" -> "bor_sr_barrel_01_stray"
    expected_full_str = rule_part_string.replace("part", inv, 1)
    # print(f"  Expected Full String: {expected_full_str}")

    # Direct Match
    if db_partname == expected_full_str:
        return True

    # Suffix/Tag Match
    # Case: DB="bor_sr_barrel_01", Rule="bor_sr_barrel_01_stray"
    if expected_full_str.startswith(db_partname):
        # Extract the suffix: "_stray"
        suffix = expected_full_str[len(db_partname):].strip("_")
        
        # Check if this suffix exists in tags (e.g., 'uni_stray' or just 'stray')
        # We check both exact tag match and "uni_" prefix which is common
        for tag in db_tags:
            tag = tag.lower()
            if tag == suffix or tag == f"uni_{suffix}":
                return True
    # print("No match found.")
    # print("----")
    return False