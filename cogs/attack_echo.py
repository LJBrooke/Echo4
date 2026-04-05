import discord
from discord.ext import commands
import re
from datetime import datetime, timedelta, timezone
import asyncpg

# Configuration IDs
TARGET_GUILD_ID = 1357925020860551328  # Soup Kitchen guild ID
GEAR_CHANNEL_ID = 1490422924996251688  # gear-requests channel ID

async def is_gear_request(message: discord.Message, db_pool: asyncpg.Pool) -> bool:
    """
    Evaluates short messages to determine if they are asking for gear using
    a database-backed heuristic scoring system.
    """
    
    print(f"\n--- DEBUG: Message from {message.author} has passed outer guards ---")
    
    # 1. OUTER GUARD: Only run this logic in the specific community guild
    TARGET_GUILD_ID = 1357925020860551328  # Soup Kitchen guild ID
    if message.guild is None or message.guild.id != TARGET_GUILD_ID:
        return False
    
    # 2. Guard clauses: Skip long theorycrafting posts and messages missing the core topic
    if len(message.content) > 100:
        return False
        
    content_lower = message.content.lower()
    if "drop" not in content_lower or "give" not in content_lower or "anyone" not in content_lower:
        return False

    # 3. Fetch the dynamic heuristics from your PostgreSQL database
    # Note: For production, you may want to cache these heuristics in memory 
    # similar to how the persistent users are cached, to save DB calls.
    query = "SELECT keyword, weight FROM gear_heuristics;"
    records = await db_pool.fetch(query)

    # 4. Score the message
    total_score = 0
    for record in records:
        keyword = record['keyword'].lower()
        weight = record['weight']
        
        # Use regex \b to match exact word boundaries
        if re.search(rf'\b{re.escape(keyword)}\b', content_lower):
            total_score += weight

    # 5. Check against your threshold
    THRESHOLD = 3 
    return total_score >= THRESHOLD

async def handle_gear_routing(message: discord.Message, bot: commands.Bot) -> bool:
    """
    Checks if a user is asking for gear and routes them appropriately based on
    account age in the server or persistent cache overrides.
    Returns True if the message was routed, False otherwise.
    """
    
    print(f"\n--- DEBUG: Message from {message.author} is being checked for gear heuristics ---")
    # 1. GUILD GUARD: Only run this logic in the specific community guild
    if message.guild is None or message.guild.id != TARGET_GUILD_ID:
        return False
    
    # 2. CHANNEL GUARD: Do not trigger if the message is already in the gear channel
    if message.channel.id == GEAR_CHANNEL_ID:
        return False

    # 3. Check if user is in the persistent cache
    # Assumes bot.persistent_users_cache was populated in bot.setup_hook()
    is_persistent = message.author.id in getattr(bot, 'persistent_users_cache', set())

    # 4. If not persistent, check the 72-hour window
    if not is_persistent:
        if message.author.joined_at is None:
            return False
            
        time_since_join = datetime.now(timezone.utc) - message.author.joined_at
        if time_since_join > timedelta(hours=72):
            return False
        
    # 5. If they passed the user checks, evaluate the message content
    # Assumes bot.db_pool was instantiated in bot.setup_hook()
    if await is_gear_request(message, bot.db_pool):
        gear_channel = message.guild.get_channel(GEAR_CHANNEL_ID)
        
        if gear_channel:
            await message.reply(
                f"Hey there! It looks like you're looking for gear. "
                f"Check out {gear_channel.mention} to get sorted."
            )
        return True

    return False

class GearRoutingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bot messages to prevent infinite loops
        if message.author.bot:
            return

        # Fire the gear handler
        # If it returns True, it means we triggered the auto-reply
        if await handle_gear_routing(message, self.bot):
            return

# Standard setup function required by discord.py to load the extension
async def setup(bot):
    await bot.add_cog(GearRoutingCog(bot))