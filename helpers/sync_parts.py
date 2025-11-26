# File: helpers/sync_parts.py
import aiohttp
import asyncio
import asyncpg
import psycopg2
import io
import os
import re
from typing import List, Tuple
from xml.etree import ElementTree
# import asyncio, aiohttp, etc. (already in your async function)
# LEMON_TABLE and other constants need to be defined outside this snippet

# --- Configuration (Constants) ---
# The Google Sheet URL for the CSV export
LEMON_URL = "https://www.lootlemon.com/sitemap.xml"
LEMON_TABLE = "lootlemon_urls"
CSV_URL = "https://docs.google.com/spreadsheets/d/17LHzPR7BltqgzbJZplr-APhORgT2PTIsV08n4RD3tMw/export?format=csv&gid=1178633367"
TABLE_NAME = "part_list"

GAME_CODES = {'bl1', 'bl2', 'bl3', 'bl4', 'wl', 'tps'} 

def _sync_core(csv_data_string: str, db_host: str, db_name: str, db_user: str, db_pass: str) -> int:
    """
    Synchronous core function that connects via psycopg2 and uses COPY.
    """
    conn = None
    try:
        # 1. Connect to the PostgreSQL database (Synchronous)
        conn = psycopg2.connect(
            host=db_host,
            dbname=db_name,
            user=db_user,
            password=db_pass
        )
        # We need a cursor for copy_expert
        cur = conn.cursor() 

        # 2. Clear the table and run COPY (Synchronous)
        cur.execute(f"TRUNCATE TABLE {TABLE_NAME} RESTART IDENTITY;")
        
        f = io.StringIO(csv_data_string)

        # Skip the header row so COPY can handle it natively
        next(f) 
        
        # Use copy_expert with the native COPY command
        cur.copy_expert(
            sql=f"COPY {TABLE_NAME} FROM STDIN WITH (FORMAT csv)", # HEADER=TRUE is removed as we skip it
            file=f
        )

        conn.commit()
        return cur.rowcount

    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        raise e # Re-raise error to be caught by the async wrapper
    finally:
        if conn:
            conn.close()

def _get_url_parts(url: str) -> Tuple[str, str, str]:
    """
    Extracts item_type, url_stub, and game code from a lootlemon URL.
    
    The URL format is generally: 
    'https://www.lootlemon.com/{item_type}/{url_stub}'
    e.g., 'https://www.lootlemon.com/bonus-item/x-y-combo-bl4'
    """
    try:
        # 1. Clean up URL and split by '/'
        # We only care about the path part of the URL (everything after .com/)
        path_parts = url.split('.com/', 1)[1].split('/')
        
        # 2. Extract item_type (penultimate part) and url_stub (last part)
        # Assuming format is always at least {item_type}/{url_stub}
        if len(path_parts) < 2:
             # Handle unexpected URL structure gracefully
             raise ValueError(f"URL format unexpected: {url}")
             
        item_type = path_parts[-2]
        url_stub = path_parts[-1]

        # 3. Extract game code from the url_stub (e.g., bl4)
        # Use regex to find one of the known codes at the end of the stub
        # The pattern looks for a hyphen followed by a game code (bl1/bl2/etc.) at the end of the string.
        match = re.search(r'-(' + '|'.join(GAME_CODES) + r')$', url_stub)
        game = match.group(1) if match else "unknown" # Use "unknown" or similar placeholder if no code found

        return game, item_type, url_stub
        
    except Exception as e:
        print(f"Warning: Could not parse URL: {url}. Error: {e}")
        # Return empty data to be filtered out later or a sentinel value
        return None, None, None


