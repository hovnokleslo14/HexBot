"""
instanotifier.py — Instagram Notifier Plugin
Sleduje Instagram ucty a posilá notifikace do Discord kanálu pri novém príspevku.

Závislosti: pip install instaloader
Prikazy (pouze admin):
  !ig add <username>         — prida ucet ke sledování
  !ig remove <username>      — odebere ucet
  !ig list                   — vypise vsechny sledované ucty
  !ig check                  — okamzite zkontroluje vsechny ucty
  !ig interval <minuty>      — nastavi interval kontroly (min. 5 min)
  !ig channel <channel_id>   — zmeni kanal pro notifikace
  !ig login <user> <pass>    — prihlas Instagram ucet (pro soukrome ucty / vyhnutí se rate limit)
"""

import discord
from discord.ext import commands, tasks
import json
import os
import asyncio
from datetime import datetime, timezone

try:
    import instaloader
    INSTALOADER_OK = True
except ImportError:
    INSTALOADER_OK = False

# ─── Konfigurace ──────────────────────────────────────────────────────────────

NOTIFY_CHANNEL_ID = 1429566695730839552
DATA_FILE         = "insta_data.json"
CHECK_INTERVAL    = 15   # minuty

# ─── Data Manager ─────────────────────────────────────────────────────────────

