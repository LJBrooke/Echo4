import json
import discord
from discord import app_commands
from discord.ext import commands
import math

# --- CONFIGURATION ---
RANK_MAPPING = {
    "GbxActor.Character.Rank.Badass": "Badass",
    "GbxActor.Character.Rank.Badass.Corrupt": "Badass",
    "GbxActor.Character.Rank.Badass.Super": "Badass",
    "GbxActor.Character.Rank.Boss": "Boss",
    "GbxActor.Character.Rank.Boss.Mini": "Boss",
    "GbxActor.Character.Rank.Boss.Vault": "Boss",
    "GbxActor.Character.Rank.Chump": "Normal",
    "GbxActor.Character.Rank.Elite": "Elite",
    "GbxActor.Character.Rank.Loot": "Boss",
    "GbxActor.Character.Rank.Normal": "Normal"
}

def calc_enemy_health(base: float, level: int, uvh_scale: float, mayhem_scale: float, player_scale: float) -> int:
    # Formula: Base * 80 * PlayerScale * UVHScale * ((1.09 ^ Level) * (1 + 0.02*Level))
    level_multiplier = (1.09 ** level) * (1 + (0.02 * level))
    final_health = base * 80 * player_scale * uvh_scale * mayhem_scale * level_multiplier
    return int(final_health)

