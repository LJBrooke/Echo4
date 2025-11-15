# File: helpers/item_parser.py
import re
import json
import logging
log = logging.getLogger(__name__)

# Serialization URL, Nicnl and InflamedSebi are amazing.
LOCAL_URL = 'http://borderlands-serials:8080/api/v1/'
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
    payload = {"serial_b85": serial.strip()}
    
    try: 
        endpoint = f'{LOCAL_URL}deserialize'
        # Use the async session
        async with session.post(endpoint, json=payload, timeout=5) as response:
            # This will raise an aiohttp.ClientResponseError
            # if the status code is 4xx or 5xx, which triggers the 'except' block.
            response.raise_for_status()

            # If we get here, status was 200-OK
            return await response.json()
    except:
        # Fallback to original API in case local is down.
        endpoint = f'{NICNL_URL}deserialize'
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
    payload = {"deserialized": component_string.strip()}
    
    try:
        endpoint = f'{LOCAL_URL}reserialize'
        # Use the async session
        async with session.post(endpoint, json=payload, timeout=5) as response:
            # This will raise an aiohttp.ClientResponseError
            # if the status code is 4xx or 5xx, which triggers the 'except' block.
            response.raise_for_status()

            # If we get here, status was 200-OK
            return await response.json()
    except:
        # Fallback to original API in case local is down.
        endpoint = f'{NICNL_URL}reserialize'
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
    
    return result.get('part_string') if result else None

async def query_type(db_pool, id: int) -> list[str]:
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
    return result.get('item_type'), result.get('manufacturer') if result else None

async def query_element_id(db_pool, primary: str, secondary: str, Maliwan: bool) -> str:
    """
    Uses the async asyncpg pool to fetch a single element part id.
    Args:
        db_pool: The bot's asyncpg.Pool
    """
    query = f"""
    SELECT id 
    FROM element_list 
    WHERE lower(primary_element) = lower('{primary}')
    and underbarrel is {Maliwan}"""

    if secondary is None: query=query + ' and secondary_element is null'
    else: query=query + f" and lower(secondary_element) =lower('{secondary}')"    
    print(query)
    # Use 'with pool.acquire()' to get a connection
    async with db_pool.acquire() as conn:
        result = await conn.fetchrow(query)
    print(result.get('id'))
    return '{1:'+str(result.get('id'))+'}' if result else None

async def query_elements_by_id(db_pool, element_token: str) -> tuple[str | None, str | None]:
    """
    Uses the async asyncpg pool to fetch a single element part id.
    Args:
        db_pool: The bot's asyncpg.Pool
    """
    
    # Extract the ID from the token: '{1:12}' -> '12'
    id_str = element_token.strip()[1:-1].split(':')[1]
    
    query = """
    SELECT 
        primary_element, 
        secondary_element 
    FROM element_list 
    WHERE id = $1"""

    async with db_pool.acquire() as conn:
        # Pass the ID as an integer parameter for safety and correctness
        result = await conn.fetchrow(query, int(id_str))
        
    if result:
        # Returns the primary element and the secondary element (if one exists in that row)
        return result.get('primary_element'), result.get('secondary_element')
    else:
        # Default to Kinetic if the ID lookup fails
        return "Kinetic", None

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
        part_type,
        id,
        stats,
        effects
    FROM part_list 
    WHERE 
        id = ANY($1) AND
        lower(weapon_type) = lower($2) AND 
        lower(Manufacturer) = lower($3)
    """

    async with db_pool.acquire() as conn:
        results = await conn.fetch(query, part_list, Weapon_Type, Manufacturer)

    return results # Returns a list of Record objects

async def query_part_by_string(db_pool, manufacturer: str, weapon_type: str, part_string: str) -> dict | None:
    """
    Fetches a single part record by its exact part_string.
    Args:
        db_pool: The bot's asyncpg.Pool
    """
    query = """
    SELECT
        id,
        part_string, 
        part_type,
        stats,
        effects
    FROM part_list 
    WHERE 
        part_string = $1 AND 
        lower(weapon_type) = lower($2) AND 
        lower(manufacturer) = lower($3)
    """
    async with db_pool.acquire() as conn:
        # Use fetchrow and pass parameters safely
        result = await conn.fetchrow(query, part_string, weapon_type, manufacturer)
    
    # asyncpg.Record supports dict-like access
    return dict(result) if result else None

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
        lower(part_type) = lower($1) AND 
        lower(weapon_type) = lower($2) AND 
        lower(manufacturer) = lower($3)
    """
    async with db_pool.acquire() as conn:
        results = await conn.fetch(query, Part_Type, Weapon_Type, Manufacturer)
    
    return results # Returns a list of Record objects

