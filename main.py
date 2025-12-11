import discord
from discord.ext import commands
from datetime import timedelta, datetime
import json
import os

# ===================== CONFIG =====================

TOKEN = " MTQ0NTM4NjYxMzk5OTAwOTgzMw.GUwxbV.LZZpkmX8S93APTznvLG0-0tCQEEa4_CLXMqPFs"  # ⚠️ NE PAS PARTAGER

# ID du salon public où les messages anonymes sont publiés
ANON_OUTPUT_CHANNEL_ID = 1445389268397854901  # <-- ID du salon public anonyme

# ID du salon staff privé où les logs sont envoyés
STAFF_LOG_CHANNEL_ID = 1445389232569978890  # <-- ID du salon staff

# Fichier de mots bannis (un mot/phrase par ligne)
BANNED_WORDS_FILE = "banned_words.txt"

# Fichier de persistance des warns
WARNINGS_FILE = "warnings.json"

# Bloquer les invitations Discord ?
BLOCK_DISCORD_INVITES = True

# Bloquer tous les liens (http/https/www) ?
BLOCK_URLS = False  # passe à True si tu veux bloquer tous les liens

# Longueur minimale d'un message anonyme
MIN_MESSAGE_LENGTH = 5

# Seuils de sanctions automatiques
WARN_MUTE_THRESHOLD = 3        # à partir de 3 warns -> mute
WARN_BAN_THRESHOLD = 5         # à partir de 5 warns -> ban
MUTE_MINUTES_ON_THRESHOLD = 30 # durée du mute auto

# ==================================================


# ===================== UTIL : MOTS BANNIS =====================

def load_banned_words():
    """
    Charge les mots interdits depuis le fichier 'banned_words.txt'.
    Un mot ou une expression par ligne.
    Tout est converti en minuscules.
    """
    try:
        with open("banned_words", "r", encoding="utf-8") as f:
            words = [line.strip().lower() for line in f if line.strip()]
        print(f"✅ {len(words)} mots interdits chargés depuis {BANNED_WORDS_FILE}")
        return words
    except FileNotFoundError:
        print(f"⚠️ Fichier '{BANNED_WORDS_FILE}' introuvable. Aucuns mots interdits chargés.")
        return []


BANNED_WORDS = load_banned_words()


# ===================== UTIL : WARNINGS PERSISTANTS =====================

