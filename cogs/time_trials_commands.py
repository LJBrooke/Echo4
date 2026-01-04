import discord
import asyncpg
import re
import json
import asyncio
from helpers.sheet_manager import TimeTrialsSheets
from datetime import timedelta
from discord import app_commands
from discord.ext import commands

# --- CONFIGURATION / CONSTANTS ---
# Single source of truth for game data

ACTIVITY_LIST = ["Bloomreaper", "Vault of Origo", "Vault of Inceptus", "Vault of Radix", "Vault Marathon"]

VAULT_HUNTERS = ["Amon", "Harlowe", "Rafa", "Vex"]

ACTION_SKILLS = [
    "Crucible", "Scourge", "Onslaughter", 
    "Flux Generator", "Zero-Point", "CHROMA Accelerator", 
    "Arc-Knives", "APOPHIS Lance", "Peacebreaker Cannons", 
    "Incarnate", "Dead Ringer", "Phase Phamiliar"
]

# UVH Levels 6 down to 0
# UVH_LEVELS = list(range(6, -1, -1))
UVH_LEVELS = [6]

# Pre-compiled Choice lists for Discord Decorators
VH_CHOICES = [app_commands.Choice(name=vh, value=vh) for vh in VAULT_HUNTERS]
AS_CHOICES = [app_commands.Choice(name=askill, value=askill) for askill in ACTION_SKILLS]
UVH_CHOICES = [app_commands.Choice(name=str(lvl), value=lvl) for lvl in UVH_LEVELS]
ACTIVITY_CHOICES = [app_commands.Choice(name=activity, value=activity) for activity in ACTIVITY_LIST]

# --- UTILITIES ---
class TimeTrialsUtils:
    """Static helpers so both the View and Cog can share logic."""
    
    @staticmethod
    def parse_time_input(time_str: str) -> timedelta:
        """
        Parses a string input (e.g. '1:30', '90.5') into a timedelta.
        """
        if not time_str:
            raise ValueError("Empty time string")
            
        time_str = time_str.strip()

        # Regex for MM:SS or HH:MM:SS
        colon_match = re.match(r'^(?:(\d+):)?(\d+)(?:\.(\d+))?$', time_str)
        
        if colon_match:
            parts = time_str.split(':')
            if len(parts) == 2: # MM:SS
                m, s = parts
                return timedelta(minutes=int(m), seconds=float(s))
            elif len(parts) == 3: # HH:MM:SS
                h, m, s = parts
                return timedelta(hours=int(h), minutes=int(m), seconds=float(s))
        
        # If it's just a raw number (int or float), treat as Seconds
        try:
            return timedelta(seconds=float(time_str))
        except ValueError:
            raise ValueError("Invalid time format")

    @staticmethod
    def format_timedelta(td: timedelta) -> str:
        """Standardizes how we display time in the UI."""
        total_seconds = int(td.total_seconds())
        minutes = total_seconds // 60
        seconds = td.total_seconds() % 60
        return f"{minutes}:{seconds:05.2f}"


# --- UI CLASSES ---