async def get_compatible_parts(db_pool, Manufacturer: str, Weapon_Type: str, Part_Type: str) -> list:
    """
    Uses the async asyncpg pool to fetch all compatible parts,
    including re-classified 'Manufacturer Part' entries.
    
    Args:
        db_pool: The bot's asyncpg.Pool
        Manufacturer (str): Weapon Manufacturer
        Weapon_Type (str): Weapon Type
        Part_Type (str): The *functional* part type being requested
    """
    
    # We will build a dynamic WHERE clause for the part_type
    
    # $1 = Part_Type, $2 = Weapon_Type, $3 = Manufacturer
    params = [Part_Type, Weapon_Type, Manufacturer]
    
    # Base condition: The part_type in the DB matches the one requested
    part_type_conditions = [f"lower(part_type) = lower($1)"]
    
    # --- Add 'Manufacturer Part' logic based on the requested Part_Type ---
    
    if Part_Type == "Body Accessory":
        part_type_conditions.append(
            "(lower(part_type) = 'manufacturer part' AND part_string LIKE '%.part_shield_%')"
        )
    elif Part_Type == "Magazine":
        part_type_conditions.append(
            "(lower(part_type) = 'manufacturer part' AND part_string LIKE '%.part_mag_torgue_%')"
        )
    elif Part_Type == "Barrel Accessory":
        part_type_conditions.append(
            "(lower(part_type) = 'manufacturer part' AND part_string LIKE '%.part_barrel_licensed_%')"
        )
    elif Part_Type == "Stat Modifier":
        # This is the complex "fallback" logic from your _get_true_part_type
        part_type_conditions.append(
            """(
                lower(part_type) = 'manufacturer part' AND 
                (
                    part_string LIKE '%.part_secondary_ammo_%' OR
                    (
                        part_string NOT LIKE '%.part_shield_%' AND
                        part_string NOT LIKE '%.part_mag_torgue_%' AND
                        part_string NOT LIKE '%.part_barrel_licensed_%'
                    )
                )
            )"""
        )
    
    # Combine all part logic (e.g., "(part_type = 'Barrel')")
    # or "(part_type = 'Barrel Accessory' OR (part_type = 'Manufacturer Part' AND ...))"
    combined_part_logic = f"({' OR '.join(part_type_conditions)})"
    
    # Build the final query
    query = f"""
    SELECT
        id,
        part_string, 
        stats,
        requirements,
        effects
    FROM part_list 
    WHERE 
        lower(weapon_type) = lower($2) AND 
        lower(manufacturer) = lower($3) AND
        {combined_part_logic}
    Order by part_string
    """
    
    async with db_pool.acquire() as conn:
        results = await conn.fetch(query, *params)
    
    return results