class EnemyData(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- OPTIMIZED AUTOCOMPLETE ---
    async def enemy_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        async with self.bot.db_pool.acquire() as conn:
            # LOGIC:
            # 1. CTE 'raw_data':
            #    - FROM gbxactor (aliased as 'ga')
            #    - Explicitly references ga.attributes to avoid ambiguity.
            #    - Extracts 'display_lookup_key' (e.g. "Name_BeastWhitehorn").
            #    - Extracts 'balance_path' for the command payload.
            # 2. Main Query:
            #    - Joins 'display_data' (aliased as 'dd').
            #    - Filters by user input.
            
            query = """
                WITH valid_actors AS (
                    SELECT DISTINCT ON (entry_key)
                        -- Extract lookup key: "display_data'Name_X'"
                        substring(
                            (attributes ->> 'uxdisplayname') 
                            FROM 'display_data''([^'']+)'''
                        ) as display_lookup_key,
                        
                        -- Clean balance path (Payload)
                        lower(TRIM(BOTH '''' FROM REGEXP_REPLACE(
                            (balance_data #>> '{balancetablerowhandle, datatable}'), 
                            '^gbx_ue_data_table', 
                            ''
                        ))) AS balance_path,
                        
                        -- Rank (Payload)
                        (attributes #>> '{tag_rank, tagname}') AS rank_key
                    FROM gbxactor
                    WHERE 
                        (attributes #>> '{tag_rank, tagname}') LIKE 'GbxActor.Character.Rank.%' AND
                        (balance_data #>> '{balancetablerowhandle, datatable}') LIKE 'gbx_ue_data_table%'
                    ORDER BY entry_key, internal_id DESC
                ),
                unique_display AS (
                    -- Ensure we only check the LATEST version of every display key
                    SELECT DISTINCT ON (entry_key)
                        entry_key,
                        text
                    FROM display_data
                    ORDER BY entry_key, internal_id DESC
                )
                SELECT DISTINCT
                    va.balance_path,
                    va.rank_key,
                    -- Regex: ^.*, matches everything from start up to the LAST comma. 
                    -- We replace that match with empty string '' to leave only the name.
                    TRIM(REGEXP_REPLACE(ud.text, '^.*,', '')) as friendly_name,
                    -- Fallback ID
                    substring(va.balance_path FROM 7 FOR length(va.balance_path) - 14) as fallback_id
                FROM valid_actors va
                LEFT JOIN unique_display ud 
                    ON lower(ud.entry_key) = lower(va.display_lookup_key)
                WHERE 
                    (ud.text ILIKE $1 OR va.balance_path ILIKE $1)
                ORDER BY friendly_name ASC
                LIMIT 24;
            """
            results = await conn.fetch(query, f"%{current}%")

        choices = []
        for r in results:
            # Determine the name to show (Friendly Name -> Fallback ID)
            name_text = r['friendly_name'] if r['friendly_name'] else r['fallback_id']
            
            rank_raw = r['rank_key']
            # Simple rank display: "GbxActor.Character.Rank.Badass" -> "Badass"
            rank_display = rank_raw.split('.')[-1] if rank_raw else "Unknown"
            
            # Label: "Whitehorn [Badass]"
            name_display = f"{name_text} [{rank_display}]"
            
            # Value: "table_beast_whitehorn_balance|GbxActor.Character.Rank.Badass"
            packed_value = f"{r['balance_path']}|{rank_raw}"
            
            choices.append(app_commands.Choice(name=name_display[:100], value=packed_value[:100]))
        
        return choices

    async def fetch_friendly_name(self, balance_key: str, row_name: str) -> str:
        """Looks up the localized name based on balance key and specific variant row_name."""
        query = """
            WITH valid_actor AS (
                SELECT 
                    substring(
                        (attributes ->> 'uxdisplayname') 
                        FROM 'display_data''([^'']+)'''
                    ) as display_lookup_key
                FROM gbxactor
                WHERE lower(TRIM(BOTH '''' FROM REGEXP_REPLACE(
                    (balance_data #>> '{balancetablerowhandle, datatable}'), 
                    '^gbx_ue_data_table', 
                    ''
                ))) = lower($1) AND
                lower(balance_data #>> '{balancetablerowhandle, rowname}') = lower($2)
                ORDER BY internal_id DESC
                LIMIT 1
            )
            SELECT 
                TRIM(REGEXP_REPLACE(text, '^.*,', '')) as friendly_name
            FROM display_data dd
            JOIN valid_actor va ON lower(dd.entry_key) = lower(va.display_lookup_key)
            ORDER BY dd.internal_id DESC
            LIMIT 1;
        """
        async with self.bot.db_pool.acquire() as conn:
            # Pass both the balance_key and row_name to the query
            return await conn.fetchval(query, balance_key, row_name)
        
    # --- COMMAND ---
    @app_commands.command(name="enemy_health", description="Calculate enemy health stats.")
    @app_commands.describe(
        enemy_name="The enemy to check (search by name or ID).",
        level="The level of the enemy.",
        uvh="UVH Level (0-7). Default is 7.",
        mayhem="Mayhem Level (0-20). Default is 0.",
        player_count="Number of players (1-4). Default is 1."
    )
    @app_commands.autocomplete(enemy_name=enemy_autocomplete)
    @app_commands.choices(player_count=[
        app_commands.Choice(name="1", value=1),
        app_commands.Choice(name="2", value=2),
        app_commands.Choice(name="3", value=3),
        app_commands.Choice(name="4", value=4)
    ], uvh=[
        app_commands.Choice(name="0", value=0),
        app_commands.Choice(name="1", value=1),
        app_commands.Choice(name="2", value=2),
        app_commands.Choice(name="3", value=3),
        app_commands.Choice(name="4", value=4),
        app_commands.Choice(name="5", value=5),
        app_commands.Choice(name="6", value=6),
        app_commands.Choice(name="7", value=7)
    ], mayhem=[
        app_commands.Choice(name="0", value=0),
        app_commands.Choice(name="1", value=1),
        app_commands.Choice(name="2", value=2),
        app_commands.Choice(name="3", value=3),
        app_commands.Choice(name="4", value=4),
        app_commands.Choice(name="5", value=5),
        app_commands.Choice(name="6", value=6),
        app_commands.Choice(name="7", value=7),
        app_commands.Choice(name="8", value=8),
        app_commands.Choice(name="9", value=9),
        app_commands.Choice(name="10", value=10),
        app_commands.Choice(name="11", value=11),
        app_commands.Choice(name="12", value=12),
        app_commands.Choice(name="13", value=13),
        app_commands.Choice(name="14", value=14),
        app_commands.Choice(name="15", value=15),
        app_commands.Choice(name="16", value=16),
        app_commands.Choice(name="17", value=17),
        app_commands.Choice(name="18", value=18),
        app_commands.Choice(name="19", value=19),
        app_commands.Choice(name="20", value=20),
    ])
    async def check(self, interaction: discord.Interaction, enemy_name: str, level: int, uvh: int = 7, mayhem: int = 0, player_count: int = 1):
        await interaction.response.defer(ephemeral=False)
        
        if not (1 <= player_count <= 4) or not (0 <= uvh <= 7):
            await interaction.followup.send("Player count must be between 1 and 4.")
            return
        
        # 1. UNPACK DATA 
        try:
            balance_key, rank_raw = enemy_name.split('|')
        except ValueError:
            # Handle case where user types a raw string instead of clicking a choice
            await interaction.followup.send("Please select a valid enemy from the autocomplete list.")
            return

        # Determine Complexity (Normal/Badass/Boss) from the packed rank
        target_complexity = RANK_MAPPING.get(rank_raw, "Boss")

        async with self.bot.db_pool.acquire() as conn:
            # 2. FETCH BASE MULTIPLIERS
            bal_query = "SELECT data FROM gbx_ue_data_table WHERE entry_key = $1"
            bal_data = await conn.fetchval(bal_query, balance_key)
            
            if not bal_data:
                await interaction.followup.send(f"Could not find balance data for `{balance_key}`.")
                return

            # 3. FETCH UVH SCALE
            uvh_scale = 1.0
            if uvh > 0:
                uvh_query = "SELECT data FROM gbx_ue_data_table WHERE entry_key = 'table_difficulty_uvh'"
                uvh_json = await conn.fetchval(uvh_query)
                if uvh_json:
                    uvh_data = json.loads(uvh_json) if isinstance(uvh_json, str) else uvh_json
                    target_row = f"UVH{uvh}"
                    for row in uvh_data:
                        if row.get('row_name') == target_row:
                            val_str = row.get('row_value', {}).get('enemyhealth', "1.0")
                            uvh_scale = float(val_str)
                            break
            
            # 4. FETCH MAYHEM SCALE
            mayhem_scale = 1.0
            if mayhem > 0:
                uvh_scale = 1.0 # Mayhem overrides UVH, so we reset UVH scale to 1.0
                mayhem_query = "SELECT data FROM gbx_ue_data_table WHERE entry_key = 'table_difficulty_mayhem' order by internal_id asc limit 1"
                mayhem_json = await conn.fetchval(mayhem_query)
                if mayhem_json:
                    mayhem_data = json.loads(mayhem_json) if isinstance(mayhem_json, str) else mayhem_json
                    target_row = f"Mayhem{mayhem}"
                    for row in mayhem_data:
                        if row.get('row_name') == target_row:
                            val_str = row.get('row_value', {}).get('enemyhealth', "1.0")
                            mayhem_scale = float(val_str)
                            break
            
            # 5. FETCH PLAYER SCALE (Using the unpacked complexity)
            player_scale = 1.0
            if player_count > 1:
                player_query = "SELECT data FROM gbx_ue_data_table WHERE entry_key = 'enemy_health_scalars_by_player_count'"
                player_json = await conn.fetchval(player_query)
                if player_json:
                    p_data = json.loads(player_json) if isinstance(player_json, str) else player_json
                    
                    p_map = {1: "oneplayer", 2: "twoplayers", 3: "threeplayers", 4: "fourplayers"}
                    p_key = p_map.get(player_count, "oneplayer")
                    
                    for row in p_data:
                        if row.get('row_name') == target_complexity:
                            val_obj = row.get('row_value', {}).get(p_key, {})
                            val_str = val_obj.get('constant', "1.0")
                            player_scale = float(val_str)
                            break

        # --- OUTPUT ---
        enemy_rows = json.loads(bal_data) if isinstance(bal_data, str) else bal_data
        
        # Display the friendly ID for the main embed title as a fallback
        clean_id = balance_key.replace("table_", "").replace("_balance", "")

        embed = discord.Embed(
            title=f"Health Stats",
            description=f"**Level:** {level} | **Players:** {player_count}\n**UVH:** {uvh} | **Mayhem:** {mayhem}\n**Rank:** {target_complexity}",
            color=discord.Color.fuchsia()
        )

        found_multipliers = False
        
        for row in enemy_rows:
            row_name = row.get('row_name', 'Unknown Variant')
            values = row.get('row_value', {})
            
            # Fetch the specific friendly name for this variant
            friendly_name = await self.fetch_friendly_name(balance_key, row_name)
            
            # Fallback label if the database lookup fails
            display_field_name = friendly_name if friendly_name else f"{clean_id} ({row_name})"
            
            multipliers = {k: v for k, v in values.items() if k.startswith("healthmultiplier")}
            
            # Check if Bar 1 exists. If not, default it to 1.0.
            if "healthmultiplier_01" not in multipliers:
                multipliers["healthmultiplier_01"] = "1.0"

            found_multipliers = True
            lines = []
            
            for m_key in sorted(multipliers.keys()):
                base_val = float(multipliers[m_key])
                final_hp = calc_enemy_health(base_val, level, uvh_scale, mayhem_scale, player_scale)
                
                bar_num = m_key.split('_')[-1] 
                lines.append(f"**Bar {bar_num}:** {final_hp:,.0f}")
                
            embed.add_field(name=display_field_name, value="\n".join(lines), inline=False)

        if not found_multipliers:
             await interaction.followup.send(f"Found data for `{clean_id}`, but it contained no health multipliers.")
        else:
            await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(EnemyData(bot))
    print("✅ Cog 'EnemyData Commands' loaded.")