import os
import json
import asyncio
import gspread
from gspread_formatting import *
from datetime import timedelta
from functools import lru_cache

# Configuration
SPREADSHEET_ID = "1i8vUUNKiIjoqlKnT1EpEzxjrl90988fVfTzR2d-44HY" 
JSON_CREDENTIALS = "g_account_access.json"

class TimeTrialsSheets:
    # CONFIGURATION: Define which activities belong to which Tab.
    # Only list the BASE activity name (e.g., "Vault 1"). 
    # The code automatically handles splitting it into "True" and "Standard" tables.
    ACTIVITY_GROUPS = {
        "Raid Bosses": ["Bloomreaper"], 
        "Vaults": ["Vault of Radix", "Vault of Inceptus", "Vault of Origo", "Vault Marathon"] 
    }

    def __init__(self, db_pool):
        self.db_pool = db_pool
        # self.gc = gspread.service_account(filename=JSON_CREDENTIALS)
        # self.sheet = self.gc.open_by_key(SPREADSHEET_ID)
        creds_env = os.getenv("GOOGLE_CREDS_JSON")
    
        creds_dict = json.loads(creds_env)
        self.gc = gspread.service_account_from_dict(creds_dict)
            
        self.sheet = self.gc.open_by_key(SPREADSHEET_ID)

    def _format_time(self, td: timedelta) -> str:
        total_seconds = int(td.total_seconds())
        minutes = total_seconds // 60
        seconds = td.total_seconds() % 60
        return f"{minutes}:{seconds:05.2f}"

    @lru_cache(maxsize=32)
    def hex_to_color(self, hex_code: str) -> Color:
        hex_code = hex_code.lstrip('#')
        r = int(hex_code[0:2], 16)
        g = int(hex_code[2:4], 16)
        b = int(hex_code[4:6], 16)
        return Color(red=r/255.0, green=g/255.0, blue=b/255.0)

    async def update_leaderboard(self, activity_name: str):
        """
        Entry point. 
        - Pass "ALL" to update every tab in ACTIVITY_GROUPS.
        - Pass specific name (e.g. "Vault 1") to update the "Vaults" tab.
        """
        # 1. Wildcard: Update EVERYTHING
        if activity_name == "ALL":
            for sheet_name, activities in self.ACTIVITY_GROUPS.items():
                await self._process_sheet_group(sheet_name, activities)
            return

        # 2. Specific Activity: Find which sheet it belongs to
        target_sheet = None
        target_group = []
        
        for sheet_name, activities in self.ACTIVITY_GROUPS.items():
            if activity_name in activities:
                target_sheet = sheet_name
                target_group = activities
                break
        
        if target_sheet:
            # We must update the WHOLE group to keep the sheet consistent.
            # E.g., if updating "Vault 1", we fetch "Vault 2" as well 
            # so we can rewrite the "Vaults" tab cleanly.
            await self._process_sheet_group(target_sheet, target_group)
        else:
            print(f"Warning: Activity '{activity_name}' is not defined in ACTIVITY_GROUPS. Skipping sheet update.")

    async def _process_sheet_group(self, sheet_name: str, activities: list):
        """
        Fetches data for ALL activities in a group, then triggers the write.
        """
        sheet_payload = [] # List of tuples: (activity_name, data_tree)
        
        async with self.db_pool.acquire() as conn:
            # Prepare statement for efficiency since we run it multiple times
            stmt = await conn.prepare("""
                with records as (
                    SELECT DISTINCT ON (LOWER(runner), true_mode)
                        runner, run_time, vault_hunter, action_skill, true_mode, notes, url
                    FROM time_trials
                    WHERE activity = $1 AND uvh_level = 6
                    ORDER BY LOWER(runner), true_mode, run_time ASC )
                select * from records order by run_time
            """)
            
            for activity in activities:
                rows = await stmt.fetch(activity)
                
                # Split single DB result into True/Standard buckets
                data_tree = {
                    True: {"Amon": [], "Harlowe": [], "Rafa": [], "Vex": []},
                    False: {"Amon": [], "Harlowe": [], "Rafa": [], "Vex": []}
                }

                for row in rows:
                    mode = row['true_mode']
                    vh = row['vault_hunter']
                    if len(data_tree[mode][vh]) < 5:
                        data_tree[mode][vh].append(row)
                
                sheet_payload.append((activity, data_tree))

        # Perform the blocking IO in a thread
        await asyncio.to_thread(self._write_to_sheet, sheet_name, sheet_payload)

    def _write_category_runs(self, output_rows: list, data_tree: dict, true_mode: bool):
        """Helper to build the 8-row block for a specific mode."""
        vh_row = []
        header_row = ["Rank"]
        for vh in ["Amon", "Harlowe", "Rafa", "Vex"]:
            vh_row.extend(["", f"{vh}", "", "", ""])
            header_row.extend([f"Player", "Action Skill", "Gear/Equipment", "Time", ""]) 
        
        output_rows.append(vh_row)
        output_rows.append(header_row)
        
        for i in range(5):
            row_data = [f"#{i+1}"]
            for vh in ["Amon", "Harlowe", "Rafa", "Vex"]:
                runs = data_tree[true_mode][vh]
                if i < len(runs):
                    r = runs[i]
                    time_str = self._format_time(r['run_time'])
                    hyperlink = f'=HYPERLINK("{r["url"]}", "{time_str}")'
                    row_data.extend([r['runner'], r['action_skill'], r['notes'], hyperlink, ""])
                else:
                    row_data.extend(["-", "-", "-", "-",""])
            output_rows.append(row_data)
        return output_rows

    def _write_to_sheet(self, sheet_name: str, sheet_payload: list):
        """
        Writes multiple activities to a single sheet, stacking them vertically.
        """
        try:
            worksheet = self.sheet.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            worksheet = self.sheet.add_worksheet(title=sheet_name, rows=100, cols=20)

        worksheet.clear()
        worksheet.freeze(cols=1)
        
        output_rows = []
        formatting_jobs = [] 
        merge_request_jobs = [] 

        current_row = 1
        
        # Start at index 2 (Format 2) as requested
        if sheet_name=='Raid Bosses': color_start_index = 0
        elif sheet_name=='Vaults': color_start_index = 2
        else: color_start_index = 10

        for i, (activity_name, data_tree) in enumerate(sheet_payload):
            # Automatically cycle colors: 2, 3, 4, ...
            fmt_idx = (color_start_index + (2*i))
            
            # --- TRUE MODE ---
            output_rows.append(["", f"TRUE {activity_name.upper()} (UVH 6)"]) 
            true_start = current_row
            
            output_rows = self._write_category_runs(output_rows, data_tree, True)
            
            formatting_jobs.append((true_start, fmt_idx))
            merge_request_jobs.append(true_start)
            current_row += 8 # Title(1) + Table(7)
            
            output_rows.append([]) # Small Spacer
            current_row += 1

            # --- STANDARD MODE ---
            output_rows.append(["", f"{activity_name.upper()} (UVH 6)"]) 
            std_start = current_row
            
            output_rows = self._write_category_runs(output_rows, data_tree, False)
            
            formatting_jobs.append((std_start, fmt_idx+1)) 
            merge_request_jobs.append(std_start)
            current_row += 8 # Title(1) + Table(7)

            # --- LARGE SPACER (Between different activities) ---
            output_rows.append([])
            output_rows.append([])
            current_row += 2

        # 1. Update Values (Single API Call)
        worksheet.update(values=output_rows, range_name='A1', value_input_option='USER_ENTERED')

        # 2. Batch Metadata (Formatting + Merges in Single API Call)
        with batch_updater(self.sheet) as batch:
            # Queue formatting
            for start_row, color_idx in formatting_jobs:
                self._apply_category_formatting(worksheet, start_row, color_idx)
            
            self._apply_sheet_formatting(worksheet)
            
            # Queue merges
            all_merges = []
            for start_row in merge_request_jobs:
                all_merges.extend(self._get_merge_requests(worksheet.id, start_row))
            
            batch.requests.extend(all_merges)

    def _apply_sheet_formatting(self, worksheet: gspread.worksheet):
        set_column_widths(worksheet, [
            ('A', 40), ('B', 150), ('G', 150), ('L', 150), ('Q', 150),
            ('F', 40), ('K', 40), ('P', 40),
            ('C:D', 150), ('H:I', 150), ('M:N', 150), ('R:S', 150)
        ])

    def _apply_category_formatting(self, worksheet: gspread.worksheet, initial_row: int, format_choice: int):
        header_base = {"textFormat": textFormat(bold=True, fontSize=11), "horizontalAlignment": 'CENTER'} # type: ignore
        char_header_base = {"textFormat": textFormat(bold=True, fontSize=13), "horizontalAlignment": 'CENTER'} # type: ignore
        content_base = {"textFormat": textFormat(bold=False, fontSize=11), "horizontalAlignment": 'CENTER', "wrapStrategy": 'WRAP'} # type: ignore

        header_hexes = ["#85200c", "#990000", "#b45f06", "#bf9000", "#38761d", "#134f5c", "#1155cc", "#0b5394", "#351c75", "#741b47"]
        content_hexes = ["#cc4125", "#e06666", "#f5b26b", "#ffd966", "#95c47d", "#76a5af", "#6d9eeb", "#6fa8dc", "#8e7cc3", "#c27ba0"]

        idx = format_choice % len(header_hexes)
        header_fmt = cellFormat(backgroundColor=self.hex_to_color(header_hexes[idx]), **header_base) # type: ignore
        char_header_fmt = cellFormat(backgroundColor=self.hex_to_color(header_hexes[idx]), **char_header_base) # type: ignore
        content_fmt = cellFormat(backgroundColor=self.hex_to_color(content_hexes[idx]), **content_base) # type: ignore
        
        rank_fmt = cellFormat( # type: ignore
            backgroundColor=self.hex_to_color("#999999"), 
            textFormat=textFormat(bold=True, foregroundColor=Color(1, 1, 1)), # type: ignore
            horizontalAlignment='CENTER'
        )
        activity_header = cellFormat(backgroundColor=self.hex_to_color(header_hexes[idx]), textFormat=textFormat(bold=True, fontSize=14), horizontalAlignment='CENTER') # type: ignore
        divider_fmt = cellFormat(backgroundColor=self.hex_to_color("#00000041")) # type: ignore
        center_fmt = cellFormat(horizontalAlignment='CENTER') # type: ignore

        format_cell_ranges(worksheet, [
            (f'A{initial_row+0}:T{initial_row+0}', activity_header),
            (f'A{initial_row+1}:T{initial_row+1}', char_header_fmt),
            (f'A{initial_row+2}:T{initial_row+2}', header_fmt),
            (f'B{initial_row+1}:E{initial_row+1}', center_fmt),
            (f'G{initial_row+1}:J{initial_row+1}', center_fmt),
            (f'L{initial_row+1}:O{initial_row+1}', center_fmt),
            (f'Q{initial_row+1}:T{initial_row+1}', center_fmt),
            (f'B{initial_row+3}:T{initial_row+7}', content_fmt),
            (f'F{initial_row+0}:F{initial_row+7}', divider_fmt),
            (f'K{initial_row+0}:K{initial_row+7}', divider_fmt),
            (f'P{initial_row+0}:P{initial_row+7}', divider_fmt),
            (f'A{initial_row+3}:A{initial_row+7}', rank_fmt)
        ])
        set_row_heights(worksheet, [(f"{initial_row+3}:{initial_row+7}", 48)])

    def _get_merge_requests(self, sheet_id: int, initial_row: int) -> list:
        base_idx = initial_row - 1 
        merges = [
            (base_idx, 1, 4),       # B-D (Title row)
            (base_idx + 1, 1, 5),   # B-E (Amon)
            (base_idx + 1, 6, 10),  # G-J (Harlowe)
            (base_idx + 1, 11, 15), # L-O (Rafa)
            (base_idx + 1, 16, 20)  # Q-T (Vex)
        ]
        requests = []
        for row_idx, col_start, col_end in merges:
            requests.append({
                "mergeCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row_idx,
                        "endRowIndex": row_idx + 1,
                        "startColumnIndex": col_start,
                        "endColumnIndex": col_end
                    },
                    "mergeType": "MERGE_ALL"
                }
            })
        return requests