async def query_element(db_pool, element_list: list) -> list:
    """
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

async def query_shield_perks(db_pool, part_type: str, perk_ids: list[int]) -> list:
    """
    Fetches the full perk details from the shield_parts table.

    Args:
        db_pool: The bot's asyncpg.Pool
        part_type (str): The type of perk ('General', 'Energy', 'Armor').
        perk_ids (list[int]): A list of perk IDs to query.
    
    Returns:
        A list of asyncpg.Record objects, e.g.:
        [{'id': 7, 'name': 'Baker', 'perk_type': 'Firmware'}]
    """
    if not perk_ids:
        return []

    query = f"""
    SELECT
        id,
        name,
        perk_type
    FROM shield_parts 
    WHERE 
        lower(shield_type) = lower($1) AND
        id = ANY($2)
    ORDER BY
        id
    """

    async with db_pool.acquire() as conn:
        # $1 = part_type, $2 = perk_ids
        results = await conn.fetch(query, part_type, perk_ids)

    # Return the full list of Record objects
    return results

async def query_unique_shield(db_pool, manufacturer: str, perk_id: int) -> list:
    """
    Fetches the unique shields name and perk from the unique_shields table.

    Args:
        db_pool: The bot's asyncpg.Pool
        manufacturer (str): The shield Manufacturer.
        perk_id (int): The unique perks id.
    
    Returns:
        A list of asyncpg.Record objects, e.g.:
        [{'id': 7, 'name': 'Baker', 'perk_type': 'Firmware'}]
    """
    if not perk_id or not manufacturer:
        return []

    query = f"""
    select 
        unique_perk, 
        shield_name
    from unique_shields
    where 
        lower(manufacturer)=lower($1)
        and id = $2
    """

    async with db_pool.acquire() as conn:
        # $1 = part_type, $2 = perk_ids
        results = await conn.fetch(query, manufacturer, perk_id)

    # Return the full list of Record objects
    return results

async def query_repkit_perks(db_pool, perk_ids: list[int]) -> list:
    """
    Fetches the full perk details from the repkit_parts table.
    """
    if not perk_ids:
        return []

    query = f"""
    SELECT
        id,
        name,
        perk_type,
        description
    FROM repkit_parts 
    WHERE 
        id = ANY($1)
    ORDER BY
        name
    """
    async with db_pool.acquire() as conn:
        results = await conn.fetch(query, perk_ids)
    return results

async def query_unique_repkit(db_pool, manufacturer: str, perk_id: int) -> list:
    """
    Fetches the unique repkit name and effect from the unique_repkits table.
    """
    if not perk_id or not manufacturer:
        return []

    query = f"""
    SELECT 
        unique_perk, 
        repkit_name,
        repkit_effect
    FROM unique_repkits
    WHERE 
        lower(manufacturer)=lower($1)
        AND id = $2
    """
    async with db_pool.acquire() as conn:
        results = await conn.fetch(query, manufacturer, perk_id)
    return results

async def query_clanker_response(db_pool) -> str:
    """Fetches a random response from the clanker_responses table."""
    query = "SELECT response FROM clanker_responses ORDER BY RANDOM() LIMIT 1"
    try:
        # Use fetchval to get the first column of the first row directly
        response = await db_pool.fetchval(query)
        if response:
            return response
        return "Clanker!" # Fallback if table is empty
    except Exception as e:
        log.error(f"Failed to query clanker response: {e}")
        return "Clanker... (error)" # Fallback on DB error
    
async def log_item_edit(
    db_pool,
    session_id: str,
    user_id: int,
    edit_type: str,
    item_name: str = None,
    item_type: str = None,
    manufacturer: str = None,
    serial: str = None,
    component_string: str = None,
    parts_json: dict = None
    ) -> int | None:
    """
    Inserts a record into the item_edit_history table.

    Args:
        db_pool: The asyncpg.Pool object.
        session_id (str): The unique ID for this editing session (e.g., interaction.id).
        user_id (int): The discord.User.id of the user.
        edit_type (str): The type of edit (e.g., 'PART', 'LEVEL', 'ELEMENT').
        item_name (str, optional): The in-game name of the item.
        item_type (str, optional): The item's base type (e.g., 'Pistol', 'Shield').
        manufacturer (str, optional): The item's manufacturer.
        serial (str, optional): The new serial generated after the edit.
        component_string (str, optional): The component string for the new serial.
        parts_json (dict, optional): A dictionary of the item's current parts.
                                     asyncpg handles Python dict -> JSONB conversion.

    Returns:
        The integer ID of the newly inserted row, or None if insertion fails.
    """
    query = """
    INSERT INTO item_edit_history (
        session_id, user_id, edit_type,
        item_name, item_type, manufacturer,
        serial, component_string, parts_json
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
    RETURNING id;
    """
    parts_json_string = json.dumps(parts_json) if parts_json is not None else None
    try:
        async with db_pool.acquire() as conn:
            # Pass the Python dict (or None) directly for parts_json
            # asyncpg will serialize it to JSONB
            new_id = await conn.fetchval(
                query,
                session_id,
                user_id,
                edit_type,
                item_name,
                item_type,
                manufacturer,
                serial,
                component_string,
                parts_json_string 
            )
            log.info(f"Successfully logged item edit for user {user_id}. New history ID: {new_id}")
            return new_id
    except Exception as e:
        log.error(f"Failed to log item edit to history table for user {user_id}: {e}", exc_info=True)
        return None
    
async def query_edit_history(
    db_pool,
    edit_type: str,
    search_term: str,
    part_filter: str = None
    ) -> list:
    """
    Searches the item_edit_history table.

    Args:
        db_pool: The asyncpg.Pool object.
        edit_type (str): The edit_type to filter by (e.g., 'FINALIZE').
        search_term (str): A string to search for in item_name or parts_json.
        part_filter (str, optional): A second string to filter by *within* parts_json.

    Returns:
        A list of asyncpg.Record objects (serial, parts_json) or an empty list.
    """
    params = []
    
    # --- Build the query dynamically ---
    query = """
    SELECT item_name, serial, parts_json
    FROM item_edit_history
    WHERE
        edit_type = $1
    """
    params.append(edit_type)
    
    # Param $2: The main search_term
    # We add '%' for wildcard matching
    search_term_like = f"%{search_term}%"
    query += " AND (item_name ILIKE $2 OR parts_json::text ILIKE $2)"
    params.append(search_term_like)

    # Param $3 (Optional): The specific part_filter
    if part_filter:
        part_filter_like = f"%{part_filter}%"
        # This adds an additional filter, both must be true.
        query += " AND (parts_json::text ILIKE $3)"
        params.append(part_filter_like)
        
    query += " ORDER BY timestamp DESC LIMIT 10"
    
    try:
        async with db_pool.acquire() as conn:
            results = await conn.fetch(query, *params)
            return results
    except Exception as e:
        log.error(f"Failed to search edit history: {e}", exc_info=True)
        return []

# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# LOGIC FUNCTIONS
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

def format_part_name(part_string: str) -> str:
    """
    Converts a raw part_string (e.g., 'MAN_WP.part_barrel_01')
    into a human-readable name (e.g., 'Barrel 01').
    """
    if not part_string:
        return "Unknown Part"
    
    # Find the 'part_' substring
    marker = 'part_'
    part_index = part_string.find(marker)
    
    if part_index == -1:
        # Fallback if 'part_' isn't in the string
        return part_string.replace('_', ' ').title()

    # Get the substring after 'part_' (e.g., 'barrel_01_a')
    name_part = part_string[part_index + len(marker):]
    
    # Replace underscores and title case (e.g., 'Barrel 01 A')
    return name_part.replace('_', ' ').title()

def split_item_str(item_str: str) -> list[str, int, list[int]]:
    base_aspect, part_aspect = item_str.split('||')
    base = base_aspect.split('|')[0]
    item_type, base_0, base_1, level = base.split(', ')
    parts =part_aspect.split('|')[0]
    skin = part_aspect.split('|')[1:]

    # The regex pattern:
    # r"\{"  -> Matches a literal {
    # ".*?" -> Matches any character (.), 0 or more times (*), non-greedily (?)
    # r"\}"  -> Matches a literal }
    pattern = r"\{.*?\}"
    part_list = re.findall(pattern, parts)
    
    return item_type, level, part_list
    
async def create_part_and_element_list(db_pool, part_list: list) -> list[list]:
    int_part_list = []
    int_ele_list = []
    
    for part in part_list:
        if ':' not in part:
            int_part_list.append(int(part.strip()[1:-1]))
        elif ':' in part:
            # print(part)
            ele_part = str(part[1:-1]).split(':')
            if int(ele_part[0]) == 1:
                int_ele_list.append(int(ele_part[1]))
    elements = await query_element(db_pool, int_ele_list)
    
    return int_part_list, elements

async def get_button_dict(db_pool: str, session, item_serial: str) -> dict:
    item_components = deserialize(session, item_serial)
    item_type, level, part_list = split_item_str(item_components)
    type, manufacturer = query_type(db_pool, item_type)
    if type.lower() in ["assault rifle", "pistol", "smg", "shotgun", "sniper"]:
        return 1 # Wrapping function must return this as an item type unsupported error
    parts, elements = create_part_and_element_list(db_pool, part_list)
    part_dict = query_part_list(db_pool, manufacturer, type, parts)
    
    # TODO FINISH THIS FUNC
    return part_dict
    

async def compile_part_list(db_pool, item_code: str) -> str:
    """
    Compiles a part list, calling async DB functions.
    :param db_pool: The bot's asyncpg.Pool
    """
    try:
        item_type, level, part_list = split_item_str(item_code)
        
        type, manufacturer = await query_type(db_pool, int(item_type))
        if type not in ['pistol', 'shotgun', 'assault_rifle', 'smg', 'sniper']:
            return "Sorry, only weapons are supported currently"

        int_part_list, elements = await create_part_and_element_list(db_pool, part_list)
        print(int_part_list)
        # This function is now async, so we must 'await' it
        str_part_list = await query_part_list(
            db_pool, 
            manufacturer, 
            type, 
            int_part_list
        )
        
        formatted_response = ''
        for element in elements:
            if element[1] is None:
                formatted_response = formatted_response+ f'Primary Element: {element[0]}\n'
            else: formatted_response = formatted_response+ f'Secondary Element: {element[1]}\n\n'
        for part in str_part_list:
            # 'part' is now an asyncpg.Record, access by key
            line = f"- {str(part.get('id')):<3}: {part.get('part_string').ljust(50)}"
            if part.get('stats') and len(part.get('stats')) > 0:
                line += part.get('stats')
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
    formatted_response = f'ID: {str("Part String").ljust(30)}: Stats : Effects\n\n'
    # formatted_response = f'ID: {str("Part String").ljust(30)}: Requirements : Stats : Effects\n\n'
    for part in part_list_str:
        line = f"{part[0]:<2}: {part[1]:<30}: {str(part[2]):<6}: {part[4]}\n"
        # line = f"{part[0]:<2}: {part[1]:<30}: {str(part[3]):<13}: {str(part[2]):<6}: {part[4]}\n"
        formatted_response = formatted_response + '\n' + line
    
    return f"# {manufacturer} {part_type} for {weapon_type}s\n```{formatted_response}```"