class InstaData:
    def __init__(self):
        self.data = self._load()

    def _load(self):
        if not os.path.exists(DATA_FILE):
            return {
                "accounts": {},       # username -> {"last_shortcode": str, "last_ts": int}
                "channel_id": NOTIFY_CHANNEL_ID,
                "interval": CHECK_INTERVAL,
            }
        try:
            with open(DATA_FILE, "r") as f:
                d = json.load(f)
                d.setdefault("accounts", {})
                d.setdefault("channel_id", NOTIFY_CHANNEL_ID)
                d.setdefault("interval", CHECK_INTERVAL)
                return d
        except Exception:
            return {"accounts": {}, "channel_id": NOTIFY_CHANNEL_ID, "interval": CHECK_INTERVAL}

    def save(self):
        try:
            with open(DATA_FILE, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            print(f"[InstaNotifier] Nelze ulozit data: {e}")

    def add_account(self, username: str):
        self.data["accounts"].setdefault(username.lower(), {"last_shortcode": None, "last_ts": 0})
        self.save()

    def remove_account(self, username: str):
        self.data["accounts"].pop(username.lower(), None)
        self.save()

    def get_accounts(self) -> dict:
        return self.data["accounts"]

    def update_last(self, username: str, shortcode: str, ts: int):
        self.data["accounts"][username.lower()]["last_shortcode"] = shortcode
        self.data["accounts"][username.lower()]["last_ts"] = ts
        self.save()

    @property
    def channel_id(self) -> int:
        return int(self.data["channel_id"])

    @channel_id.setter
    def channel_id(self, val: int):
        self.data["channel_id"] = val
        self.save()

    @property
    def interval(self) -> int:
        return int(self.data.get("interval", CHECK_INTERVAL))

    @interval.setter
    def interval(self, val: int):
        self.data["interval"] = val
        self.save()


# ─── Cog ──────────────────────────────────────────────────────────────────────

class InstaNotifier(commands.Cog, name="InstaNotifier"):
    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self.db     = InstaData()
        self.loader = None
        self._init_loader()
        self.check_loop.change_interval(minutes=self.db.interval)
        self.check_loop.start()
        print(f"[InstaNotifier] Spusten — interval: {self.db.interval} min, "
              f"sledovanych uctu: {len(self.db.get_accounts())}")

    def cog_unload(self):
        self.check_loop.cancel()
        print("[InstaNotifier] Zastaven")

    # ── Instaloader init ──────────────────────────────────────────────────────

    def _init_loader(self):
        if not INSTALOADER_OK:
            print("[InstaNotifier] CHYBA: instaloader neni nainstalovan!")
            print("[InstaNotifier] Spust: pip install instaloader")
            return
        self.loader = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            post_metadata_txt_pattern="",
            quiet=True,
        )

    def loader_login(self, username: str, password: str) -> tuple[bool, str]:
        """Prihlasi Instagram ucet do instaloaeru."""
        if not self.loader:
            return False, "instaloader neni dostupny"
        try:
            self.loader.login(username, password)
            return True, None
        except Exception as e:
            return False, str(e)

    # ── Fetch nových příspěvků ─────────────────────────────────────────────────

    def fetch_latest_post(self, username: str):
        """
        Vrátí nejnovejší príspevek jako dict nebo None.
        Spustí se v executor (blocking).
        """
        if not self.loader:
            return None
        try:
            profile = instaloader.Profile.from_username(self.loader.context, username)
            posts   = profile.get_posts()
            post    = next(iter(posts), None)
            if post is None:
                return None
            return {
                "shortcode":  post.shortcode,
                "url":        f"https://www.instagram.com/p/{post.shortcode}/",
                "caption":    (post.caption or "")[:300],
                "timestamp":  int(post.date_utc.timestamp()),
                "likes":      post.likes,
                "is_video":   post.is_video,
                "type":       "Video" if post.is_video else "Fotka",
                "thumb_url":  post.url,
                "username":   username,
                "full_name":  profile.full_name,
                "followers":  profile.followers,
                "profile_pic": profile.profile_pic_url,
            }
        except instaloader.exceptions.ProfileNotExistsException:
            print(f"[InstaNotifier] Profil neexistuje: {username}")
            return None
        except Exception as e:
            print(f"[InstaNotifier] Chyba pri nacitani @{username}: {e}")
            return None

    # ── Build embed ───────────────────────────────────────────────────────────

    def build_embed(self, post: dict) -> discord.Embed:
        ts  = datetime.fromtimestamp(post["timestamp"], tz=timezone.utc)
        icon = "🎬" if post["is_video"] else "🖼️"

        embed = discord.Embed(
            title=f"{icon} Nový příspěvek — @{post['username']}",
            url=post["url"],
            color=0xE1306C,   # Instagram pink
            timestamp=ts,
        )

        if post["caption"]:
            caption = post["caption"]
            if len(caption) > 280:
                caption = caption[:277] + "..."
            embed.description = caption

        embed.add_field(
            name="📊 Statistiky",
            value=f"❤️ **{post['likes']:,}** liků\n👤 **{post['followers']:,}** sledujících",
            inline=True,
        )
        embed.add_field(
            name="📁 Typ",
            value=post["type"],
            inline=True,
        )
        embed.add_field(
            name="🔗 Odkaz",
            value=f"[Otevřít příspěvek]({post['url']})",
            inline=True,
        )

        embed.set_author(
            name=post["full_name"] + f" (@{post['username']})",
            url=f"https://www.instagram.com/{post['username']}/",
            icon_url=post["profile_pic"],
        )
        embed.set_image(url=post["thumb_url"])
        embed.set_footer(text="Instagram Notifier • HexBot")
        return embed

    # ── Check loop ────────────────────────────────────────────────────────────

    @tasks.loop(minutes=CHECK_INTERVAL)
    async def check_loop(self):
        accounts = self.db.get_accounts()
        if not accounts:
            return
        if not INSTALOADER_OK or not self.loader:
            return

        channel = self.bot.get_channel(self.db.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(self.db.channel_id)
            except Exception:
                print("[InstaNotifier] Nelze najit kanal " + str(self.db.channel_id))
                return

        for username, meta in list(accounts.items()):
            await asyncio.sleep(3)   # rate limit prevence
            loop = asyncio.get_event_loop()
            post = await loop.run_in_executor(None, self.fetch_latest_post, username)

            if post is None:
                continue

            last_sc = meta.get("last_shortcode")
            if post["shortcode"] == last_sc:
                continue   # nic noveho

            # Nový příspěvek!
            self.db.update_last(username, post["shortcode"], post["timestamp"])
            embed = self.build_embed(post)

            try:
                await channel.send(
                    content=f"📸 **@{username}** přidal nový příspěvek!",
                    embed=embed
                )
                print(f"[InstaNotifier] Notifikace odeslana: @{username} — {post['shortcode']}")
            except Exception as e:
                print(f"[InstaNotifier] Chyba pri odesilani notifikace: {e}")

    @check_loop.before_loop
    async def before_check_loop(self):
        await self.bot.wait_until_ready()
        # Inicializuj last_shortcode pri prvnim startu (aby neposílal starý post)
        if not INSTALOADER_OK or not self.loader:
            return
        accounts = self.db.get_accounts()
        for username, meta in accounts.items():
            if meta.get("last_shortcode") is None:
                loop = asyncio.get_event_loop()
                post = await loop.run_in_executor(None, self.fetch_latest_post, username)
                if post:
                    self.db.update_last(username, post["shortcode"], post["timestamp"])
                    print(f"[InstaNotifier] Init @{username} — last post: {post['shortcode']}")

    # ── Prikazy ───────────────────────────────────────────────────────────────

    @commands.group(name="ig", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def ig_group(self, ctx: commands.Context):
        """Správa Instagram notifikací. Použití: !ig <prikaz>"""
        accounts = self.db.get_accounts()
        embed = discord.Embed(
            title="📸 Instagram Notifier",
            color=0xE1306C,
        )
        embed.add_field(
            name="📋 Příkazy",
            value=(
                "`!ig add <username>` — přidat účet\n"
                "`!ig remove <username>` — odebrat účet\n"
                "`!ig list` — seznam sledovaných účtů\n"
                "`!ig check` — okamžitá kontrola\n"
                "`!ig interval <min>` — interval kontroly\n"
                "`!ig channel <id>` — změna kanálu\n"
                "`!ig login <user> <pass>` — Instagram login"
            ),
            inline=False,
        )
        embed.add_field(
            name="⚙️ Stav",
            value=(
                f"📡 Sledovaných účtů: **{len(accounts)}**\n"
                f"⏱️ Interval: **{self.db.interval} min**\n"
                f"📺 Kanál: <#{self.db.channel_id}>\n"
                f"{'✅ instaloader OK' if INSTALOADER_OK else '❌ instaloader neni nainstalovan'}"
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    @ig_group.command(name="add")
    @commands.has_permissions(administrator=True)
    async def ig_add(self, ctx: commands.Context, username: str):
        """Přidá Instagram účet ke sledování. Použití: !ig add <username>"""
        username = username.lstrip("@").lower()
        if username in self.db.get_accounts():
            await ctx.send(embed=discord.Embed(
                description=f"ℹ️ Účet **@{username}** je již sledován.",
                color=0xffb84f
            ))
            return

        msg = await ctx.send(embed=discord.Embed(
            description=f"⏳ Přidávám **@{username}** — ověřuji profil...",
            color=0xffb84f
        ))

        if INSTALOADER_OK and self.loader:
            loop = asyncio.get_event_loop()
            post = await loop.run_in_executor(None, self.fetch_latest_post, username)
            if post is None:
                await msg.edit(embed=discord.Embed(
                    description=f"❌ Profil **@{username}** nenalezen nebo není dostupný.",
                    color=0xff4f6a
                ))
                return
            self.db.add_account(username)
            self.db.update_last(username, post["shortcode"], post["timestamp"])
            await msg.edit(embed=discord.Embed(
                title="✅ Účet přidán",
                description=(
                    f"**@{username}** bude nyní sledován.\n\n"
                    f"👤 Jméno: **{post['full_name']}**\n"
                    f"👥 Sledující: **{post['followers']:,}**\n"
                    f"📌 Poslední příspěvek: [odkaz]({post['url']})"
                ),
                color=0x4fffb0
            ))
        else:
            self.db.add_account(username)
            await msg.edit(embed=discord.Embed(
                description=f"✅ Účet **@{username}** přidán (bez ověření — instaloader není k dispozici).",
                color=0x4fffb0
            ))

    @ig_group.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def ig_remove(self, ctx: commands.Context, username: str):
        """Odebere Instagram účet ze sledování. Použití: !ig remove <username>"""
        username = username.lstrip("@").lower()
        if username not in self.db.get_accounts():
            await ctx.send(embed=discord.Embed(
                description=f"❌ Účet **@{username}** není sledován.",
                color=0xff4f6a
            ))
            return
        self.db.remove_account(username)
        await ctx.send(embed=discord.Embed(
            description=f"✅ Účet **@{username}** byl odebrán.",
            color=0x4fffb0
        ))

    @ig_group.command(name="list")
    @commands.has_permissions(administrator=True)
    async def ig_list(self, ctx: commands.Context):
        """Zobrazí seznam sledovaných účtů. Použití: !ig list"""
        accounts = self.db.get_accounts()
        if not accounts:
            await ctx.send(embed=discord.Embed(
                description="Žádné Instagram účty nejsou sledovány.\nPoužij `!ig add <username>`.",
                color=0x5a6a82
            ))
            return

        lines = []
        for uname, meta in accounts.items():
            last = meta.get("last_shortcode")
            last_str = f"[odkaz](https://www.instagram.com/p/{last}/)" if last else "neznámo"
            lines.append(f"📸 **@{uname}** — poslední: {last_str}")

        embed = discord.Embed(
            title=f"📋 Sledované Instagram účty ({len(accounts)})",
            description="\n".join(lines),
            color=0xE1306C,
        )
        embed.set_footer(text=f"Interval kontroly: {self.db.interval} min")
        await ctx.send(embed=embed)

    @ig_group.command(name="check")
    @commands.has_permissions(administrator=True)
    async def ig_check(self, ctx: commands.Context):
        """Okamžitě zkontroluje všechny sledované účty. Použití: !ig check"""
        accounts = self.db.get_accounts()
        if not accounts:
            await ctx.send(embed=discord.Embed(
                description="Žádné účty nejsou sledovány.",
                color=0x5a6a82
            ))
            return
        if not INSTALOADER_OK or not self.loader:
            await ctx.send(embed=discord.Embed(
                description="❌ instaloader není nainstalován.\nSpusť: `pip install instaloader`",
                color=0xff4f6a
            ))
            return

        msg = await ctx.send(embed=discord.Embed(
            description=f"⏳ Kontroluji {len(accounts)} účtů...",
            color=0xffb84f
        ))
        await self.check_loop()
        await msg.edit(embed=discord.Embed(
            description="✅ Kontrola dokončena.",
            color=0x4fffb0
        ))

    @ig_group.command(name="interval")
    @commands.has_permissions(administrator=True)
    async def ig_interval(self, ctx: commands.Context, minutes: int):
        """Nastaví interval kontroly v minutách (min. 5). Použití: !ig interval <minuty>"""
        if minutes < 5:
            await ctx.send(embed=discord.Embed(
                description="❌ Minimální interval je **5 minut**.",
                color=0xff4f6a
            ))
            return
        self.db.interval = minutes
        self.check_loop.change_interval(minutes=minutes)
        await ctx.send(embed=discord.Embed(
            description=f"✅ Interval nastaven na **{minutes} minut**.",
            color=0x4fffb0
        ))

    @ig_group.command(name="channel")
    @commands.has_permissions(administrator=True)
    async def ig_channel(self, ctx: commands.Context, channel_id: int):
        """Změní Discord kanál pro notifikace. Použití: !ig channel <channel_id>"""
        self.db.channel_id = channel_id
        await ctx.send(embed=discord.Embed(
            description=f"✅ Notifikace budou odesílány do <#{channel_id}>.",
            color=0x4fffb0
        ))

    @ig_group.command(name="login")
    @commands.has_permissions(administrator=True)
    async def ig_login(self, ctx: commands.Context, username: str, password: str):
        """Přihlásí Instagram účet (pomáhá s rate limity). Použití: !ig login <user> <pass>"""
        try:
            await ctx.message.delete()
        except Exception:
            pass

        if not INSTALOADER_OK or not self.loader:
            await ctx.send(embed=discord.Embed(
                description="❌ instaloader není nainstalován.",
                color=0xff4f6a
            ))
            return

        msg = await ctx.send(embed=discord.Embed(
            description="⏳ Přihlašuji se k Instagramu...",
            color=0xffb84f
        ))
        loop = asyncio.get_event_loop()
        ok, err = await loop.run_in_executor(
            None, self.loader_login, username, password
        )
        if ok:
            await msg.edit(embed=discord.Embed(
                description=f"✅ Přihlášen jako **{username}**.",
                color=0x4fffb0
            ))
        else:
            await msg.edit(embed=discord.Embed(
                description=f"❌ Přihlášení selhalo: `{err}`",
                color=0xff4f6a
            ))

    # ── Error handler ─────────────────────────────────────────────────────────

    @ig_group.error
    async def ig_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            m = await ctx.send(embed=discord.Embed(
                description="❌ Nemáš oprávnění administrátora.",
                color=0xff4f6a
            ))
            await m.delete(delay=5)


# ─── Setup / Teardown ─────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    if not INSTALOADER_OK:
        print("[InstaNotifier] VAROVANI: instaloader neni nainstalovan!")
        print("[InstaNotifier] Pro instalaci spust: pip install instaloader")
    await bot.add_cog(InstaNotifier(bot))
    print("[InstaNotifier] Plugin nacteno")

async def teardown(bot: commands.Bot):
    await bot.remove_cog("InstaNotifier")
    print("[InstaNotifier] Plugin odpojen")