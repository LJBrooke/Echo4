import json
import discord
from discord import app_commands
from discord.ext import commands
import math

# --- SCALING LOGIC ---

def calc_enemy_health(base: float, level: int, uvh_scale: float, player_scale: float) -> int:
    """
    Calculates final health. 
    Formula: Base * 80 * PlayerScale * UVHScale * ((1.09 ^ Level) * (1 + 0.02*Level))
    """
    print(f"Calculating health with base={base}, level={level}, uvh_scale={uvh_scale}, player_scale={player_scale}")
    # Scaling logic from your uploaded file
    level_multiplier = (1.09 ** level) * (1 + (0.02 * level))
    
    final_health = base * 80 * player_scale * uvh_scale * level_multiplier
    return int(final_health)


class EnemyData(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- AUTOCOMPLETE ---
    
    async def enemy_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        # Access db_pool through self.bot
        async with self.bot.db_pool.acquire() as conn:
            query = """
                WITH valid_tables AS (
                    SELECT 
                        entry_key as table_key,
                        -- Extract ID: remove 'table_' (6 chars) and '_balance' (8 chars)
                        substring(entry_key FROM 7 FOR length(entry_key) - 14) as enemy_id
                    FROM gbx_ue_data_table
                    WHERE entry_key LIKE 'table_%_balance'
                )
                SELECT 
                    vt.table_key,
                    vt.enemy_id,
                    -- Try to find a friendly name, fallback to NULL
                    (SELECT substring(text FROM ',\s+([^,]+)$') 
                     FROM display_data 
                     WHERE entry_key = 'name_' || vt.enemy_id 
                     LIMIT 1) as friendly_name
                FROM valid_tables vt
                WHERE 
                    vt.enemy_id ILIKE $1 OR 
                    vt.table_key ILIKE $1
                LIMIT 25;
            """
            results = await conn.fetch(query, f"%{current}%")

        choices = []
        for r in results:
            name = r['friendly_name']
            eid = r['enemy_id']
            full_key = r['table_key']
            
            # Format: "Friendly Name (ID)" or just "ID"
            display_str = f"{name} ({eid})" if name else eid
            
            # Discord choice limit is 100 chars
            choices.append(app_commands.Choice(name=display_str[:100], value=full_key))
        
        return choices

    # async def enemy_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    #     async with self.bot.db_pool.acquire() as conn:
    #         # We use a CASE statement inside jsonb_array_elements to prevent 
    #         # crashing on rows that aren't arrays (Scalars).
    #         query = """
    #             SELECT DISTINCT
    #                 t.entry_key,
    #                 r.value->>'row_name' as variant_name
    #             FROM gbx_ue_data_table t
    #             CROSS JOIN LATERAL jsonb_array_elements(
    #                 CASE 
    #                     WHEN jsonb_typeof(t.data) = 'array' THEN t.data 
    #                     ELSE '[]'::jsonb 
    #                 END
    #             ) r
    #             WHERE 
    #                 t.entry_key LIKE 'table_%_balance' 
    #                 AND r.value->>'row_name' ILIKE $1
    #             ORDER BY variant_name ASC
    #             LIMIT 25;
    #         """
    #         results = await conn.fetch(query, f"%{current}%")

    #     return [
    #         app_commands.Choice(name=r['variant_name'][:100], value=r['entry_key']) 
    #         for r in results
    #     ]

    # --- COMMAND ---

    @app_commands.command(name="enemy_health", description="Calculate enemy health stats.")
    @app_commands.describe(
        enemy_name="The enemy to check (search by name or ID).",
        level="The level of the enemy.",
        uvh="UVH Level (0-6). Default is 6.",
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
        app_commands.Choice(name="6", value=6)
    ])
    async def check(self, interaction: discord.Interaction, enemy_name: str, level: int, uvh: int = 6, player_count: int = 1):
        await interaction.response.defer(ephemeral=False)
        
        if not (1 <= player_count <= 4) or not (0 <= uvh <= 6):
            await interaction.followup.send("Player count must be between 1 and 4.")
            return

        async with self.bot.db_pool.acquire() as conn:
            # 1. FETCH BASE MULTIPLIERS
            enemy_query = """
                SELECT data
                FROM gbx_ue_data_table
                WHERE entry_key = $1
            """
            enemy_data = await conn.fetchval(enemy_query, enemy_name)
            
            if not enemy_data:
                await interaction.followup.send(f"Could not find data for `{enemy_name}`.")
                return
                
            # 2. DETERMINE RANK/COMPLEXITY ---
            # Extract ID from 'table_ID_balance' -> 'ID'
            # Example: table_catunique_balance -> catunique
            clean_id = enemy_name.replace("table_", "").replace("_balance", "")
            char_key = f"char_{clean_id}"

            rank_query = """
                SELECT attributes ->> 'tag_rank' 
                FROM gbxactor 
                WHERE entry_key = $1 
                LIMIT 1
            """
            tag_rank_raw = await conn.fetchval(rank_query, char_key)
            
            if not tag_rank_raw or 'Normal' in tag_rank_raw:
                target_complexity = "Normal"  # Default
            else: 
                tag_rank_raw = tag_rank_raw.lower()
                # Map the tag (e.g. Tag_Rank_Badass) to complexity (e.g. Badass)
                # Default to "Boss" if tag is missing or unknown, as per previous request
                if 'elite' in tag_rank_raw: target_complexity = "Elite"
                elif 'badass' in tag_rank_raw: target_complexity = "Badass"
                elif 'boss' in tag_rank_raw: target_complexity = "Boss"
            
            # 3. FETCH UVH SCALE
            uvh_scale = 1.0
            if uvh > 0:
                uvh_query = """
                    SELECT data 
                    FROM gbx_ue_data_table 
                    WHERE entry_key = 'table_difficulty_uvh'
                """
                uvh_json = await conn.fetchval(uvh_query)
                if uvh_json:
                    uvh_data = json.loads(uvh_json) if isinstance(uvh_json, str) else uvh_json
                    target_row = f"UVH{uvh}"
                    
                    for row in uvh_data:
                        if row.get('row_name') == target_row:
                            # FIXED: Changed 'EnemyData' back to 'enemyhealth'
                            val_str = row.get('row_value', {}).get('enemyhealth', "1.0")
                            uvh_scale = float(val_str)
                            break
            
            # 4. FETCH PLAYER SCALE
            player_scale = 1.0
            if player_count > 1:
                player_query = """
                    SELECT data 
                    FROM gbx_ue_data_table 
                    WHERE entry_key = 'enemy_health_scalars_by_player_count'
                """
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

        # --- PROCESSING ---
        
        enemy_rows = json.loads(enemy_data) if isinstance(enemy_data, str) else enemy_data
        
        embed = discord.Embed(
            title=f"Health Stats: {enemy_name.replace('table_', '').replace('_balance', '')}",
            description=f"**Level:** {level} | **Players:** {player_count} | **UVH:** {uvh}",
            color=discord.Color.fuchsia()
        )

        found_multipliers = False
        
        for row in enemy_rows:
            row_name = row.get('row_name', 'Unknown Variant')
            values = row.get('row_value', {})
            
            multipliers = {k: v for k, v in values.items() if k.startswith("healthmultiplier")}
            
            if not multipliers:
                continue

            found_multipliers = True
            lines = []
            
            for m_key in sorted(multipliers.keys()):
                base_val = float(multipliers[m_key])
                
                final_hp = calc_enemy_health(base_val, level, uvh_scale, player_scale)
                
                bar_num = m_key.split('_')[1] 
                lines.append(f"**Bar {bar_num}:** {final_hp:,.0f}")
                
            embed.add_field(name=row_name, value="\n".join(lines), inline=False)

        if not found_multipliers:
             await interaction.followup.send(f"Found data for `{enemy_name}`, but it contained no health multipliers.")
        else:
            await interaction.followup.send(embed=embed)
            
async def setup(bot: commands.Bot):
    await bot.add_cog(EnemyData(bot))
    print("✅ Cog 'EnemyData Commands' loaded.")