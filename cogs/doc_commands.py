import os
import discord
from discord import app_commands
from discord.ext import commands

# Load your specific user ID from the .env file.
OWNER_ID = int(os.getenv("OWNER_ID", 0))


class DocCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="doc", description="Provides Json format example")
    @app_commands.describe(resource="The Vault Hunter.")
    @app_commands.choices(resource=[
        app_commands.Choice(name="Class Mods", value="Class Mods"),
        app_commands.Choice(name="Builds", value="Builds"),
        app_commands.Choice(name="Skill Info", value="Skill Info"),
    ])
    async def doc(self, interaction: discord.Interaction, resource: str):
        response=f'To submit data for {resource} please follow this example: ```json\n'
        
        format_example=""
        if resource=='Class Mods':
            format_example='''{
    "character": "Harlowe",
    "rarity": "Legendary",
    "name": "Class Mod Name",
    "red_text": "Brrr",
    "skills": ["Skill1", "Skill2", "Skill3", "Skill4"],
    "skill_notes": "X skill gets Y points max instead of X",
    "passive_count": 2,
    "fixed_stat": "Something",
    "drop_location": "Graveward",
    "lootlemon": "https://www.lootlemon.com/class-mod/some-com-name-bl4"
}'''
        if resource=='Builds':
            format_example='''{
    "name": "Descriptive name, I will block your clickbait, try me.",
    "author": "Rat, [Youtuber Manuel](<Manuel's Youtube Channel Link>)",
    "tree": "Green/Red/Blue",
    "com": ["Com1", "Com2"],
    "description": "Functional, concise description on why I should be interested in this build.",
    "moba": "https://mobalytics.gg/borderlands-4/....",
    "youtube": "https://youtube/..."
}'''
        if resource=='Skill Info':
            format_example='''{
    "name": "Skill/Enhancement Effect/Passive Name",
    "skill description": "When Theorycrafter thinks, take bonus soup damage.",
    "damage type": "All/Gun Damage/Enhancement/Debuff/Elemental/Amp/Skill Damage/Action SKill Damage/Weakpoint Crit/Skill Tree Crit/Minion Damage/Flat On Shot/Order Charge/Status Effect Damage",
    "damage category": "Enhancement/Flat On Shot/Soup",
    "affects": "Gun/Bullet/Skill/Action Skill/Minions/Dots/Ordnance/Melee",
    "element": null,
    "note": "This is weird, GBX?"
}'''
        
        response+= format_example+"```\n_ _"
        
        await interaction.response.send_message(response)


async def setup(bot: commands.Bot):
    # This check ensures the commands are only added if the ID is set
    await bot.add_cog(DocCommands(bot))
    print("✅ Cog 'Documentation Commands' loaded and restricted to the admin server.")