class RunEditModal(discord.ui.Modal, title="Edit Run Details"):
    def __init__(self, view):
        super().__init__()
        self.view_ref = view

        # Pre-fill inputs
        self.runner_input = discord.ui.TextInput(
            label="Runner Name", default=view.data['runner'], required=True
        )
        self.time_input = discord.ui.TextInput(
            label="Run Time", default=view.data['run_time_str'], 
            placeholder="e.g. 1:30 or 90.5", required=True
        )
        self.url_input = discord.ui.TextInput(
            label="Video URL", default=view.data['url'], required=True
        )
        self.notes_input = discord.ui.TextInput(
            label="Gear/Equipment", default=view.data['notes'], 
            style=discord.TextStyle.paragraph, required=False
        )

        self.add_item(self.runner_input)
        self.add_item(self.time_input)
        self.add_item(self.url_input)
        self.add_item(self.notes_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.view_ref.data['runner'] = self.runner_input.value
        self.view_ref.data['run_time_str'] = self.time_input.value
        self.view_ref.data['url'] = self.url_input.value
        self.view_ref.data['notes'] = self.notes_input.value
        
        await self.view_ref.update_display(interaction)

class RunEditView(discord.ui.View):
    def __init__(self, bot, record, db_pool, available_tags=[], sheet_callback=None):
        super().__init__(timeout=300)
        self.bot = bot
        self.db_pool = db_pool
        self.record_id = record['id']
        self.activity_name = record['activity']
        self.sheet_callback = sheet_callback
        self.available_tags = available_tags
        
        tags_raw = record.get('tags', '[]')
        if isinstance(tags_raw, str):
            current_tags = json.loads(tags_raw)
        else:
            current_tags = tags_raw or []
        # 1. Load Data
        self.data = {
            'runner': record['runner'],
            'vault_hunter': record['vault_hunter'],
            'action_skill': record['action_skill'],
            'uvh_level': record['uvh_level'],
            'true_mode': record['true_mode'],
            'url': record['url'],
            'notes': record['notes'] or "",
            'run_time_str': TimeTrialsUtils.format_timedelta(record['run_time']),
            'tags': current_tags
        }

        # 2. Build Components dynamically from Constants
        
        # Vault Hunter Select
        vh_options = [discord.SelectOption(label=name) for name in VAULT_HUNTERS]
        self.vh_select = discord.ui.Select(placeholder="Select Vault Hunter", options=vh_options, row=1)
        self.vh_select.callback = self.vh_callback
        self.add_item(self.vh_select)

        # Action Skill Select
        as_options = [discord.SelectOption(label=s) for s in ACTION_SKILLS]
        self.as_select = discord.ui.Select(placeholder="Select Action Skill", options=as_options, row=2)
        self.as_select.callback = self.as_callback
        self.add_item(self.as_select)
        
        # Tag Select (Only if tags exist in DB)
        if self.available_tags:
            # Discord limits selects to 25 options. Slice if necessary.
            tag_options = [
                discord.SelectOption(label=t, value=t) 
                for t in self.available_tags[:25]
            ]
            
            self.tag_select = discord.ui.Select(
                placeholder="Select Tags (Multi-select)",
                options=tag_options,
                min_values=0,
                max_values=len(tag_options),
                row=3
            )
            self.tag_select.callback = self.tag_callback
            self.add_item(self.tag_select)

        # UVH Select
        # uvh_options = [discord.SelectOption(label=str(i), value=str(i)) for i in UVH_LEVELS]
        # self.uvh_select = discord.ui.Select(placeholder="UVH Level", options=uvh_options, row=3)
        # self.uvh_select.callback = self.uvh_callback
        # self.add_item(self.uvh_select)

        # True Mode Button
        self.tm_button_obj = discord.ui.Button(label="True Mode", row=0)
        self.tm_button_obj.callback = self.tm_callback
        self.add_item(self.tm_button_obj)

        # Static Buttons
        edit_btn = discord.ui.Button(label="📝 Edit Text Details", style=discord.ButtonStyle.primary, row=0)
        edit_btn.callback = self.edit_text_callback
        self.add_item(edit_btn)

        save_btn = discord.ui.Button(label="Save Changes", style=discord.ButtonStyle.success, row=4)
        save_btn.callback = self.save_callback
        self.add_item(save_btn)

        del_btn = discord.ui.Button(label="Delete Run", style=discord.ButtonStyle.danger, row=4)
        del_btn.callback = self.delete_callback
        self.add_item(del_btn)

        disc_btn = discord.ui.Button(label="Discard Changes", style=discord.ButtonStyle.secondary, row=4)
        disc_btn.callback = self.discard_callback
        self.add_item(disc_btn)

        # 3. Apply Defaults
        self._refresh_components()

    def _refresh_components(self):
        # Update Defaults for Selects
        for opt in self.vh_select.options:
            opt.default = (opt.label == self.data['vault_hunter'])
            
        for opt in self.as_select.options:
            opt.default = (opt.label == self.data['action_skill'])
            
        # Update Tag Select Defaults
        if hasattr(self, 'tag_select'):
            for opt in self.tag_select.options:
                opt.default = (opt.value in self.data['tags'])
            
        # for opt in self.uvh_select.options:
        #     opt.default = (opt.value == str(self.data['uvh_level']))

        # Update True Mode Button Style
        state = self.data['true_mode']
        self.tm_button_obj.label = "True Mode: ON" if state else "True Mode: OFF"
        self.tm_button_obj.style = discord.ButtonStyle.green if state else discord.ButtonStyle.grey

    def get_embed(self):
        tags_str = ", ".join(self.data['tags']) if self.data['tags'] else "None"
        desc = (
            f"**Runner:** {self.data['runner']}\n"
            f"**Time:** {self.data['run_time_str']}\n"
            f"**Class:** {self.data['vault_hunter']} / {self.data['action_skill']}\n"
            f"**Tags:** {tags_str}\n"
            f"**Difficulty:** UVH {self.data['uvh_level']} | {'True Mode' if self.data['true_mode'] else 'Standard'}\n"
            f"**URL:** {self.data['url']}\n"
            f"**Build/Gear:** {self.data['notes']}"
        )
        return discord.Embed(title=f"Editing Run #{self.record_id}", description=desc, color=discord.Color.blue())

    async def update_display(self, interaction: discord.Interaction):
        self._refresh_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    # --- Callbacks ---
    async def vh_callback(self, interaction: discord.Interaction):
        self.data['vault_hunter'] = self.vh_select.values[0]
        await self.update_display(interaction)

    async def as_callback(self, interaction: discord.Interaction):
        self.data['action_skill'] = self.as_select.values[0]
        await self.update_display(interaction)
        
    async def tag_callback(self, interaction: discord.Interaction):
        # The select menu returns a list of all currently selected values
        self.data['tags'] = self.tag_select.values
        await self.update_display(interaction)

    # async def uvh_callback(self, interaction: discord.Interaction):
    #     self.data['uvh_level'] = int(self.uvh_select.values[0])
    #     await self.update_display(interaction)

    async def tm_callback(self, interaction: discord.Interaction):
        self.data['true_mode'] = not self.data['true_mode']
        await self.update_display(interaction)

    async def edit_text_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RunEditModal(self))

    async def save_callback(self, interaction: discord.Interaction):
        # Use the SHARED utility to parse
        try:
            val = TimeTrialsUtils.parse_time_input(self.data['run_time_str'])
        except ValueError:
             await interaction.response.send_message("❌ Invalid Time Format.", ephemeral=True)
             return
         
        tags_json = json.dumps(self.data['tags'])
        
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE time_trials SET
                    runner = $1, vault_hunter = $2, action_skill = $3,
                    uvh_level = $4, true_mode = $5, url = $6, notes = $7, 
                    run_time = $8, tags = $9::jsonb
                WHERE id = $10
            """, 
            self.data['runner'], self.data['vault_hunter'], self.data['action_skill'],
            self.data['uvh_level'], self.data['true_mode'], self.data['url'], 
            self.data['notes'], val, tags_json, self.record_id)
            
        # Trigger Sheet Update
        if self.sheet_callback and self.activity_name:
            self.sheet_callback(self.activity_name)
            
        for item in self.children:
            item.disabled = True
        
        await interaction.response.edit_message(content="✅ **Run Updated Successfully!**", embed=self.get_embed(), view=self)

    async def delete_callback(self, interaction: discord.Interaction):
        async with self.db_pool.acquire() as conn:
            # await conn.execute("DELETE FROM time_trials WHERE id = $1", self.record_id)
            await conn.execute("UPDATE time_trials set mark_as_deleted = true WHERE id = $1", self.record_id)
        
        # Trigger Sheet Update
        if self.sheet_callback and self.activity_name:
            self.sheet_callback(self.activity_name)
        
        await interaction.response.edit_message(content="🗑️ **Run Deleted.**", embed=None, view=None)

    async def discard_callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content="❌ **Edit Cancelled.**", embed=None, view=None)


# --- MAIN COG ---

class TimeTrialsCommand(commands.Cog):
    def __init__(self, bot: commands.Bot, db_pool: asyncpg.Pool):
        self.bot = bot
        self.db_pool = db_pool
        self.sheets_mgr = TimeTrialsSheets(db_pool)

    # --- Helper: Permissions ---
    async def check_admin(self, interaction: discord.Interaction) -> bool:
        """Centralized admin check. Works in both Servers (Guilds) and DMs."""
        
        # 1. Start with just the user's ID
        ids_to_check = [interaction.user.id]

        # 2. Safely add role IDs if they exist (only for discord.Member)
        # The 'getattr' method returns an empty list [] if 'roles' doesn't exist
        roles = getattr(interaction.user, 'roles', [])
        ids_to_check.extend([role.id for role in roles])

        async with self.db_pool.acquire() as conn:
            # 3. Check if ANY of these IDs (User or Roles) are in the admin table
            admin_check = await conn.fetchval(
                "SELECT 1 FROM time_trials_admin WHERE user_id = ANY($1)", 
                ids_to_check
            )
        
        return admin_check is not None

    # --- Autocomplete Logic ---
    async def run_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        runner = interaction.namespace.runner
        vault_hunter = interaction.namespace.vault_hunter

        if not runner or not vault_hunter:
            return []

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, activity, run_time, action_skill, submit_date 
                FROM time_trials 
                WHERE runner ILIKE $1 AND vault_hunter = $2 and mark_as_deleted is not true
                ORDER BY submit_date DESC
                LIMIT 25
            """, f"%{runner}%", vault_hunter)

        choices = []
        for r in rows:
            time_str = TimeTrialsUtils.format_timedelta(r['run_time'])
            date_str = r['submit_date'].strftime('%d/%m/%Y')
            display = f"{r['activity']}: {time_str} - {date_str}"
            # display = f"{r['activity']}: {time_str} - {r['action_skill']} - {date_str}"
            choices.append(app_commands.Choice(name=display, value=str(r['id'])))
        
        return choices

    async def tag_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """Autocomplete for existing tags."""
        async with self.db_pool.acquire() as conn:
            records = await conn.fetch("""
                SELECT tag_name FROM time_trials_tag_definitions
                WHERE tag_name ILIKE $1
                LIMIT 25
            """, f"%{current}%")
        return [app_commands.Choice(name=r['tag_name'], value=r['tag_name']) for r in records]

    def trigger_sheet_update(self, activity_name: str):
        """Fire-and-forget background task to update the Google Sheet."""
        if not activity_name:
            return
        asyncio.create_task(self.sheets_mgr.update_leaderboard(activity_name))
        
    # --- Main Command: Check Leaderboard ---
    @app_commands.command(name="time_trials", description="View the top 5 runs for a chosen Activity.")
    @app_commands.describe(
        activity="Choose the activity to view",
        vault_hunter="[Optional] Filter by a specific Vault Hunter",
        # uvh_level="[Optional] Filter by UVH Level (Default: 6)",
        true_mode="[Optional] Filter by True Mode (Default: True)",
        tag="[Optional] Filter by a specific Tag (e.g. No Homing)"
    )
    # Use constants for choices
    @app_commands.choices(activity=ACTIVITY_CHOICES)
    @app_commands.choices(vault_hunter=VH_CHOICES)
    @app_commands.autocomplete(tag=tag_autocomplete)
    # @app_commands.choices(uvh_level=UVH_CHOICES)
    async def time_trials(
        self,
        interaction: discord.Interaction,
        activity: app_commands.Choice[str],
        vault_hunter: app_commands.Choice[str] = None,
        # uvh_level: app_commands.Choice[int] = None,
        true_mode: bool = True,
        tag: str = None
    ):
        await interaction.response.defer()
        # Time trial only supports one UVH level currently.
        # target_uvh = uvh_level.value if uvh_level else 6
        target_uvh = 6
        target_vh = vault_hunter.value if vault_hunter else None
        
        query = """
            with records as (
                SELECT DISTINCT ON (LOWER(runner), true_mode)
                    runner, run_time, vault_hunter, action_skill, true_mode, notes, url
                FROM time_trials
                WHERE 
                    activity = $4 AND 
                    uvh_level = $1 AND 
                    true_mode=$2 AND 
                    ($3::text IS NULL OR vault_hunter = $3::text) AND 
                    ($5::text IS NULL OR tags ? $5) AND
                    mark_as_deleted is not true
                ORDER BY LOWER(runner), true_mode, run_time ASC )
            select * from records order by run_time
            limit 5
        """

        async with self.db_pool.acquire() as conn:
            results = await conn.fetch(query, target_uvh, true_mode, target_vh, activity.value, tag)

        if not results:
            await interaction.followup.send("No runs found for these settings.")
            return

        # Formatting
        vh_text = f" ({target_vh})" if target_vh else ""
        tag_str=''
        if tag: tag_str= f"\n[{tag}]"
        tm_text = "True Mode" if true_mode else "Standard Mode"
        title = f"🏆 {activity.value.title()} Leaderboard{vh_text}\n*UVH {target_uvh} | {tm_text}{tag_str}*"

        description = []
        for rank, row in enumerate(results, start=1):
            time_str = TimeTrialsUtils.format_timedelta(row['run_time'])
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"**{rank}.**")
            line = (
                f"{medal} **{time_str}** - [{row['runner']}]({row['url']})\n"
                f"└ *{row['vault_hunter']} ({row['action_skill']})* • {row['notes']}"
            )
            description.append(line)

        embed = discord.Embed(title=title, description="\n\n".join(description), color=discord.Color.gold())
        await interaction.followup.send(embed=embed)
        
    # --- Main Command: Add Time ---
    @app_commands.command(name="add_time", description="[TT Admin Only] Submit a time trial run.")
    @app_commands.describe(
        activity="Activity of the run.",
        run_time="Time achieved (e.g., '39.6', '120', '1:30')",
        runner="Name of the player who did the run",
        vault_hunter="The character used",
        action_skill="The Action Skill used",
        # uvh_level="The UVH Level (0-6)",
        true_mode="Was True Mode enabled?",
        url="Link to the video proof",
        gear="[Optional] A brief description of the Build/Gear used"
    )
    # Use constants for choices
    @app_commands.choices(activity=ACTIVITY_CHOICES)
    @app_commands.choices(vault_hunter=VH_CHOICES)
    @app_commands.choices(action_skill=AS_CHOICES)
    # @app_commands.choices(uvh_level=UVH_CHOICES)
    async def add_time(
        self, 
        interaction: discord.Interaction, 
        activity: app_commands.Choice[str],
        run_time: str, 
        runner: str, 
        vault_hunter: app_commands.Choice[str], 
        action_skill: app_commands.Choice[str],
        # uvh_level: app_commands.Choice[int], 
        true_mode: bool, 
        url: str, 
        gear: str = None
    ):
        await interaction.response.defer(ephemeral=True)
        
        # 1. Permission Check (Refactored)
        if not await self.check_admin(interaction):
            await interaction.followup.send("⛔ You do not have permission to add times. Please ping Girth.")
            return

        # 2. Parse Time (Refactored)
        try:
            duration_obj = TimeTrialsUtils.parse_time_input(run_time)
        except ValueError:
            await interaction.followup.send(f"⚠️ Could not understand time format: `{run_time}`")
            return

        # 3. Insert Data
        async with self.db_pool.acquire() as conn:
            try:
                record_id = await conn.fetchval(
                    """
                    INSERT INTO time_trials 
                    (activity, vault_hunter, action_skill, run_time, uvh_level, true_mode, url, runner, notes)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING id
                    """,
                    activity.value, 
                    vault_hunter.value, 
                    action_skill.value, 
                    duration_obj, 
                    6,
                    # uvh_level.value, 
                    true_mode, 
                    url, 
                    runner, 
                    gear
                )

                await interaction.followup.send(
                    f"✅ **Run Added!** (ID: {record_id})\n"
                    f"**Runner:** {runner}\n"
                    f"**Time:** {duration_obj}\n"
                    f"**Build:** {vault_hunter.name} / {action_skill.name} (UVH 6)"
                )
            except Exception as e:
                await interaction.followup.send(f"💥 Database Error: {e}")
                
            try:
                self.trigger_sheet_update(activity.value)
            except Exception as e:
                print(f"Failed to sync Sheet: {e}")
    
    # --- Edit Command ---
    @app_commands.command(name="edit_time", description="[TT Admin Only] Edit or delete an existing run.")
    @app_commands.describe(
        runner="The name of the runner to search for",
        vault_hunter="The Vault Hunter they used",
        run_selection="Select the specific run to edit"
    )
    # Use constants for choices
    @app_commands.choices(vault_hunter=VH_CHOICES)
    @app_commands.autocomplete(run_selection=run_autocomplete)
    async def edit_time(
        self, 
        interaction: discord.Interaction, 
        runner: str, 
        vault_hunter: app_commands.Choice[str],
        run_selection: str
    ):
        await interaction.response.defer(ephemeral=True)

        # 1. Permission Check (Refactored)
        if not await self.check_admin(interaction):
            await interaction.followup.send("⛔ Permission Denied.")
            return

        # 2. Fetch Data
        async with self.db_pool.acquire() as conn:
            try:
                run_id = int(run_selection)
                record = await conn.fetchrow("SELECT * FROM time_trials WHERE id = $1", run_id)
            except ValueError:
                await interaction.followup.send("❌ Invalid selection. Please use the autocomplete list.")
                return

            if not record:
                await interaction.followup.send("❌ Run not found.")
                return
            
            # Fetch available tags for the view
            tag_rows = await conn.fetch("SELECT tag_name FROM time_trials_tag_definitions ORDER BY tag_name")
            available_tags = [row['tag_name'] for row in tag_rows]

        # 3. Launch View
        view = RunEditView(self.bot, record, self.db_pool, available_tags, sheet_callback=self.trigger_sheet_update)
        await interaction.followup.send(embed=view.get_embed(), view=view)

    @app_commands.command(name="add_tag", description="[TT Admin] Define a new tag available for runs.")
    @app_commands.describe(name="The name of the tag (e.g. 'No Homing', 'No AOE', 'Melee')", description="Optional description")
    async def create_tag(self, interaction: discord.Interaction, name: str, description: str = None):
        if not await self.check_admin(interaction):
            await interaction.response.send_message("⛔ Permission Denied.", ephemeral=True)
            return

        async with self.db_pool.acquire() as conn:
            try:
                await conn.execute(
                    "INSERT INTO time_trials_tag_definitions (tag_name, description) VALUES ($1, $2)",
                    name, description
                )
                await interaction.response.send_message(f"✅ Tag **{name}** created successfully.", ephemeral=True)
            except asyncpg.UniqueViolationError:
                await interaction.response.send_message(f"⚠️ The tag **{name}** already exists.", ephemeral=True)
                
    @app_commands.command(name="delete_tag", description="[TT Admin] Permanently delete a tag definition.")
    @app_commands.autocomplete(name=tag_autocomplete)
    async def delete_tag(self, interaction: discord.Interaction, name: str):
        if not await self.check_admin(interaction):
            await interaction.response.send_message("⛔ Permission Denied.", ephemeral=True)
            return

        async with self.db_pool.acquire() as conn:
            result = await conn.execute("DELETE FROM time_trials_tag_definitions WHERE tag_name = $1", name)
        
        if result == "DELETE 0":
            await interaction.response.send_message(f"⚠️ Tag **{name}** not found.", ephemeral=True)
        else:
            await interaction.response.send_message(f"🗑️ Tag **{name}** deleted.", ephemeral=True)
            
    @app_commands.command(name="list_tags", description="View all available Time Trial tags and their descriptions.")
    async def list_tags(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        async with self.db_pool.acquire() as conn:
            records = await conn.fetch("SELECT tag_name, description FROM time_trials_tag_definitions ORDER BY tag_name ASC")
            
        if not records:
            await interaction.followup.send("No tags have been defined yet.")
            return

        embed = discord.Embed(title="🏷️ Time Trial Run Tags", color=discord.Color.blue())
        
        # Group them into the description
        desc_lines = []
        for r in records:
            desc = f" - *{r['description']}*" if r['description'] else ""
            desc_lines.append(f"**{r['tag_name']}**{desc}")
            
        embed.description = "\n".join(desc_lines)
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    if not hasattr(bot, 'db_pool'):
        print("Error: bot.db_pool not found.")
        return
    await bot.add_cog(TimeTrialsCommand(bot, bot.db_pool))