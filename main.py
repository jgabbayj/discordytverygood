import discord
import asyncio
import os
from discord.ext import commands


class MyBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def on_ready(self):
        print(f"Logged in as {self.user}")

    async def setup_hook(self):
        for fn in os.listdir("cogs"):
            if fn.endswith(".py"):
                await self.load_extension(f"cogs.{fn[:-3]}")
        await self.tree.sync()


intents = discord.Intents.default()
intents.message_content = True
bot = MyBot(command_prefix='kobi.', intents=intents)

@bot.command()
async def sync(ctx) -> None:
    await ctx.send("Syncing...")
    res = await bot.tree.sync()
    await ctx.send(f"Synced {len(res)} commands.")

bot.run(open("token.txt").read())