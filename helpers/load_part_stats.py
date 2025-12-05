import aiohttp
import asyncpg
from bs4 import BeautifulSoup
import json
from typing import List, Dict, Any

# --- Configuration ---
TARGET_URL = "https://borderlands.be/complete_parts_viewer.html"

# --- Pure Utility Functions ---
# (These remain the same as they are structural/pure data logic)

def parse_value(value_str):
    """Attempts to convert string values to numbers if possible."""
    value_str = value_str.strip()
    try:
        if '.' in value_str:
            return float(value_str)
        return int(value_str)
    except ValueError:
        return value_str

def parse_stats_container(container):
    """
    Recursively parses a container to extract key-value pairs.
    """
    stats = {}
    stat_rows = container.find_all('div', class_='stat-row', recursive=False)
    
    for row in stat_rows:
        name_tag = row.find('span', class_='stat-name')
        value_tag = row.find('span', class_='stat-value')
        
        if not name_tag or not value_tag:
            continue
            
        key = name_tag.get_text(strip=True).rstrip(':')
        raw_value = value_tag.get_text(strip=True)
        
        if raw_value == '[Object]':
            nested_div = row.find_next_sibling('div', class_='nested-stats')
            stats[key] = parse_stats_container(nested_div) if nested_div else {}
        else:
            stats[key] = parse_value(raw_value)
            
    return stats

def is_header_card(part_name):
    """
    Determines if a part card is actually a section divider/header.
    """
    name = part_name.strip()
    return (
        name.endswith('_Init') or 
        name.startswith('Unique_') or 
        name.endswith('_Table') or
        name.startswith('Weapon_')
    )

# -----------------------------------------------------------------
# CORE REFACTORED LOGIC: Contains all website structure dependence
# -----------------------------------------------------------------

async def scrape_parts_data(html_content) -> List[Dict[str, Any]]:
    """
    Scrapes the raw HTML content and extracts structured data for each part.
    This function is the primary target for adjustments if the website changes.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Select both headers and part-cards to track the flow
    elements = soup.find_all(lambda tag: 
        (tag.name == 'div' and 'part-card' in tag.get('class', [])) or 
        (tag.name == 'h2' and 'report-title' in tag.get('class', []))
    )
    
    parts_data = []
    current_category = "General"

    for elem in elements:
        if elem.name == 'h2':
            # Update category from H2 headers
            current_category = elem.get_text(strip=True).split(' ')[0]
            continue

        # If it's a part-card
        try:
            name_div = elem.find('div', class_='part-name')
            part_name = name_div.get_text(strip=True) if name_div else "Unknown"

            if is_header_card(part_name):
                current_category = part_name
                
            number_label = elem.find('span', class_='number-label')
            part_number_text = number_label.get_text(strip=True).replace('#', '') if number_label else None
            
            if not part_number_text or not part_number_text.isdigit():
                continue
                
            part_number = int(part_number_text)
            stats_data = parse_stats_container(elem)

            parts_data.append({
                'part_number': part_number,
                'part_name': part_name,
                'part_type': current_category,
                'stats': stats_data # Keep as dict/list structure
            })
            
        except Exception as e:
            # Report parsing errors but continue
            print(f"Error parsing element in scrape_parts_data for {part_name}: {e}")
            continue
            
    return parts_data


# -----------------------------------------------------------------
# MAIN ASYNC LOGIC: Handles I/O (Web/DB) and is structure-agnostic
# -----------------------------------------------------------------

async def sync_parts(session: aiohttp.ClientSession, db_pool: asyncpg.Pool):
    """
    Asynchronously coordinates the web scrape and database load.
    """
    try:
        # 1. Fetch Data
        print(f"Fetching data from {TARGET_URL}...")
        async with session.get(TARGET_URL) as response:
            response.raise_for_status()
            html_content = await response.text()
            print("Data fetched successfully.")

        # 2. Scrape/Parse Data
        parts_to_insert = await scrape_parts_data(html_content)
        
        if not parts_to_insert:
             return "⚠️ **Warning!** Scraping returned no parts. Database sync skipped."

        print(f"Scraped {len(parts_to_insert)} unique part records.")
        
        # 3. Database Operations
        async with db_pool.acquire() as conn:
            # Start Transaction for atomicity
            async with conn.transaction():
                
                # A. Ensure Table Exists
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS weapon_parts (
                        part_number INTEGER PRIMARY KEY,
                        part_name TEXT NOT NULL,
                        part_type TEXT,
                        stats JSONB NOT NULL
                    );
                """)

                # B. Check and Truncate (Wipe-and-Load logic as requested)
                row_count = await conn.fetchval("SELECT count(*) FROM weapon_parts")
                
                if row_count and row_count > 0:
                    await conn.execute("TRUNCATE TABLE weapon_parts")
                    print(f"Truncated table, removed {row_count} old records.")
                
                # C. Prepare data for efficient executemany (list of tuples)
                # json.dumps converts the nested Python dict to a JSON string for JSONB column
                data_for_db = [
                    (p['part_number'], p['part_name'], p['part_type'], json.dumps(p['stats']))
                    for p in parts_to_insert
                ]

                # D. Insert Data using a prepared statement (still the most efficient asyncpg way)
                stmt = await conn.prepare("""
                    INSERT INTO weapon_parts (part_number, part_name, part_type, stats)
                    VALUES ($1, $2, $3, $4::jsonb)
                    ON CONFLICT (part_number) 
                    DO NOTHING
                """)
                # Using DO NOTHING since the table is fresh (truncated), 
                # but it safely handles any duplicate part_number from the source data.
                
                await stmt.executemany(data_for_db)
                
            # fetch the final count after insertion/update
            final_count = await conn.fetchval("SELECT count(*) FROM weapon_parts")

            return f"✅ **Sync Complete!** Database re-populated with **{final_count}** parts."

    except aiohttp.ClientResponseError as e:
        return f"❌ **Error fetching data!** URL responded with status code: {e.status} ({e.message})"
    except Exception as e:
        return f"❌ **An unexpected error occurred during sync:** {type(e).__name__}: {e}"