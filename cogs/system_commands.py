import os
import json
import random
import asyncpg
import discord
from discord import app_commands
from discord.ext import commands
from helpers import sync_parts, load_part_stats

# Load your specific user ID from the .env file.
OWNER_ID = int(os.getenv("OWNER_ID", 0))
# NEW: Load the admin server ID
ADMIN_SERVER_ID = int(os.getenv("ADMIN_SERVER_ID", 0))

class ClassModModal(discord.ui.Modal, title='Add New Class Mod'):
    # Define the 5 remaining text inputs
    red_text = discord.ui.TextInput(label='Red Text Effect', style=discord.TextStyle.paragraph, required=False)
    lootlemon = discord.ui.TextInput(label='Lootlemon URL', required=False)
    fixed_stat = discord.ui.TextInput(label='Fixed Stat', required=False)
    skill_notes = discord.ui.TextInput(label='Spaghet Explanation', style=discord.TextStyle.paragraph, required=False)
    drop_location = discord.ui.TextInput(label='Drop Location', required=False)

    def __init__(self, db_pool, base_data: dict):
        super().__init__()
        self.db_pool = db_pool
        self.base_data = base_data  # Data passed from the slash command

    async def on_submit(self, interaction: discord.Interaction):
        # 1. Build the JSON attributes payload
        attributes = {
            "name": self.base_data['name'],
            "rarity": self.base_data['rarity'],
            "skills": self.base_data['skills'],
            "red_text": self.red_text.value or None,
            "character": self.base_data['character_name'],
            "lootlemon": self.lootlemon.value or None,
            "fixed_stat": self.fixed_stat.value or None,
            "skill_notes": self.skill_notes.value or None,
            "drop_location": self.drop_location.value or None,
            "passive_count": self.base_data['passive_count']
        }

        # 2. Insert into the database
        query = """
            INSERT INTO entities (name, source_category, character_id, attributes)
            VALUES ($1, $2, $3, $4::jsonb)
        """
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                query,
                self.base_data['name'],
                "Class Mod",
                self.base_data['character_id'],
                json.dumps(attributes)
            )

        # 3. Confirm success (this is where we can safely use ephemeral)
        await interaction.response.send_message(f"✅ Class Mod **{self.base_data['name']}** successfully added to the Echo-net.", ephemeral=True)

import discord
from discord import app_commands
import json

class GearModal(discord.ui.Modal, title='Add New Gear'):
    red_text = discord.ui.TextInput(label='Red Text Effect', style=discord.TextStyle.paragraph, required=False)
    lootlemon = discord.ui.TextInput(label='Lootlemon URL', required=False)
    skill_notes = discord.ui.TextInput(label='Notes', style=discord.TextStyle.paragraph, required=False)
    drop_location = discord.ui.TextInput(label='Drop Location', required=False)

    def __init__(self, db_pool, base_data: dict):
        super().__init__()
        self.db_pool = db_pool
        self.base_data = base_data 

    async def on_submit(self, interaction: discord.Interaction):
        # Build the simplified JSON attributes payload
        attributes = {
            "name": self.base_data['name'],
            "rarity": self.base_data['rarity'],
            "red_text": self.red_text.value or None,
            "lootlemon": self.lootlemon.value or None,
            "skill_notes": self.skill_notes.value or None,
            "drop_location": self.drop_location.value or None
        }

        # Insert into the database (character_id is explicitly None/NULL)
        query = """
            INSERT INTO entities (name, source_category, character_id, attributes)
            VALUES ($1, $2, $3, $4::jsonb)
        """
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                query,
                self.base_data['name'],
                self.base_data['gear_type'], 
                None, 
                json.dumps(attributes)
            )

        await interaction.response.send_message(f"✅ Gear **{self.base_data['name']}** successfully added to the Echo-net.", ephemeral=True)
        
