"""
instanotifier.py — Instagram Notifier Plugin
Sleduje Instagram ucty a posila notifikace pri novem prispevku.

Zavislosti: pip install instaloader

Prikazy (pouze admin):
  !ig login <username> <password>  — prihlaseni (heslo se okamzite smaze ze zpravy)
  !ig add <username>               — prida ucet ke sledovani
  !ig remove <username>            — odebere ucet
  !ig list                         — vypise sledovane ucty
  !ig check                        — okamzita kontrola
  !ig interval <minuty>            — nastavi interval (min. 5)
  !ig channel <id>                 — zmeni notifikacni kanal
  !ig status                       — zobrazi stav
"""

import discord
from discord.ext import commands, tasks
import json
import os
import asyncio
import time
from datetime import datetime, timezone

try:
    import instaloader
    INSTALOADER_OK = True
except ImportError:
    INSTALOADER_OK = False

# ─── Konfigurace ──────────────────────────────────────────────────────────────

NOTIFY_CHANNEL_ID = 1429566695730839552
DATA_FILE         = "insta_data.json"
SESSION_FILE      = "insta_session.json"
CHECK_INTERVAL    = 15

# ─── Data Manager ─────────────────────────────────────────────────────────────

class InstaData:
    def __init__(self):
        self.data = self._load()

    def _load(self):
        if not os.path.exists(DATA_FILE):
            return {"accounts": {}, "channel_id": NOTIFY_CHANNEL_ID, "interval": CHECK_INTERVAL}
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

    def add_account(self, username):
        self.data["accounts"].setdefault(username.lower(), {"last_shortcode": None, "last_ts": 0})
        self.save()

    def remove_account(self, username):
        self.data["accounts"].pop(username.lower(), None)
        self.save()

    def get_accounts(self):
        return self.data["accounts"]

    def update_last(self, username, shortcode, ts):
        self.data["accounts"][username.lower()]["last_shortcode"] = shortcode
        self.data["accounts"][username.lower()]["last_ts"] = ts
        self.save()

    @property
    def channel_id(self):
        return int(self.data["channel_id"])

    @channel_id.setter
    def channel_id(self, val):
        self.data["channel_id"] = val
        self.save()

    @property
    def interval(self):
        return int(self.data.get("interval", CHECK_INTERVAL))

    @interval.setter
    def interval(self, val):
        self.data["interval"] = val
        self.save()


# ─── Session helpers ──────────────────────────────────────────────────────────

def extract_cookies(loader):
    """Vytahne vsechny cookies z instaloader session jako dict."""
    cookies = {}
    for cookie in loader.context._session.cookies:
        cookies[cookie.name] = {
            "value":  cookie.value,
            "domain": cookie.domain,
            "path":   cookie.path,
        }
    return cookies

def inject_cookies(loader, cookies: dict):
    """Vlozi ulozene cookies zpet do instaloader session."""
    jar = loader.context._session.cookies
    for name, attrs in cookies.items():
        jar.set(name, attrs["value"],
                domain=attrs.get("domain", ".instagram.com"),
                path=attrs.get("path", "/"))

def save_session_file(username: str, loader):
    """Ulozi session cookies na disk."""
    try:
        cookies = extract_cookies(loader)
        with open(SESSION_FILE, "w") as f:
            json.dump({"username": username, "cookies": cookies, "saved_at": int(time.time())}, f)
        print(f"[InstaNotifier] Session ulozena pro @{username}")
    except Exception as e:
        print(f"[InstaNotifier] Nelze ulozit session: {e}")

def load_session_file():
    """Nacte session cookies z disku. Vraci (username, cookies) nebo (None, None)."""
    if not os.path.exists(SESSION_FILE):
        return None, None
    try:
        with open(SESSION_FILE, "r") as f:
            data = json.load(f)
        return data.get("username"), data.get("cookies", {})
    except Exception:
        return None, None


# ─── Login worker (blokujici, spousti se v executor) ─────────────────────────

