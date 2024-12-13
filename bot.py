import discord
from discord.ext import commands
from discord.ui import Button, View
from discord import app_commands
import yt_dlp as youtube_dl
import asyncio
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Get the token
TOKEN = os.getenv("DISCORD_TOKEN")

# Ensure the token is loaded
if not TOKEN:
    raise ValueError("DISCORD_TOKEN not found in the environment. Check your .env file.")

# Define intents
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.voice_states = True
intents.message_content = True

# Initialize the bot with intents
bot = commands.Bot(command_prefix="#", intents=intents)
tree = bot.tree  # Slash commands handler

# Global variables
queues = {}
current_song = {}

# Event for bot readiness
@bot.event
async def on_ready():
    await tree.sync()  # Sync slash commands
    print(f"Bot is ready as {bot.user}")

# Helper function to get the queue for the guild
def get_queue(guild):
    if guild.id not in queues:
        queues[guild.id] = []
    return queues[guild.id]

# Command to join the voice channel
@bot.command(name="join")
async def join(ctx):
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        await channel.connect()
        await ctx.send("Joined your voice channel!")
    else:
        await ctx.send("You're not in a voice channel!")

@tree.command(name="join", description="Join your voice channel")
async def join_slash(interaction: discord.Interaction):
    if interaction.user.voice:
        channel = interaction.user.voice.channel
        await channel.connect()
        await interaction.response.send_message("Joined your voice channel!")
    else:
        await interaction.response.send_message("You're not in a voice channel!", ephemeral=True)

# Command to play a song
@bot.command(name="play", aliases=["p", "P", "Play"])
async def play(ctx, *, query: str):
    await play_song(ctx, query)

@tree.command(name="play", description="Play a song in your voice channel")
async def play_slash(interaction: discord.Interaction, query: str):
    await play_song(interaction, query, slash=True)

async def play_song(ctx, query, slash=False):
    # Check if user is in a voice channel
    if slash:
        if not ctx.user.voice:
            await ctx.response.send_message("You're not in a voice channel!", ephemeral=True)
            return
    else:
        if not ctx.author.voice:
            await ctx.send("You're not in a voice channel!")
            return

    # Ensure bot is in a voice channel
    if not (ctx.guild.voice_client and ctx.guild.voice_client.is_connected()):
        voice_channel = ctx.author.voice.channel if not slash else ctx.user.voice.channel
        await voice_channel.connect()

    # Fetch song details from YouTube
    ydl_opts = {'format': 'bestaudio', 'noplaylist': True, 'quiet': True}
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(f"ytsearch:{query}", download=False)
            if not info or 'entries' not in info or len(info['entries']) == 0:
                response = "No results found!"
                if slash:
                    await ctx.response.send_message(response, ephemeral=True)
                else:
                    await ctx.send(response)
                return

            # Extract song details
            song_info = info['entries'][0]
            url = song_info['url']
            title = song_info['title']
            thumbnail = song_info['thumbnails'][0]['url']

            # Add song to queue
            queue = get_queue(ctx.guild)
            queue.append({"url": url, "title": title, "thumbnail": thumbnail})

            # Play song if queue was empty
            if len(queue) == 1:
                await play_next(ctx.guild, ctx)

            # Create embed and buttons
            embed = discord.Embed(
                title="Added to Queue",
                description=f"[{title}]({url})",
                color=discord.Color.blue()
            ).set_thumbnail(url=thumbnail)

            view = create_playback_controls()

            # Send response
            if slash:
                await ctx.response.send_message(embed=embed, view=view)
            else:
                await ctx.send(embed=embed, view=view)

        except Exception as e:
            error_msg = f"Error: {e}"
            print(error_msg)
            if slash:
                await ctx.response.send_message(error_msg, ephemeral=True)
            else:
                await ctx.send(error_msg)

