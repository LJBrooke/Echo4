# import json
import discord
from discord import app_commands
from discord.ext import commands

# --- Define the Cog Class ---
class FormulaCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- Autocomplete Function for the 'name' option ---
    async def formula_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=formula_name, value=formula_name)
            for formula_name in ['Overview', 'Gun', 'Minion', "Action Skill"] if current.lower() in formula_name.lower()
        ][:25]

    # --- The Slash Command ---
    @app_commands.command(name="formula", description="Overview of how the damage formula fits together.")
    @app_commands.describe(formula_type="Returns the damage formula for a specific type of damage.")
    @app_commands.autocomplete(formula_type=formula_name_autocomplete)
    async def formula(self, interaction: discord.Interaction, formula_type: str):
        
        if formula_type.lower()=='overview':
            final_response ='''# Formula Overview
            ```
[ 
  ( Base Damage x 
  Order Charge x
  (1+Enhancement) x
  (1+Amp) )
  + Flat On Shot
] x
( 1 + Soup + Skill Damage + Action Skill Damage + Minion Damage + { 1 + (2 x Skill Crit) + Gear Crit } ) x
Elemental Match x
Resistance 
```
_ _'''

        elif formula_type.lower()=='gun':
            final_response ='''# Gun Damage Overview
            ```
[ 
  ( Base Damage x 
  Order Charge x
  (1+Enhancement) x
  (1+Amp) )
  + Flat On Shot
] x
( 1 + Soup + { 1 + (2 x Skill Crit) + Gear Crit } ) x
Elemental Match x
Resistance 
```
_ _'''
        
        elif formula_type.lower()=='action skill':
            final_response ='''# Action Skill Damage Overview
            ```
[ 
  Gun Card + Flat On Shot
] x
( 1 + Soup + Action Skill Damage + { 1 + (2 x Skill Crit)} ) x
Elemental Match x
Resistance 
```
_ _'''

        elif formula_type.lower()=='minion':
            final_response ='''# Minion Formula Overview
            ```
  Base Damage x
( 1 + Soup + Skill Damage + Minion Damage + { 1 + (2 x Skill Crit) } ) x
Elemental Match x
Resistance 
```
_ _'''




        
        # Note: Discord messages have a 2000 character limit. 
        # If the combined result is too long, you might need to implement pagination.
        if len(final_response) > 2000:
            final_response = final_response[:1985] + "\n... (truncated)"

        await interaction.response.send_message(final_response)


# --- Setup Function ---
async def setup(bot: commands.Bot):
    await bot.add_cog(FormulaCommand(bot))
    print("✅ Cog 'formulaCommands' loaded.")