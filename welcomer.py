"""
welcomer.py — Welcomer s invite trackingem
- Trackuje invites na serveru
- Pri pripojeni zjisti kdo pozval noveho clena
- Posila welcome zpravu s realnyma datama
- !w  — admin test
- !invites [@user] — zobraz invite statistiky
- !invitetop — zebricek pozyvatelov
"""

import discord
from discord.ext import commands
from datetime import datetime, timezone
import json
import os

# ─── Konfigurace ──────────────────────────────────────────────────────────────

WELCOME_CHANNEL_ID = 1429566622321999952
DATA_FILE = "invite_data.json"   # ulozi invite statistiky na disk

# ─── Invite Data Manager ──────────────────────────────────────────────────────

class InviteData:
    """Spravuje invite statistiky ulozene na disku."""

    def __init__(self):
        self.data = self._load()

    def _load(self) -> dict:
        if not os.path.exists(DATA_FILE):
            return {}
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self):
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Welcomer] Nelze ulozit invite data: {e}")

    def get_user(self, user_id: int) -> dict:
        key = str(user_id)
        if key not in self.data:
            self.data[key] = {
                "invited_count": 0,      # celkovy pocet pozvanich
                "invited_users": [],      # seznam pozvanich user ID
                "invited_by": None,       # kdo pozval tohoto clena
                "invite_code": None,      # jakym kodem byl pozvan
            }
        return self.data[key]

    def record_join(self, new_member_id: int, inviter_id: int | None, code: str | None):
        """Zaznamenej ze new_member byl pozvan inviterem."""
        nm = self.get_user(new_member_id)
        nm["invited_by"]   = str(inviter_id) if inviter_id else None
        nm["invite_code"]  = code
        self._save()

        if inviter_id is None:
            return

        inv = self.get_user(inviter_id)
        if str(new_member_id) not in inv["invited_users"]:
            inv["invited_users"].append(str(new_member_id))
            inv["invited_count"] += 1
        self._save()

    def get_invited_count(self, user_id: int) -> int:
        return self.get_user(user_id).get("invited_count", 0)

    def get_invited_by(self, user_id: int) -> str | None:
        return self.get_user(user_id).get("invited_by")

    def get_top(self, limit: int = 10) -> list[tuple[str, int]]:
        """Vrati serazeny seznam (user_id, count) podle poctu invitu."""
        items = [
            (uid, d.get("invited_count", 0))
            for uid, d in self.data.items()
            if d.get("invited_count", 0) > 0
        ]
        items.sort(key=lambda x: x[1], reverse=True)
        return items[:limit]


# ─── Cog ──────────────────────────────────────────────────────────────────────