def load_warnings():
    """Charge les avertissements depuis WARNINGS_FILE."""
    if not os.path.isfile(WARNINGS_FILE):
        return {}

    try:
        with open(WARNINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            return {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_warnings(data: dict):
    """Sauvegarde les avertissements dans WARNINGS_FILE."""
    try:
        with open(WARNINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError:
        print("⚠️ Impossible d'écrire dans WARNINGS_FILE.")


WARNINGS = load_warnings()
# Structure : {
#   "<guild_id>": {
#       "<user_id>": {
#           "count": int,
#           "warnings": [
#               {
#                   "reason": str,
#                   "moderator_id": int,
#                   "timestamp": str (ISO)
#               },
#               ...
#           ]
#       }
#   }
# }


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
    if BLOCK_URLS and ("http://" in low or "https://" in low or "www." in low or "https://" in low):
        return False, "Les liens externes ne sont pas autorisés dans les messages anonymes."

    # ok
    return True, None


# ===================== GESTION DES WARNS =====================

def get_user_warn_data(guild_id: int, user_id: int) -> dict:
    """Retourne la data de warns pour un user, en créant les structures si besoin."""
    gid = str(guild_id)
    uid = str(user_id)

    if gid not in WARNINGS:
        WARNINGS[gid] = {}
    if uid not in WARNINGS[gid]:
        WARNINGS[gid][uid] = {"count": 0, "warnings": []}

    return WARNINGS[gid][uid]


def add_warning(guild_id: int, user_id: int, moderator_id: int, reason: str) -> int:
    """
    Ajoute un warn à un user.
    Retourne le nouveau total de warns.
    """
    data = get_user_warn_data(guild_id, user_id)
    data["count"] += 1
    data["warnings"].append({
        "reason": reason,
        "moderator_id": moderator_id,
        "timestamp": datetime.utcnow().isoformat()
    })
    save_warnings(WARNINGS)
    return data["count"]


def reset_warnings(guild_id: int, user_id: int):
    """Réinitialise les warns d'un user."""
    gid = str(guild_id)
    uid = str(user_id)

    if gid in WARNINGS and uid in WARNINGS[gid]:
        WARNINGS[gid][uid] = {"count": 0, "warnings": []}
        save_warnings(WARNINGS)


def get_warnings(guild_id: int, user_id: int) -> dict:
    """Retourne un dict {"count": int, "warnings": [...] } (éventuellement vide)."""
    gid = str(guild_id)
    uid = str(user_id)
    return WARNINGS.get(gid, {}).get(uid, {"count": 0, "warnings": []})


async def apply_warn_consequences(ctx, member: discord.Member, total_warns: int, last_reason: str):
    """
    Applique les sanctions automatiques si le nombre de warns dépasse les seuils.
    - >= WARN_BAN_THRESHOLD : ban
    - >= WARN_MUTE_THRESHOLD : mute (timeout)
    """
    log_channel = get_staff_log_channel()

    # Ban si on a atteint le seuil de ban
    if total_warns >= WARN_BAN_THRESHOLD:
        try:
            await member.send(
                f"🚫 Tu as été banni de **{ctx.guild.name}** en raison d'un trop grand nombre "
                f"d'avertissements ({total_warns}).\n"
                f"Dernière raison : {last_reason}"
            )
        except discord.Forbidden:
            pass

        try:
            await ctx.guild.ban(member, reason=f"Trop de warns ({total_warns}). Dernière raison : {last_reason}")
        except discord.Forbidden:
            await ctx.send("❌ Je n'ai pas la permission de bannir ce membre.")
            return

        await ctx.send(f"🚫 {member.mention} a été banni automatiquement (trop de warns).")

        if log_channel:
            await log_channel.send(
                f"🚫 **Ban automatique** : {member.mention} (ID {member.id}) "
                f"pour {total_warns} warns. Dernière raison : {last_reason}"
            )

        return

    # Sinon, mute si on a atteint le seuil de mute (et pas encore ban)
    if total_warns >= WARN_MUTE_THRESHOLD:
        until = discord.utils.utcnow() + timedelta(minutes=MUTE_MINUTES_ON_THRESHOLD)

        try:
            await member.edit(timed_out_until=until)
        except discord.Forbidden:
            await ctx.send("❌ Je n'ai pas la permission de mute ce membre (timeout).")
            return

        try:
            await member.send(
                f"⏱️ Tu as été mis en timeout sur **{ctx.guild.name}** pendant "
                f"{MUTE_MINUTES_ON_THRESHOLD} minutes en raison de tes avertissements "
                f"({total_warns}).\nDernière raison : {last_reason}"
            )
        except discord.Forbidden:
            pass

        await ctx.send(
            f"⏱️ {member.mention} a été mute automatiquement pendant "
            f"{MUTE_MINUTES_ON_THRESHOLD} minutes (trop de warns : {total_warns})."
        )

        if log_channel:
            await log_channel.send(
                f"⏱️ **Mute automatique** : {member.mention} (ID {member.id}) "
                f"pour {total_warns} warns. Dernière raison : {last_reason}"
            )


# ===================== EVENTS =====================

@bot.event
async def on_ready():
    print(f"AlterBot connecté : {bot.user} (id={bot.user.id})")
    await bot.change_presence(
        activity=discord.Game(name="DM-moi ton texte ✍️")
    )


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
            await message.author.send(
                f"❌ Ton message n’a pas pu être envoyé anonymement :\n> {reason}"
            )

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
                value=content,
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
        # compteur anonyme stocké en attribut sur le bot pour garder un état simple
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
            value=content,
            inline=False
        )

        await log_channel.send(embed=embed_log)

        await message.author.send(
            "✅ Ton texte a été envoyé **anonymement** au salon.\n"
            "Merci pour ta confiance 🙏"
        )

        return

    # Pour que les commandes (!warn, !mute, etc.) fonctionnent
    await bot.process_commands(message)


# ===================== COMMANDES MODÉRATION & UTILES =====================

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


@bot.command(name="warn")
@commands.has_guild_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason: str = "Aucune raison spécifiée."):
    """Ajoute un avertissement à un membre + sanctions automatiques si seuil."""
    if member == ctx.author:
        await ctx.send("❌ Tu ne peux pas te warn toi-même.")
        return

    total = add_warning(ctx.guild.id, member.id, ctx.author.id, reason)

    # DM au membre
    try:
        await member.send(
            f"⚠️ Tu as reçu un avertissement sur **{ctx.guild.name}**.\n"
            f"Raison : {reason}\n"
            f"Nombre total d'avertissements : {total}"
        )
    except discord.Forbidden:
        pass

    await ctx.send(
        f"⚠️ {member.mention} a été averti. (Total : {total} warns)\n"
        f"Raison : {reason}"
    )

    log_channel = get_staff_log_channel()
    if log_channel:
        await log_channel.send(
            f"⚠️ **Warn** : {member.mention} (ID {member.id}) par {ctx.author.mention}.\n"
            f"Raison : {reason}\nTotal warns : {total}"
        )

    await apply_warn_consequences(ctx, member, total, reason)


@bot.command(name="warns")
@commands.has_guild_permissions(manage_messages=True)
async def warns(ctx, member: discord.Member):
    """Affiche le nombre de warns d'un membre et les détails."""
    data = get_warnings(ctx.guild.id, member.id)
    count = data["count"]
    warns_list = data["warnings"]

    if count == 0:
        await ctx.send(f"✅ {member.mention} n'a aucun avertissement.")
        return

    embed = discord.Embed(
        title=f"⚠️ Avertissements de {member}",
        colour=discord.Colour.orange()
    )
    embed.add_field(name="Total", value=str(count), inline=False)

    # On affiche max 5 derniers warns
    for w in warns_list[-5:]:
        ts = w.get("timestamp", "??")
        mod_id = w.get("moderator_id", None)
        mod_txt = f"<@{mod_id}>" if mod_id else "Inconnu"
        reason = w.get("reason", "Aucune raison spécifiée.")
        embed.add_field(
            name=f"{ts} par {mod_txt}",
            value=reason,
            inline=False
        )

    await ctx.send(embed=embed)


@bot.command(name="reset_warns")
@commands.has_guild_permissions(manage_messages=True)
async def reset_warns(ctx, member: discord.Member):
    """Réinitialise tous les warns d'un membre."""
    reset_warnings(ctx.guild.id, member.id)
    await ctx.send(f"✅ Tous les avertissements de {member.mention} ont été réinitialisés.")

    log_channel = get_staff_log_channel()
    if log_channel:
        await log_channel.send(
            f"✅ **Reset warns** : avertissements de {member.mention} remis à zéro par {ctx.author.mention}."
        )


@bot.command(name="mute")
@commands.has_guild_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int = 10, *, reason: str = "Aucune raison spécifiée."):
    """Met en timeout (mute) un membre pendant X minutes."""
    if minutes <= 0:
        await ctx.send("❌ La durée doit être positive.")
        return

    until = discord.utils.utcnow() + timedelta(minutes=minutes)

    try:
        await member.edit(timed_out_until=until, reason=reason)
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de mute ce membre.")
        return

    await ctx.send(
        f"⏱️ {member.mention} a été mute pendant **{minutes} minutes**.\nRaison : {reason}"
    )

    try:
        await member.send(
            f"⏱️ Tu as été mute sur **{ctx.guild.name}** pendant {minutes} minutes.\nRaison : {reason}"
        )
    except discord.Forbidden:
        pass

    log_channel = get_staff_log_channel()
    if log_channel:
        await log_channel.send(
            f"⏱️ **Mute** : {member.mention} (ID {member.id}) pendant {minutes} minutes par {ctx.author.mention}.\n"
            f"Raison : {reason}"
        )


