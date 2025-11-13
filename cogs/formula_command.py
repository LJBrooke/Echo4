import json
import discord
from discord import app_commands
from discord.ext import commands

# --- Load Data and Prepare Choices ---
try:
    with open('data/Formula.json', 'r', encoding='utf-8') as f:
        FORMULA_DATA = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"Error loading data/Formula.json for FormulaCommand cog: {e}")
    FORMULA_DATA = {}
    
# Prepare Creator Names list.
FORMULA_NAMES = sorted(list(set(
    str(formula)
    for formula in FORMULA_DATA.get("Formula").keys() if FORMULA_DATA.get("Formula").get(formula).get('Visible')==True
)))

def _gen_formula(formula: str):
    response = f"# {formula} Formula\n```"
    formula_dict = FORMULA_DATA.get('Formula').get(formula)
    formula_list = formula_dict.get('Affected by')
    
    # Controls indent levels for readability.
    indent = 0
    if 'Flat On Shot' in formula_list: indent = 2
    indent = str('\n' + indent * ' ')
    
    # Crit Formula
    
    crit_formula = '1 + ( 2 × Skill Tree Crit )'
    if "Gear Crit" in formula_list: crit_formula = crit_formula + ' + Gear Crit'
    
    # On Shot Formula, Simpler section hence hard coding.
    on_shot_formula = str(formula_dict.get('Base'))
    if 'Order Charge' in formula_list: on_shot_formula = on_shot_formula + str(indent) + ' × Order Charge'
    if 'Enhancement' in formula_list: on_shot_formula = on_shot_formula + str(indent) + ' × (1 + Enhancement)'
    if 'Amp' in formula_list: on_shot_formula = on_shot_formula + str(indent) + ' × (1 + Amp)'
    if 'Flat On Shot' in formula_list: on_shot_formula = '[  '+ indent + '('+ on_shot_formula + str(indent) + ')' + ' + Flat On Shot\n]'
    
    if formula_dict.get('Bonus Element') is not None: on_shot_formula = on_shot_formula + '\n× '+formula_dict.get('Bonus Element')
    
    # On Hit Formula
    on_hit_formula = '[\n  1\n'
    for on_shot in ["Gun Damage", "Skill Damage", "Action Skill Damage", "Melee Damage", "Status Effect Damage", "Minion Damage", "Splash", "Elemental", "Debuff", "Damage Dealt"]:
        if on_shot in formula_list: on_hit_formula = on_hit_formula + f'  + {on_shot}\n'
    on_hit_formula = on_hit_formula + '  + { '+crit_formula+' }\n'
    on_hit_formula = on_hit_formula + ']\n× Elemental Match\n× Resistance'
    
    response = response + '\n'+str(on_shot_formula)+'\n×\n'+str(on_hit_formula)+'```'
    
    return response

class detailView(discord.ui.View):
    def __init__(self, cog: 'FormulaCommand', formula_msg: str, affected_by: list, vault_hunter: str = None):
        self.cog = cog
        self.message = None
        self.formula_msg = formula_msg
        self.affected_by = affected_by
        self.vault_hunter = vault_hunter
        self.type_information = FORMULA_DATA.get("Type Information")
        
        # Set a timeout (was 3 minutes, upped to 5.)
        super().__init__(timeout=300.0)
        index=0
        # 2. Loop through the list and create a button for each skill name
        for modifier in affected_by:
            button_style=discord.ButtonStyle.secondary
            if self.type_information.get(modifier).get("Check")=='On Shot':
                button_style=discord.ButtonStyle.primary
            if self.type_information.get(modifier).get("Check")=='On Hit':
                button_style=discord.ButtonStyle.success
            button = discord.ui.Button(
                label=modifier,
                # Use a specific style, e.g., Blue
                style=button_style, 
                # Use the name as the custom_id for easy lookup in the callback
                custom_id=str(modifier), 
            )
            # 3. Assign the unified callback to the buttonYes.
            button.callback = self.affected_by_button_callback
            
            # 4. Add the button to the View
            self.add_item(button)
            index+=1
            
    def set_message(self, message: discord.Message):
        """Stores the message object to be used for editing on timeout."""
        self.message = message  
    
    async def _send_info(self, interaction: discord.Interaction, modifier: str):
        modifier_info = self.type_information.get(modifier)
        additional_info=f"## {modifier}\n- **Applies to:** {modifier_info.get('Applies to')}\n- **Example:** {modifier_info.get('Example')}\n\nBlue Buttons indicate on shot modifiers, Green indicates on hit modifiers:"
        
        # Creates a fresh view object on button click. Refreshing an old one causes issues at time out.
        new_view = detailView(self.cog, self.formula_msg, self.affected_by, self.vault_hunter)
        
        edited_message = await interaction.edit_original_response(
            content=self.formula_msg+'\n'+additional_info, 
            view=new_view
        )
        
        new_view.set_message(edited_message)
        
    async def affected_by_button_callback(self, interaction: discord.Interaction):
        # Pass the build name to the core processing logic
        await interaction.response.defer()
        await self._send_info(interaction, str(interaction.data['custom_id']))
    
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
        
# --- Define the Cog Class ---
class FormulaCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- Autocomplete Function for the 'name' option ---
    async def formula_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=formula_name, value=formula_name)
            for formula_name in FORMULA_NAMES if current.lower() in formula_name.lower()
        ][:25]
        
            
    # --- The Slash Command ---
    @app_commands.command(name="formula", description="Overview of how the damage formula fits together.")
    @app_commands.describe(formula_type="Returns the damage formula for a specific type of damage.")
    @app_commands.autocomplete(formula_type=formula_name_autocomplete)
    async def formula(self, interaction: discord.Interaction, formula_type: str):
        response = _gen_formula(formula_type)
        formula_dict = FORMULA_DATA.get('Formula').get(formula_type)
        response = response + '\n- **Applies to: **' + formula_dict.get('Vault Hunter')
        response = response + '\n- **Notes: **' + formula_dict.get('Notes')
        
        view = detailView(self, response, formula_dict.get('Affected by'), formula_dict.get('Vault Hunter'))
        
        # Send the message
        await interaction.response.send_message(content=response+ '\n\nBlue Buttons indicate on shot modifiers, Green indicates on hit modifiers:', view=view)
        
        # Handle time out update to message.
        message = await interaction.original_response()
        view.set_message(message)


# --- Setup Function ---
async def setup(bot: commands.Bot):
    await bot.add_cog(FormulaCommand(bot))
    print("✅ Cog 'formulaCommands' loaded.")