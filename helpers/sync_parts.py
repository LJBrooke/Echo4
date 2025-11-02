# File: helpers/sync_parts.py
import aiohttp
import asyncpg
import csv
import io

# --- Configuration (Constants) ---
# The Google Sheet URL for the CSV export
CSV_URL = "https://docs.google.com/spreadsheets/d/17LHzPR7BltqgzbJZplr-APhORgT2PTIsV08n4RD3tMw/export?format=csv&gid=1178633367"
TABLE_NAME = "part_list"

async def sync_part_sheet(session: aiohttp.ClientSession, db_pool: asyncpg.Pool) -> str:
    """
    Downloads the Google Sheet CSV and syncs it with the 'part_list' table.
    
    This function will:
    1. Truncate (clear) the existing table.
    2. Download the fresh CSV data.
    3. Bulk-load the new data using COPY.
    
    Returns:
        A string summarizing the result of the operation.
    """
    
    try:
        # --- 1. Download the CSV data (Async) ---
        print(f"Sync: Downloading data from Google Sheet...")
        async with session.get(CSV_URL) as response:
            response.raise_for_status() # Raise an exception for bad status codes
            csv_data_string = await response.text()

        # --- 2. Process the CSV data ---
        # We use io.StringIO to treat the string as an in-memory file.
        # This requires no "cleanup," as it's not a real file on disk.
        f = io.StringIO(csv_data_string)
        
        # Use the csv module to parse the data
        reader = csv.reader(f)
        
        # Get the header row (column names) from the CSV
        header = next(reader)
        # Get the rest of the data as a list of tuples/lists
        # File: helpers/sync_parts.py

        records = list(reader)

        if not records:
            return "Sync Failed: Downloaded data was empty."
            
        # --- FINAL SURGICAL DATA CLEANING FIX (ID at Index 2) ---
        cleaned_records = []
        for row in records:
            cleaned_row = []
            
            # 1. Process the entire row up to the ID column (Indices 0 and 1)
            # These are TEXT columns.
            for i in range(2): # Process indices 0 and 1
                cell = row[i] if len(row) > i else None
                
                if cell is None:
                    cleaned_row.append(None)
                    continue
                    
                stripped_cell = str(cell).strip()
                cleaned_row.append(stripped_cell if stripped_cell else None)

            # 2. Process the ID column (Index 2)
            # This is the INTEGER column.
            id_cell = row[2] if len(row) > 2 else None # <--- Your corrected line
            
            if id_cell:
                stripped_id = str(id_cell).strip()
                # Check if it's a valid integer string. If not, convert to None (NULL).
                cleaned_id = stripped_id if stripped_id.isdigit() else None
            else:
                cleaned_id = None
            
            cleaned_row.append(cleaned_id)
            
            # 3. Process all remaining columns (Index 3 onwards)
            # These are all TEXT columns.
            for cell in row[3:]:
                if cell is None:
                    cleaned_row.append(None)
                    continue
                    
                stripped_cell = str(cell).strip()
                cleaned_row.append(stripped_cell if stripped_cell else None)

            cleaned_records.append(cleaned_row)
        
        if not records:
            return "Sync Failed: Downloaded data was empty."
        
        print(f"Sync: Downloaded {len(records)} rows. Connecting to database...")

        # --- 3. Database Operation (Async) ---
        async with db_pool.acquire() as conn:
            # Use a transaction for safety. It's all-or-nothing.
            async with conn.transaction():
                
                # Request 1: Clear the table before writing
                print(f"Sync: Clearing table '{TABLE_NAME}'...")
                await conn.execute(f"TRUNCATE TABLE {TABLE_NAME} RESTART IDENTITY")
                
                # Request 2: Load new data
                print(f"Sync: Loading new data...")
                await conn.copy_records_to_table(
                    TABLE_NAME,
                    records=cleaned_records,
                    timeout=120.0    # Give it 2 minutes
                )

        success_message = f"✅ Sync complete. Successfully loaded {len(records)} rows into '{TABLE_NAME}'."
        print(success_message)
        return success_message

    except aiohttp.ClientError as e:
        error_msg = f"❌ Sync Failed: Error downloading file. {e}"
        print(error_msg)
        return error_msg
    except asyncpg.exceptions.PostgresError as e:
        error_msg = f"❌ Sync Failed: Database error. {e}"
        print(error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"❌ Sync Failed: An unexpected error occurred. {e}"
        print(error_msg)
        return error_msg