@bot.command(name="unmute")
@commands.has_guild_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    """Retire le timeout (mute) d'un membre."""
    try:
        await member.edit(timed_out_until=None)
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de unmute ce membre.")
        return

    await ctx.send(f"🔊 {member.mention} a été unmute.")

    try:
        await member.send(
            f"🔊 Ton mute a été retiré sur **{ctx.guild.name}**."
        )
    except discord.Forbidden:
        pass

    log_channel = get_staff_log_channel()
    if log_channel:
        await log_channel.send(
            f"🔊 **Unmute** : {member.mention} (ID {member.id}) par {ctx.author.mention}."
        )


@bot.command(name="kick")
@commands.has_guild_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "Aucune raison spécifiée."):
    """Kick un membre du serveur."""
    try:
        await member.send(
            f"👢 Tu as été expulsé de **{ctx.guild.name}**.\nRaison : {reason}"
        )
    except discord.Forbidden:
        pass

    try:
        await ctx.guild.kick(member, reason=reason)
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de kick ce membre.")
        return

    await ctx.send(f"👢 {member.mention} a été expulsé.\nRaison : {reason}")

    log_channel = get_staff_log_channel()
    if log_channel:
        await log_channel.send(
            f"👢 **Kick** : {member.mention} (ID {member.id}) par {ctx.author.mention}.\n"
            f"Raison : {reason}"
        )


@bot.command(name="ban")
@commands.has_guild_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "Aucune raison spécifiée."):
    """Ban un membre du serveur."""
    try:
        await member.send(
            f"🚫 Tu as été banni de **{ctx.guild.name}**.\nRaison : {reason}"
        )
    except discord.Forbidden:
        pass

    try:
        await ctx.guild.ban(member, reason=reason)
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de bannir ce membre.")
        return

    await ctx.send(f"🚫 {member.mention} a été banni.\nRaison : {reason}")

    log_channel = get_staff_log_channel()
    if log_channel:
        await log_channel.send(
            f"🚫 **Ban** : {member.mention} (ID {member.id}) par {ctx.author.mention}.\n"
            f"Raison : {reason}"
        )


# ===================== LANCEMENT =====================

bot.run(TOKEN)
