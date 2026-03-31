import discord
import logging
import asyncpg
from builds import build
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

# Shared constant for consistent ordering across views
# Orders by: Red -> Green -> Blue -> Others, then Alphabetical by Name
ORDER_BY_SQL = """
    ORDER BY 
        CASE tree 
            WHEN 'Red' THEN 1 
            WHEN 'Green' THEN 2 
            WHEN 'Blue' THEN 3 
            ELSE 4 
        END,
        name ASC
"""

MAX_LEVEL = 60

# --- View 1: Creator View (Filtered by Author) ---
class CreatorView(discord.ui.View):
    def __init__(self, cog: 'BuildCommands', creator: str, level: int = MAX_LEVEL):
        self.cog = cog
        self.creator = creator
        self.message = None
        self.builds_data = [] # Store fetched records here
        self.level = level
        
        # Set a timeout (5 minutes)
        super().__init__(timeout=300.0)

    async def init_buttons(self):
        """Async initializer to fetch data and setup buttons"""
        # We query for builds where the author string contains the creator name
        query = f"""
            SELECT * FROM endgame_builds 
            WHERE author ILIKE $1 and level = $2
            {ORDER_BY_SQL}
        """
        search_term = [f"%{self.creator}%", self.level]
        
        async with self.cog.db_pool.acquire() as conn:
            self.builds_data = await conn.fetch(query, search_term)

        for index, build in enumerate(self.builds_data):
            button_style = discord.ButtonStyle.secondary
            tree = build['tree']
            
            if tree == 'Blue':
                button_style = discord.ButtonStyle.primary
            elif tree == 'Red':
                button_style = discord.ButtonStyle.danger
            elif tree == 'Green':
                button_style = discord.ButtonStyle.success
            
            button = discord.ui.Button(
                label=build['name'],
                style=button_style,
                custom_id=str(index)
            )
            button.callback = self.builds_button_callback
            self.add_item(button)

    def set_message(self, message: discord.Message):
        """Stores the message object to be used for editing on timeout."""
        self.message = message  
    
    async def _send_build(self, interaction: discord.Interaction, build_index: int):
        build = self.builds_data[build_index]
        
        response = f"# {build['name']}\n**Author(s):** {build['author']}\n{build['description']}\n"
        if build['moba_url']: 
            response += f"\n- [Mobalytics Written Guide](<{build['moba_url']}>)"
        if build['youtube_url']: 
            response += f"\n- [Youtube Video]({build['youtube_url']})"
        if build['highlight_url']: 
            response += f"\n- [Highlight Reel](<{build['highlight_url']}>)"
        
        # Refresh view logic
        new_view = CreatorView(self.cog, self.creator)
        await new_view.init_buttons() # Must await the async init
        
        edited_message = await interaction.edit_original_response(
            content=response, 
            view=new_view
        )
        new_view.set_message(edited_message)
        
    async def builds_button_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._send_build(interaction, int(interaction.data['custom_id']))
    
    async def on_timeout(self) -> None:
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.NotFound:
                pass

# --- View 2: Build View (Filtered by VH and optionally COM) ---
class BuildView(discord.ui.View):
    def __init__(self, cog: 'BuildCommands', vault_hunter: str, class_mod: str = None, level: int = MAX_LEVEL):
        self.cog = cog
        self.vault_hunter = vault_hunter
        self.class_mod = class_mod
        self.message = None
        self.builds_data = []
        self.level = level

        super().__init__(timeout=300.0)
    
    async def init_buttons(self):
        """Async initializer to fetch data and setup buttons"""
        # Base Query
        query = "SELECT * FROM endgame_builds WHERE vault_hunter ILIKE $1 AND level = $2"
        params = [self.vault_hunter, self.level]

        # Add COM filter if present
        if self.class_mod:
            # Check if the class_mod string exists within the class_mods text array
            query += " AND $3 = ANY(class_mods)"
            params.append(self.class_mod)
        
        query += ORDER_BY_SQL

        async with self.cog.db_pool.acquire() as conn:
            self.builds_data = await conn.fetch(query, *params)

        for index, build in enumerate(self.builds_data):
            button_style = discord.ButtonStyle.secondary
            tree = build['tree']
            
            if tree == 'Blue':
                button_style = discord.ButtonStyle.primary
            elif tree == 'Red':
                button_style = discord.ButtonStyle.danger
            elif tree == 'Green':
                button_style = discord.ButtonStyle.success

            button = discord.ui.Button(
                label=build['name'],
                style=button_style,
                custom_id=str(index)
            )
            button.callback = self.builds_button_callback
            self.add_item(button)

    def set_message(self, message: discord.Message):
        self.message = message

    async def _send_build(self, interaction: discord.Interaction, build_index: int):
        build = self.builds_data[build_index]
        
        response = f"# {build['name']}\n**Author(s):** {build['author']}\n{build['description']}\n"
        if build['moba_url']: 
            response += f"\n- [Mobalytics Written Guide](<{build['moba_url']}>)"
        if build['youtube_url']: 
            response += f"\n- [Youtube Video]({build['youtube_url']})"
        if build['highlight_url']: 
            response += f"\n- [Highlight Reel](<{build['highlight_url']}>)"
        
        # Refresh view logic
        new_view = BuildView(self.cog, self.vault_hunter, self.class_mod)
        await new_view.init_buttons() 
        
        edited_message = await interaction.edit_original_response(
            content=response, 
            view=new_view
        )
        new_view.set_message(edited_message)

    async def builds_button_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._send_build(interaction, int(interaction.data['custom_id']))

    async def on_timeout(self) -> None:
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.NotFound:
                pass

