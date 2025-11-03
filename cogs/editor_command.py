# cogs/editor_command.py
import json
import discord
from discord import app_commands
from discord.ext import commands
from helpers import item_parser

# Footers are standard for all messages dependent on data presented. Hence declared globally.
serial_footer = """\n-# Serialization thanks to [Nicnl and InflamedSebi](https://borderlands4-deserializer.nicnl.com/)"""
parts_footer = """\n-# Part information thanks to [this amazing resource](<https://docs.google.com/spreadsheets/d/17LHzPR7BltqgzbJZplr-APhORgT2PTIsV08n4RD3tMw/edit?gid=1385091622#gid=1385091622>)"""

# --- Define the Cog Class ---
class EditorCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    async def cog_load(self):
        """
        This function is called by discord.py when the cog is loaded.
        It's the perfect place for async setup.
        """
        # Load your JSON data here
        try:
            with open('data/part_data.json', 'r', encoding='utf-8') as f:
                self.part_data = json.load(f)
            # print("Cog: Part Data loaded.")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error loading Part Data for cog: {e}")
            
        # --- 2. Populate the autocomplete caches from the DB ---
        # print("Cog: Building autocomplete caches...")
        try:
            # async with self.bot.db_pool.acquire() as conn:
            #     # Fetch and store manufacturers
            #     m_records = await conn.fetch("SELECT DISTINCT manufacturer FROM part_list where part_type is not null ORDER BY manufacturer")
            #     self.manufacturer_options = [r['manufacturer'] for r in m_records]
                
            #     # Fetch and store weapon types
            #     wt_records = await conn.fetch("SELECT DISTINCT weapon_type FROM part_list where part_type is not null ORDER BY weapon_type")
            #     self.weapon_type_options = [r['weapon_type'] for r in wt_records]
                
            #     # Fetch and store part types
            #     pt_records = await conn.fetch("SELECT DISTINCT part_type FROM part_list where part_type is not null ORDER BY part_type")
            #     self.part_type_options = [r['part_type'] for r in pt_records]
            self.manufacturer_options = ["Daedalus", "Jakobs", "Maliwan", "Order", "Ripper", "Tediore", "Torgue", "Vladof"]
            self.weapon_type_options = ["Assault Rifle", "Pistol", "SMG", "Shotgun", "Sniper"]
            self.part_type_options = ["Barrel", "Barrel Accessory", "Body", "Body Accessory", "Foregrip", "Grip", "Magazine", "Manufacturer Part", "Scope", "Scope Accessory", "Stat Modifier", "Underbarrel", "Underbarrel Accessory"]    
            # print(f"Cog: Autocomplete caches built. (Manufacturers: {len(self.manufacturer_options)})")
        except Exception as e:
            print(f"CRITICAL: Failed to build autocomplete caches: {e}")
            
    async def manufacturer_autocomplete(self, 
        interaction: discord.Interaction, 
        current: str
    ) -> list[app_commands.Choice[str]]:
        
        # Filter the cached list based on the user's typing
        choices = [
            app_commands.Choice(name=m, value=m) 
            for m in self.manufacturer_options if current.lower() in m.lower()
        ]
        # Return up to 25 choices (Discord's limit)
        return choices[:25]

    async def weapon_type_autocomplete(self, 
        interaction: discord.Interaction, 
        current: str
    ) -> list[app_commands.Choice[str]]:
        
        choices = [
            app_commands.Choice(name=wt, value=wt) 
            for wt in self.weapon_type_options if current.lower() in wt.lower()
        ]
        return choices[:25]

    async def part_type_autocomplete(self, 
        interaction: discord.Interaction, 
        current: str
    ) -> list[app_commands.Choice[str]]:
        
        choices = [
            app_commands.Choice(name=pt, value=pt) 
            for pt in self.part_type_options if current.lower() in pt.lower()
        ]
        return choices[:25]
          
    # --- The Slash Command ---
    @app_commands.command(name="deserialize", description="Convert a Bl4 item code to its components")
    @app_commands.describe(serial="Item serial to decode.")
    async def deserialize(self, interaction: discord.Interaction, serial: str):
        response = await item_parser.deserialize(self.bot.session, serial.strip())
        
        print(response)
        message = '**Item:** '+response.get('additional_data') + '\n**Deserialized String:** '+response.get('deserialized')
               
        message = message+parts_footer
        await interaction.response.send_message(content=message)

    # --- The Slash Command ---
    @app_commands.command(name="serialize", description="Encode a Bl4 item string to its serial value")
    @app_commands.describe(serial="Item string to serialize.")
    async def serialize(self, interaction: discord.Interaction, serial: str):
        response = await item_parser.reserialize(self.bot.session, serial.strip())
        
        message = '**Item:** '+response.get('additional_data') + '\n**Serialized String:** '+response.get('serial_b85')
        
        message = message+serial_footer
        await interaction.response.send_message(content=message)
    
    # --- The Slash Command ---
    @app_commands.command(name="inspect", description="Show weapon parts associated with a serial or component list")
    @app_commands.describe(weapon_id="weapon serial or component list")
    async def inspect(self, interaction: discord.Interaction, weapon_id: str):
        message = await item_parser.part_list_driver(
            session=self.bot.session,
            db_pool=self.bot.db_pool,
            part_data=self.part_data,
            item_code=weapon_id
        )
        message = message+serial_footer+parts_footer
        await interaction.response.send_message(content=message)

    # --- The Slash Command ---
    @app_commands.command(name="parts", description="Filter possible parts")
    @app_commands.describe(manufacturer="The Weapon Manufacturer")
    @app_commands.describe(weapon_type="What type of weapon do you parts for want?")
    @app_commands.describe(part_type="Which part type do you want?")
    @app_commands.autocomplete(
        manufacturer=manufacturer_autocomplete,
        weapon_type=weapon_type_autocomplete,
        part_type=part_type_autocomplete
    )
    async def parts(self, interaction: discord.Interaction, manufacturer: str, weapon_type: str, part_type: str):
        message = await item_parser.possible_parts_driver(
            db_pool=self.bot.db_pool,
            manufacturer=manufacturer,
            weapon_type=weapon_type,
            part_type=part_type
        )
        message = message+parts_footer
        await interaction.response.send_message(content=message)

        # --- The Slash Command ---
    @app_commands.command(name="element_id", description="Fetch the part id for elements on a gun")
    @app_commands.describe(primary_element="The Primary or only element on your gun")
    @app_commands.describe(secondary_element="The element you can switch to if the gun has the option, otherwise 'None'")
    @app_commands.describe(underbarrel="Do you want the id for the second element of a dual element gun?")
    @app_commands.choices(
        primary_element=[
            app_commands.Choice(name="Corrosive", value="Corrosive"),
            app_commands.Choice(name="Cryo", value="Cryo"),
            app_commands.Choice(name="Fire", value="Fire"),
            app_commands.Choice(name="Radiation", value="Radiation"),
            app_commands.Choice(name="Shock", value="Shock"),
        ],
        secondary_element=[
            app_commands.Choice(name="None", value="None"),
            app_commands.Choice(name="Corrosive", value="Corrosive"),
            app_commands.Choice(name="Cryo", value="Cryo"),
            app_commands.Choice(name="Fire", value="Fire"),
            app_commands.Choice(name="Radiation", value="Radiation"),
            app_commands.Choice(name="Shock", value="Shock"),
        ],
        underbarrel=[
            app_commands.Choice(name="No", value='False'),
            app_commands.Choice(name="Yes", value='True'),
        ]
    )
    async def get_element_id(self, interaction: discord.Interaction, primary_element: str, secondary_element: str, underbarrel: str):
        if underbarrel == 'True': underbarrel=True
        else: underbarrel=False
        message = await item_parser.query_element_id(
            db_pool=self.bot.db_pool,
            primary=primary_element,
            secondary=secondary_element,
            underbarrel=underbarrel
        )
        message = f"Primary Element: {primary_element}\nSecondary Element: {None}\nUnderbarrel: {str(underbarrel)}\n\n**Element ID:** {message}\n{parts_footer}"
        await interaction.response.send_message(content=message)
         
# --- Setup Function ---
async def setup(bot: commands.Bot):
    await bot.add_cog(EditorCommands(bot))
    print("✅ Cog 'EditorCommands' loaded.")