def do_login_worker(loader, username: str, password: str):
    """
    Pokusi se o prihlaseni. Vrati (ok, error_msg, session_cookies).
    Spousti se mimo event loop (blokujici operace).
    """
    try:
        loader.login(username, password)
        cookies = extract_cookies(loader)
        return True, None, cookies
    except instaloader.exceptions.BadCredentialsException:
        return False, "Spatne jmeno nebo heslo.", {}
    except instaloader.exceptions.TwoFactorAuthRequiredException:
        # I kdyz vyzaduje 2FA, cookies uz mohly byt nastaveny — zkusime je vytahnout
        cookies = extract_cookies(loader)
        if cookies.get("sessionid"):
            return True, None, cookies
        return False, "Ucet ma zapnutou dvoufaktorovou autentizaci. Pouzij !ig cookie.", {}
    except instaloader.exceptions.ConnectionException as e:
        msg = str(e)
        # Checkpoint — Instagram chce overeni v prohlizeci
        if "checkpoint" in msg.lower() or "Checkpoint" in msg:
            # Cookies mohly byt cástecne nastaveny — zkusime je ulozit
            cookies = extract_cookies(loader)
            sid = cookies.get("sessionid", {}).get("value", "") if isinstance(cookies.get("sessionid"), dict) else ""
            if sid:
                return True, "checkpoint_saved", cookies
            return False, (
                "Instagram vyzaduje checkpoint overeni.\n\n"
                "**Reseni:**\n"
                "1. Otevri instagram.com v prohlizeci a prihlas se\n"
                "2. Proved overeni ktere Instagram pozaduje\n"
                "3. F12 → Application → Cookies → instagram.com\n"
                "4. Zkopiruj hodnotu cookie **`sessionid`**\n"
                "5. Pouzij: `!ig cookie <username> <session_id>`"
            ), {}
        return False, f"Chyba pripojeni: {msg}", {}
    except Exception as e:
        return False, str(e), {}


# ─── Cog ──────────────────────────────────────────────────────────────────────