def _sync_lemon(
    xml_data_string: str,
    db_host: str,
    db_name: str,
    db_user: str,
    db_pass: str
) -> int:
    
    # ... (XML parsing setup remains the same) ...
    root = ElementTree.fromstring(xml_data_string)
    ns = {'sitemap': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    
    rows: List[Tuple[str, str, str]] = []
    
    # Set to track duplicates
    seen_stubs = set()

    for url_element in root.findall('sitemap:url', ns):
        loc_element = url_element.find('sitemap:loc', ns)
        if loc_element is not None and loc_element.text:
            url = loc_element.text
            game, item_type, url_stub = _get_url_parts(url)
            
            # CHECK 1: Ensure parsing worked
            if not all([game, item_type, url_stub]):
                continue

            # CHECK 2: Filter out "unknown" games
            # The error 'class-mods' suggests you are picking up category pages 
            # that don't have the specific game suffix (e.g. -bl4). 
            # If you ONLY want game items, keep this check:
            if game == "unknown":
                continue 

            # CHECK 3: Deduplicate
            # If we have already processed this url_stub, skip it to avoid PK violation
            if url_stub in seen_stubs:
                continue
            
            seen_stubs.add(url_stub)
            rows.append((game, item_type, url_stub))
    
    # 2. Prepare data for insertion (psycopg2 COPY FROM)
    # The COPY command is the fastest way to insert large amounts of data.
    
    # The data needs to be a file-like object; we use io.StringIO for in-memory data.
    data_stream = io.StringIO()
    for row in rows:
        # Format the row as a tab-separated line (default for copy_from)
        # Note: psycopg2.extensions.adapt is safer for real-world data 
        # but for simple stubs/types, this should be fine.
        data_stream.write('\t'.join(row) + '\n')
    data_stream.seek(0)
    
    # 3. Database Connection and Insertion
    conn = None
    rows_inserted = 0
    try:
        # Establish connection
        conn = psycopg2.connect(
            host=db_host,
            database=db_name,
            user=db_user,
            password=db_pass
        )
        cur = conn.cursor()
        
        # Truncate/Clear the table before inserting new data
        cur.execute(f"TRUNCATE TABLE {LEMON_TABLE} RESTART IDENTITY;")
        
        # Execute COPY FROM STDIN
        cur.copy_from(
            file=data_stream,
            table=LEMON_TABLE,
            columns=('game', 'item_type', 'url_stub'),
            sep='\t' # Must match the separator used above
        )
        
        rows_inserted = cur.rowcount
        
        # Commit the transaction
        conn.commit()
        
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        raise e # Re-raise to be caught by the async driver
    finally:
        if conn:
            conn.close()
            
    return rows_inserted

# -------------------------------------------------------------
# ASYNCHRONOUS ENTRYPOINT
# -------------------------------------------------------------
async def sync_part_sheet(session: aiohttp.ClientSession, db_pool: asyncpg.Pool) -> str:
    """
    Async driver that coordinates download and safe synchronous database sync.
    """
    try:
        # 2. Download the CSV data (Async, non-blocking)
        print(f"Sync: Downloading data from Google Sheet...")
        async with session.get(CSV_URL) as response:
            response.raise_for_status()
            csv_data_string = await response.text()
            
        # 3. Execute the synchronous core logic in a separate thread
        print(f"Sync: Running blocking database operation...")
        db_host = os.getenv("DATABASE_HOST")
        db_name = os.getenv("DATABASE_NAME")
        db_user = os.getenv("DATABASE_USER")
        db_pass = os.getenv("DATABASE_PWD")
        
        # NOTE: This is the critical change: Use asyncio.to_thread()
        rows_synced = await asyncio.to_thread(
            _sync_core, 
            csv_data_string, 
            db_host, 
            db_name, 
            db_user, 
            db_pass
        )

        success_message = f"✅ Sync complete. Successfully loaded {rows_synced} rows into '{TABLE_NAME}'."
        print(success_message)
        return success_message

    except aiohttp.ClientError as e:
        return f"❌ Sync Failed: Error downloading file: {e}"
    except psycopg2.Error as e:
        return f"❌ Sync Failed: Database error during COPY: {e}"
    except Exception as e:
        return f"❌ Sync Failed: An unexpected error occurred: {e}"

async def sync_lemons(session: aiohttp.ClientSession) -> str:
    """
    Async driver that coordinates download and safe synchronous database sync.
    """
    try:
        # 2. Download the CSV data (Async, non-blocking)
        print(f"Sync: Downloading data from Lootlemon...")
        async with session.get(LEMON_URL) as response:
            response.raise_for_status()
            xml_data_string = await response.text()
            
        # 3. Execute the synchronous core logic in a separate thread
        print(f"Sync: Running blocking database operation...")
        db_host = os.getenv("DATABASE_HOST")
        db_name = os.getenv("DATABASE_NAME")
        db_user = os.getenv("DATABASE_USER")
        db_pass = os.getenv("DATABASE_PWD")
        
        # NOTE: This is the critical change: Use asyncio.to_thread()
        rows_synced = await asyncio.to_thread(
            _sync_lemon, 
            xml_data_string, 
            db_host, 
            db_name, 
            db_user, 
            db_pass
        )

        success_message = f"✅ Sync complete. Successfully loaded {rows_synced} rows into '{TABLE_NAME}'."
        print(success_message)
        return success_message

    except aiohttp.ClientError as e:
        return f"❌ Sync Failed: Error downloading file: {e}"
    except psycopg2.Error as e:
        return f"❌ Sync Failed: Database error during COPY: {e}"
    except Exception as e:
        return f"❌ Sync Failed: An unexpected error occurred: {e}"