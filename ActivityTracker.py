"""
activity_tracker.py — Activity Tracker Plugin
Každých 12 hodin pošle report o aktivitě členů do nastaveného kanálu.
Sleduje počet zpráv každého uživatele od posledního reportu.
"""

import asyncio
import discord
from discord.ext import commands, tasks
from collections import defaultdict
from datetime import datetime, timezone

# ─── Konfigurace ──────────────────────────────────────────────────────────────

ACTIVITY_CHANNEL_ID = 1480194831644098600
INTERVAL_HOURS = 12

# ─── Cog ──────────────────────────────────────────────────────────────────────

class ActivityTracker(commands.Cog, name="ActivityTracker"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # { user_id: { "count": int, "name": str } }
        self.message_counter: dict[int, dict] = defaultdict(lambda: {"count": 0, "name": ""})
        self.activity_loop.start()
        print("[Plugin:activity_tracker] Spuštěn – report každých 12 hodin.")

    def cog_unload(self):
        self.activity_loop.cancel()
        print("[Plugin:activity_tracker] Zastaven.")

    # ─── Poslouchej zprávy ────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignoruj boty
        if message.author.bot:
            return
        uid = message.author.id
        self.message_counter[uid]["count"] += 1
        self.message_counter[uid]["name"] = message.author.display_name

    # ─── 12h smyčka ───────────────────────────────────────────────────────────

    @tasks.loop(hours=INTERVAL_HOURS)
    async def activity_loop(self):
        await self.send_activity_report()

    @activity_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

    # ─── Sestavení embedů ─────────────────────────────────────────────────────

    def build_activity_embeds(self) -> list[discord.Embed]:
        now = datetime.now(timezone.utc)

        if not self.message_counter:
            embed = discord.Embed(
                title="📊 Activity Check – Posledních 12 hodin",
                description="> ❌ Nikdo nenapsal žádnou zprávu za posledních 12 hodin.",
                color=0xff4444,
                timestamp=now,
            )
            embed.set_footer(text="HexBot • Activity Check")
            return [embed]

        # Seřadit podle počtu zpráv
        sorted_users = sorted(
            self.message_counter.items(),
            key=lambda x: x[1]["count"],
            reverse=True,
        )

        def czech_word(count: int) -> str:
            if count == 1:
                return "zpráva"
            elif count < 5:
                return "zprávy"
            return "zpráv"

        def medal(index: int) -> str:
            return ["🥇", "🥈", "🥉"][index] if index < 3 else f"**{index + 1}.**"

        lines = [
            f"{medal(i)} <@{uid}> — **{data['count']}** {czech_word(data['count'])}"
            for i, (uid, data) in enumerate(sorted_users)
        ]

        # Rozděl na chunky po 25 řádcích (Discord limit)
        chunks = [lines[i:i + 25] for i in range(0, len(lines), 25)]
        embeds = []

        for i, chunk in enumerate(chunks):
            embed = discord.Embed(color=0x5865f2, timestamp=now)
            suffix = f" ({i + 1}/{len(chunks)})" if len(chunks) > 1 else ""
            embed.set_footer(text=f"HexBot • Activity Check{suffix}")

            if i == 0:
                embed.title = "📊 Activity Check – Posledních 12 hodin"
                embed.description = (
                    f"Celkem aktivních členů: **{len(sorted_users)}**\n\n"
                    + "\n".join(chunk)
                )
            else:
                embed.description = "\n".join(chunk)

            embeds.append(embed)

        return embeds

    # ─── Odeslání reportu ─────────────────────────────────────────────────────

    async def send_activity_report(self):
        channel = self.bot.get_channel(ACTIVITY_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(ACTIVITY_CHANNEL_ID)
            except discord.NotFound:
                print("❌ [activity_tracker] Kanál nebyl nalezen.")
                return
            except discord.Forbidden:
                print("❌ [activity_tracker] Nemám přístup ke kanálu.")
                return

        if not isinstance(channel, discord.TextChannel):
            print("❌ [activity_tracker] Kanál není textový.")
            return

        embeds = self.build_activity_embeds()
        for embed in embeds:
            await channel.send(embed=embed)

        count = len(self.message_counter)
        print(f"✅ [activity_tracker] Report odeslán – {count} uživatelů.")
        self.message_counter.clear()

    # ─── Manuální příkazy ─────────────────────────────────────────────────────

    @commands.command(name="activity")
    @commands.has_permissions(administrator=True)
    async def activity_cmd(self, ctx: commands.Context, subcommand: str = "report"):
        """
        Správa activity trackeru.
        Použití:
          !activity report   – odešle report ihned
          !activity stats    – zobrazí aktuální statistiky zde
          !activity reset    – resetuje čítače bez odeslání
        """
        if subcommand == "report":
            await ctx.send("📤 Odesílám activity report...")
            await self.send_activity_report()
            await ctx.send("✅ Hotovo.")

        elif subcommand == "stats":
            embeds = self.build_activity_embeds()
            for embed in embeds:
                await ctx.send(embed=embed)

        elif subcommand == "reset":
            count = len(self.message_counter)
            self.message_counter.clear()
            await ctx.send(f"🗑️ Čítače resetovány. Bylo smazáno **{count}** záznamů.")

        else:
            await ctx.send(
                "❓ Neznámý příkaz. Použití: `!activity report` | `!activity stats` | `!activity reset`"
            )

    @activity_cmd.error
    async def activity_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ Potřebuješ oprávnění administrátora.")


# ─── Setup / Teardown ─────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(ActivityTracker(bot))
    print("[Plugin:activity_tracker] Načten ✓")

async def teardown(bot: commands.Bot):
    await bot.remove_cog("ActivityTracker")
    print("[Plugin:activity_tracker] Odpojen ✓")