class BuildCommands(commands.Cog):
    def __init__(self, bot: commands.Bot, db_pool: asyncpg.Pool):
        self.bot = bot
        self.db_pool = db_pool
        
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

    # --- Autocomplete Logic ---
    async def author_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """
        Dynamic autocomplete for authors directly from the DB.
        This handles the markdown cleaning logic previously done in Python.
        """
        # Query distinct authors. 
        # Since authors are stored as "[Name](<link>)", we can fetch them all 
        # and process simple string matching in python for the top 25, 
        # or use SQL regex to extract names if performance matters (likely not needed for < 50 rows).
        
        query = "SELECT DISTINCT author FROM endgame_builds"
        
        choices = []
        try:
            async with self.db_pool.acquire() as conn:
                records = await conn.fetch(query)
                
            unique_names = set()
            for record in records:
                raw_author = record['author']
                # Clean the author name if it's in markdown format
                if '](<' in raw_author:
                    clean_name = raw_author[1:raw_author.find("]")]
                else:
                    clean_name = raw_author
                
                unique_names.add(clean_name)

            # Filter by current input
            filtered_names = [name for name in unique_names if current.lower() in name.lower()]
            
            # Sort and limit to 25
            choices = [
                app_commands.Choice(name=name, value=name)
                for name in sorted(filtered_names)[:25]
            ]
            
        except Exception as e:
            log.error(f"Autocomplete error: {e}")
            
        return choices

    # --- Commands ---

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
        for tree in build_obj.skill_trees:
            for skill in build_obj.skill_trees[tree]:
                for name, pts in build_obj.skill_trees[tree][skill].items():
                        embed_content = embed_content + f"\n -> {name}: **{pts}**"
            embed_content = embed_content + "\n"
        embed = discord.Embed(title=f"{build_obj.vh.title()}", description=embed_content)
        embed.color = discord.Color.green() # Default to Harlowe's colour.
        match build_obj.vh:
            case "amon": embed.color = discord.Color.red()
            case "rafa": embed.color = discord.Color.blue()
            case "vex": embed.color = discord.Color.purple()
            
        embed.url = build_obj.to_lootlemon()
        await interaction.response.send_message(embed=embed)
        
    @app_commands.command(name="builds", description="Show endgame builds for a specific Vault Hunter.")
    @app_commands.choices(vault_hunter=[
        app_commands.Choice(name="Amon", value="Amon"),
        app_commands.Choice(name="C4sh", value="C4sh"),
        app_commands.Choice(name="Harlowe", value="Harlowe"),
        app_commands.Choice(name="Rafa", value="Rafa"),
        app_commands.Choice(name="Vex", value="Vex")
    ],
    level=[
        app_commands.Choice(name="60", value=60),
        app_commands.Choice(name="50", value=50)
    ])
    @app_commands.describe(class_mod="Filter by specific Class Mod")
    async def builds(self, interaction: discord.Interaction, vault_hunter: app_commands.Choice[str], class_mod: str = None, level: app_commands.Choice[int] = None):
        """Displays a menu of builds for the selected VH."""
        await interaction.response.defer()
        
        actual_level = level.value if level else MAX_LEVEL
        
        view = BuildView(self, vault_hunter.value, class_mod, actual_level)
        await view.init_buttons() # Initialize async data fetching
        
        if not view.children:
            msg = f"No builds found for **{vault_hunter.value}**"
            if class_mod:
                msg += f" using **{class_mod}**"
            await interaction.followup.send(msg)
            return

        msg = await interaction.followup.send(
            f'''# Community {vault_hunter.value} Builds \n_Button Colour indicates the builds focus skill tree._ \n\nHeres a selection our community recommended builds. This assortment was co created by The Soup Kitchen's best!\n\nAll creators present on this list are members of this community. Dont hesitate to ask for help!\n\n-# This message times out after 5 minutes._ _'''  , 
            view=view
        )
        view.set_message(msg)

    @app_commands.command(name="creator_builds", description="Show builds by a specific creator.")
    @app_commands.autocomplete(creator=author_autocomplete)
    @app_commands.choices(level=[
        app_commands.Choice(name="60", value=60),
        app_commands.Choice(name="50", value=50)
    ])
    async def creator_builds(self, interaction: discord.Interaction, creator: str, level: app_commands.Choice[int] = None):
        """Displays a menu of builds for the selected Creator."""
        await interaction.response.defer()

        actual_level = level.value if level else MAX_LEVEL
        view = CreatorView(self, creator, actual_level)
        await view.init_buttons() # Initialize async data fetching
        
        if not view.children:
            await interaction.followup.send(f"No builds found for creator **{creator}**.")
            return

        msg = await interaction.followup.send(
            f'''# Builds by {creator}\n_Button Colour indicates the builds focus skill tree._ \n\n-# This message times out after 5 minutes._ _''' ,
            view=view
        )
        view.set_message(msg)

async def setup(bot: commands.Bot):
    if not hasattr(bot, 'db_pool'):
        log.error("Error: bot.db_pool not found. Ensure Database is connected in main.py")
        return
    await bot.add_cog(BuildCommands(bot, bot.db_pool))
    print("✅ Cog 'BuildCommands' loaded.")