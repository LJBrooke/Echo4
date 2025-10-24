import json
import discord
from discord import app_commands
from discord.ext import commands

# --- Load Data and Prepare Choices ---
try:
    with open('data/builds.json', 'r', encoding='utf-8') as f:
        BUILD_DATA = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"Error loading data/builds.json for BuildsCommand cog: {e}")
    BUILD_DATA = {}

class BuildView(discord.ui.View):
    def __init__(self, cog: 'BuildCommands', vault_hunter: str):
        self.cog = cog
        self.vault_hunter = vault_hunter
        self.message = None
        
        # Set a timeout (was 3 minutes, upped to 5.)
        super().__init__(timeout=300.0)
        builds = BUILD_DATA.get(vault_hunter)
        index=0
        # 2. Loop through the list and create a button for each skill name
        for build in builds:
            button_style=discord.ButtonStyle.secondary
            if build.get("tree")=='Blue':
                button_style=discord.ButtonStyle.primary
            if build.get("tree")=='Red':
                button_style=discord.ButtonStyle.danger
            if build.get("tree")=='Green':
                button_style=discord.ButtonStyle.success
            button = discord.ui.Button(
                label=build.get("name"),
                # Use a specific style, e.g., Blue
                style=button_style, 
                # Use the name as the custom_id for easy lookup in the callback
                custom_id=str(index), 
            )
            # 3. Assign the unified callback to the buttonYes.
            button.callback = self.builds_button_callback
            
            # 4. Add the button to the View
            self.add_item(button)
            index+=1
            
    def set_message(self, message: discord.Message):
        """Stores the message object to be used for editing on timeout."""
        self.message = message  
    
    async def _send_build(self, interaction: discord.Interaction, build_index: int):
        build = BUILD_DATA.get(self.vault_hunter)[build_index]
        response=f"# {build.get('name')}\n**Author(s):** {build.get('author')}\n{build.get('description')}\n"
        if build.get('moba') is not None: response = response+f"\n- [Mobalytics Written Guide](<{build.get('moba')}>)"
        if build.get('youtube') is not None: response = response+f"\n- [Youtube Video]({build.get('youtube')})"
        
        # Creates a fresh view object on button click. Refreshing an old one causes issues at time out.
        new_view = BuildView(self.cog, self.vault_hunter)
        
        edited_message = await interaction.edit_original_response(
            content=response, 
            view=new_view
        )
        
        new_view.set_message(edited_message)
        
        # Removed with introduction of fresh view object per interaction.
        # message = await interaction.original_response()
        # self.set_message(message)
        
    async def builds_button_callback(self, interaction: discord.Interaction):
        # Pass the build name to the core processing logic
        await interaction.response.defer()
        await self._send_build(interaction, int(interaction.data['custom_id']))
    
    async def on_timeout(self) -> None:
        """Called when the view times out (after 300 seconds)."""
        if self.message:
            try:
                # Edit the message, setting 'view=None' to remove all buttons
                await self.message.edit(
                    view=None
                )
            except discord.NotFound:
                pass

class BuildCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- The Slash Command ---
    @app_commands.command(name="builds", description="Community recommended builds.")
    @app_commands.describe(vault_hunter="Who would you like a build for?")
    @app_commands.choices(vault_hunter=[
        app_commands.Choice(name="Amon", value="Amon"),
        app_commands.Choice(name="Harlowe", value="Harlowe"),
        app_commands.Choice(name="Vex", value="Vex"),
        app_commands.Choice(name="Rafa", value="Rafa"),
    ])
    async def builds(self, interaction: discord.Interaction, vault_hunter: str):
        initial_content =f'''# Community {vault_hunter} Builds \n_Button Colour indicates the builds focus skill tree._ \n\nHeres a selection our community recommended builds. This assortment was co created by The Soup Kitchen's best!\n\nAll creators present on this list are members of this community. Dont hesitate to ask for help!\n\n-# This message times out after 5 minutes._ _'''  
        view = BuildView(self, vault_hunter)
        
        # Send the message
        await interaction.response.send_message(content=initial_content, view=view)
        
        # Handle time out update to message.
        message = await interaction.original_response()
        view.set_message(message)

# --- To load the Cog ---
async def setup(bot):
    await bot.add_cog(BuildCommands(bot))
    print("✅ Cog 'BuildCommands' loaded.")