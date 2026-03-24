"""
rolesaver.py — Role Saver Plugin
Ukládá role uživatelů a při opětovném připojení je vrátí.
Sleduje každou změnu rolí v reálném čase.
"""

import discord
from discord.ext import commands
import json
import os

DATA_FILE = "role_data.json"

# ─── Storage ──────────────────────────────────────────────────────────────────

class RoleStorage:
    def __init__(self):
        self.data: dict = self._load()

    def _load(self) -> dict:
        if not os.path.exists(DATA_FILE):
            return {}
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self):
        try:
            with open(DATA_FILE, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            print(f"[RoleSaver] Nelze ulozit: {e}")

    def save_roles(self, member: discord.Member):
        """Ulož aktuální role člena (bez @everyone)."""
        guild_key  = str(member.guild.id)
        member_key = str(member.id)

        if guild_key not in self.data:
            self.data[guild_key] = {}

        role_ids = [r.id for r in member.roles if r.name != "@everyone"]
        self.data[guild_key][member_key] = role_ids
        self._save()

    def get_roles(self, guild_id: int, user_id: int) -> list[int]:
        return self.data.get(str(guild_id), {}).get(str(user_id), [])

    def remove_member(self, guild_id: int, user_id: int):
        key = str(guild_id)
        if key in self.data and str(user_id) in self.data[key]:
            del self.data[key][str(user_id)]
            self._save()

# ─── Cog ──────────────────────────────────────────────────────────────────────

class RoleSaver(commands.Cog, name="RoleSaver"):
    def __init__(self, bot: commands.Bot):
        self.bot     = bot
        self.storage = RoleStorage()
        print("[Plugin:rolesaver] Nacteno")

    def cog_unload(self):
        print("[Plugin:rolesaver] Odpojen")

    # ── Ulož role při každé změně ─────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Zavolá se při jakékoliv změně člena — včetně změny rolí."""
        if before.roles != after.roles:
            self.storage.save_roles(after)

    # ── Ulož role všem při startu (sync) ─────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        count = 0
        for guild in self.bot.guilds:
            for member in guild.members:
                self.storage.save_roles(member)
                count += 1
        print(f"[RoleSaver] Synchronizovano {count} clenu")

    # ── Vrať role při připojení ───────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        saved_ids = self.storage.get_roles(member.guild.id, member.id)
        if not saved_ids:
            return

        roles_to_add = []
        skipped      = []

        for role_id in saved_ids:
            role = member.guild.get_role(role_id)
            if role is None:
                continue
            # Přeskoč managed role (boty, boosty atd.) a @everyone
            if role.managed or role.name == "@everyone":
                skipped.append(role_id)
                continue
            # Přeskoč role výše než bot
            if role >= member.guild.me.top_role:
                skipped.append(role_id)
                continue
            roles_to_add.append(role)

        if not roles_to_add:
            return

        try:
            await member.add_roles(*roles_to_add, reason="RoleSaver — obnova rolí po připojení")
            names = ", ".join(r.name for r in roles_to_add)
            print(f"[RoleSaver] Obnoveny role pro {member} ({member.id}): {names}")
            if skipped:
                print(f"[RoleSaver] Preskocene role (nedostupne/managed): {skipped}")
        except discord.Forbidden:
            print(f"[RoleSaver] Nemam opravneni obnovit role pro {member}")
        except Exception as e:
            print(f"[RoleSaver] Chyba pri obnove roli pro {member}: {e}")

    # ── Admin příkazy ─────────────────────────────────────────────────────────

    @commands.command(name="roles")
    @commands.has_permissions(administrator=True)
    async def roles_cmd(self, ctx: commands.Context, member: discord.Member = None):
        """Zobraz uložené role člena. Použití: !roles [@member]"""
        target   = member or ctx.author
        saved    = self.storage.get_roles(ctx.guild.id, target.id)

        if not saved:
            embed = discord.Embed(
                description=f"Pro **{target.display_name}** nejsou žádné uložené role.",
                color=0x5a6a82
            )
            await ctx.send(embed=embed)
            return

        lines = []
        for rid in saved:
            r = ctx.guild.get_role(rid)
            lines.append(r.mention if r else f"~~`{rid}`~~ *(smazána)*")

        embed = discord.Embed(
            title=f"💾 Uložené role — {target.display_name}",
            description="\n".join(lines),
            color=0x4fb8ff,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.set_footer(text=f"{len(saved)} rolí uloženo")
        await ctx.send(embed=embed)

    @commands.command(name="rolesync")
    @commands.has_permissions(administrator=True)
    async def rolesync_cmd(self, ctx: commands.Context):
        """Manuálně synchronizuj role všech členů. Použití: !rolesync"""
        msg = await ctx.send(embed=discord.Embed(
            description="⏳ Synchronizuji role všech členů...",
            color=0xffb84f
        ))
        count = 0
        for member in ctx.guild.members:
            self.storage.save_roles(member)
            count += 1
        await msg.edit(embed=discord.Embed(
            description=f"✅ Synchronizováno **{count}** členů.",
            color=0x4fffb0
        ))

    @roles_cmd.error
    async def roles_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            m = await ctx.send(embed=discord.Embed(
                description="❌ Nemáš oprávnění administrátora.",
                color=0xff4f6a
            ))
            await m.delete(delay=5)

    @rolesync_cmd.error
    async def rolesync_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            m = await ctx.send(embed=discord.Embed(
                description="❌ Nemáš oprávnění administrátora.",
                color=0xff4f6a
            ))
            await m.delete(delay=5)


# ─── Setup / Teardown ─────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(RoleSaver(bot))
    print("[Plugin:rolesaver] Spusten")

async def teardown(bot: commands.Bot):
    await bot.remove_cog("RoleSaver")
    print("[Plugin:rolesaver] Zastasen")