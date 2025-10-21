import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

# --- Load Environment ---
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")


# --- Bot Definition ---
# It's good practice to subclass the Bot for more complex setups.
class MyBot(commands.Bot):
    def __init__(self):
        # Set up intents and the command prefix
        super().__init__(
            command_prefix="!",
            intents=discord.Intents.default()
        )

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