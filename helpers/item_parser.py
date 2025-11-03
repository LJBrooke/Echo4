# File: helpers/item_parser.py
import re

# Serialization URL, Nicnl and InflamedSebi are amazing.
NICNL_URL = 'https://borderlands4-deserializer.nicnl.com/api/v1/'

# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# ASYNC SERIALIZATION FUNCTIONS
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

async def deserialize(session, serial: str) -> dict:
    """
    Uses an async aiohttp session to deserialize a string.
    Args:
        session: The bot's aiohttp.ClientSession
        serial (str): The serial string
    """
    endpoint = f'{NICNL_URL}deserialize'
    payload = {"serial_b85": serial.strip()}
    
    # Use the async session
    async with session.post(endpoint, json=payload) as response:
        if response.status == 200:
            return await response.json()
        return {"error": f"API returned status {response.status}"}

async def reserialize(session, component_string: str) -> dict:
    """
    Uses an async aiohttp session to reserialize a string.
    Args:
        session: The aiohttp.ClientSession
        component_string (str): The deserialized component string
    """
    endpoint = f'{NICNL_URL}reserialize'
    payload = {"deserialized": component_string.strip()}
    
    # Use the async session
    async with session.post(endpoint, json=payload) as response:
        if response.status == 200:
            return await response.json()
        return {"error": f"API returned status {response.status}"}

# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# ASYNC DATABASE FUNCTIONS
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

async def query_id(db_pool, Manufacturer: str, Weapon_Type: str, id: int) -> str:
    """
    Uses the async asyncpg pool to fetch a single part.
    Args:
        db_pool: The bot's asyncpg.Pool
    """
    query = """
    SELECT part_string 
    FROM part_list 
    WHERE id = $1 
      AND weapon_type = $2 
      AND Manufacturer = $3
    """
    # Use 'with pool.acquire()' to get a connection
    async with db_pool.acquire() as conn:
        result = await conn.fetchrow(query, id, Weapon_Type, Manufacturer)
    
    return result['part_string'] if result else None

async def query_type(db_pool, id: int) -> str:
    """
    Uses the async asyncpg pool to fetch a single part.
    Args:
        db_pool: The bot's asyncpg.Pool
    """
    query = """
    SELECT manufacturer, item_type 
    FROM type_and_manufacturer 
    WHERE id = $1 
    """
    # Use 'with pool.acquire()' to get a connection
    async with db_pool.acquire() as conn:
        result = await conn.fetchrow(query, id)
    
    return result['item_type'], result['manufactuer'] if result else None

async def query_element_id(db_pool, primary: str, secondary: str, underbarrel: bool) -> str:
    """
    Uses the async asyncpg pool to fetch a single element part id.
    Args:
        db_pool: The bot's asyncpg.Pool
    """
    query = f"""
    SELECT id 
    FROM element_list 
    WHERE lower(primary_element) = lower('{primary}')
    and underbarrel is {underbarrel}"""

    if secondary is None: query=query + ' and secondary_element is null'
    else: query=query + f" and lower(secondary_element) =lower('{secondary}')"    
    print(query)
    # Use 'with pool.acquire()' to get a connection
    async with db_pool.acquire() as conn:
        result = await conn.fetchrow(query)
    print(result.get('id'))
    return '{1:'+str(result.get('id'))+'}' if result else None

async def query_part_list(db_pool, Manufacturer: str, Weapon_Type: str, part_list: list) -> list:
    """
    Uses the async asyncpg pool to fetch multiple parts.
    Args:
        db_pool: The bot's asyncpg.Pool
        Manufacturer (str): Weapon Manufacturer
        Weapon_Type (str): Weapon Type
    """
    query = f"""
    SELECT
        part_string, 
        id,
        stats,
        effects
    FROM part_list 
    WHERE 
        id = ANY($1) AND 
        lower(weapon_type) = lower($2) AND 
        lower(Manufacturer) = lower($3)
    """
    # Using ANY($1) is the safe, correct way to handle a list
    async with db_pool.acquire() as conn:
        results = await conn.fetch(query, part_list, Weapon_Type, Manufacturer)
    
    return results # Returns a list of Record objects

async def query_possible_parts(db_pool, Manufacturer: str, Weapon_Type: str, Part_Type: str) -> list:
    """
    Uses the async asyncpg pool to possible multiple parts.
    Args:
        db_pool: The bot's asyncpg.Pool
        Manufacturer (str): Weapon Manufacturer
        Weapon_Type (str): Weapon Type
        Part_Type (str): Part Type
    """
    query = f"""
    SELECT
        id,
        part_string, 
        stats,
        requirements,
        effects
    FROM part_list 
    WHERE 
        part_type = $1 AND 
        weapon_type = $2 AND 
        manufacturer = $3
    """
    async with db_pool.acquire() as conn:
        results = await conn.fetch(query, Part_Type, Weapon_Type, Manufacturer)
    
    return results # Returns a list of Record objects

async def query_element(db_pool, element_list: list) -> list:
    """
    Uses the async asyncpg pool to fetch multiple parts.
    Args:
        db_pool: The bot's asyncpg.Pool
        Manufacturer (str): Weapon Manufacturer
        Weapon_Type (str): Weapon Type
    """
    query = f"""
    SELECT
        primary_element,
        secondary_element,
        underbarrel
    FROM element_list 
    WHERE 
        id = ANY($1)
    """
    # Using ANY($1) is the safe, correct way to handle a list
    async with db_pool.acquire() as conn:
        results = await conn.fetch(query, element_list)
    
    return results # Returns a list of Record objects

# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# LOGIC FUNCTIONS (Now accept part_data)
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

def split_item_str(item_str: str) -> list[str, int, list[int]]:
    base_aspect, part_aspect = item_str.split('||')
    base, unknown = base_aspect.split('|')
    item_type, base_0, base_1, level = base.split(', ')
    parts, skin = part_aspect.split('|')

    # The regex pattern:
    # r"\{"  -> Matches a literal {
    # ".*?" -> Matches any character (.), 0 or more times (*), non-greedily (?)
    # r"\}"  -> Matches a literal }
    pattern = r"\{.*?\}"
    part_list = re.findall(pattern, parts)
    
    return item_type, level, part_list

def find_aspect(part_data: dict, part: str, id: str) -> dict:
    """
    Finds an aspect from the passed-in part_data dictionary.
    Args:
        part_data: The loaded part_data.json
        part (str): Aspect type to Query, Manufacturer or Element
        id: instance of part to find.
    """
    options = part_data.get(part)
    if not options:
        return None
        
    for option in options:
        if str(option.get('id')) == str(id):
            return option
    return None

async def create_part_and_element_list(db_pool, part_list: list) -> list[list]:
    int_part_list = []
    int_ele_list = []
    
    for part in part_list:
        if ':' not in part and part.startswith('{') and part.endswith('}'):
            int_part_list.append(int(part.strip()[1:-1]))
        elif ':' in part:
            # print(part)
            ele_part = str(part[1:-1]).split(':')
            print(ele_part)
            if int(ele_part[0]) == 1:
                int_ele_list.append(int(ele_part[1]))
    elements = await query_element(db_pool, int_ele_list)
    
    return int_part_list, elements

async def compile_part_list(db_pool, item_code: str) -> str:
    """
    Compiles a part list, calling async DB functions.
    :param db_pool: The bot's asyncpg.Pool
    """
    try:
        item_type, level, part_list = split_item_str(item_code)
        
        type, manufacturer = query_type(db_pool, item_type)
        if type not in ['pistol', 'shotgun', 'assault_rifle', 'smg', 'sniper']:
            return "Sorry, only weapons are supported currently"

        int_part_list, elements = await create_part_and_element_list(db_pool, part_list)
        
        # This function is now async, so we must 'await' it
        str_part_list = await query_part_list(
            db_pool, 
            manufacturer, 
            type, 
            int_part_list
        )
        
        formatted_response = ''
        
        for element in reversed(elements):
            if element[1] is None:
                formatted_response = formatted_response+ f'Primary Element: {element[0]}\n'
            else: formatted_response = formatted_response+ f'Secondary Element: {element[1]}\n\n'
        for part in str_part_list:
            # 'part' is now an asyncpg.Record, access by key
            line = f"- {str(part['id']):<3}: {part['part_string'].ljust(50)}"
            if part['stats'] and len(part['stats']) > 0:
                line += part['stats']
            formatted_response += line + '\n'
        
        return formatted_response if formatted_response else "No parts found."
    except Exception as e:
        return f"Error during part list compilation: {e}"


# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# ASYNC DRIVER FUNCTIONS
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

# Driver functions are intented To handle logic for fetching information and returning pre formatted message components that
# can then be incorporated into the bigger message structure of the calling cog.    

async def part_list_driver(session, db_pool, item_code: str) -> str:
    """
    Async driver that accepts all dependencies.
    """
    serialization_required = False
    original_code = item_code
    
    if '@Ug' in item_code:
        deserial_data = await deserialize(session, item_code)
        item_code = deserial_data.get('deserialized')
        if not item_code:
            return f"Error deserializing: {deserial_data.get('error')}"
        serialization_required = True
    else: original_code = await reserialize(session, item_code)
    
    # This function is now async
    part_list_str = await compile_part_list(db_pool, item_code)
    
    
    item_name = "Unknown Item" # A safe default
    additional_data = deserial_data.get('additional_data')

    # Check if data exists and has quotes
    if additional_data and '"' in additional_data:
        parts = additional_data.split('"')
        if len(parts) > 1:
            item_name = parts[1] # Get the text between the quotes
            
    if serialization_required:
        return f"# Part List for: {item_name} \n**Serial:** ```{original_code}```\n**Component String:** ```{item_code}```\n```\n{part_list_str}\n```"
    else:
        return f"**Part List for:** ```{original_code}```\n```\n{part_list_str}\n```"

async def possible_parts_driver(db_pool, manufacturer: str, weapon_type: str, part_type: str) -> str:
    """
    Async driver that accepts all dependencies.
    """

    # This function is now async
    part_list_str = await query_possible_parts(db_pool, manufacturer, weapon_type, part_type)
    formatted_response = f'ID: {str("Part String").ljust(30)}: Requirements : Stats : Effects\n\n'
    for part in part_list_str:
        line = f"{part[0]:<2}: {part[1]:<30}: {str(part[3]):<13}: {str(part[2]):<6}: {part[4]}\n"
        formatted_response = formatted_response + '\n' + line
    
    return f"# {manufacturer} {part_type} for {weapon_type}s\n```{formatted_response}```"