class InstaNotifier(commands.Cog, name="InstaNotifier"):
    def __init__(self, bot: commands.Bot):
        self.bot         = bot
        self.db          = InstaData()
        self.loader      = None
        self.logged_in   = False
        self.ig_username = None
        self._init_loader()
        self._restore_session()
        self.check_loop.change_interval(minutes=self.db.interval)
        self.check_loop.start()
        print(f"[InstaNotifier] Spusten — interval:{self.db.interval}m "
              f"uctu:{len(self.db.get_accounts())} prihlasen:{self.logged_in}")

    def cog_unload(self):
        self.check_loop.cancel()
        print("[InstaNotifier] Zastaven")

    # ── Init & session ────────────────────────────────────────────────────────

    def _init_loader(self):
        if not INSTALOADER_OK:
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

    def _restore_session(self):
        """Nacte ulozene cookies a obnovi session bez hesla."""
        if not self.loader:
            return
        username, cookies = load_session_file()
        if not username or not cookies:
            return
        try:
            inject_cookies(self.loader, cookies)
            self.loader.context.username = username
            self.logged_in   = True
            self.ig_username = username
            print(f"[InstaNotifier] Session obnovena pro @{username}")
        except Exception as e:
            print(f"[InstaNotifier] Nelze obnovit session: {e}")

    # ── Fetch ─────────────────────────────────────────────────────────────────

    def fetch_latest_post(self, username: str):
        if not self.loader:
            return None
        try:
            profile = instaloader.Profile.from_username(self.loader.context, username)
            post    = next(iter(profile.get_posts()), None)
            if not post:
                return None
            return {
                "shortcode":   post.shortcode,
                "url":         f"https://www.instagram.com/p/{post.shortcode}/",
                "caption":     (post.caption or "")[:300],
                "timestamp":   int(post.date_utc.timestamp()),
                "likes":       post.likes,
                "is_video":    post.is_video,
                "type":        "Video" if post.is_video else "Fotka",
                "thumb_url":   post.url,
                "username":    username,
                "full_name":   profile.full_name,
                "followers":   profile.followers,
                "profile_pic": profile.profile_pic_url,
            }
        except instaloader.exceptions.ProfileNotExistsException:
            print(f"[InstaNotifier] Profil neexistuje: @{username}")
            return None
        except Exception as e:
            print(f"[InstaNotifier] Chyba @{username}: {e}")
            return None

    # ── Embed ─────────────────────────────────────────────────────────────────

    def build_embed(self, post: dict) -> discord.Embed:
        ts   = datetime.fromtimestamp(post["timestamp"], tz=timezone.utc)
        icon = "🎬" if post["is_video"] else "🖼️"
        embed = discord.Embed(
            title=f"{icon} Nový příspěvek — @{post['username']}",
            url=post["url"],
            color=0xE1306C,
            timestamp=ts,
        )
        if post["caption"]:
            cap = post["caption"][:280] + ("..." if len(post["caption"]) > 280 else "")
            embed.description = cap
        embed.add_field(
            name="📊 Statistiky",
            value=f"❤️ **{post['likes']:,}** liků\n👤 **{post['followers']:,}** sledujících",
            inline=True,
        )
        embed.add_field(name="📁 Typ",   value=post["type"],                               inline=True)
        embed.add_field(name="🔗 Odkaz", value=f"[Otevřít příspěvek]({post['url']})",     inline=True)
        embed.set_author(
            name=f"{post['full_name']} (@{post['username']})",
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
        if not accounts or not INSTALOADER_OK or not self.loader:
            return
        channel = self.bot.get_channel(self.db.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(self.db.channel_id)
            except Exception:
                return

        loop = asyncio.get_event_loop()
        for username, meta in list(accounts.items()):
            await asyncio.sleep(4)
            post = await loop.run_in_executor(None, self.fetch_latest_post, username)
            if not post:
                continue
            if post["shortcode"] == meta.get("last_shortcode"):
                continue
            self.db.update_last(username, post["shortcode"], post["timestamp"])
            try:
                await channel.send(
                    content=f"📸 **@{username}** přidal nový příspěvek!",
                    embed=self.build_embed(post),
                )
                print(f"[InstaNotifier] Notifikace: @{username} — {post['shortcode']}")
            except Exception as e:
                print(f"[InstaNotifier] Chyba odeslani: {e}")

    @check_loop.before_loop
    async def before_check_loop(self):
        await self.bot.wait_until_ready()
        if not INSTALOADER_OK or not self.loader:
            return
        loop = asyncio.get_event_loop()
        for username, meta in self.db.get_accounts().items():
            if meta.get("last_shortcode") is None:
                post = await loop.run_in_executor(None, self.fetch_latest_post, username)
                if post:
                    self.db.update_last(username, post["shortcode"], post["timestamp"])

    # ── Příkazy ───────────────────────────────────────────────────────────────

    @commands.group(name="ig", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def ig_group(self, ctx: commands.Context):
        accounts = self.db.get_accounts()
        login_status = (
            f"✅ Přihlášen jako **@{self.ig_username}**"
            if self.logged_in else
            "⚠️ Nepřihlášen — použij `!ig login <user> <heslo>`"
        )
        embed = discord.Embed(title="📸 Instagram Notifier", color=0xE1306C)
        embed.add_field(
            name="📋 Příkazy",
            value=(
                "`!ig login <user> <heslo>` — přihlásit se\n"
                "`!ig cookie <user> <sessionid>` — login přes cookie\n"
                "`!ig add <user>` — přidat účet\n"
                "`!ig remove <user>` — odebrat účet\n"
                "`!ig list` — seznam účtů\n"
                "`!ig check` — okamžitá kontrola\n"
                "`!ig interval <min>` — nastavit interval\n"
                "`!ig channel <id>` — změnit kanál\n"
                "`!ig status` — zobrazit stav"
            ),
            inline=False,
        )
        embed.add_field(
            name="⚙️ Stav",
            value=(
                f"{login_status}\n"
                f"📡 Sledovaných: **{len(accounts)}**\n"
                f"⏱️ Interval: **{self.db.interval} min**\n"
                f"📺 Kanál: <#{self.db.channel_id}>\n"
                f"{'✅ instaloader OK' if INSTALOADER_OK else '❌ pip install instaloader'}"
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    @ig_group.command(name="login")
    @commands.has_permissions(administrator=True)
    async def ig_login(self, ctx: commands.Context, username: str, password: str):
        """Přihlásí se k Instagramu a uloží session cookie. Použití: !ig login <user> <heslo>"""
        # Okamzite smazat zpravu s heslem
        try:
            await ctx.message.delete()
        except Exception:
            pass

        if not INSTALOADER_OK or not self.loader:
            await ctx.send(embed=discord.Embed(
                description="❌ instaloader není nainstalován.\n`pip install instaloader`",
                color=0xff4f6a,
            ))
            return

        msg = await ctx.send(embed=discord.Embed(
            description=f"⏳ Přihlašuji se jako **@{username}**...",
            color=0xffb84f,
        ))

        loop = asyncio.get_event_loop()
        ok, err, cookies = await loop.run_in_executor(
            None, do_login_worker, self.loader, username.lstrip("@"), password
        )

        if ok:
            # Uloz cookies a nastav stav
            save_session_file(username.lstrip("@"), self.loader)
            self.logged_in   = True
            self.ig_username = username.lstrip("@")

            if err == "checkpoint_saved":
                await msg.edit(embed=discord.Embed(
                    title="⚠️ Přihlášen s varováním",
                    description=(
                        f"Session cookie pro **@{username}** byl uložen.\n\n"
                        "Instagram detekoval přihlášení přes script — možná budeš "
                        "muset ověřit účet v prohlížeči.\n"
                        "Pokud scraping nefunguje, použij `!ig cookie`."
                    ),
                    color=0xffb84f,
                ))
            else:
                await msg.edit(embed=discord.Embed(
                    title="✅ Přihlášení úspěšné",
                    description=(
                        f"Přihlášen jako **@{username}**.\n"
                        "Session cookie byl uložen a bude použit při příštím startu."
                    ),
                    color=0x4fffb0,
                ))
        else:
            self.logged_in = False
            await msg.edit(embed=discord.Embed(
                title="❌ Přihlášení selhalo",
                description=err,
                color=0xff4f6a,
            ))

    @ig_group.command(name="cookie")
    @commands.has_permissions(administrator=True)
    async def ig_cookie(self, ctx: commands.Context, username: str, session_id: str):
        """
        Záložní přihlášení přes session cookie z prohlížeče.
        Jak získat: F12 → Application → Cookies → instagram.com → sessionid
        Použití: !ig cookie <username> <session_id>
        """
        try:
            await ctx.message.delete()
        except Exception:
            pass

        if not INSTALOADER_OK or not self.loader:
            await ctx.send(embed=discord.Embed(
                description="❌ instaloader není nainstalován.", color=0xff4f6a))
            return

        msg = await ctx.send(embed=discord.Embed(
            description="⏳ Ověřuji session cookie...", color=0xffb84f))

        username = username.lstrip("@")
        jar = self.loader.context._session.cookies
        jar.set("sessionid", session_id, domain=".instagram.com", path="/")
        self.loader.context.username = username

        # Over prihlaseni
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None, instaloader.Profile.from_username,
                self.loader.context, username
            )
            save_session_file(username, self.loader)
            self.logged_in   = True
            self.ig_username = username
            await msg.edit(embed=discord.Embed(
                title="✅ Přihlášeno přes cookie",
                description=(
                    f"Session pro **@{username}** ověřen a uložen.\n"
                    "Bude automaticky obnoven při příštím startu."
                ),
                color=0x4fffb0,
            ))
        except Exception as e:
            self.logged_in = False
            await msg.edit(embed=discord.Embed(
                title="❌ Neplatné cookie",
                description=(
                    f"Chyba: `{e}`\n\n"
                    "Ujisti se, že jsi zkopíroval správnou hodnotu cookie **`sessionid`** "
                    "z instagram.com."
                ),
                color=0xff4f6a,
            ))

    @ig_group.command(name="status")
    @commands.has_permissions(administrator=True)
    async def ig_status(self, ctx: commands.Context):
        embed = discord.Embed(title="📊 Stav Instagram Notifier", color=0xE1306C)
        embed.add_field(
            name="🔐 Přihlášení",
            value=f"✅ @{self.ig_username}" if self.logged_in else "❌ Nepřihlášen",
            inline=True,
        )
        embed.add_field(name="📡 Sledovaných",  value=str(len(self.db.get_accounts())), inline=True)
        embed.add_field(name="⏱️ Interval",     value=f"{self.db.interval} min",        inline=True)
        embed.add_field(name="📺 Kanál",         value=f"<#{self.db.channel_id}>",       inline=True)
        embed.add_field(
            name="📦 instaloader",
            value="✅ OK" if INSTALOADER_OK else "❌ pip install instaloader",
            inline=True,
        )
        session_ok = os.path.exists(SESSION_FILE)
        embed.add_field(name="💾 Session soubor", value="✅ Uložen" if session_ok else "❌ Chybí", inline=True)
        next_run = self.check_loop.next_iteration
        if next_run:
            embed.add_field(name="⏭️ Další kontrola", value=f"<t:{int(next_run.timestamp())}:R>", inline=True)
        await ctx.send(embed=embed)

    @ig_group.command(name="add")
    @commands.has_permissions(administrator=True)
    async def ig_add(self, ctx: commands.Context, username: str):
        username = username.lstrip("@").lower()
        if username in self.db.get_accounts():
            await ctx.send(embed=discord.Embed(
                description=f"ℹ️ **@{username}** je již sledován.", color=0xffb84f))
            return
        msg = await ctx.send(embed=discord.Embed(
            description=f"⏳ Přidávám **@{username}**...", color=0xffb84f))
        if INSTALOADER_OK and self.loader:
            loop = asyncio.get_event_loop()
            post = await loop.run_in_executor(None, self.fetch_latest_post, username)
            if post is None:
                await msg.edit(embed=discord.Embed(
                    description=f"❌ Profil **@{username}** nenalezen nebo není dostupný.",
                    color=0xff4f6a))
                return
            self.db.add_account(username)
            self.db.update_last(username, post["shortcode"], post["timestamp"])
            await msg.edit(embed=discord.Embed(
                title="✅ Účet přidán",
                description=(
                    f"**@{username}** bude sledován.\n\n"
                    f"👤 {post['full_name']}\n"
                    f"👥 {post['followers']:,} sledujících\n"
                    f"📌 Poslední: [odkaz]({post['url']})"
                ),
                color=0x4fffb0,
            ))
        else:
            self.db.add_account(username)
            await msg.edit(embed=discord.Embed(
                description=f"✅ **@{username}** přidán.", color=0x4fffb0))

    @ig_group.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def ig_remove(self, ctx: commands.Context, username: str):
        username = username.lstrip("@").lower()
        if username not in self.db.get_accounts():
            await ctx.send(embed=discord.Embed(
                description=f"❌ **@{username}** není sledován.", color=0xff4f6a))
            return
        self.db.remove_account(username)
        await ctx.send(embed=discord.Embed(
            description=f"✅ **@{username}** odebrán.", color=0x4fffb0))

    @ig_group.command(name="list")
    @commands.has_permissions(administrator=True)
    async def ig_list(self, ctx: commands.Context):
        accounts = self.db.get_accounts()
        if not accounts:
            await ctx.send(embed=discord.Embed(
                description="Žádné účty nejsou sledovány. Použij `!ig add <username>`.",
                color=0x5a6a82))
            return
        lines = []
        for uname, meta in accounts.items():
            last = meta.get("last_shortcode")
            last_str = f"[odkaz](https://www.instagram.com/p/{last}/)" if last else "neznámo"
            lines.append(f"📸 **@{uname}** — poslední: {last_str}")
        embed = discord.Embed(
            title=f"📋 Sledované účty ({len(accounts)})",
            description="\n".join(lines),
            color=0xE1306C,
        )
        embed.set_footer(text=f"Interval: {self.db.interval} min")
        await ctx.send(embed=embed)

    @ig_group.command(name="check")
    @commands.has_permissions(administrator=True)
    async def ig_check(self, ctx: commands.Context):
        if not self.db.get_accounts():
            await ctx.send(embed=discord.Embed(
                description="Žádné účty nejsou sledovány.", color=0x5a6a82))
            return
        if not INSTALOADER_OK or not self.loader:
            await ctx.send(embed=discord.Embed(
                description="❌ instaloader není nainstalován.", color=0xff4f6a))
            return
        msg = await ctx.send(embed=discord.Embed(
            description=f"⏳ Kontroluji {len(self.db.get_accounts())} účtů...", color=0xffb84f))
        await self.check_loop()
        await msg.edit(embed=discord.Embed(description="✅ Kontrola dokončena.", color=0x4fffb0))

    @ig_group.command(name="interval")
    @commands.has_permissions(administrator=True)
    async def ig_interval(self, ctx: commands.Context, minutes: int):
        if minutes < 5:
            await ctx.send(embed=discord.Embed(
                description="❌ Minimum je **5 minut**.", color=0xff4f6a))
            return
        self.db.interval = minutes
        self.check_loop.change_interval(minutes=minutes)
        await ctx.send(embed=discord.Embed(
            description=f"✅ Interval nastaven na **{minutes} minut**.", color=0x4fffb0))

    @ig_group.command(name="channel")
    @commands.has_permissions(administrator=True)
    async def ig_channel(self, ctx: commands.Context, channel_id: int):
        self.db.channel_id = channel_id
        await ctx.send(embed=discord.Embed(
            description=f"✅ Notifikace budou odesílány do <#{channel_id}>.", color=0x4fffb0))

    @ig_group.error
    async def ig_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            m = await ctx.send(embed=discord.Embed(
                description="❌ Nemáš oprávnění administrátora.", color=0xff4f6a))
            await m.delete(delay=5)


# ─── Setup / Teardown ─────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    if not INSTALOADER_OK:
        print("[InstaNotifier] VAROVANI: pip install instaloader")
    await bot.add_cog(InstaNotifier(bot))
    print("[InstaNotifier] Nacteno")

async def teardown(bot: commands.Bot):
    await bot.remove_cog("InstaNotifier")
    print("[InstaNotifier] Odpojen")
