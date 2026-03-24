"""
welcomer.py — Welcomer Plugin
Posila vitaci zpravu do kanalu pri pripojeni noveho clena.
!w — admin test prikaz pro otestovani welcome zpravy.
"""

import discord
from discord.ext import commands

# ─── Konfigurace ──────────────────────────────────────────────────────────────

WELCOME_CHANNEL_ID = 1429566622321999952

WELCOME_MESSAGE = """# <a:peepohey:1429926296208805930>メ Vítej na serveru 
> Vítej {mention} u nás v __komunitě__ doufáme že se ti tu bude líbit! <:pepeworker:1383880630248407070>
> Až si **přečteš <#1430953032056832083>** tak si pojď __s námi povídat__. 
> <:fire:1431777548093751317>  メ Pozval tě na server **$ Dr4gxn_** a ten již pozval **1**."""

# ─── Cog ──────────────────────────────────────────────────────────────────────

class Welcomer(commands.Cog, name="Welcomer"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("[Plugin:welcomer] Nacteno")

    def cog_unload(self):
        print("[Plugin:welcomer] Odpojen")

    async def send_welcome(self, member: discord.Member):
        channel = self.bot.get_channel(WELCOME_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(WELCOME_CHANNEL_ID)
            except Exception as e:
                print(f"[Plugin:welcomer] Nelze najit kanal: {e}")
                return

        msg = WELCOME_MESSAGE.format(mention=member.mention)
        try:
            await channel.send(msg)
        except Exception as e:
            print(f"[Plugin:welcomer] Chyba pri odesilani: {e}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self.send_welcome(member)

    @commands.command(name="w")
    @commands.has_permissions(administrator=True)
    async def test_welcome(self, ctx: commands.Context):
        """Test welcome zpravy. Pouziti: !w"""
        await self.send_welcome(ctx.author)
        try:
            await ctx.message.delete()
        except Exception:
            pass

    @test_welcome.error
    async def test_welcome_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            m = await ctx.send(embed=discord.Embed(
                description="❌ Nemáš oprávnění administrátora.",
                color=0xff4f6a
            ))
            await m.delete(delay=5)


# ─── Setup / Teardown ─────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(Welcomer(bot))
    print("[Plugin:welcomer] Spusten")

async def teardown(bot: commands.Bot):
    await bot.remove_cog("Welcomer")
    print("[Plugin:welcomer] Zastasen")