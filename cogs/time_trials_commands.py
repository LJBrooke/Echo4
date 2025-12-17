import discord
import asyncpg
import re
from datetime import timedelta
from discord import app_commands
from discord.ext import commands

class TimeTrialsCommand(commands.Cog):
    def __init__(self, bot: commands.Bot, db_pool: asyncpg.Pool):
        self.bot = bot
        self.db_pool = db_pool

    # --- Helper: Time Parser ---
    def parse_time_input(self, time_str: str) -> timedelta:
        """
        Parses a string input into a timedelta.
        Supported formats:
        - "39.6" -> 39.6 seconds
        - "120" -> 120 seconds
        - "1:30" -> 1 minute, 30 seconds
        - "1m 30s" -> 1 minute, 30 seconds
        """
        # Remove whitespace
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
            pass

        # Fallback error (caught in the main command)
        raise ValueError("Invalid time format")

    # --- Main Command: Check Leaderboard ---
    @app_commands.command(name="time_trials", description="View the top 5 runs for Bloomreaper.")
    @app_commands.describe(
        vault_hunter="[Optional] Filter by a specific Vault Hunter",
        uvh_level="[Optional] Filter by UVH Level (Default: 6)",
        true_mode="[Optional] Filter by True Mode (Default: True)"
    )
    @app_commands.choices(vault_hunter=[
        app_commands.Choice(name="Amon", value="Amon"),
        app_commands.Choice(name="Harlowe", value="Harlowe"),
        app_commands.Choice(name="Rafa", value="Rafa"),
        app_commands.Choice(name="Vex", value="Vex")
    ])
    @app_commands.choices(uvh_level=[
        app_commands.Choice(name=str(i), value=i) for i in range(6, -1, -1)
    ])
    async def time_trials(
        self,
        interaction: discord.Interaction,
        vault_hunter: app_commands.Choice[str] = None,
        uvh_level: app_commands.Choice[int] = None,
        true_mode: bool = True
    ):
        await interaction.response.defer()

        # Set Defaults if not provided
        target_uvh = uvh_level.value if uvh_level else 6
        target_vh = vault_hunter.value if vault_hunter else None
        
        # We use a clever SQL trick here: ($3::text IS NULL OR vault_hunter = $3::text)
        # This allows us to pass 'None' to the query and have it automatically ignore that filter.
        query = """
            SELECT * FROM (
                SELECT DISTINCT ON (runner, action_skill)
                    runner,
                    run_time,
                    vault_hunter,
                    action_skill,
                    url
                FROM time_trials
                WHERE activity = 'Bloomreaper'
                  AND uvh_level = $1
                  AND true_mode = $2
                  AND ($3::text IS NULL OR vault_hunter = $3::text)
                ORDER BY runner, action_skill, run_time ASC
            ) sub_query
            ORDER BY run_time ASC
            LIMIT 5;
        """

        async with self.db_pool.acquire() as conn:
            results = await conn.fetch(query, target_uvh, true_mode, target_vh)

        if not results:
            await interaction.followup.send("No runs found for these settings.")
            return

        # --- Formatting the Message ---
        
        # Title logic
        vh_text = f" ({target_vh})" if target_vh else ""
        tm_text = "True Mode" if true_mode else "Standard Mode"
        title = f"🏆 Bloomreaper Leaderboard{vh_text}\n*UVH {target_uvh} | {tm_text}*"

        description = []
        for rank, row in enumerate(results, start=1):
            # Format time (remove simple microseconds for cleaner look if desired)
            # row['run_time'] is a timedelta
            total_seconds = row['run_time'].total_seconds()
            minutes = int(total_seconds // 60)
            seconds = total_seconds % 60
            time_str = f"{minutes}:{seconds:05.2f}" # e.g., 1:39.60

            # Emoji medals for top 3
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"**{rank}.**")

            line = (
                f"{medal} **{time_str}** - {row['runner']}\n"
                f"└ *{row['vault_hunter']} ({row['action_skill']})* • [Link]({row['url']})"
            )
            description.append(line)

        embed = discord.Embed(
            title=title,
            description="\n\n".join(description),
            color=discord.Color.gold()
        )

        await interaction.followup.send(embed=embed)
        
    # --- Main Command: Add Time ---
    @app_commands.command(name="add_time", description="Submit a time trial run for Bloomreaper.")
    @app_commands.describe(
        run_time="Time achieved (e.g., '39.6', '120', '1:30')",
        runner="Name of the player who did the run",
        vault_hunter="The character used",
        action_skill="The Action Skill used",
        uvh_level="The UVH Level (0-6)",
        true_mode="Was True Mode enabled?",
        url="Link to the video proof",
        notes="[Optional] Any additional details"
    )
    # Vault Hunter Choices
    @app_commands.choices(vault_hunter=[
        app_commands.Choice(name="Amon", value="Amon"),
        app_commands.Choice(name="Harlowe", value="Harlowe"),
        app_commands.Choice(name="Rafa", value="Rafa"),
        app_commands.Choice(name="Vex", value="Vex")
    ])
    # Action Skill Choices (In the order you requested)
    @app_commands.choices(action_skill=[
        app_commands.Choice(name="Crucible", value="Crucible"),
        app_commands.Choice(name="Scourge", value="Scourge"),
        app_commands.Choice(name="Onslaughter", value="Onslaughter"),
        app_commands.Choice(name="Flux Generator", value="Flux Generator"),
        app_commands.Choice(name="Zero-Point", value="Zero-Point"),
        app_commands.Choice(name="CHROMA Accelerator", value="CHROMA Accelerator"),
        app_commands.Choice(name="Arc-Knives", value="Arc-Knives"),
        app_commands.Choice(name="APOPHIS Lance", value="APOPHIS Lance"),
        app_commands.Choice(name="Peacebreaker Cannons", value="Peacebreaker Cannons"),
        app_commands.Choice(name="Incarnate", value="Incarnate"),
        app_commands.Choice(name="Dead Ringer", value="Dead Ringer"),
        app_commands.Choice(name="Phase Phamiliar", value="Phase Phamiliar")
    ])
    # UVH Choices (6 to 0)
    @app_commands.choices(uvh_level=[
        app_commands.Choice(name=str(i), value=i) for i in range(6, -1, -1)
    ])
    async def add_time(
        self, 
        interaction: discord.Interaction, 
        run_time: str, 
        runner: str, 
        vault_hunter: app_commands.Choice[str], 
        action_skill: app_commands.Choice[str],
        uvh_level: app_commands.Choice[int], 
        true_mode: bool, 
        url: str, 
        notes: str = None
    ):
        await interaction.response.defer(ephemeral=True)

        async with self.db_pool.acquire() as conn:
            # 1. Permission Check
            admin_check = await conn.fetchval(
                "SELECT 1 FROM time_trials_admin WHERE user_id = $1", 
                interaction.user.id
            )

            if not admin_check:
                await interaction.followup.send(
                    "⛔ You do not have permission to add times. Please ping Girth."
                )
                return

            # 2. Parse Time
            try:
                duration_obj = self.parse_time_input(run_time)
            except ValueError:
                await interaction.followup.send(f"⚠️ Could not understand time format: `{run_time}`")
                return

            # 3. Insert Data
            try:
                record_id = await conn.fetchval(
                    """
                    INSERT INTO time_trials 
                    (activity, vault_hunter, action_skill, run_time, uvh_level, true_mode, url, runner, notes)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING id
                    """,
                    'Bloomreaper',              # $1 Activity
                    vault_hunter.value,         # $2 Vault Hunter
                    action_skill.value,         # $3 Action Skill
                    duration_obj,               # $4 Run Time
                    uvh_level.value,            # $5 UVH Level
                    true_mode,                  # $6 True Mode
                    url,                        # $7 URL
                    runner,                     # $8 Runner (Manual Input)
                    notes                       # $9 Notes
                )

                # 4. Success Response
                await interaction.followup.send(
                    f"✅ **Run Added!** (ID: {record_id})\n"
                    f"**Runner:** {runner}\n"
                    f"**Time:** {duration_obj}\n"
                    f"**Build:** {vault_hunter.name} / {action_skill.name} (UVH {uvh_level.value})"
                )

            except Exception as e:
                await interaction.followup.send(f"💥 Database Error: {e}")

# Helper for loading the cog
async def setup(bot: commands.Bot):
    if not hasattr(bot, 'db_pool'):
        print("Error: bot.db_pool not found.")
        return
    await bot.add_cog(TimeTrialsCommand(bot, bot.db_pool))