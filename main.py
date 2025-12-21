import discord
from discord.ext import commands
import os

# ===================== CONFIG =====================

TOKEN = " MTQ0NTM4NjYxMzk5OTAwOTgzMw.GUwxbV.LZZpkmX8S93APTznvLG0-0tCQEEa4_CLXMqPFs"  # ⚠️ NE PAS PARTAGER

# ID du salon public où les messages anonymes sont publiés
ANON_OUTPUT_CHANNEL_ID = 1446300023129116772  # <-- ID du salon public anonyme

# ID du salon staff privé où les logs sont envoyés
STAFF_LOG_CHANNEL_ID = 1446299983979741216  # <-- ID du salon staff

# Fichier de mots bannis (un mot/phrase par ligne)
BANNED_WORDS_FILE = "banned_words.txt"

# Bloquer les invitations Discord ?
BLOCK_DISCORD_INVITES = True

# Bloquer tous les liens (http/https/www) ?
BLOCK_URLS = False  # passe à True si tu veux bloquer tous les liens

# Longueur minimale d'un message anonyme
MIN_MESSAGE_LENGTH = 5

# ==================================================


# ===================== UTIL : MOTS BANNIS =====================

def load_banned_words():
    """
    Charge les mots interdits depuis le fichier banned_words.txt.
    Un mot ou une expression par ligne.
    Tout est converti en minuscules.
    """
    try:
        with open(BANNED_WORDS_FILE, "r", encoding="utf-8") as f:  # ✅ FIX: bon fichier
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
    """Récupère le salon staff de logs si possible."""
    return bot.get_channel(STAFF_LOG_CHANNEL_ID)


# ===================== FILTRE CONTENU ANONYME =====================

def check_message_allowed(content: str):
    """
    Vérifie si un message anonyme est acceptable.
    Retourne (allowed: bool, reason_if_blocked: str | None)
    """
    txt = content.strip()
    low = txt.lower()

    # 1) longueur minimale
    if len(txt) < MIN_MESSAGE_LENGTH:
        return False, "Ton message est trop court. Essaie de développer un peu ton texte 🙂"

    # 2) mots / expressions interdits
    for bad in BANNED_WORDS:
        if bad and bad in low:
            return False, "Ton message contient un mot ou une expression non autorisée sur ce serveur."

    # 3) liens Discord / invites
    if BLOCK_DISCORD_INVITES and ("discord.gg/" in low or "discord.com/invite" in low):
        return False, "Les invitations de serveurs Discord ne sont pas acceptées dans les messages anonymes."

    # 4) blocage global des URLs
    if BLOCK_URLS and ("http://" in low or "https://" in low or "www." in low):
        return False, "Les liens externes ne sont pas autorisés dans les messages anonymes."

    return True, None


# ===================== EVENTS =====================

@bot.event
async def on_ready():
    print(f"AlterBot connecté : {bot.user} (id={bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="DM-moi ton texte ✍️"))


@bot.event
async def on_message(message: discord.Message):
    global BANNED_WORDS

    # Ignorer les bots (y compris soi-même)
    if message.author == bot.user or message.author.bot:
        return

    # ----- CAS : DM ENVOYÉ AU BOT (ANON) -----
    if isinstance(message.channel, discord.DMChannel):
        content = message.content.strip()

        # 1) message vide
        if not content:
            await message.author.send("❌ Ton message est vide. Envoie simplement un **texte**.")
            return

        # 2) pièces jointes interdites
        if message.attachments:
            await message.author.send(
                "📎 AlterBot accepte **uniquement du texte**.\n"
                "Merci d’envoyer ton inspiration sans image, fichier ou audio."
            )
            return

        # 3) vérifier le contenu
        allowed, reason = check_message_allowed(content)

        out_channel = bot.get_channel(ANON_OUTPUT_CHANNEL_ID)
        log_channel = get_staff_log_channel()

        if out_channel is None or log_channel is None:
            await message.author.send(
                "⚠️ Erreur interne : je ne suis pas correctement configuré sur le serveur.\n"
                "Contacte un administrateur."
            )
            return

        # Message refusé
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
                value=content[:1800],  # évite dépassement Discord
                inline=False
            )
            embed_block.add_field(
                name="Raison du blocage",
                value=reason,
                inline=False
            )

            await log_channel.send(embed=embed_block)
            return

        # Message accepté
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

    # Pour que les commandes fonctionnent
    await bot.process_commands(message)


# ===================== COMMANDES UTILES =====================

@bot.command()
async def ping(ctx):
    """Test rapide pour voir si le bot répond."""
    await ctx.send("AlterBot opérationnel 🕊️")


@bot.command(name="reload_words")
@commands.has_guild_permissions(manage_messages=True)
async def reload_words(ctx):
    """Recharger la liste des mots interdits depuis banned_words.txt."""
    global BANNED_WORDS
    BANNED_WORDS = load_banned_words()
    await ctx.send("🔄 Liste des mots bannis rechargée depuis `banned_words.txt`.")


@reload_words.error
async def reload_words_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Tu n’as pas la permission d’utiliser cette commande.")


# ===================== LANCEMENT =====================

bot.run(TOKEN)
