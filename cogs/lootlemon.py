import discord
from discord import app_commands
from discord.ext import commands
from urllib.parse import quote
import aiohttp # Asynchronous HTTP client
from bs4 import BeautifulSoup

class LootlemonCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Create a persistent aiohttp session for the cog
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        # Clean up the session when the cog is unloaded
        await self.session.close()

    @app_commands.command(name='lemon', description='Search the LootLemon website straight from Discord!')
    @app_commands.describe(query="The full name of the skill or item to look up.")
    async def search(self, interaction: discord.Interaction, query: str):
        # Defer the response because scraping a website can take time
        await interaction.response.defer()

        # --- Input Validation ---
        if len(query) < 3:
            await interaction.followup.send(
                f"Your query '{query}' is too short. Please use at least 3 characters.",
                ephemeral=True
            )
            return

        # --- Web Scraping Logic ---
        # URL encode the query to make it safe for a URL
        formatted_query = quote(query)
        base_link = "https://www.lootlemon.com"
        search_url = f"{base_link}/search?query={formatted_query}"

        try:
            # Use the asynchronous session to make the web request
            async with self.session.get(search_url) as response:
                if response.status != 200:
                    await interaction.followup.send(f"Error: LootLemon returned a {response.status} status code.")
                    return
                
                html_page = await response.text()
                soup = BeautifulSoup(html_page, "html.parser")
                
                # Find the container for search results
                # grid = soup.find("div",{"class":"card_grid search-result-items"})
                grid=soup.find("div",{"class":"card_grid search-results search-result-items"})
                # if not grid: grid=soup.find("div",{"class":"card_grid search-results search-result-items"})
                if not grid:
                    await interaction.followup.send(f"No results found for '{query}' on LootLemon.")
                    return

                # Find the first link within the container
                first_link = grid.find("a")
                if first_link and first_link.get("href"):
                    result_url = base_link + first_link.get("href")
                    await interaction.followup.send(result_url)
                else:
                    await interaction.followup.send(f"Found a result grid, but couldn't extract a link for '{query}'.")

        except aiohttp.ClientError:
            await interaction.followup.send("An error occurred while trying to connect to LootLemon.", ephemeral=True)
        except Exception as e:
            # Catch any other unexpected errors during scraping
            print(f"An error occurred in the lemon command: {e}")
            await interaction.followup.send("An unknown error occurred. Please contact the bot administrator.", ephemeral=True)

# Standard setup function to add the cog to the bot
async def setup(bot: commands.Bot):
    await bot.add_cog(LootlemonCommand(bot))
    print("✅ Cog 'LemonCommand' loaded.")