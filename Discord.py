import os
import sys
import time
import discord
import aiohttp
import asyncpg
import logging
import colorlog
from dotenv import load_dotenv
from discord.ext import commands
from discord import app_commands, Interaction

# --- LOGGING SETUP ---
# Set the default level to DEBUG for development, or INFO for production
log_level = logging.INFO 

# 1. Create the ColoredFormatter
#    NOTICE: We are using standard %(name)s and %(message)s.
#    NO custom color tokens. NO extra %(reset)s for them.
log_format = (
    '%(asctime)s '
    '%(log_color)s[%(levelname)-8s] '
    '%(name)-15s: '  # <-- STANDARD TOKEN
    '%(reset)s\n%(message)s'     # <-- STANDARD TOKEN
)

# This maps log levels to specific colors (for %(log_color)s)
log_colors_config = {
    'DEBUG': 'cyan',
    'INFO': 'blue',
    'WARNING': 'yellow',
    'ERROR': 'red',
    'CRITICAL': 'bold_red',
}

# This maps logger names to colors (for 'name')
name_colors_config = {
    'helpers': 'purple',
    'helpers.shield_class': 'purple', # This is fine, but 'helpers' already covers it
    'cogs': 'blue',
    '': 'yellow', # Root/main logger
}

# This maps the message itself to colors (for 'message')
message_colors_config = {
    'WARNING': 'yellow',
    'ERROR': 'red',
    'CRITICAL': 'bold_red',
}

formatter = colorlog.ColoredFormatter(
    log_format,
    datefmt='%Y-%m-%d %H:%M:%S',
    log_colors=log_colors_config,
    secondary_log_colors={
        'name': name_colors_config,
        
        # The key is the *attribute name* ('message')
        # NOT the custom token ('message_log_color')
        'message': message_colors_config
    },
    style='%'
)

# 2. Get the root logger
logger = logging.getLogger()
logger.setLevel(log_level)

# 3. Create the handler and set the formatter
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(formatter)

# 4. Remove any old handlers and add the new one
logger.handlers = [] 
logger.addHandler(stdout_handler)

# --- END OF LOGGING SETUP ---

# Keep a single, easy-to-access logger for this file
log = logging.getLogger(__name__)

# Example of using the logger
log.info("Logging is configured! Bot is starting...")

# --- Load Environment ---
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
GQ_SERVER_ID = int(os.getenv("GQ_SERVER_ID"))
ADMIN_SERVER_ID = int(os.getenv("ADMIN_SERVER_ID"))
command_start_times = {}

# --- Bot Definition ---
# It's good practice to subclass the Bot for more complex setups.
class MyBot(commands.Bot):
    def __init__(self):
        # Set up intents and the command prefix
        super().__init__(
            command_prefix="!",
            intents=discord.Intents.default()
        )
        
    @commands.Cog.listener()
    async def on_interaction(self, interaction: Interaction):
        # Log the start time as soon as the bot receives the interaction
        if interaction.type == discord.InteractionType.application_command:
            # Use a unique ID to map start time to completion time
            command_start_times[interaction.id] = time.time()
        
    @commands.Cog.listener()
    async def on_app_command_completion(self, interaction: Interaction, command: app_commands.Command):
        end_time = time.time()
        response_time = -1 # Declare var, and set known impossible value in case of no start_time.
        # 1. Log the command name
        command_name = command.name
        
        user = 'Prismatic'
        # 2. Get the user/guild info
        if interaction.user.id != OWNER_ID:
            user="User"
        if interaction.guild:
            if interaction.guild==GQ_SERVER_ID:
                guild_id='GQ Server'
            elif interaction.guild==ADMIN_SERVER_ID:
                guild_id='Admin Server'
            else: guild_id=interaction.guild
        else: guild_id="DMs"
        
        
        start_time = command_start_times.pop(interaction.id, None)
    
        if start_time:
            response_time = (end_time - start_time) * 1000 # Convert to milliseconds
        
        log.info(f"COMMAND USED: /{command_name}:\n  - User:{user} in {guild_id}\n  - Response took: {response_time:.2f}ms")
        

    async def setup_hook(self):
        """This function is called when the bot is preparing to connect."""
        log.info(f"Loading cogs...")
        
        # Define the path to your CSV file
        cogs_csv_path = 'cogs/cogs.csv'
        
        # 1. Create the async web session
        self.session = aiohttp.ClientSession()
        
        # 2. Create the async database pool
        try:
            self.db_pool = await asyncpg.create_pool(
                host=os.getenv("DATABASE_HOST"),
                database=os.getenv("DATABASE_NAME"),
                user=os.getenv("DATABASE_USER"),
                password=os.getenv("DATABASE_PWD")
            )
        except Exception as e:
            log.info(f"Failed to connect to database: {e}")
            return # Don't load cogs if DB fails
        
        try:
            # Open and read the CSV file
            with open(cogs_csv_path, mode='r') as f:
                # Read the single line and split it by commas to get a list of filenames
                cogs_to_load = f.readline().strip().split(',')
            
            # Loop through each filename from the CSV
            for cog_file in cogs_to_load:
                if cog_file: # Ensure it's not an empty string
                    # Format the filename into the correct import path (e.g., 'cogs.find_command')
                    cog_path = f"cogs.{cog_file.replace('.py', '')}"
                    try:
                        # Load the extension
                        await self.load_extension(cog_path)
                        print(f"✅ Loaded cog: {cog_path}")
                    except Exception as e:
                        print(f"❌ Failed to load cog {cog_path}: {e}")
                        log.error("❌ Failed to load cog "+cog_path+": %s", e, exc_info=True)
        
        except FileNotFoundError:
            log.info(f"⚠️ {cogs_csv_path} not found. No cogs were loaded dynamically.")

        print("--- Finished loading cogs ---")
        
        # Sync the command tree to register the slash commands.
        try:
            synced = await self.tree.sync()
            log.info(f"Synced {len(synced)} command(s)")
        except Exception as e:
            log.info(f"Failed to sync commands: {e}")

    async def on_ready(self):
        """This event is called when the bot is fully connected."""
        log.info(f'✅ Logged in as {self.user} (ID: {self.user.id})\n------')


# --- Run the Bot ---
if __name__ == "__main__":
    if not TOKEN:
        log.info("ERROR: DISCORD_TOKEN not found in .env file.")
    else:
        bot = MyBot()
        bot.run(TOKEN)