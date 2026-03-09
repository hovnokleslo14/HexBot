"""
hex_info.py — HexBot Info Plugin
!hex — zobrazí všechny dostupné příkazy + statistiky bota.
"""

import discord
from discord.ext import commands
from datetime import datetime, timezone
import time
import platform
import sys

# ─── Cog ──────────────────────────────────────────────────────────────────────

class HexInfo(commands.Cog, name="HexInfo"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = time.time()
        print("[Plugin:hex_info] Načten ✓")

    def cog_unload(self):
        print("[Plugin:hex_info] Odpojen ✓")

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def format_uptime(self) -> str:
        seconds = int(time.time() - self.start_time)
        days, rem = divmod(seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, secs = divmod(rem, 60)
        parts = []
        if days:    parts.append(f"{days}d")
        if hours:   parts.append(f"{hours}h")
        if minutes: parts.append(f"{minutes}m")
        parts.append(f"{secs}s")
        return " ".join(parts)

    def get_prefix_commands(self) -> dict[str, list[commands.Command]]:
        """Vrátí příkazy seskupené podle Cog (pluginu)."""
        grouped: dict[str, list[commands.Command]] = {}
        for cmd in self.bot.commands:
            if cmd.hidden:
                continue
            cog_name = cmd.cog_name or "Ostatní"
            grouped.setdefault(cog_name, []).append(cmd)
        return grouped

    def get_slash_commands(self) -> list[discord.app_commands.AppCommand]:
        """Vrátí registrované slash příkazy."""
        return list(self.bot.tree.get_commands())

    # ─── !hex ─────────────────────────────────────────────────────────────────

    @commands.command(name="hex")
    async def hex_cmd(self, ctx: commands.Context):
        """Zobrazí všechny příkazy a statistiky bota."""

        latency_ms = round(self.bot.latency * 1000)
        uptime_str = self.format_uptime()
        guild_count = len(self.bot.guilds)
        member_count = sum(g.member_count or 0 for g in self.bot.guilds)
        prefix_cmd_count = len([c for c in self.bot.commands if not c.hidden])
        slash_cmds = self.get_slash_commands()

        # ── Embed 1: Stats ────────────────────────────────────────────────────
        stats_embed = discord.Embed(
            title="⬡ HexBot",
            description="Přehled příkazů a informace o botovi.",
            color=0x5865f2,
            timestamp=datetime.now(timezone.utc),
        )

        # Ping indikátor
        if latency_ms < 100:
            ping_icon = "🟢"
        elif latency_ms < 250:
            ping_icon = "🟡"
        else:
            ping_icon = "🔴"

        stats_embed.add_field(
            name="📡 Systém",
            value=(
                f"{ping_icon} **Ping:** `{latency_ms}ms`\n"
                f"⏱️ **Uptime:** `{uptime_str}`\n"
                f"🐍 **Python:** `{sys.version.split()[0]}`\n"
                f"📦 **discord.py:** `{discord.__version__}`"
            ),
            inline=True,
        )
        stats_embed.add_field(
            name="🌐 Statistiky",
            value=(
                f"🏠 **Serverů:** `{guild_count}`\n"
                f"👥 **Členů:** `{member_count:,}`\n"
                f"🔧 **Prefix příkazů:** `{prefix_cmd_count}`\n"
                f"✨ **Slash příkazů:** `{len(slash_cmds)}`"
            ),
            inline=True,
        )
        stats_embed.set_footer(text="HexBot • použij !hex pro obnovení")

        await ctx.send(embed=stats_embed)

        # ── Embed 2: Prefix příkazy ───────────────────────────────────────────
        grouped = self.get_prefix_commands()

        if grouped:
            prefix_embed = discord.Embed(
                title="🔧 Prefix příkazy  (`!`)",
                color=0x4fffb0,
                timestamp=datetime.now(timezone.utc),
            )

            for cog_name, cmds in sorted(grouped.items()):
                lines = []
                for cmd in sorted(cmds, key=lambda c: c.name):
                    # Aliases
                    aliases = f" *(aliasy: {', '.join(cmd.aliases)})*" if cmd.aliases else ""
                    # Popis
                    brief = cmd.brief or cmd.help or "–"
                    # Zkrátit popis
                    if len(brief) > 60:
                        brief = brief[:57] + "..."
                    lines.append(f"**`!{cmd.name}`**{aliases}\n╰ {brief}")

                if lines:
                    # Rozdělení pokud je moc dlouhé
                    chunk = "\n".join(lines)
                    if len(chunk) > 1020:
                        chunk = chunk[:1017] + "..."
                    prefix_embed.add_field(
                        name=f"📂 {cog_name}",
                        value=chunk,
                        inline=False,
                    )

            prefix_embed.set_footer(text="HexBot • Prefix příkazy")
            await ctx.send(embed=prefix_embed)

        # ── Embed 3: Slash příkazy ────────────────────────────────────────────
        if slash_cmds:
            slash_embed = discord.Embed(
                title="✨ Slash příkazy  (`/`)",
                color=0x4fb8ff,
                timestamp=datetime.now(timezone.utc),
            )

            lines = []
            for cmd in sorted(slash_cmds, key=lambda c: c.name):
                desc = cmd.description or "–"
                if len(desc) > 60:
                    desc = desc[:57] + "..."
                lines.append(f"**`/{cmd.name}`**\n╰ {desc}")

            # Rozdělení do fieldů po 10 příkazech
            chunk_size = 10
            chunks = [lines[i:i + chunk_size] for i in range(0, len(lines), chunk_size)]
            for i, chunk in enumerate(chunks):
                slash_embed.add_field(
                    name=f"Příkazy {i * chunk_size + 1}–{i * chunk_size + len(chunk)}" if len(chunks) > 1 else "Příkazy",
                    value="\n".join(chunk),
                    inline=False,
                )

            slash_embed.set_footer(text="HexBot • Slash příkazy")
            await ctx.send(embed=slash_embed)

        # ── Pokud žádné příkazy ───────────────────────────────────────────────
        if not grouped and not slash_cmds:
            empty = discord.Embed(
                description="❌ Žádné příkazy nebyly nalezeny.",
                color=0xff4444,
            )
            await ctx.send(embed=empty)

    # ─── Error handler ────────────────────────────────────────────────────────

    @hex_cmd.error
    async def hex_error(self, ctx, error):
        await ctx.send(f"❌ Chyba: `{error}`")


# ─── Setup / Teardown ─────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(HexInfo(bot))
    print("[Plugin:hex_info] Spuštěn ✓")

async def teardown(bot: commands.Bot):
    await bot.remove_cog("HexInfo")
    print("[Plugin:hex_info] Zastaven ✓")