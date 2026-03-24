"""
purge.py — Purge Plugin
!purge <pocet> — smaze zpravy v kanalu (pouze administrator)
Zobrazi embed s tlacitky pro potvrzeni / zruseni.
"""

import discord
from discord.ext import commands
from discord.ui import View, Button

# ─── Confirmation View ────────────────────────────────────────────────────────

class PurgeConfirmView(View):
    def __init__(self, author: discord.Member, amount: int):
        super().__init__(timeout=30)
        self.author  = author
        self.amount  = amount
        self.done    = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Pouze autor prikazu muze klikat na tlacitka."""
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "Toto tlacitko muze pouzit pouze ten, kdo zadal prikaz.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Ano, smazat", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: Button):
        self.done = True
        self.stop()

        # Disabluj tlacitka
        for child in self.children:
            child.disabled = True

        # Uprav embed na "probiha mazani"
        processing_embed = discord.Embed(
            description=f"⏳ Mazám **{self.amount}** zpráv...",
            color=0xffb84f
        )
        await interaction.response.edit_message(embed=processing_embed, view=self)

        # Smaz zpravy (+1 = vcetne samotne zpravy s embedem)
        deleted = await interaction.channel.purge(limit=self.amount + 1)
        actual  = max(len(deleted) - 1, 0)

        # Potvrzovaci zprava (zmizi po 5s)
        confirm_embed = discord.Embed(
            description=f"✅ Úspěšně smazáno **{actual}** zpráv.",
            color=0x4fffb0
        )
        confirm_embed.set_footer(text=f"Provedl: {self.author.display_name}")
        msg = await interaction.channel.send(embed=confirm_embed)
        await msg.delete(delay=5)

    @discord.ui.button(label="Zrušit", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: Button):
        self.done = True
        self.stop()

        for child in self.children:
            child.disabled = True

        cancel_embed = discord.Embed(
            description="❌ Mazání zpráv bylo zrušeno.",
            color=0x5a6a82
        )
        await interaction.response.edit_message(embed=cancel_embed, view=self)
        await interaction.message.delete(delay=4)

    async def on_timeout(self):
        """Pokud nikdo neklikne do 30s, disabluj tlacitka."""
        if self.done:
            return
        for child in self.children:
            child.disabled = True
        # Zkus upravit zpravu (nemusí existovat)
        try:
            timeout_embed = discord.Embed(
                description="⏱️ Časový limit vypršel. Akce zrušena.",
                color=0x5a6a82
            )
            await self.message.edit(embed=timeout_embed, view=self)
            await self.message.delete(delay=3)
        except Exception:
            pass


# ─── Cog ──────────────────────────────────────────────────────────────────────

class Purge(commands.Cog, name="Purge"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("[Plugin:purge] Nacteno")

    def cog_unload(self):
        print("[Plugin:purge] Odpojen")

    @commands.command(name="purge")
    @commands.has_permissions(administrator=True)
    async def purge_cmd(self, ctx: commands.Context, amount: int):
        """
        Smaze zadany pocet zprav v kanalu.
        Pouziti: !purge <pocet>
        Pouze pro administratory.
        """

        # Smaz prikaz samotny
        try:
            await ctx.message.delete()
        except Exception:
            pass

        # Validace
        if amount < 1:
            err = discord.Embed(
                description="❌ Počet zpráv musí být alespoň **1**.",
                color=0xff4f6a
            )
            m = await ctx.send(embed=err)
            await m.delete(delay=5)
            return

        if amount > 500:
            err = discord.Embed(
                description="❌ Maximální počet zpráv je **500**.",
                color=0xff4f6a
            )
            m = await ctx.send(embed=err)
            await m.delete(delay=5)
            return

        # Potvrzovaci embed
        embed = discord.Embed(
            color=0xff4f6a,
            title="🗑️ Potvrzení smazání zpráv"
        )
        embed.description = (
            f"{ctx.author.mention} chce smazat **{amount}** zpráv v kanálu {ctx.channel.mention}.\n\n"
            f"Opravdu chceš pokračovat?"
        )
        embed.add_field(
            name="📋 Detail",
            value=(
                f"**Kanál:** {ctx.channel.mention}\n"
                f"**Počet:** `{amount}` zpráv\n"
                f"**Zadal:** {ctx.author.mention}"
            ),
            inline=False
        )
        embed.set_footer(text="Tato zpráva vyprší za 30 sekund.")
        embed.set_thumbnail(url=ctx.author.display_avatar.url)

        view = PurgeConfirmView(author=ctx.author, amount=amount)
        msg  = await ctx.send(embed=embed, view=view)
        view.message = msg   # potreba pro on_timeout

    # ── Error handlery ────────────────────────────────────────────────────────

    @purge_cmd.error
    async def purge_error(self, ctx: commands.Context, error):
        try:
            await ctx.message.delete()
        except Exception:
            pass

        if isinstance(error, commands.MissingPermissions):
            embed = discord.Embed(
                description="❌ Nemáš oprávnění administrátora pro použití tohoto příkazu.",
                color=0xff4f6a
            )
        elif isinstance(error, commands.MissingRequiredArgument):
            embed = discord.Embed(
                description="❌ Zadej počet zpráv.\n**Použití:** `!purge <počet>`",
                color=0xff4f6a
            )
        elif isinstance(error, commands.BadArgument):
            embed = discord.Embed(
                description="❌ Počet zpráv musí být celé číslo.\n**Použití:** `!purge <počet>`",
                color=0xff4f6a
            )
        else:
            embed = discord.Embed(
                description=f"❌ Nastala chyba: `{error}`",
                color=0xff4f6a
            )

        m = await ctx.send(embed=embed)
        await m.delete(delay=6)


# ─── Setup / Teardown ─────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(Purge(bot))
    print("[Plugin:purge] Spusten")

async def teardown(bot: commands.Bot):
    await bot.remove_cog("Purge")
    print("[Plugin:purge] Zastasen")