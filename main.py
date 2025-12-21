import discord
from discord.ext import commands, tasks
import json
import os
import aiohttp
import feedparser

# ===================== CONFIG =====================

TOKEN = " MTQ0NTM4NjYxMzk5OTAwOTgzMw.GUwxbV.LZZpkmX8S93APTznvLG0-0tCQEEa4_CLXMqPFs"  # ⚠️ NE PAS PARTAGER

# ID du salon public où les messages anonymes sont publiés
ANON_OUTPUT_CHANNEL_ID = 1446300023129116772

# ID du salon staff privé où les logs sont envoyés
STAFF_LOG_CHANNEL_ID = 1446299983979741216

# Fichier de mots bannis (un mot/phrase par ligne)
BANNED_WORDS_FILE = "banned_words.txt"

# Bloquer les invitations Discord ?
BLOCK_DISCORD_INVITES = True

# Bloquer tous les liens (http/https/www) ?
BLOCK_URLS = False

# Longueur minimale d'un message anonyme
MIN_MESSAGE_LENGTH = 5

# ======= NOTIFS RÉSEAUX (RSS) =======
# Salon où poster les notifs réseaux
SOCIAL_NOTIF_CHANNEL_ID = 1446300023129116772  # <-- mets un salon "annonces" si tu veux

# Flux RSS (TikTok / Insta posts) -> tu colles ici des URL RSS
RUTRA_TIKTOK_RSS = "COLLE_ICI_RSS_TIKTOK"
RUTRA_INSTAGRAM_RSS = "https://rsshub.app/instagram/user/test.59898989"


# Ping @everyone ?
PING_EVERYONE = True

# Fréquence (en secondes)
SOCIAL_CHECK_SECONDS = 60

# Fichier d'état pour ne pas renvoyer la même notif
SOCIAL_STATE_FILE = "social_state.json"

# ==================================================


# ===================== UTIL : MOTS BANNIS =====================

def load_banned_words():
    """
    Charge les mots interdits depuis banned_words.txt
    """
    try:
        with open(BANNED_WORDS_FILE, "r", encoding="utf-8") as f:
            words = [line.strip().lower() for line in f if line.strip()]
        print(f"✅ {len(words)} mots interdits chargés depuis {BANNED_WORDS_FILE}")
        return words
    except FileNotFoundError:
        print(f"⚠️ Fichier '{BANNED_WORDS_FILE}' introuvable. Aucun mot interdit chargé.")
        return []


BANNED_WORDS = load_banned_words()


# ===================== DISCORD SETUP =====================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
if hasattr(intents, "dm_messages"):
    intents.dm_messages = True

bot = commands.Bot(command_prefix="!", intents=intents)


def get_staff_log_channel():
    return bot.get_channel(STAFF_LOG_CHANNEL_ID)


# ===================== FILTRE CONTENU ANONYME =====================

def check_message_allowed(content: str):
    txt = content.strip()
    low = txt.lower()

    if len(txt) < MIN_MESSAGE_LENGTH:
        return False, "Ton message est trop court. Essaie de développer un peu ton texte 🙂"

    for bad in BANNED_WORDS:
        if bad and bad in low:
            return False, "Ton message contient un mot ou une expression non autorisée sur ce serveur."

    if BLOCK_DISCORD_INVITES and ("discord.gg/" in low or "discord.com/invite" in low):
        return False, "Les invitations de serveurs Discord ne sont pas acceptées dans les messages anonymes."

    if BLOCK_URLS and ("http://" in low or "https://" in low or "www." in low):
        return False, "Les liens externes ne sont pas autorisés dans les messages anonymes."

    return True, None


# ===================== NOTIFS RÉSEAUX (RSS) =====================

