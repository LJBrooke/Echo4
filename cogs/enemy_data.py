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

# --- SHARED APP COMMAND CHOICES ---
RANK_CHOICES = [
    app_commands.Choice(name="Normal", value="Normal"),
    app_commands.Choice(name="Elite", value="Elite"),
    app_commands.Choice(name="Badass", value="Badass"),
    app_commands.Choice(name="Boss", value="Boss")
]

UVH_CHOICES = [app_commands.Choice(name=str(i), value=i) for i in range(8)]
MAYHEM_CHOICES = [app_commands.Choice(name=str(i), value=i) for i in range(21)]
PLAYER_CHOICES = [app_commands.Choice(name=str(i), value=i) for i in range(1, 5)]

SHOW_ALL_CHOICES = [
    app_commands.Choice(name="Yes", value=1),
    app_commands.Choice(name="No", value=2)
]

def calc_enemy_health(base: float, level: int, uvh_scale: float, mayhem_scale: float, player_scale: float) -> int:
    # Formula: Base * 80 * PlayerScale * UVHScale * ((1.09 ^ Level) * (1 + 0.02*Level))
    level_multiplier = (1.09 ** level) * (1 + (0.02 * level))
    final_health = base * 80 * player_scale * uvh_scale * mayhem_scale * level_multiplier
    return int(final_health)

