import os
import time
import discord
from discord.ext import commands
from discord import app_commands, Interaction
from dotenv import load_dotenv

# --- Load Environment ---
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
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
        if interaction.user.id != int(os.getenv("OWNER_ID")):
            user="User"
        guild_id = interaction.guild.id if interaction.guild else "DMs"
        
        start_time = command_start_times.pop(interaction.id, None)
    
        if start_time:
            response_time = (end_time - start_time) * 1000 # Convert to milliseconds
        
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] COMMAND USED: /{command_name}, Response took: {response_time:.2f}ms \nUser:{user} in {guild_id}")
        

    async def setup_hook(self):
        """This function is called when the bot is preparing to connect."""
        print("Loading cogs...")
        
        # Define the path to your CSV file
        cogs_csv_path = 'cogs/cogs.csv'
        
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
        
        except FileNotFoundError:
            print(f"⚠️ {cogs_csv_path} not found. No cogs were loaded dynamically.")

        print("--- Finished loading cogs ---")
        
        # Sync the command tree to register the slash commands.
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} command(s)")
        except Exception as e:
            print(f"Failed to sync commands: {e}")

    async def on_ready(self):
        """This event is called when the bot is fully connected."""
        print(f'✅ Logged in as {self.user} (ID: {self.user.id})')
        print('------')


# --- Run the Bot ---
if __name__ == "__main__":
    if not TOKEN:
        print("ERROR: DISCORD_TOKEN not found in .env file.")
    else:
        bot = MyBot()
        bot.run(TOKEN)