import os
from dotenv import load_dotenv

import discord
from discord.ext import commands
from datetime import timedelta
from datetime import datetime

from db import db_exec, db_fetchall, db_fetchone

# ===================== CONFIG =====================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "")  # Mets-le dans .env, PAS en dur

ANON_OUTPUT_CHANNEL_ID = 1446300023129116772
STAFF_LOG_CHANNEL_ID = 1446299983979741216

BLOCK_DISCORD_INVITES = True
BLOCK_URLS = False
MIN_MESSAGE_LENGTH = 5

WARN_MUTE_THRESHOLD = 3
WARN_BAN_THRESHOLD = 5
MUTE_MINUTES_ON_THRESHOLD = 30

# ==================================================


# ===================== DISCORD SETUP =====================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def get_staff_log_channel():
    return bot.get_channel(STAFF_LOG_CHANNEL_ID)


# ===================== BANNED WORDS (DB) =====================

def get_banned_words(guild_id: int) -> list[str]:
    rows = db_fetchall(
        "SELECT word FROM banned_words WHERE guild_id=%s",
        (guild_id,)
    )
    return [r[0].lower() for r in rows]


def find_triggered_word(content: str, banned_words: list[str]) -> str | None:
    low = content.lower()
    for w in banned_words:
        if w and w in low:
            return w
    return None


def check_message_allowed(content: str, banned_words: list[str]):
    txt = content.strip()
    low = txt.lower()

    if len(txt) < MIN_MESSAGE_LENGTH:
        return False, "Ton message est trop court. Essaie de développer un peu ton texte 🙂", None

    triggered = find_triggered_word(txt, banned_words)
    if triggered:
        return False, "Ton message contient un mot ou une expression non autorisée sur ce serveur.", triggered

    if BLOCK_DISCORD_INVITES and ("discord.gg/" in low or "discord.com/invite" in low):
        return False, "Les invitations de serveurs Discord ne sont pas acceptées dans les messages anonymes.", "discord_invite"

    if BLOCK_URLS and ("http://" in low or "https://" in low or "www." in low):
        return False, "Les liens externes ne sont pas autorisés dans les messages anonymes.", "url"

    return True, None, None


def log_anonymous_report(guild_id: int, author_id: int, content: str, triggered_word: str | None):
    try:
        db_exec(
            "INSERT INTO anonymous_reports (guild_id, author_id, content, triggered_word) VALUES (%s, %s, %s, %s)",
            (guild_id, author_id, content, triggered_word)
        )
    except Exception as e:
        print(f"[DB] log anonymous_reports failed: {e}")


# ===================== WARNS (DB) =====================

def add_warning(guild_id: int, user_id: int, moderator_id: int, reason: str) -> int:
    """
    Ta table warns n'a PAS moderator_id, donc on ne le stocke pas.
    (Si tu veux, je te donne l'ALTER pour l'ajouter.)
    """
    db_exec(
        "INSERT INTO warns (guild_id, user_id, reason) VALUES (%s, %s, %s)",
        (guild_id, user_id, reason)
    )

    row = db_fetchone(
        "SELECT COUNT(*) FROM warns WHERE guild_id=%s AND user_id=%s",
        (guild_id, user_id)
    )
    return int(row[0]) if row else 0


def reset_warnings(guild_id: int, user_id: int):
    db_exec(
        "DELETE FROM warns WHERE guild_id=%s AND user_id=%s",
        (guild_id, user_id)
    )


def get_warnings(guild_id: int, user_id: int) -> dict:
    rows = db_fetchall(
        "SELECT reason, created_at FROM warns WHERE guild_id=%s AND user_id=%s ORDER BY created_at ASC",
        (guild_id, user_id)
    )

    warnings = []
    for reason, created_at in rows:
        warnings.append({
            "reason": reason,
            "moderator_id": None,  # pas stocké dans ta table actuelle
            "timestamp": created_at.isoformat() if created_at else "??"
        })

    return {"count": len(warnings), "warnings": warnings}


