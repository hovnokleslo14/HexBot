"""
verification.py — Verification Plugin
Posila verifikacni embed do kanalu s tlacitkem.
Po kliknuti posle uzivately DM s matematickym prikladem.
Po spravne odpovedi da uzivately roli a posle uvitaci DM.
!sendverify — admin prikaz pro odeslani verifikacni zpravy
"""

import discord
from discord.ext import commands
from discord.ui import View, Button
import random
import asyncio

# ─── Konfigurace ──────────────────────────────────────────────────────────────

VERIFY_CHANNEL_ID = 1404131893779238953
VERIFY_ROLE_ID    = 1430957229892174057
DM_TIMEOUT        = 60   # sekund na odpoved

# ─── Math captcha generator ───────────────────────────────────────────────────

def generate_math() -> tuple[str, int]:
    """Vygeneruje nahodny matematicky priklad a vrati (otazka, spravna_odpoved)."""
    ops = [
        # Scitani
        lambda: (random.randint(10, 99), random.randint(10, 99), "+",  lambda a, b: a + b),
        # Odcitani
        lambda: (random.randint(20, 99), random.randint(1, 19),  "-",  lambda a, b: a - b),
        # Nasobeni
        lambda: (random.randint(2, 12),  random.randint(2, 12),  "×",  lambda a, b: a * b),
    ]
    gen      = random.choice(ops)()
    a, b, op, calc = gen
    question = f"{a} {op} {b}"
    answer   = calc(a, b)
    return question, answer

# ─── Verification View (tlacitko) ─────────────────────────────────────────────

class VerifyView(View):
    """Persistentni view — prezije restart bota."""

    def __init__(self):
        super().__init__(timeout=None)   # zadny timeout

    @discord.ui.button(
        label="Verifikovat",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="verify_button"
    )
    async def verify_button(self, interaction: discord.Interaction, button: Button):
        guild  = interaction.guild
        member = interaction.user

        # Zkontroluj jestli uz ma roli
        role = guild.get_role(VERIFY_ROLE_ID)
        if role and role in member.roles:
            await interaction.response.send_message(
                "✅ Již jsi verifikován/a!",
                ephemeral=True
            )
            return

        # Zkus poslat DM
        question, answer = generate_math()

        dm_embed = discord.Embed(
            title="🔐 Verifikace — Math Captcha",
            color=0x4fb8ff,
        )
        dm_embed.description = (
            f"Ahoj **{member.display_name}**! 👋\n\n"
            f"Pro ověření, že nejsi robot, vyřeš následující příklad:\n\n"
            f"## `{question} = ?`\n\n"
            f"Napiš mi sem **pouze číslo** jako odpověď.\n"
            f"Máš na to **{DM_TIMEOUT} sekund**."
        )
        dm_embed.set_footer(text="Odpověz přímo do této DM konverzace.")
        dm_embed.set_thumbnail(url=guild.icon.url if guild.icon else None)

        try:
            dm_channel = await member.create_dm()
            await dm_channel.send(embed=dm_embed)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Nepodařilo se ti poslat DM. Zkontroluj, zda máš povolené přijímání zpráv od členů serveru.\n"
                "> Nastavení → Soukromí → Přijímat přímé zprávy od členů serveru ✅",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "📨 Poslal jsem ti DM s příkladem! Zkontroluj si zprávy.",
            ephemeral=True
        )

        # Cekej na odpoved v DM
        def check(m: discord.Message):
            return (
                m.channel == dm_channel
                and m.author.id == member.id
            )

        try:
            msg = await interaction.client.wait_for("message", check=check, timeout=DM_TIMEOUT)
        except asyncio.TimeoutError:
            timeout_embed = discord.Embed(
                title="⏱️ Čas vypršel",
                description=(
                    "Neodpověděl/a jsi včas.\n\n"
                    "Vrať se na server a klikni znovu na tlačítko **Verifikovat**."
                ),
                color=0xff4f6a,
            )
            await dm_channel.send(embed=timeout_embed)
            return

        # Zkontroluj odpoved
        user_answer = msg.content.strip().replace(" ", "").replace(",", ".")
        try:
            user_num = int(float(user_answer))
        except ValueError:
            wrong_embed = discord.Embed(
                title="❌ Neplatná odpověď",
                description=(
                    "Odpověď musí být **číslo**.\n\n"
                    "Vrať se na server a klikni znovu na tlačítko **Verifikovat**."
                ),
                color=0xff4f6a,
            )
            await dm_channel.send(embed=wrong_embed)
            return

        if user_num != answer:
            wrong_embed = discord.Embed(
                title="❌ Špatná odpověď",
                description=(
                    f"Správná odpověď byla **{answer}**, ty jsi napsal/a **{user_num}**.\n\n"
                    "Vrať se na server a klikni znovu na tlačítko **Verifikovat**."
                ),
                color=0xff4f6a,
            )
            await dm_channel.send(embed=wrong_embed)
            return

        # Spravna odpoved — dej roli
        try:
            if role:
                await member.add_roles(role, reason="Verifikace — math captcha")
            else:
                print(f"[Verification] Role {VERIFY_ROLE_ID} nenalezena!")
        except discord.Forbidden:
            await dm_channel.send(embed=discord.Embed(
                description="❌ Bot nemá oprávnění přidělit roli. Kontaktuj admina.",
                color=0xff4f6a,
            ))
            return

        # Uvitaci DM
        success_embed = discord.Embed(
            title="🎉 Verifikace úspěšná!",
            color=0x4fffb0,
        )
        success_embed.description = (
            f"Správně! **{question} = {answer}** ✅\n\n"
            f"Byl/a jsi úspěšně verifikován/a na serveru **{guild.name}**!\n\n"
            f"Doufáme, že se ti u nás bude líbit. 😊\n"
            f"Nezapomeň si přečíst pravidla a pak se pojď s námi bavit!\n\n"
            f"Přejeme ti hodně zábavy! 🔥"
        )
        if guild.icon:
            success_embed.set_thumbnail(url=guild.icon.url)
        success_embed.set_footer(text=f"{guild.name} • Verifikace")

        await dm_channel.send(embed=success_embed)
        print(f"[Verification] {member} ({member.id}) uspesne verifikovan")