def load_social_state() -> dict:
    if not os.path.isfile(SOCIAL_STATE_FILE):
        return {}
    try:
        with open(SOCIAL_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_social_state(state: dict):
    try:
        with open(SOCIAL_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception:
        print("⚠️ Impossible d'écrire social_state.json")


SOCIAL_STATE = load_social_state()
_http_session: aiohttp.ClientSession | None = None


async def fetch_rss(url: str) -> bytes | None:
    global _http_session
    if _http_session is None:
        _http_session = aiohttp.ClientSession(headers={"User-Agent": "AlterBot/1.0"})

    try:
        async with _http_session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                print(f"⚠️ RSS HTTP {resp.status} sur {url}")
                return None
            return await resp.read()
    except Exception as e:
        print(f"⚠️ RSS fetch error: {e}")
        return None


async def send_social_message(source: str, title: str, link: str):
    channel = bot.get_channel(SOCIAL_NOTIF_CHANNEL_ID)
    if not channel:
        print("⚠️ SOCIAL_NOTIF_CHANNEL_ID invalide.")
        return

    ping = "@everyone " if PING_EVERYONE else ""
    msg = f"{ping}📢 **Nouveau {source} de Rutra** : {title}\n{link}".strip()

    try:
        await channel.send(
            msg,
            allowed_mentions=discord.AllowedMentions(everyone=PING_EVERYONE)
        )
    except Exception as e:
        print(f"⚠️ Impossible d'envoyer notif réseaux: {e}")


async def check_one_feed(source: str, feed_url: str, state_key: str):
    if not feed_url or "COLLE_ICI" in feed_url:
        return

    data = await fetch_rss(feed_url)
    if not data:
        return

    parsed = feedparser.parse(data)
    if not parsed.entries:
        return

    latest = parsed.entries[0]
    latest_id = getattr(latest, "id", None) or getattr(latest, "link", None) or getattr(latest, "title", None)
    latest_title = getattr(latest, "title", "Nouveau post")
    latest_link = getattr(latest, "link", "")

    last_seen = SOCIAL_STATE.get(state_key)

    # 1er lancement : on initialise sans ping (évite spam du vieux contenu)
    if last_seen is None:
        SOCIAL_STATE[state_key] = latest_id
        save_social_state(SOCIAL_STATE)
        return

    # Nouveau contenu
    if latest_id and latest_id != last_seen:
        await send_social_message(source, latest_title, latest_link)
        SOCIAL_STATE[state_key] = latest_id
        save_social_state(SOCIAL_STATE)


@tasks.loop(seconds=SOCIAL_CHECK_SECONDS)
async def social_notifier_loop():
    await check_one_feed("TikTok", RUTRA_TIKTOK_RSS, "tiktok_last_id")
    await check_one_feed("Instagram", RUTRA_INSTAGRAM_RSS, "instagram_last_id")


@social_notifier_loop.before_loop
async def before_social_notifier_loop():
    await bot.wait_until_ready()


# ===================== EVENTS =====================

@bot.event
async def on_ready():
    print(f"AlterBot connecté : {bot.user} (id={bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="DM-moi ton texte ✍️"))

    if not social_notifier_loop.is_running():
        social_notifier_loop.start()
        print("✅ Social notifier lancé (RSS).")


@bot.event
async def on_message(message: discord.Message):
    global BANNED_WORDS

    if message.author == bot.user or message.author.bot:
        return

    # ----- DM -> message anonyme -----
    if isinstance(message.channel, discord.DMChannel):
        content = message.content.strip()

        if not content:
            await message.author.send("❌ Ton message est vide. Envoie simplement un **texte**.")
            return

        if message.attachments:
            await message.author.send(
                "📎 AlterBot accepte **uniquement du texte**.\n"
                "Merci d’envoyer ton inspiration sans image, fichier ou audio."
            )
            return

        allowed, reason = check_message_allowed(content)

        out_channel = bot.get_channel(ANON_OUTPUT_CHANNEL_ID)
        log_channel = get_staff_log_channel()

        if out_channel is None or log_channel is None:
            await message.author.send(
                "⚠️ Erreur interne : je ne suis pas correctement configuré sur le serveur.\n"
                "Contacte un administrateur."
            )
            return

        if not allowed:
            await message.author.send(f"❌ Ton message n’a pas pu être envoyé anonymement :\n> {reason}")

            embed_block = discord.Embed(
                title="🚫 Message anonyme BLOQUÉ",
                colour=discord.Colour.orange()
            )
            embed_block.add_field(
                name="Auteur réel",
                value=f"{message.author} (ID {message.author.id})",
                inline=False
            )
            embed_block.add_field(
                name="Texte",
                value=content[:1800],
                inline=False
            )
            embed_block.add_field(
                name="Raison du blocage",
                value=reason,
                inline=False
            )

            await log_channel.send(embed=embed_block)
            return

        if not hasattr(bot, "anon_counter"):
            bot.anon_counter = 0
        bot.anon_counter += 1
        num = bot.anon_counter

        embed_public = discord.Embed(
            title=f"💬 Message anonyme #{num}",
            description=content,
            colour=discord.Colour.purple()
        )
        embed_public.set_footer(text="Envoyé anonymement via AlterBot.")

        await out_channel.send(embed=embed_public)

        embed_log = discord.Embed(
            title="📥 Nouveau message anonyme ACCEPTÉ",
            colour=discord.Colour.dark_green()
        )
        embed_log.add_field(
            name="Auteur réel",
            value=f"{message.author} (ID {message.author.id})",
            inline=False
        )
        embed_log.add_field(
            name="Texte",
            value=content[:1800],
            inline=False
        )

        await log_channel.send(embed=embed_log)

        await message.author.send("✅ Ton texte a été envoyé **anonymement** au salon.\nMerci 🙏")
        return

    await bot.process_commands(message)


# ===================== COMMANDES UTILES =====================

@bot.command()
async def ping(ctx):
    await ctx.send("AlterBot opérationnel 🕊️")


@bot.command(name="reload_words")
@commands.has_guild_permissions(manage_messages=True)
async def reload_words(ctx):
    global BANNED_WORDS
    BANNED_WORDS = load_banned_words()
    await ctx.send("🔄 Liste des mots bannis rechargée depuis `banned_words.txt`.")


@reload_words.error
async def reload_words_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Tu n’as pas la permission d’utiliser cette commande.")


# ===================== LANCEMENT =====================

bot.run(TOKEN)
