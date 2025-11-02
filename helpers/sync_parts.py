# File: helpers/sync_parts.py
import aiohttp
import asyncio # <-- NEW
import asyncpg
import psycopg2 # <-- NEW (requires pip install psycopg2-binary)
import csv
import io
import os # <-- NEW (for DB details)

# --- Configuration (Constants) ---
# The Google Sheet URL for the CSV export
CSV_URL = "https://docs.google.com/spreadsheets/d/17LHzPR7BltqgzbJZplr-APhORgT2PTIsV08n4RD3tMw/export?format=csv&gid=1178633367"
TABLE_NAME = "part_list"

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