class EnemyData(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- SCALE FETCHING FUNCTIONS ---
    async def get_uvh_scale(self, conn, uvh: int) -> float:
        if uvh <= 0:
            return 1.0
        uvh_query = "SELECT data FROM gbx_ue_data_table WHERE entry_key = 'table_difficulty_uvh'"
        uvh_json = await conn.fetchval(uvh_query)
        if uvh_json:
            uvh_data = json.loads(uvh_json) if isinstance(uvh_json, str) else uvh_json
            target_row = f"UVH{uvh}"
            for row in uvh_data:
                if row.get('row_name') == target_row:
                    return float(row.get('row_value', {}).get('enemyhealth', "1.0"))
        return 1.0

    async def get_mayhem_scale(self, conn, mayhem: int) -> float:
        if mayhem <= 0:
            return 1.0
        mayhem_query = "SELECT data FROM gbx_ue_data_table WHERE entry_key = 'table_difficulty_mayhem' order by internal_id asc limit 1"
        mayhem_json = await conn.fetchval(mayhem_query)
        if mayhem_json:
            mayhem_data = json.loads(mayhem_json) if isinstance(mayhem_json, str) else mayhem_json
            target_row = f"Mayhem{mayhem}"
            for row in mayhem_data:
                if row.get('row_name') == target_row:
                    return float(row.get('row_value', {}).get('enemyhealth', "1.0"))
        return 1.0

    async def get_player_scales(self, conn, target_complexity: str) -> dict:
        player_scales = {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0}
        player_query = "SELECT data FROM gbx_ue_data_table WHERE entry_key = 'enemy_health_scalars_by_player_count'"
        player_json = await conn.fetchval(player_query)
        
        if player_json:
            p_data = json.loads(player_json) if isinstance(player_json, str) else player_json
            p_map = {1: "oneplayer", 2: "twoplayers", 3: "threeplayers", 4: "fourplayers"}
            
            for row in p_data:
                if row.get('row_name') == target_complexity:
                    row_vals = row.get('row_value', {})
                    for pc in range(1, 5):
                        p_key = p_map[pc]
                        player_scales[pc] = float(row_vals.get(p_key, {}).get('constant', "1.0"))
                    break
        return player_scales

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

    async def get_health_types(self, row_name: str, balance_path: str) -> list[dict]:
        # 1. The initial query uses the datatable and rowname
        initial_query = """
            SELECT attributes ->> 'healthtypes' AS healthtypes, 
                attributes ->> 'parent' AS parent
            FROM gbxactor 
            WHERE balance_data -> 'balancetablerowhandle' ->> 'rowname' = $1 
            AND lower(balance_data -> 'balancetablerowhandle' ->> 'datatable') = lower($2::text);
        """
        
        # 2. The parent query only needs the entry_key
        parent_query = """
            SELECT attributes ->> 'healthtypes' AS healthtypes, 
                attributes ->> 'parent' AS parent
            FROM gbxactor 
            WHERE entry_key = lower($1::text);
        """
        
        # This will hold lists of healthtypes arrays. 
        # By prepending parents, index 0 will always be the oldest ancestor.
        collected_health_types = []
        
        async with self.bot.db_pool.acquire() as conn:
            # Fetch the base child object
            current_row = await conn.fetchrow(initial_query, row_name, balance_path)
            
            # Traverse up the parent chain
            while current_row:
                # Process and store the current row's health types
                ht_raw = current_row['healthtypes']
                if ht_raw:
                    ht_data = json.loads(ht_raw)
                    if isinstance(ht_data, list):
                        # Prepend so ancestors get pushed to the front of the line
                        collected_health_types.insert(0, ht_data)
                
                # Check if a parent exists to continue the loop
                parent_raw = current_row['parent']
                if parent_raw and parent_raw.startswith("gbxactor'"):
                    # Extract 'Char_Thresher_SHARED' from "gbxactor'Char_Thresher_SHARED'"
                    parent_key = parent_raw.split("'")[1]
                    
                    # Run the parent query and update current_row for the next loop iteration
                    current_row = await conn.fetchrow(parent_query, parent_key)
                else:
                    # No parent found, or format is unrecognized; break the loop
                    break
                    
        # 3. Flatten our list of lists into a single continuous list of dictionaries
        final_health_types = []
        for ht_list in collected_health_types:
            final_health_types.extend(ht_list)
            
        return final_health_types[-3:]
                
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
        
    # --- COMMANDS ---

    @app_commands.command(name="enemy_health", description="Calculate enemy health stats.")
    @app_commands.describe(
        enemy_name="The enemy to check (search by name or ID).",
        level="The level of the enemy.",
        uvh="UVH Level (0-7). Default is 7.",
        mayhem="Mayhem Level (0-20). Default is 0.",
        player_count="Number of players (1-4). Default is 1."
    )
    @app_commands.autocomplete(enemy_name=enemy_autocomplete)
    @app_commands.choices(
        player_count=PLAYER_CHOICES,
        uvh=UVH_CHOICES,
        mayhem=MAYHEM_CHOICES,
        show_all=SHOW_ALL_CHOICES
    )
    async def check(self, interaction: discord.Interaction, enemy_name: str, level: int, uvh: int = 7, mayhem: int = 0, player_count: int = 1, show_all: int = 2):
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

            # 3. FETCH SCALES VIA HELPERS
            uvh_scale = await self.get_uvh_scale(conn, uvh)
            mayhem_scale = await self.get_mayhem_scale(conn, mayhem)
            if mayhem > 0:
                uvh_scale = 1.0 # Mayhem overrides UVH
                
            all_player_scales = await self.get_player_scales(conn, target_complexity)
            player_scale = all_player_scales.get(player_count, 1.0)

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
        
        field_count=0
        for row in enemy_rows:
            if field_count >= 24:
                embed.add_field(name="Clanker issue", value="Only the first 24 variants are displayed. Some variants may be omitted.", inline=False)
                break
            row_name = row.get('row_name', 'Unknown Variant')
            values = row.get('row_value', {})
            
            multipliers = {k: v for k, v in values.items() if k.startswith("healthmultiplier")}
            
            # 1. Check for _TRUE and setup the base row name for the database query
            is_true_variant = False
            query_row_name = row_name

            if row_name.endswith("_TRUE"):
                is_true_variant = True
                # Strip off the last 5 characters ("_TRUE") to get the base name
                query_row_name = row_name[:-5] 

            # 2. Fetch using the adjusted query_row_name so it correctly inherits
            health_type_data = await self.get_health_types(query_row_name, f"gbx_ue_data_table'{balance_key}'")
            
            # Fetch the specific friendly name for this variant
            friendly_name = await self.fetch_friendly_name(balance_key, query_row_name)
            
            # Fallback label if the database lookup fails
            display_field_name = friendly_name if friendly_name else f"{clean_id} ({row_name})"

            # Check if Bar 1 exists. If not, default it to 1.0.
            if "healthmultiplier_01" not in multipliers:
                multipliers["healthmultiplier_01"] = "1.0"

            found_multipliers = True
            lines = []

            for m_key in sorted(multipliers.keys()):
                # Convert '01' to integer 1 for the label, and use it to find the 0-based array index
                bar_num = int(m_key.split('_')[-1]) 
                list_index = bar_num - 1
                
                # Only process this multiplier if a corresponding entry exists in the healthtypes list
                if list_index < len(health_type_data):
                    raw_health_string = health_type_data[list_index].get("healthtype", "")
                    prefix = "healthtype'HealthType_AI_"
                    
                    if raw_health_string.startswith(prefix):
                        # Slice off the prefix and the trailing single quote
                        clean_health_type = raw_health_string[len(prefix):-1]
                    else:
                        clean_health_type = raw_health_string 
                    
                    base_val = float(multipliers[m_key])
                    final_hp = calc_enemy_health(base_val, level, uvh_scale, mayhem_scale, player_scale)
                    
                    # Build the formatted string: "**Bar 1 (Armor):** 10,000"
                    lines.append(f"**Bar {bar_num} ({clean_health_type}):** {final_hp:,.0f}")
                elif show_all==1:                   
                    base_val = float(multipliers[m_key])
                    final_hp = calc_enemy_health(base_val, level, uvh_scale, mayhem_scale, player_scale)
                    
                    # Build the formatted string: "**Bar 1 (Armor):** 10,000"
                    lines.append(f"**Bar {bar_num} (Unknown):** {final_hp:,.0f}")
                    
            if lines:
                # 3. Handle the "Big Encore" naming logic for _TRUE variants
                if is_true_variant:
                    if not display_field_name.startswith("Big Encore"):
                        display_field_name = f"Big Encore {display_field_name}"

                embed.add_field(name=display_field_name, value="\n".join(lines), inline=False)
                field_count += 1

        if not found_multipliers:
             await interaction.followup.send(f"Found data for `{clean_id}`, but it contained no health multipliers.")
        else:
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="calc_health", description="Calculate health using a custom base value for modding.")
    @app_commands.describe(
        base_value="The custom base health value.",
        level="The level of the enemy.",
        enemy_rank="The rank of the enemy.",
        uvh="UVH Level (0-7). Default is 7.",
        mayhem="Mayhem Level (0-20). Default is 0."
    )
    @app_commands.choices(
        enemy_rank=RANK_CHOICES,
        uvh=UVH_CHOICES, 
        mayhem=MAYHEM_CHOICES
    )
    async def custom_health(
        self, 
        interaction: discord.Interaction, 
        base_value: float, 
        level: int, 
        enemy_rank: app_commands.Choice[str], 
        uvh: int = 7, 
        mayhem: int = 0
    ):
        await interaction.response.defer(ephemeral=False)
        
        target_complexity = getattr(enemy_rank, 'value', enemy_rank)

        async with self.bot.db_pool.acquire() as conn:
            # SCALES VIA HELPERS
            uvh_scale = await self.get_uvh_scale(conn, uvh)
            mayhem_scale = await self.get_mayhem_scale(conn, mayhem)
            if mayhem > 0:
                uvh_scale = 1.0 # Mayhem overrides UVH
                
            player_scales = await self.get_player_scales(conn, target_complexity)

        # CALCULATE AND FORMAT OUTPUT
        lines = []
        for pc in range(1, 5):
            final_hp = calc_enemy_health(base_value, level, uvh_scale, mayhem_scale, player_scales[pc])
            lines.append(f"**{pc} Player{'s' if pc > 1 else ''}:** {final_hp:,.0f}")

        embed = discord.Embed(
            title="Custom Health Calculation",
            description=f"**Base Value:** {base_value:,.2f} | **Level:** {level}\n**UVH:** {uvh} | **Mayhem:** {mayhem}\n**Rank:** {target_complexity}",
            color=discord.Color.brand_green()
        )
        embed.add_field(name="HP Scaling", value="\n".join(lines), inline=False)
        
        # --- CALCULATION BREAKDOWN EMBED ---
        level_multiplier = (1.09 ** level) * (1 + (0.02 * level))
        example_hp = calc_enemy_health(base_value, level, uvh_scale, mayhem_scale, player_scales[4])
        
        calc_embed = discord.Embed(
            title="Calculation Breakdown (4-Player Example)",
            color=discord.Color.blue()
        )
        calc_embed.add_field(
            name="Value Modifiers",
            value=f"**Level Multiplier:** `(1.09 ^ {level}) x (1 + 0.02 x {level})` = {level_multiplier:.4f}\n"
                  f"**4-Player Scale:** {player_scales[4]:.4f}\n"
                  f"**UVH Scale:** {uvh_scale:.4f}\n"
                  f"**Mayhem Scale:** {mayhem_scale:.4f}",
            inline=False
        )
        calc_embed.add_field(
            name="Values Inserted",
            value=f"`Base x 80 x PlayerScale x UVHScale x MayhemScale x LevelMultiplier`\n"
                  f"`{base_value:,.2f} * 80 * {player_scales[4]:.4f} * {uvh_scale:.4f} * {mayhem_scale:.4f} * {level_multiplier:.4f}` = **{example_hp:,.0f}**",
            inline=False
        )

        await interaction.followup.send(embeds=[embed, calc_embed])


    @app_commands.command(name="reverse_calc_health", description="Calculate the required base health to hit a target HP.")
    @app_commands.describe(
        target_hp="The final HP number you want to achieve.",
        level="The level of the enemy.",
        enemy_rank="The rank of the enemy.",
        uvh="UVH Level (0-7). Default is 7.",
        mayhem="Mayhem Level (0-20). Default is 0."
    )
    @app_commands.choices(
        enemy_rank=RANK_CHOICES,
        uvh=UVH_CHOICES, 
        mayhem=MAYHEM_CHOICES
    )
    async def reverse_health(
        self, 
        interaction: discord.Interaction, 
        target_hp: int, 
        level: int, 
        enemy_rank: app_commands.Choice[str], 
        uvh: int = 7, 
        mayhem: int = 0
    ):
        await interaction.response.defer(ephemeral=False)
        
        target_complexity = getattr(enemy_rank, 'value', enemy_rank)

        async with self.bot.db_pool.acquire() as conn:
            # SCALES VIA HELPERS
            uvh_scale = await self.get_uvh_scale(conn, uvh)
            mayhem_scale = await self.get_mayhem_scale(conn, mayhem)
            if mayhem > 0:
                uvh_scale = 1.0 # Mayhem overrides UVH
                
            player_scales = await self.get_player_scales(conn, target_complexity)

        # REVERSE ENGINEER BASE VALUES
        level_multiplier = (1.09 ** level) * (1 + (0.02 * level))
        lines = []
        
        for pc in range(1, 5):
            # Formula inversion: base = target_hp / (80 * player * uvh * mayhem * level_mult)
            total_scaler = 80 * player_scales[pc] * uvh_scale * mayhem_scale * level_multiplier
            req_base = target_hp / total_scaler if total_scaler > 0 else 0
            lines.append(f"**{pc} Player{'s' if pc > 1 else ''}:** {req_base:,.2f}")

        embed = discord.Embed(
            title="Reverse Health Calculation",
            description=f"**Target HP:** {target_hp:,} | **Level:** {level}\n**UVH:** {uvh} | **Mayhem:** {mayhem}\n**Rank:** {target_complexity}",
            color=discord.Color.brand_red()
        )
        embed.add_field(name="Required Base Values", value="\n".join(lines), inline=False)
        
        # --- CALCULATION BREAKDOWN EMBED ---
        total_scaler_4 = 80 * player_scales[4] * uvh_scale * mayhem_scale * level_multiplier
        example_base = target_hp / total_scaler_4 if total_scaler_4 > 0 else 0
        
        calc_embed = discord.Embed(
            title="Reverse Calculation Breakdown (4-Player Example)",
            color=discord.Color.blue()
        )
        calc_embed.add_field(
            name="Value Modifiers",
            value=f"**Level Multiplier:** `(1.09 ^ {level}) x (1 + 0.02 x {level})` = {level_multiplier:.4f}\n"
                  f"**4-Player Scale:** {player_scales[4]:.4f}\n"
                  f"**UVH Scale:** {uvh_scale:.4f}\n"
                  f"**Mayhem Scale:** {mayhem_scale:.4f}",
            inline=False
        )
        calc_embed.add_field(
            name="Values Inserted",
            value=f"`TargetHP / (80 x PlayerScale x UVHScale x MayhemScale x LevelMultiplier)`\n"
                  f"`{target_hp:,} / (80 * {player_scales[4]:.4f} * {uvh_scale:.4f} * {mayhem_scale:.4f} * {level_multiplier:.4f})` = **{example_base:,.2f}**",
            inline=False
        )

        await interaction.followup.send(embeds=[embed, calc_embed])

async def setup(bot: commands.Bot):
    await bot.add_cog(EnemyData(bot))
    print("✅ Cog 'EnemyData Commands' loaded.")