# Function to play the next song in the queue
async def play_next(guild, ctx=None):
    queue = get_queue(guild)
    if len(queue) == 0:
        await guild.voice_client.disconnect()
        return

    song = queue[0]
    ffmpeg_opts = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn'
    }
    try:
        source = await discord.FFmpegOpusAudio.from_probe(song['url'], **ffmpeg_opts)

        current_song[guild.id] = song
        queue.pop(0)  # Remove the song from the queue

        def after_playing(_):
            asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop).result()

        guild.voice_client.play(source, after=after_playing)

        if ctx:
            # Inform the user about the current song
            await ctx.send(
                embed=discord.Embed(
                    title="Now Playing",
                    description=f"[{song['title']}]({song['url']})",
                    color=discord.Color.green()
                ).set_thumbnail(url=song['thumbnail'])
            )
    except Exception as e:
        print(f"Error playing next song: {e}")
        if ctx:
            await ctx.send(f"Error playing next song: {e}")

# Command to pause playback
@bot.command(name="pause")
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("Playback paused!")
    else:
        await ctx.send("No song is currently playing!")

@tree.command(name="pause", description="Pause the current playback")
async def pause_slash(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        interaction.guild.voice_client.pause()
        await interaction.response.send_message("Playback paused!")
    else:
        await interaction.response.send_message("No song is currently playing!", ephemeral=True)

# Command to resume playback
@bot.command(name="resume")
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("Playback resumed!")
    else:
        await ctx.send("No song is currently paused!")

@tree.command(name="resume", description="Resume the paused playback")
async def resume_slash(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_paused():
        interaction.guild.voice_client.resume()
        await interaction.response.send_message("Playback resumed!")
    else:
        await interaction.response.send_message("No song is currently paused!", ephemeral=True)

# Command to skip to the next song
@bot.command(name="skip")
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("Skipped to the next song!")
    else:
        await ctx.send("No song is currently playing!")

@tree.command(name="skip", description="Skip to the next song in the queue")
async def skip_slash(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("Skipped to the next song!")
    else:
        await interaction.response.send_message("No song is currently playing!", ephemeral=True)

# Command to stop playback
@bot.command(name="stop")
async def stop(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        queues[ctx.guild.id] = []
        current_song.pop(ctx.guild.id, None)
        await ctx.send("Stopped playback and cleared the queue!")
    else:
        await ctx.send("I'm not in a voice channel!")

@tree.command(name="stop", description="Stop playback and clear the queue")
async def stop_slash(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        queues[interaction.guild.id] = []
        current_song.pop(interaction.guild.id, None)
        await interaction.response.send_message("Stopped playback and cleared the queue!")
    else:
        await interaction.response.send_message("I'm not in a voice channel!", ephemeral=True)

# Function to create playback controls
def create_playback_controls():
    view = View(timeout=None)

    play_button = Button(label="Play", style=discord.ButtonStyle.green, custom_id="play")
    pause_button = Button(label="Pause", style=discord.ButtonStyle.grey, custom_id="pause")
    skip_button = Button(label="Skip", style=discord.ButtonStyle.blurple, custom_id="skip")
    stop_button = Button(label="Stop", style=discord.ButtonStyle.red, custom_id="stop")

    view.add_item(play_button)
    view.add_item(pause_button)
    view.add_item(skip_button)
    view.add_item(stop_button)
    return view

# Event to handle button interactions
@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data["custom_id"]

        if custom_id == "play":
            if interaction.guild.voice_client and interaction.guild.voice_client.is_paused():
                interaction.guild.voice_client.resume()
                await interaction.response.send_message("Resumed playback!", ephemeral=True)
        elif custom_id == "pause":
            if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
                interaction.guild.voice_client.pause()
                await interaction.response.send_message("Paused playback!", ephemeral=True)
        elif custom_id == "skip":
            if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
                interaction.guild.voice_client.stop()
                await interaction.response.send_message("Skipped to the next song!", ephemeral=True)
        elif custom_id == "stop":
            if interaction.guild.voice_client:
                await interaction.guild.voice_client.disconnect()
                queues[interaction.guild.id] = []
                current_song.pop(interaction.guild.id, None)
                await interaction.response.send_message("Stopped playback and cleared the queue!", ephemeral=True)

# Run the bot
bot.run(TOKEN)