# ─── Cog ──────────────────────────────────────────────────────────────────────

class Verification(commands.Cog, name="Verification"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Registruj persistentni view
        bot.add_view(VerifyView())
        print("[Plugin:verification] Nacteno")

    def cog_unload(self):
        print("[Plugin:verification] Odpojen")

    async def send_verify_embed(self, channel: discord.TextChannel):
        """Odesle verifikacni embed do kanalu."""
        embed = discord.Embed(
            title="🛡️ VERIFIKACE",
            color=0x4fb8ff,
        )
        embed.description = (
            "Vítej na serveru! Než se dostaneš dovnitř, musíš projít rychlou verifikací.\n\n"
            "**Proč verifikace?**\n"
            "> Chráníme komunitu před boty a spammery.\n\n"
            "**Jak to funguje?**\n"
            "> 1. Klikni na tlačítko **✅ Verifikovat** níže\n"
            "> 2. Pošleme ti DM s jednoduchým matematickým příkladem\n"
            "> 3. Odpověz správně a automaticky dostaneš přístup\n\n"
            "**Než začneš:**\n"
            "> Ujisti se, že máš povoleno přijímání DM zpráv od členů serveru.\n"
            "> *(Nastavení → Soukromí → Přijímat přímé zprávy ✅)*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━"
        )
        embed.set_footer(text="Verifikace je rychlá a jednoduchá • max 60 sekund")
        if channel.guild.icon:
            embed.set_thumbnail(url=channel.guild.icon.url)

        await channel.send(embed=embed, view=VerifyView())

    @commands.command(name="sendverify")
    @commands.has_permissions(administrator=True)
    async def send_verify(self, ctx: commands.Context):
        """Odesle verifikacni zpravu do verifikacniho kanalu. Pouziti: !sendverify"""
        channel = self.bot.get_channel(VERIFY_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(VERIFY_CHANNEL_ID)
            except Exception as e:
                await ctx.send(embed=discord.Embed(
                    description=f"❌ Kanál nenalezen: `{e}`",
                    color=0xff4f6a
                ))
                return

        await self.send_verify_embed(channel)

        confirm = discord.Embed(
            description=f"✅ Verifikační zpráva odeslána do {channel.mention}.",
            color=0x4fffb0
        )
        msg = await ctx.send(embed=confirm)
        await ctx.message.delete(delay=2)
        await msg.delete(delay=5)

    @send_verify.error
    async def send_verify_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            m = await ctx.send(embed=discord.Embed(
                description="❌ Nemáš oprávnění administrátora.",
                color=0xff4f6a
            ))
            await m.delete(delay=5)


# ─── Setup / Teardown ─────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(Verification(bot))
    print("[Plugin:verification] Spusten")

async def teardown(bot: commands.Bot):
    await bot.remove_cog("Verification")
    print("[Plugin:verification] Zastasen")