async def apply_warn_consequences(ctx, member: discord.Member, total_warns: int, last_reason: str):
    log_channel = get_staff_log_channel()

    if total_warns >= WARN_BAN_THRESHOLD:
        try:
            await member.send(
                f"🚫 Tu as été banni de **{ctx.guild.name}** car tu as atteint {total_warns} warns.\n"
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

    if total_warns >= WARN_MUTE_THRESHOLD:
        until = discord.utils.utcnow() + timedelta(minutes=MUTE_MINUTES_ON_THRESHOLD)

        try:
            await member.edit(timed_out_until=until)
        except discord.Forbidden:
            await ctx.send("❌ Je n'ai pas la permission de mute ce membre (timeout).")
            return

        try:
            await member.send(
                f"⏱️ Tu as été mis en timeout sur **{ctx.guild.name}** pendant {MUTE_MINUTES_ON_THRESHOLD} minutes "
                f"car tu as {total_warns} warns.\nDernière raison : {last_reason}"
            )
        except discord.Forbidden:
            pass

        await ctx.send(
            f"⏱️ {member.mention} a été mute automatiquement pendant {MUTE_MINUTES_ON_THRESHOLD} minutes "
            f"(trop de warns : {total_warns})."
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
    await bot.change_presence(activity=discord.Game(name="DM-moi ton texte ✍️"))


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user or message.author.bot:
        return

    # ----- CAS : DM ENVOYÉ AU BOT (ANON) -----
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

        out_channel = bot.get_channel(ANON_OUTPUT_CHANNEL_ID)
        log_channel = get_staff_log_channel()

        if out_channel is None or log_channel is None:
            await message.author.send(
                "⚠️ Erreur interne : je ne suis pas correctement configuré sur le serveur.\n"
                "Contacte un administrateur."
            )
            return

        guild_id = out_channel.guild.id
        banned_words = get_banned_words(guild_id)

        allowed, reason, triggered = check_message_allowed(content, banned_words)

        # Message refusé
        if not allowed:
            await message.author.send(f"❌ Ton message n’a pas pu être envoyé anonymement :\n> {reason}")

            # Log DB
            log_anonymous_report(guild_id, message.author.id, content, triggered)

            # Log staff
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
                value=content[:1000],
                inline=False
            )
            embed_block.add_field(
                name="Raison",
                value=f"{reason} (trigger: {triggered})",
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
            value=content[:1000],
            inline=False
        )
        await log_channel.send(embed=embed_log)

        await message.author.send("✅ Ton texte a été envoyé **anonymement** au salon.\nMerci pour ta confiance 🙏")
        return

    await bot.process_commands(message)


# ===================== COMMANDES =====================

@bot.command()
async def ping(ctx):
    await ctx.send("AlterBot opérationnel 🕊️")


@bot.command(name="warn")
@commands.has_guild_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason: str = "Aucune raison spécifiée."):
    if member == ctx.author:
        await ctx.send("❌ Tu ne peux pas te warn toi-même.")
        return

    total = add_warning(ctx.guild.id, member.id, ctx.author.id, reason)

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

    for w in warns_list[-5:]:
        ts = w.get("timestamp", "??")
        reason = w.get("reason", "Aucune raison spécifiée.")
        embed.add_field(name=f"{ts}", value=reason, inline=False)

    await ctx.send(embed=embed)


@bot.command(name="reset_warns")
@commands.has_guild_permissions(manage_messages=True)
async def reset_warns(ctx, member: discord.Member):
    reset_warnings(ctx.guild.id, member.id)
    await ctx.send(f"✅ Tous les avertissements de {member.mention} ont été réinitialisés.")

    log_channel = get_staff_log_channel()
    if log_channel:
        await log_channel.send(
            f"✅ **Reset warns** : avertissements de {member.mention} remis à zéro par {ctx.author.mention}."
        )


@bot.command(name="addword")
@commands.has_guild_permissions(manage_messages=True)
async def addword(ctx, *, word: str):
    word = word.strip().lower()
    if not word:
        await ctx.send("❌ Mot invalide.")
        return

    try:
        db_exec(
            "INSERT INTO banned_words (guild_id, word) VALUES (%s, %s)",
            (ctx.guild.id, word)
        )
        await ctx.send(f"🚫 Mot ajouté : `{word}`")
    except Exception as e:
        await ctx.send(f"⚠️ Erreur SQL : `{e}`")


@bot.command(name="delword")
@commands.has_guild_permissions(manage_messages=True)
async def delword(ctx, *, word: str):
    word = word.strip().lower()
    db_exec(
        "DELETE FROM banned_words WHERE guild_id=%s AND word=%s",
        (ctx.guild.id, word)
    )
    await ctx.send(f"✅ Mot supprimé : `{word}`")


@bot.command(name="listwords")
@commands.has_guild_permissions(manage_messages=True)
async def listwords(ctx):
    words = get_banned_words(ctx.guild.id)
    if not words:
        await ctx.send("✅ Aucun mot interdit.")
        return
    # limite Discord: évite les pavés
    await ctx.send("🚫 Mots interdits:\n" + "\n".join(f"- {w}" for w in words[:50]))


@bot.command(name="mute")
@commands.has_guild_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int = 10, *, reason: str = "Aucune raison spécifiée."):
    if minutes <= 0:
        await ctx.send("❌ La durée doit être positive.")
        return

    until = discord.utils.utcnow() + timedelta(minutes=minutes)

    try:
        await member.edit(timed_out_until=until, reason=reason)
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de mute ce membre.")
        return

    await ctx.send(f"⏱️ {member.mention} a été mute pendant **{minutes} minutes**.\nRaison : {reason}")

    try:
        await member.send(f"⏱️ Tu as été mute sur **{ctx.guild.name}** pendant {minutes} minutes.\nRaison : {reason}")
    except discord.Forbidden:
        pass


@bot.command(name="unmute")
@commands.has_guild_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    try:
        await member.edit(timed_out_until=None)
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de unmute ce membre.")
        return
    await ctx.send(f"🔊 {member.mention} a été unmute.")


@bot.command(name="kick")
@commands.has_guild_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "Aucune raison spécifiée."):
    try:
        await ctx.guild.kick(member, reason=reason)
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de kick ce membre.")
        return
    await ctx.send(f"👢 {member.mention} a été expulsé.\nRaison : {reason}")


@bot.command(name="ban")
@commands.has_guild_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "Aucune raison spécifiée."):
    try:
        await ctx.guild.ban(member, reason=reason)
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de bannir ce membre.")
        return
    await ctx.send(f"🚫 {member.mention} a été banni.\nRaison : {reason}")


# ===================== LANCEMENT =====================

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN est vide. Mets-le dans .env (DISCORD_TOKEN=...)")

bot.run(TOKEN)
