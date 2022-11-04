# This example requires the 'message_content' privileged intent to function.
from youtubesearchpython.__future__ import VideosSearch

import asyncio
import discord
import youtube_dl
from discord.ext import commands, tasks
from discord.ui import View, Select
# Suppress noise about console usage from errors
youtube_dl.utils.bug_reports_message = lambda: ''


ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',  # bind to ipv4 since ipv6 addresses cause issues sometimes
}

ffmpeg_options = {
    'options': '-vn',
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)


async def search_yt_videos(title: str) -> list:
    search = VideosSearch(title, limit=5)
    results = await search.next()
    return results["result"]


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)

        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.options_message = None
        self.voice_client = None
        self.printer.start()

    @tasks.loop(seconds=5.0)
    async def printer(self):
        if self.voice_client:
            print(self.voice_client.is_playing())

    @commands.hybrid_command()
    async def search(self, ctx: commands, *, title):
        """Search youtube for a song"""
        search_results = await search_yt_videos(title)
        select = Select(placeholder="songs", options=[
            discord.SelectOption(label=x["title"], value=x["link"]) for x in search_results
        ])

        async def song_selected_callback(interaction: discord.Interaction):
            if self.voice_client.is_playing():
                self.voice_client.stop()
            url = interaction.data["values"][0]
            player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
            self.voice_client.play(player, after=lambda e: print(f'Player error: {e}') if e else None)
            await interaction.response.send_message(f'{interaction.user.display_name} playing {url}')
            await self.options_message.delete()
            self.options_message = None
        select.callback = song_selected_callback
        view = View()
        view.add_item(select)
        self.options_message = await ctx.send("Choose song!", view=view, ephemeral=True)

    @commands.hybrid_command()
    async def play(self, ctx, *, url):
        """Plays from a url (almost anything youtube_dl supports)"""

        async with ctx.typing():
            if self.voice_client.is_playing():
                self.voice_client.stop()
            player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
            self.voice_client.play(player, after=lambda e: print(f'Player error: {e}') if e else None)
        await ctx.send(f'{ctx.message.author.display_name} playing: {url}')

    @commands.hybrid_command()
    async def volume(self, ctx, volume: int):
        """Changes the player's volume"""

        if self.voice_client is None:
            return await ctx.send("Not connected to a voice channel.")

        self.voice_client.source.volume = volume / 100
        await ctx.send(f"Changed volume to {volume}%")

    @commands.hybrid_command()
    async def stop(self, ctx):
        """Stops and disconnects the bot from voice"""
        if self.voice_client:
            await self.voice_client.disconnect()
        await ctx.send(f"{ctx.message.author.display_name} stopped {self.bot.user}")
        self.voice_client = None

    @search.before_invoke
    @play.before_invoke
    async def ensure_voice(self, ctx):
        if self.options_message is not None:
            await self.options_message.delete()
            self.options_message = None
        if ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
                self.voice_client = ctx.voice_client
            else:
                await ctx.send("You are not connected to a voice channel.")
                raise commands.CommandError("Author not connected to a voice channel.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MusicCog(bot))