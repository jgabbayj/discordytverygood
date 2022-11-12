# This example requires the 'message_content' privileged intent to function.
import requests
from youtubesearchpython.__future__ import VideosSearch

import os
from lyrics_extractor import SongLyrics
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


def is_valid_youtube_url(url):
    try:
        response = requests.get(f"https://www.youtube.com/oembed?format=json&url={url}")
        if response.ok:
            return True
    except:
        return False
    return False


async def search_yt_videos(title: str) -> list:
    search = VideosSearch(title, limit=5)
    results = await search.next()
    return results["result"][:5]


async def get_yt_title_by_url(url: str) -> str:
    results = await search_yt_videos(url)
    return results[0]["title"]


async def get_lyrics(title):
    extract_lyrics = SongLyrics(os.environ.get("CSJA_API_KEY"), os.environ.get("GCS_ENGINE_ID"))
    return extract_lyrics.get_lyrics(title)["lyrics"]


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
        self.ctx = None
        self.loop_task = None
        self.song_list = []
        self.current_song = None

    async def add_song_to_queue(self, song):
        self.song_list.append(song)
        if not self.voice_client.is_playing():
            await self.play_next()
        print(f"queue {self.song_list}")

    @tasks.loop(seconds=5.0)
    async def loop(self):
        if self.voice_client:
            if not self.voice_client.is_playing():
                if self.song_list:
                    await self.play_next()
                else:
                    await self.voice_client.disconnect()
                    self.voice_client = None
                    self.loop.cancel()
                    self.loop_task = None
                    self.song_list.clear()

    async def play_next(self):
        self.current_song = None
        if self.song_list:
            song = self.song_list.pop(0)[:2]
            await self.play_now(song)
            await self.ctx.channel.send(f'playing {song[0]}')

    async def play_now(self, song, ctx=None):
        if not self.voice_client and ctx:
            await ctx.author.voice.channel.connect()
            self.ctx = ctx
            self.voice_client = ctx.voice_client
        url, self.current_song = song[:2]
        player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
        self.voice_client.play(player, after=lambda e: print(f'Player error: {e}') if e else None)
        if not self.loop_task:
            self.loop_task = self.loop.start()

    @commands.hybrid_command()
    async def search(self, ctx: commands.Context, *, title):
        """Search youtube for a song"""
        search_results = await search_yt_videos(title)
        if not search_results:
            await ctx.send(f'not found', ephemeral=True)
            return
        select = Select(placeholder="songs", options=[
            discord.SelectOption(label=x["title"][:60]+" "+x["duration"], value=str(i)) for i, x in enumerate(search_results)
        ])

        async def song_selected_callback(interaction: discord.Interaction):
            item = search_results[int(interaction.data["values"][0])]
            url = item["link"]
            title = item["title"]
            if not self.voice_client or not self.voice_client.is_playing():
                await self.play_now((url,title), ctx)
                await self.ctx.send(f'playing {url}')
            else:
                await self.add_song_to_queue((url, title))
                await self.options_message.delete()
                self.options_message = None
                await ctx.channel.send(f'{url} added to queue by {ctx.message.author.display_name}', delete_after = 5)

        select.callback = song_selected_callback
        view = View()
        view.add_item(select)
        self.options_message = await ctx.send("Choose song!", view=view, ephemeral=True)

    @commands.hybrid_command()
    async def play(self, ctx, *, url):
        """Plays from a url (almost anything youtube_dl supports)"""
        if is_valid_youtube_url(url):
            async with ctx.typing():
                title = await(get_yt_title_by_url(url))
                if not self.voice_client or not self.voice_client.is_playing():
                    await self.play_now((url, title), ctx)
                    await self.ctx.send(f'playing {url}')
                else:
                    await self.add_song_to_queue((url, title))
                    await ctx.send(f'{url} added to queue by {ctx.message.author.display_name}', delete_after=5)
        else:
            await ctx.send(f"Invalid url: {url}")

    @commands.hybrid_command()
    async def next(self, ctx):
        """Skip to the next song"""
        if self.voice_client:
            self.voice_client.stop()
            await self.play_next()
        await ctx.send('skipping..', delete_after=1)

    @commands.hybrid_command()
    async def skip(self, ctx):
        """Skip to the next song"""
        if self.voice_client:
            self.voice_client.stop()
            if not self.voice_client.is_playing():
                await self.play_next()
        await ctx.send('next')

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
        await ctx.send(f"{ctx.message.author.display_name} stopped {self.bot.user.display_name}")
        self.voice_client = None
        self.loop.cancel()
        self.loop_task = None
        self.song_list.clear()

    @commands.hybrid_command()
    async def queue(self, ctx):
        """Show songs in queue"""

        if self.song_list:
            await ctx.send("Songs in queue:\n"+"\n".join(x[1] for x in self.song_list), ephemeral=True)
        else:
            await ctx.send("No songs in queue", ephemeral=True)

    @commands.hybrid_command()
    async def lyrics(self, ctx):
        """Display lyrics for song currently playing"""

        if self.current_song:
            title = self.current_song
            print("lyrics of "+title)
            lyrics = await get_lyrics(title)
            await ctx.send(lyrics, ephemeral=True)
        else:
            await ctx.send("No song is playing", ephemeral=True)

    @search.before_invoke
    @play.before_invoke
    async def ensure_voice(self, ctx):
        print("ensure voice")
        if self.options_message is not None:
            await self.options_message.delete()
            self.options_message = None
        if self.voice_client is None:
            if not ctx.author.voice:
                await ctx.send("You are not connected to a voice channel.")
                raise commands.CommandError("Author not connected to a voice channel.")

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MusicCog(bot))