class SystemCommands(commands.Cog):
    def __init__(self, bot: commands.Bot, db_pool: asyncpg.Pool):
        self.bot = bot
        self.db_pool = db_pool
        
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
        
    @app_commands.command(name="sync_sheet", description="[Owner Only] Force-sync the Google Sheet with the database.")
    @commands.is_owner()
    async def sync_part_sheet(self, interaction: discord.Interaction):
        """
        Runs the Google Sheet sync process.
        """
        try:
            # Failsafe for commands.is_owner() not working.
            if interaction.user.id != OWNER_ID:
                await interaction.response.send_message("You do not have permission to use this command. If you have found old data please report it to Prismatic.", ephemeral=True)
            
            # Defer the response, as this will take several seconds
            await interaction.response.defer(ephemeral=True)
            
            # Call the helper function, passing the bot's session and db_pool
            status_message = await sync_parts.sync_part_sheet(
                session=self.bot.session,
                db_pool=self.bot.db_pool
            )
            await interaction.followup.send(status_message, ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)
    
    @app_commands.command(name="sync_lemons", description="[Owner Only] Force-sync the Lootlemon site index with the database.")
    @commands.is_owner()
    async def sync_lootlemon(self, interaction: discord.Interaction):
        """
        Runs the Lootlemon sync process.
        """
        try:
            # Failsafe for commands.is_owner() not working.
            if interaction.user.id != OWNER_ID:
                await interaction.response.send_message("You do not have permission to use this command. If you have found old data please report it to Prismatic.", ephemeral=True)
            
            # Defer the response, as this will take several seconds
            await interaction.response.defer(ephemeral=True)
            
            # Call the helper function, passing the bot's session and db_pool
            status_message = await sync_parts.sync_lemons(
                session=self.bot.session
            )
            await interaction.followup.send(status_message, ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

    @app_commands.command(name="sync_parts", description="[Owner Only] Force-sync weapon parts from the source website.")
    @commands.is_owner()
    async def sync_weapon_parts(self, interaction: discord.Interaction):
        """
        Runs the weapon parts sync process.
        """
        try:
            # Failsafe for commands.is_owner()
            if interaction.user.id != OWNER_ID:
                await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
                return

            # Defer the response, as this is a long-running web/DB operation
            await interaction.response.defer(ephemeral=True, thinking="Fetching and processing part data...")
            
            status_message = await load_part_stats.sync_parts(
                session=self.bot.session,
                db_pool=self.db_pool # Use the asyncpg pool
            )
            
            await interaction.followup.send(status_message, ephemeral=True)
            
        except Exception as e:
            # Send the error to the user via followup
            await interaction.followup.send(f"❌ An error occurred during sync: {e}", ephemeral=True)

    @sync_part_sheet.error
    async def on_sync_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Error handler for the sync command"""
        if isinstance(error, app_commands.NotOwner):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        else:
            print(f"Error in sync command: {error}")
            if interaction.response.is_done():
                await interaction.followup.send("An unknown error occurred.", ephemeral=True)
            else:
                await interaction.response.send_message("An unknown error occurred.", ephemeral=True)
                
    # MODIFIED: Added the 'guilds' parameter to restrict this command
    @app_commands.command(name="refresh", description="[Owner Only] Refreshes all cogs and syncs commands.")
    @app_commands.guilds(ADMIN_SERVER_ID)
    async def refresh(self, interaction: discord.Interaction):
        """Refreshes all cogs, reloading code changes."""
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        
        reloaded_cogs = []
        for cog in list(self.bot.extensions.keys()):
            try:
                await self.bot.reload_extension(cog)
                reloaded_cogs.append(cog.split('.')[-1])
            except Exception as e:
                await interaction.followup.send(f"Failed to reload `{cog}`: {e}")
                return
        
        # We sync only to the admin guild for an instant update
        await self.bot.tree.sync(guild=discord.Object(id=ADMIN_SERVER_ID))
        
        await interaction.followup.send(f"✅ Successfully reloaded cogs: `{', '.join(reloaded_cogs)}` and synced commands to the admin server.")

    # MODIFIED: Added the 'guilds' parameter to restrict this command
    @app_commands.command(name="shutdown", description="[Owner Only] Shuts the bot down.")
    @app_commands.guilds(ADMIN_SERVER_ID)
    async def shutdown(self, interaction: discord.Interaction):
        """Shuts the bot down gracefully."""
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return
        
        await interaction.response.send_message("Shutting down...", ephemeral=True)
        await self.bot.close()
          
    @app_commands.command(name="credits", description="Who builds the Bot?")
    async def credits(self, interaction: discord.Interaction):
        credits='''**Bot Developer:**
- **Prismatic**

**Contributors**
- **Girthquake**: Filled out Amon information and endless support promoting this bot.
- **JoeForLong**: Filled out Rafa information.
- **Ratore**: Filled out Vex information.
- **Lango**: Built the /build_summary command.

**Information Sources**
- [Serialization tool by Nicnl and InflamedSebi](<https://borderlands4-deserializer.nicnl.com/>)
- [Everything to do with Item parts and associated effects.](<https://docs.google.com/spreadsheets/d/11TmXyGmIVoDFn4IFNJN1s2HuijSnn_nPZqN3LkDd5TA/edit?gid=1385091622#gid=1385091622>)
        '''
        await interaction.response.send_message(credits)

    @app_commands.command(name="news", description="Borderlands 4 Update Notes.")
    async def updates(self, interaction: discord.Interaction):
        link='https://borderlands.2k.com/borderlands-4/update-notes/'
        if random.random() > 0.9:
            link='https://youtu.be/dQw4w9WgXcQ?si=il--ViA_ShirGhNC'
        updates=f'''[The latest Borderlands 4 Patch notes can be found here](<{link}>)'''
        await interaction.response.send_message(updates)
        
    @app_commands.command(name="add_com", description="[Admin] Add a new Class Mod to the Echo-net.")
    @app_commands.describe(
        name="The name of the class mod",
        vault_hunter="The Vault Hunter this COM belongs to",
        rarity="Epic or Legendary",
        passive_count="Number of passives (2 or 3)",
        skill_1="First skill name", skill_2="Second skill name",
        skill_3="Third skill name", skill_4="Fourth skill name"
    )
    @app_commands.choices(
        vault_hunter=[
            app_commands.Choice(name="Amon", value=1),
            app_commands.Choice(name="Harlowe", value=2),
            app_commands.Choice(name="Rafa", value=3),
            app_commands.Choice(name="Vex", value=4),
            app_commands.Choice(name="C4sh", value=5),
            app_commands.Choice(name="Loveless", value=6)
        ],
        rarity=[
            app_commands.Choice(name="Legendary", value="Legendary"),
            app_commands.Choice(name="Epic", value="Purple")
        ],
        passive_count=[
            app_commands.Choice(name="2", value=2),
            app_commands.Choice(name="3", value=3)
        ]
    )
    async def add_com(
        self, 
        interaction: discord.Interaction, 
        name: str, 
        vault_hunter: app_commands.Choice[int], 
        rarity: app_commands.Choice[str], 
        passive_count: app_commands.Choice[int],
        skill_1: str, 
        skill_2: str, 
        skill_3: str, 
        skill_4: str
    ):
        # 1. Permission Check (Do NOT defer before this!)
        if not await self.check_admin(interaction):
            await interaction.response.send_message("⛔ Permission Denied.", ephemeral=True)
            return

        # 2. Extract values cleanly to prevent casting bugs
        # If Discord passes a Choice object, we extract the value/name. If a raw fallback occurs, we use it directly[cite: 12].
        vh_id = getattr(vault_hunter, 'value', vault_hunter)
        vh_name = getattr(vault_hunter, 'name', "Unknown")
        rarity_val = getattr(rarity, 'value', rarity)
        passives_val = getattr(passive_count, 'value', passive_count)

        # 3. Package the first-stage data to hand off to the Modal
        base_data = {
            'name': name,
            'character_id': vh_id,
            'character_name': vh_name,
            'rarity': rarity_val,
            'passive_count': passives_val,
            'skills': [skill_1, skill_2, skill_3, skill_4]
        }

        # 4. Launch the Modal
        modal = ClassModModal(self.db_pool, base_data)
        await interaction.response.send_modal(modal)


    @app_commands.command(name="add_gear", description="[Admin] Add new Gear to the Echo-net.")
    @app_commands.describe(
        name="The name of the item",
        gear_type="Gun, Enhancement, Shield, or Grenade",
        rarity="Purple or Legendary"
    )
    @app_commands.choices(
        gear_type=[
            app_commands.Choice(name="Gun", value="Gun"),
            app_commands.Choice(name="Enhancement", value="Enhancement"),
            app_commands.Choice(name="Shield", value="Shield"),
            app_commands.Choice(name="Grenade", value="Grenade")
        ],
        rarity=[
            app_commands.Choice(name="Legendary", value="Legendary"),
            app_commands.Choice(name="Epic", value="Purple")
        ]
    )
    async def add_gear(
        self, 
        interaction: discord.Interaction, 
        name: str, 
        gear_type: app_commands.Choice[str], 
        rarity: app_commands.Choice[str]
    ):
        # Permission Check
        if not await self.check_admin(interaction):
            await interaction.response.send_message("⛔ Permission Denied.", ephemeral=True)
            return

        # Extract values cleanly to prevent casting bugs[cite: 12]
        gear_type_val = getattr(gear_type, 'value', gear_type)
        rarity_val = getattr(rarity, 'value', rarity)

        # Package the first-stage data to hand off to the Modal
        base_data = {
            'name': name,
            'gear_type': gear_type_val,
            'rarity': rarity_val
        }

        # Launch the Modal
        modal = GearModal(self.db_pool, base_data)
        await interaction.response.send_modal(modal)
        
        
async def setup(bot: commands.Bot):
    # This check ensures the commands are only added if the ID is set
    if not hasattr(bot, 'db_pool'):
        print("Error: bot.db_pool not found.")
        return
    
    if ADMIN_SERVER_ID != 0:
        await bot.add_cog(SystemCommands(bot, bot.db_pool))
        print("✅ Cog 'SystemCommands' loaded and restricted to the admin server.")
    else:
        print("⚠️ Cog 'SystemCommands' not loaded: ADMIN_SERVER_ID is not set in .env file.")