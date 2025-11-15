import json
import discord
import logging
from builds import build
from discord import app_commands
from discord.ext import commands
log = logging.getLogger(__name__)

# --- Load Data and Prepare Choices ---
try:
    with open('data/builds.json', 'r', encoding='utf-8') as f:
        BUILD_DATA = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"Error loading data/builds.json for BuildsCommand cog: {e}")
    BUILD_DATA = {}

# Prepare Creator Names list.
CREATOR_NAMES = sorted(list(set(
    item['author'].strip()
    for items in BUILD_DATA.values()
    for item in items if item.get('author')
)))
UNIQUE_CREATOR_NAMES=[]
for creator in CREATOR_NAMES:
    # Expecting format [Creator Name](<link>)
    # We do not want the link included.
    if '](<' in creator:
        UNIQUE_CREATOR_NAMES.append(creator[1:creator.find("]")])
    else: UNIQUE_CREATOR_NAMES.append(creator)
    
UNIQUE_CREATOR_NAMES=set(UNIQUE_CREATOR_NAMES)

class CreatorView(discord.ui.View):
    def __init__(self, cog: 'BuildCommands', creator: str):
        self.cog = cog
        self.creator = creator
        self.message = None
        
        # Set a timeout (was 3 minutes, upped to 5.)
        super().__init__(timeout=300.0)
        self.builds = list(
            build
            for character in BUILD_DATA.values()
            for build in character if creator.lower() in build.get('author').lower()
        )
        
        index=0
        # 2. Loop through the list and create a button for each skill name
        for build in self.builds:
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
        build = self.builds[build_index]
        response=f"# {build.get('name')}\n**Author(s):** {build.get('author')}\n{build.get('description')}\n"
        if build.get('moba') is not None: response = response+f"\n- [Mobalytics Written Guide](<{build.get('moba')}>)"
        if build.get('youtube') is not None: response = response+f"\n- [Youtube Video]({build.get('youtube')})"
        
        # Creates a fresh view object on button click. Refreshing an old one causes issues at time out.
        new_view = CreatorView(self.cog, self.creator)
        
        edited_message = await interaction.edit_original_response(
            content=response, 
            view=new_view
        )
        
        new_view.set_message(edited_message)
        
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
        
class BuildView(discord.ui.View):
    def __init__(self, cog: 'BuildCommands', vault_hunter: str, class_mod: str = None):
        self.cog = cog
        self.vault_hunter = vault_hunter
        self.message = None
        self.class_mod = class_mod
        
        # Set a timeout (was 3 minutes, upped to 5.)
        super().__init__(timeout=300.0)
        builds = BUILD_DATA.get(vault_hunter)
        index=0
        # 2. Loop through the list and create a button for each skill name
        for build in builds:
            if class_mod==None or class_mod in build.get("com"):
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
        new_view = BuildView(self.cog, self.vault_hunter, self.class_mod)
        
        edited_message = await interaction.edit_original_response(
            content=response, 
            view=new_view
        )
        
        new_view.set_message(edited_message)
        
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
        
    # --- Helper Functions ---
    async def _check_for_link(self, interaction: discord.Interaction) -> str:
        """
        Checks the last 10 messages for a Lootlemon class link
        and returns the first one found (newest to oldest).
        """
        LEMON_PREFIX = "https://www.lootlemon.com/class/"
        try:
            # Scan the last 10 messages (newest to oldest)
            async for message in interaction.channel.history(limit=10):
                
                # Simple check first for performance
                if LEMON_PREFIX in message.content:
                    # If the prefix is in the message, find the actual link
                    # Handle newlines and split by space
                    words = message.content.replace('\n', ' ').split(' ') 
                    for word in words:
                        # Find the first "word" that starts with the prefix
                        if word.startswith(LEMON_PREFIX):
                            # Found the link, return it immediately
                            return word
            
            # If we get through all 10 messages without returning, no link was found
            return "No valid Lootlemon link found"

        except (discord.Forbidden, discord.HTTPException) as e:
            log.warning(f"Could not check for 'Lootlemon link' in message history: {e}")
            return "No valid Lootlemon link found" # Return the "not found" string on permission error
        except Exception as e:
            log.error(f"Unexpected error during 'Lootlemon link' check: {e}", exc_info=True)
            return "No valid Lootlemon link found" # Return the "not found" string on general error
        
    # --- Autocomplete Function for the creator 'who' option ---
    async def creator_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=creator_name, value=creator_name)
            for creator_name in UNIQUE_CREATOR_NAMES if current.lower() in creator_name.lower()
        ][:25]

    # --- The Slash Commands ---
    
    # --- Search by Vault Hunter ---
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
    
    # --- Search by Content Creator ---
    @app_commands.command(name="creators", description="Resident build Theorycrafters")
    @app_commands.describe(who="Who would you like a build from?")
    @app_commands.autocomplete(who=creator_name_autocomplete)
    async def creators(self, interaction: discord.Interaction, who: str):
        initial_content =f'''# Builds by {who}\n_Button Colour indicates the builds focus skill tree._ \n\n-# This message times out after 5 minutes._ _'''  
        view = CreatorView(self, who)
        
        # Send the message
        await interaction.response.send_message(content=initial_content, view=view)
        
        # Handle time out update to message.
        message = await interaction.original_response()
        view.set_message(message)
        
    # --- Interpret Lootlemon Build ---
    @app_commands.command(name="build_summary", description="Describe a build")
    @app_commands.describe(link="Lootlemon link of build or ^ if someone has already posted the link.")
    async def build_inspect(self, interaction: discord.Interaction, link: str):
        
        if link.strip()=='^':
            link = await self._check_for_link(interaction)
            if 'https://www.lootlemon.com/class/' not in link:
                return await interaction.response.send_message(content=link)
            
        build_obj = build.SkillBuild.from_lootlemon(link)
        # build_obj.pretty_print()
        
        embed_content = f"**Action skill:**: {build_obj.action_skill or 'None'}"
        embed_content = embed_content + f"\n**Augment:** {build_obj.augment}"
        embed_content = embed_content + f"\n**Capstone:** {build_obj.capstone}"
        embed_content = embed_content + "\n\n**Allocated skills:**"
        for name, pts in build_obj.skills.items():
            embed_content = embed_content + f"\n -> {name}: **{pts}**"
        
        embed = discord.Embed(title=f"{build_obj.vh.title()}", description=embed_content)
        
        embed.color = discord.Color.green() # Default to Harlowe's colour.
        match build_obj.vh:
            case "amon": embed.color = discord.Color.red()
            case "rafa": embed.color = discord.Color.blue()
            case "vex": embed.color = discord.Color.purple()
            
        embed.url = build_obj.to_lootlemon()
        
        await interaction.response.send_message(embed=embed)

# --- To load the Cog ---
async def setup(bot):
    await bot.add_cog(BuildCommands(bot))
    print("✅ Cog 'BuildCommands' loaded.")