class Welcomer(commands.Cog, name="Welcomer"):
    def __init__(self, bot: commands.Bot):
        self.bot          = bot
        self.invite_cache: dict[str, discord.Invite] = {}   # code -> Invite
        self.invite_db    = InviteData()
        print("[Plugin:welcomer] Nacteno")

    def cog_unload(self):
        print("[Plugin:welcomer] Odpojen")

    # ── Cache helpers ─────────────────────────────────────────────────────────

    async def build_cache(self, guild: discord.Guild) -> dict[str, discord.Invite]:
        """Nacte vsechny invites do cache."""
        try:
            invites = await guild.invites()
            return {inv.code: inv for inv in invites}
        except Exception as e:
            print(f"[Welcomer] Nelze nacist invites: {e}")
            return {}

    async def find_used_invite(
        self, guild: discord.Guild
    ) -> discord.Invite | None:
        """
        Porovnej starý cache s novým stavem — invite co zvysil uses je ten pouzity.
        """
        old_cache = self.invite_cache
        new_cache = await self.build_cache(guild)
        self.invite_cache = new_cache

        # 1) Najdi invite ktery zvysil uses
        for code, new_inv in new_cache.items():
            old_inv = old_cache.get(code)
            if old_inv is None:
                # Novy invite co uz byl pouzit (uses >= 1)
                if new_inv.uses and new_inv.uses >= 1:
                    return new_inv
            elif new_inv.uses > old_inv.uses:
                return new_inv

        # 2) Invite mohl byt smazan po pouziti (max_uses=1)
        for code, old_inv in old_cache.items():
            if code not in new_cache:
                return old_inv

        return None

    # ── Welcome zprava ────────────────────────────────────────────────────────

    async def send_welcome(
        self,
        member: discord.Member,
        inviter: discord.Member | None = None,
        invite_code: str | None = None,
        invite_count: int = 0,
        is_test: bool = False,
    ):
        channel = self.bot.get_channel(WELCOME_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(WELCOME_CHANNEL_ID)
            except Exception as e:
                print(f"[Welcomer] Nelze najit kanal: {e}")
                return

        # Sestaveni invite radku
        if inviter:
            # Pocet invitu vcetne tohoto
            total = self.invite_db.get_invited_count(inviter.id)
            invite_line = (
                f"<:fire:1431777548093751317>  メ Pozval tě na server "
                f"**{inviter.display_name}** a ten již pozval **{total}**."
            )
        else:
            invite_line = (
                "<:fire:1431777548093751317>  メ Přišel jsi přes **neznámý odkaz** "
                "nebo **vanity URL**."
            )

        test_prefix = "> 🧪 **[TEST]**\n" if is_test else ""

        msg = (
            f"# <a:peepohey:1429926296208805930>メ Vítej na serveru \n"
            f"{test_prefix}"
            f"> Vítej {member.mention} u nás v __komunitě__ doufáme že se ti tu bude líbit! <:pepeworker:1383880630248407070>\n"
            f"> Až si **přečteš <#1430953032056832083>** tak si pojď __s námi povídat__. \n"
            f"> {invite_line}"
        )

        try:
            await channel.send(msg)
        except Exception as e:
            print(f"[Welcomer] Chyba pri odesilani: {e}")

    # ── Events ────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        """Nacti invite cache pri startu bota."""
        for guild in self.bot.guilds:
            self.invite_cache.update(await self.build_cache(guild))
        print(f"[Welcomer] Invite cache nactena ({len(self.invite_cache)} invitu)")

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        """Pridej novy invite do cache."""
        self.invite_cache[invite.code] = invite

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        """Odeber smazany invite z cache."""
        self.invite_cache.pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        used = await self.find_used_invite(member.guild)

        inviter     = used.inviter if used else None
        invite_code = used.code    if used else None

        # Uloz do databaze
        self.invite_db.record_join(
            new_member_id=member.id,
            inviter_id=inviter.id if inviter else None,
            code=invite_code,
        )

        invite_count = self.invite_db.get_invited_count(inviter.id) if inviter else 0

        await self.send_welcome(
            member=member,
            inviter=inviter,
            invite_code=invite_code,
            invite_count=invite_count,
        )

    # ── Prikazy ───────────────────────────────────────────────────────────────

    @commands.command(name="w")
    @commands.has_permissions(administrator=True)
    async def test_welcome(self, ctx: commands.Context):
        """Test welcome zpravy s tebou jako novym clenem. Pouziti: !w"""
        inv_by_id = self.invite_db.get_invited_by(ctx.author.id)
        inviter   = None
        if inv_by_id:
            try:
                inviter = ctx.guild.get_member(int(inv_by_id))
            except Exception:
                pass

        await self.send_welcome(
            member=ctx.author,
            inviter=inviter,
            invite_count=self.invite_db.get_invited_count(inviter.id) if inviter else 0,
            is_test=True,
        )
        try:
            await ctx.message.delete()
        except Exception:
            pass

    @commands.command(name="invites")
    @commands.has_permissions(administrator=True)
    async def invites_cmd(self, ctx: commands.Context, member: discord.Member = None):
        """
        Zobrazi invite statistiky clena.
        Pouziti: !invites [@uzivatel]
        """
        target = member or ctx.author
        data   = self.invite_db.get_user(target.id)
        count  = data.get("invited_count", 0)
        users  = data.get("invited_users", [])
        inv_by = data.get("invited_by")
        code   = data.get("invite_code")

        # Inviter
        inviter_str = "Neznámý / vanity URL"
        if inv_by:
            m = ctx.guild.get_member(int(inv_by))
            inviter_str = m.mention if m else f"<@{inv_by}>"

        # Pozvani uzivatele (prvnich 10)
        if users:
            user_list = []
            for uid in users[:10]:
                m = ctx.guild.get_member(int(uid))
                user_list.append(m.mention if m else f"<@{uid}>")
            users_str = ", ".join(user_list)
            if len(users) > 10:
                users_str += f" a dalších {len(users) - 10}..."
        else:
            users_str = "Zatím nikoho"

        embed = discord.Embed(
            title=f"📨 Invite statistiky — {target.display_name}",
            color=0x4fb8ff,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="✉️ Celkem pozváno", value=f"**{count}** členů", inline=True)
        embed.add_field(name="📎 Pozval ho", value=inviter_str, inline=True)
        if code:
            embed.add_field(name="🔗 Kód pozvánky", value=f"`{code}`", inline=True)
        embed.add_field(name="👥 Pozvaní členové", value=users_str, inline=False)
        embed.set_footer(text="HexBot • Invite Tracker")

        await ctx.send(embed=embed)

    @commands.command(name="invitetop")
    async def invite_top(self, ctx: commands.Context):
        """Zobraz zebricek nejlepsich pozyvatelov. Pouziti: !invitetop"""
        top = self.invite_db.get_top(10)

        if not top:
            await ctx.send(embed=discord.Embed(
                description="Zatím nikdo nepozvál žádného člena.",
                color=0x5a6a82
            ))
            return

        embed = discord.Embed(
            title="🏆 Top Invite Leaderboard",
            color=0x4fffb0,
            timestamp=datetime.now(timezone.utc),
        )

        medals = ["🥇", "🥈", "🥉"]
        lines  = []
        for i, (uid, count) in enumerate(top):
            m      = ctx.guild.get_member(int(uid))
            name   = m.mention if m else f"<@{uid}>"
            medal  = medals[i] if i < 3 else f"**{i+1}.**"
            word   = "pozvání" if count == 1 else ("pozvání" if 2 <= count <= 4 else "pozvání")
            lines.append(f"{medal} {name} — **{count}** {word}")

        embed.description = "\n".join(lines)
        embed.set_footer(text="HexBot • Invite Tracker")
        await ctx.send(embed=embed)

    # ── Error handlery ────────────────────────────────────────────────────────

    @test_welcome.error
    async def test_welcome_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            m = await ctx.send(embed=discord.Embed(
                description="❌ Nemáš oprávnění administrátora.",
                color=0xff4f6a
            ))
            await m.delete(delay=5)

    @invites_cmd.error
    async def invites_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            m = await ctx.send(embed=discord.Embed(
                description="❌ Nemáš oprávnění administrátora.",
                color=0xff4f6a
            ))
            await m.delete(delay=5)
        elif isinstance(error, commands.MemberNotFound):
            m = await ctx.send(embed=discord.Embed(
                description="❌ Člen nenalezen.",
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
