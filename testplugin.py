"""
test.py — Test Plugin
A simple plugin to verify the plugin system is working correctly.
Commands:
  !ping      — responds with Pong + latency
  !info      — shows bot info
  !echo <text> — echoes back the message
"""

from discord.ext import commands
import discord
import time

# ─── Cog ──────────────────────────────────────────────────────────────────────

class TestCog(commands.Cog, name="Test"):
    def __init__(self, bot):
        self.bot = bot
        self.loaded_at = time.time()
        print("[Plugin:test] TestCog initialized")

    @commands.command(name="ping")
    async def ping(self, ctx):
        """Check bot latency."""
        latency = round(self.bot.latency * 1000)
        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"Latency: **{latency}ms**",
            color=0x4fffb0
        )
        await ctx.send(embed=embed)

    @commands.command(name="echo")
    async def echo(self, ctx, *, text: str):
        """Echo a message back."""
        embed = discord.Embed(
            description=f"💬 {text}",
            color=0x4fb8ff
        )
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="info")
    async def info(self, ctx):
        """Show bot and plugin info."""
        uptime = round(time.time() - self.loaded_at)
        embed = discord.Embed(title="ℹ️ Bot Info", color=0x4fffb0)
        embed.add_field(name="Bot", value=str(self.bot.user), inline=True)
        embed.add_field(name="Servers", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Plugin uptime", value=f"{uptime}s", inline=True)
        embed.add_field(name="Latency", value=f"{round(self.bot.latency * 1000)}ms", inline=True)
        await ctx.send(embed=embed)

    @echo.error
    async def echo_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ Usage: `!echo <text>`")

# ─── Setup / Teardown ─────────────────────────────────────────────────────────

async def setup(bot):
    await bot.add_cog(TestCog(bot))
    print("[Plugin:test] Loaded ✓")

async def teardown(bot):
    await bot.remove_cog("Test")
    print("[Plugin:test] Unloaded ✓")