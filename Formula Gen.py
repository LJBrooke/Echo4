import json
from typing import Dict, Any, List, Optional

def read_json_file(file_path: str) -> Any:
    """
    Reads a JSON file and returns its content as a Python object.

    Args:
        file_path (str): The full path to the JSON file.

    Returns:
        Any: The parsed JSON data (usually a dict or list), or None if an error occurs.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data
    except FileNotFoundError:
        print(f"Error: The file at '{file_path}' was not found.")
        return None
    except json.JSONDecodeError:
        print(f"Error: Failed to decode JSON from the file at '{file_path}'. Check if it's valid JSON.")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None
    
def find_item_by_name(source_file: str, name_to_find: str) -> Optional[Dict[str, Any]]:
    """
    The expected json structure is a dictionary where each value is a list of smaller dictionaries.
    Each of these smaller dictionaries is expected to have a 'name' key.

    Args:
        source_file (str): The json file path to search through.
        name_to_find (str): The name of the item to find.

    Returns:
        The dictionary of the item if found, otherwise None.
    """
    
    data = read_json_file(source_file)
    for item_list in data.values():
        for item in item_list:
            if item.get("name") == name_to_find:
                return item  # Return the entire dictionary as soon as we find it

    # If we finish all loops without finding a match, return None
    return None

def generate_base(damage_source: Dict) -> str:
    '''
    Expects a dictionary containing the following keys:
    - base: Either an Int value or a string descriptor
    - lvl scale exp: An integer indicating the exponential scaling per level.
    - lvl scale lin: An integer indicating the linear scaling per level.
    
    Args:
        damage_source (Dict): Dictionary object containing damage source information to generate base from
        
    Returns:
        string formula for the base damage.
    '''
    base = str(damage_source.get("base")) # Enforce string typing.
    if damage_source.get("lvl scale exp"): base = base + ' x ' +  str(damage_source.get("lvl scale exp")) + 'ˡᵛˡ'
    if damage_source.get("lvl scale lin"): base = base + ' x (' +  str(damage_source.get("lvl scale lin")) + ' x lvl)'
    # if damage_source.get("lvl scale exp") or damage_source.get("lvl scale lin"):
    return base

def compose_response(damage_source: Dict, formula: str, disclaimers: List=None) -> str:
    '''
    Args:
        damage_source (Dict): Dictionary object containing damage source information
        formula (str): The pasta.
        disclaimers (List): Notes on items included in the formula.
        
    Returns:
        A discord formatted response message.
    '''
    
    damage_type = ''
    for type in damage_source.get('type'):
        damage_type += ', '+str(type)
        
    message= f'''
# {damage_source.get('name')}
**Type(s):** {damage_type[2:]}
```{formula} ```'''

    if disclaimers:
        message += '\n## Notes:'
        for pasta in disclaimers:
            message += '\n- '+str(pasta)
    
    return message
    
    
def generate_formula(damage_source_str: str) -> str:
    '''
    Expects a string key for an object in 'Damage Source.json'.
    Generates a formula for said damage source.
    
    Args:
        damage_source_str (str): A key for an object in Damage Source.json
        
    Returns:
        formatted message including the damage formula for provided object if found, otherwise an error string.
    '''
    # Fetch damage source Json
    damage_source = find_item_by_name('Damage Source.json', damage_source_str)
    
    if damage_source == None: return "Damage Source not Supported"
    
    formula = generate_base(damage_source)
    message = compose_response(damage_source, formula, ['This is moral actual melee right?', 'Rat PLZ Test'])
    # message = compose_response(damage_source_str, formula, None)
    
    return message


if __name__=='__main__':
    print(generate_formula('Gun'))
    print(generate_formula('Splash Gun'))
    print(generate_formula('Melee'))