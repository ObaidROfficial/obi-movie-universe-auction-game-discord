import asyncio
import logging

import discord
from discord.ext import commands

import db
from config import DISCORD_TOKEN

logging.basicConfig(level=logging.INFO)

INITIAL_EXTENSIONS = [
    "cogs.universe_cog",
    "cogs.auction_cog",
]


class MovieAuctionBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await db.init_db()
        for ext in INITIAL_EXTENSIONS:
            await self.load_extension(ext)
        # Global sync -- can take up to ~1hr to appear everywhere the first time.
        # For instant updates while developing, set a TEST_GUILD_ID env var and
        # sync to that guild instead (see README).
        synced = await self.tree.sync()
        logging.info(f"Synced {len(synced)} slash commands globally.")

    async def on_ready(self):
        logging.info(f"Logged in as {self.user} (id: {self.user.id})")


async def main():
    bot = MovieAuctionBot()
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
