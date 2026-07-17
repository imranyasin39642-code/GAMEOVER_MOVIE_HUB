"""
🎮 GameOver Music Bot — Playback Controls Plugin
Premium styled control buttons panel and playback action handlers.
Uses Pyrogram callback queries to control the player.
"""

import os
import time
import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import Config
from core.queue_manager import queue_manager
from core.player import (
    stream_manager, STAR, SKIP, QUEUE, CLOCK, LINK, USER, TRASH, WARN, INFO, WAVE, SLEEP, PLAY
)
from core.vod_scraper import SubjectType

# ── Emojis ────────────────────────────────────────────────────────────────────
PAUSE_E  = '<tg-emoji emoji-id="5330250874730082574">🌟</tg-emoji>'
STOP_E   = '<tg-emoji emoji-id="5339263210765710901">🌟</tg-emoji>'
MUTE_E   = '<tg-emoji emoji-id="5330519486279740988">🌟</tg-emoji>'
LOOP_E   = '<tg-emoji emoji-id="5330418447174099706">🌟</tg-emoji>'
CHECK_E  = '<tg-emoji emoji-id="5332572076920298887">🌟</tg-emoji>'

ROYAL_HEADER = "👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ᴍᴜsɪᴄ ʙᴏᴛ</b> 👑\n\n"


def control_buttons(state: str = "play") -> InlineKeyboardMarkup:
    """Helper for basic control panel button structures (no emojis, colored)."""
    skip_btn    = InlineKeyboardButton("SKIP",   callback_data="play_skip", style="success")
    stop_btn    = InlineKeyboardButton("STOP",   callback_data="play_stop", style="danger")
    pause_btn   = InlineKeyboardButton("PAUSE",  callback_data="play_pause", style="success")
    resume_btn  = InlineKeyboardButton("RESUME", callback_data="play_resume", style="success")
    close_btn   = InlineKeyboardButton("CLOSE",   callback_data="vcplay_close", style="danger")

    if state == "pause":
        return InlineKeyboardMarkup([[skip_btn, stop_btn, resume_btn], [close_btn]])
    return InlineKeyboardMarkup([[skip_btn, stop_btn, pause_btn], [close_btn]])


def format_seconds(seconds: int) -> str:
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes:02d}:{secs:02d}"


def get_rich_control_buttons(chat_id: int, is_paused: bool = False) -> InlineKeyboardMarkup:
    """Returns styled colored buttons adjusted dynamically for 16:9 (wide) or 9:16 (vertical) aspects."""
    session_data = None
    try:
        from plugins.movies import vod_sessions
        session_data = vod_sessions.get(chat_id)
    except Exception as e:
        print(f"[Controls] Error importing/getting vod_sessions: {e}")
    next_ep_btn = None
    
    if session_data and session_data.get("current_item") and session_data["current_item"].subjectType == SubjectType.TV_SERIES:
        seasons = session_data.get("seasons", [])
        chosen_season = session_data.get("chosen_season", 1)
        chosen_episode = session_data.get("chosen_episode", 1)
        
        next_season = None
        next_episode = None
        
        current_season_info = next((s for s in seasons if s.se == chosen_season), None)
        if current_season_info:
            if chosen_episode < current_season_info.maxEp:
                next_season = chosen_season
                next_episode = chosen_episode + 1
            else:
                for s in seasons:
                    if s.se == chosen_season + 1:
                        next_season = chosen_season + 1
                        next_episode = 1
                        break
                        
        if next_season is not None and next_episode is not None:
            # No emojis! Styled
            next_ep_btn = InlineKeyboardButton(
                f"⏭ S{next_season}E{next_episode}", 
                callback_data=f"VODNEXT|{chat_id}|{next_season}|{next_episode}",
                style="success"
            )
            
    skip_btn = next_ep_btn if next_ep_btn else InlineKeyboardButton("⏭ SKIP NEXT", callback_data=f"play_skip_{chat_id}", style="success")
    play_pause_text = "⏸ PAUSE" if not is_paused else "▶️ RESUME"
    pause_btn = InlineKeyboardButton(play_pause_text, callback_data=f"play_pause_{chat_id}", style="success")
    stop_btn = InlineKeyboardButton("⏹ STOP", callback_data=f"play_stop_{chat_id}", style="danger")
    close_btn = InlineKeyboardButton("❌ CLOSE", callback_data=f"play_close_{chat_id}", style="danger")
    
    seek_back_10 = InlineKeyboardButton("⏪ -10s", callback_data=f"play_seek_-10_{chat_id}", style="primary")
    seek_fwd_10 = InlineKeyboardButton("⏩ +10s", callback_data=f"play_seek_10_{chat_id}", style="primary")
    seek_back_5m = InlineKeyboardButton("⏪ -5M", callback_data=f"play_seek_-300_{chat_id}", style="primary")
    seek_fwd_5m = InlineKeyboardButton("⏩ +5M", callback_data=f"play_seek_300_{chat_id}", style="primary")
    
    # Download Button
    download_btn = InlineKeyboardButton("📥 DOWNLOAD", callback_data=f"play_download_{chat_id}", style="success")
    
    # Returns the exact responsive layout designed to prevent narrow screen squishing
    return InlineKeyboardMarkup([
        [seek_back_10, pause_btn, seek_fwd_10],
        [seek_back_5m, stop_btn, seek_fwd_5m],
        [skip_btn, download_btn],
        [close_btn]
    ])


def get_rich_caption(song, played_secs: int = 0) -> str:
    """Returns styled HTML playback card text with dynamic seek progress bar."""
    played_time = format_seconds(played_secs)
    total_time = song.duration if song.duration else "LIVE"
    
    bar_length = 15
    total_secs = song.duration_secs if song.duration_secs else 0
    if total_secs > 0:
        percent = played_secs / total_secs
        index = int(percent * bar_length)
        index = max(0, min(index, bar_length - 1))
        bar = ["━"] * bar_length
        bar[index] = "🔘"
        bar_str = "".join(bar)
    else:
        bar_str = "━🔘━━━━━━━━━━━━"
        
    is_vod = (getattr(song, "uploader", "") == "MOVIES Engine") or (song.duration == "VOD")
    title_display = f"<code>{song.title}</code>" if is_vod else f"<a href='{song.webpage_url}'>{song.title}</a>"
    
    return (
        f"{ROYAL_HEADER}"
        f"<emoji id='5330273431898318607'>⚡</emoji> <b>ɴᴏᴡ sᴛʀᴇᴀᴍɪɴɢ</b> <emoji id='5330273431898318607'>⚡</emoji>\n\n"
        f"{LINK} <b>Title:</b> {title_display}\n"
        f"{CLOCK} <b>Duration:</b> <code>{played_time}</code> {bar_str} <code>{total_time}</code>\n"
        f"{USER} <b>Requested by:</b> <code>{song.requested_by}</code>"
    )


def help_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 USERS",   callback_data="help_user",  style="success"),
         InlineKeyboardButton("⚙️ ADMINS",  callback_data="help_admin", style="primary"),
         InlineKeyboardButton("👑 OWNER",   callback_data="help_owner", style="primary")],
        [InlineKeyboardButton("ℹ️ DEVS",    callback_data="help_devs",  style="primary"),
         InlineKeyboardButton("❌ CLOSE",   callback_data="vcplay_close", style="danger")],
        [InlineKeyboardButton("🏠 HOME",    callback_data="help_back",  style="success")]
    ])


def back_help_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 HELP", callback_data="help_all",   style="primary"),
         InlineKeyboardButton("🏠 HOME", callback_data="help_back",  style="success")],
        [InlineKeyboardButton("❌ CLOSE", callback_data="vcplay_close", style="danger")]
    ])


def _now_playing_card(song, label: str = "Now Playing", extra: str = "") -> str:
    lang_line = ""
    is_vod = (getattr(song, "uploader", "") == "MOVIES Engine") or (song.duration == "VOD")
    title_display = f"<code>{song.title}</code>" if is_vod else f"<a href='{song.webpage_url}'>{song.title}</a>"
    if getattr(song, "uploader", "") == "MOVIES Engine":
        lang_str = "Hindi" if "hindi" in song.title.lower() else "English"
        lang_line = f"🗣 <b>Language:</b> {lang_str}\n"
        
    return (
        f"{ROYAL_HEADER}"
        f"{STAR} <u><b>{label}</b></u> {STAR}\n\n"
        f"{LINK} <b>Title:</b> {title_display}\n"
        f"{CLOCK} <b>Duration:</b> {song.duration}\n"
        f"{USER} <b>Requested by:</b> <code>{song.requested_by}</code>\n"
        f"{lang_line}"
        + (f"\n{extra}" if extra else "")
    )


def register(app: Client):

    @app.on_message(filters.command(["skip", "next", "s", "vote", "voteskip"]) & filters.group)
    async def skip_command(client: Client, message: Message):
        chat_id = message.chat.id
        user = message.from_user
        user_id = user.id if user else 0
        user_name = user.first_name if user else "Someone"
        print(f"\n[Cmd] Skip/Vote in chat {chat_id} by user {user_id}")

        if not queue_manager.is_playing(chat_id):
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"{WARN} <b>Nothing is currently playing!</b>",
                parse_mode=enums.ParseMode.HTML
            )
            return

        await stream_manager.handle_vote_skip(
            chat_id=chat_id,
            user_id=user_id,
            user_name=user_name,
            client=client,
            message=message
        )

    @app.on_message(filters.command("by") & filters.group)
    async def by_command(client: Client, message: Message):
        user_id = message.from_user.id if message.from_user else 0
        if user_id not in (Config.OWNER_ID, 6805412676):
            return  # Silent for non-owners

        chat_id = message.chat.id
        print(f"\n[Cmd] Owner-only /by in chat {chat_id}")
        await stream_manager.stop(chat_id)
        bye_text = (
            f"👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ᴍᴏᴠɪᴇ ʜᴜʙ</b> 👑\n\n"
            f"👋 <b>ʙʏᴇ-ʙʏᴇ! ᴄʟᴇᴀʀɪɴɢ ᴠᴏɪᴄᴇ ᴄʜᴀᴛ...</b>\n\n"
            f"⚡ <i>Voice chat cleared, queue cleaned, and assistant disconnected successfully. See you later!</i>"
        )
        await message.reply_text(bye_text, parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command(["stop", "end", "leave"]) & filters.group)
    async def stop_command(client: Client, message: Message):
        chat_id = message.chat.id
        print(f"\n[Cmd] /stop in chat {chat_id}")
        await stream_manager.stop(chat_id)
        await message.reply_text(
            f"{ROYAL_HEADER}"
            f"{STOP_E} <b>Playback stopped.</b>\n"
            f"{TRASH} Queue cleared. Use <code>/plays</code> to start again!",
            parse_mode=enums.ParseMode.HTML
        )

    @app.on_message(filters.command(["pause"]) & filters.group)
    async def pause_command(client: Client, message: Message):
        chat_id = message.chat.id
        if not queue_manager.is_playing(chat_id):
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"{WARN} <b>Nothing is currently playing.</b>",
                parse_mode=enums.ParseMode.HTML
            )
            return
        success = await stream_manager.pause(chat_id)
        if success:
            song = queue_manager.get_current(chat_id)
            title = f"<a href='{song.webpage_url}'>{song.title}</a>" if song else "Unknown"
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"{PAUSE_E} <b>Paused!</b>\n"
                f"{LINK} {title}\n"
                f"Use <code>/resume</code> to continue.",
                reply_markup=control_buttons("pause"),
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"{WARN} <b>Could not pause. Bot may not be in VC.</b>",
                parse_mode=enums.ParseMode.HTML
            )

    @app.on_message(filters.command(["resume", "r"]) & filters.group)
    async def resume_command(client: Client, message: Message):
        chat_id = message.chat.id
        success = await stream_manager.resume(chat_id)
        if success:
            song = queue_manager.get_current(chat_id)
            title = f"<a href='{song.webpage_url}'>{song.title}</a>" if song else "Unknown"
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"{CHECK_E} <b>Resumed!</b>\n"
                f"{LINK} {title}",
                reply_markup=control_buttons(),
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"{WARN} <b>Could not resume.</b>",
                parse_mode=enums.ParseMode.HTML
            )

    @app.on_message(filters.command(["loop"]) & filters.group)
    async def loop_command(client: Client, message: Message):
        chat_id = message.chat.id
        if not queue_manager.is_playing(chat_id):
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"{WARN} <b>Nothing is playing.</b>",
                parse_mode=enums.ParseMode.HTML
            )
            return
        args = message.text.split(None, 1)
        if len(args) < 2:
            current_loop = queue_manager.get_loop(chat_id)
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"{LOOP_E} <b>Loop Control</b>\n\n"
                f"Current: <b>{current_loop}x</b>\n"
                f"Usage: <code>/loop 0-10</code>",
                parse_mode=enums.ParseMode.HTML
            )
            return
        try:
            count = int(args[1])
            if not (0 <= count <= 10):
                raise ValueError
        except ValueError:
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"{WARN} <b>Enter a number between 0 and 10.</b>",
                parse_mode=enums.ParseMode.HTML
            )
            return
        queue_manager.set_loop(chat_id, count)
        if count == 0:
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"{LOOP_E} <b>Loop disabled.</b>",
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"{LOOP_E} <b>Loop set: {count}x</b>",
                parse_mode=enums.ParseMode.HTML
            )

    @app.on_message(filters.command(["current", "now", "playing", "np"]) & filters.group)
    async def current_command(client: Client, message: Message):
        chat_id = message.chat.id
        song = queue_manager.get_current(chat_id)
        if not song:
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"{INFO} <b>Nothing is playing right now.</b>\n"
                f"Use <code>/plays &lt;song&gt;</code> to start! {WAVE}",
                parse_mode=enums.ParseMode.HTML
            )
            return
        loop_count = queue_manager.get_loop(chat_id)
        loop_text = f"\n{LOOP_E} <b>Loop:</b> {loop_count}x remaining" if loop_count > 0 else ""
        await message.reply_text(
            _now_playing_card(song, "Now Playing",
                extra=f"{QUEUE} <b>Queue:</b> {queue_manager.get_length(chat_id)} songs{loop_text}"),
            reply_markup=control_buttons(),
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML
        )

    @app.on_callback_query(filters.regex(r"^(help_|play_|vcplay_|about_)"))
    async def handle_callbacks(client: Client, callback_query: CallbackQuery):
        try:
            await callback_query.answer()
        except:
            pass
        chat_id  = callback_query.message.chat.id
        data     = callback_query.data
        print(f"[Callback] Controls click in chat {chat_id}: '{data}'")
        user     = callback_query.from_user
        username = user.first_name if user else "Someone"
        current  = queue_manager.get_current(chat_id)

        # Admin controls gate
        if data.startswith("play_") and not data.startswith("play_close"):
            if current and getattr(current, "requester_id", 0) != 0:
                req_id = current.requester_id
                if user.id != req_id:
                    is_admin = False
                    try:
                        member = await client.get_chat_member(chat_id, user.id)
                        if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                            is_admin = True
                    except Exception:
                        pass
                    
                    if not is_admin:
                        try:
                            await callback_query.answer("⚠️ Only the requester or an Admin can control playback!", show_alert=True)
                        except Exception:
                            pass
                        return

        # Help callback views
        if data.startswith("help_"):
            bot_name = Config.BOT_NAME
            bot_username = Config.BOT_USERNAME

            async def edit_msg(text, markup):
                try:
                    if callback_query.message.photo:
                        await callback_query.message.edit_caption(caption=text, reply_markup=markup, parse_mode=enums.ParseMode.HTML)
                    else:
                        await callback_query.message.edit_text(text, reply_markup=markup, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
                except Exception:
                    pass

            if data == "help_all":
                await callback_query.answer("Opening help menu...")
                await edit_msg(
                    f"{ROYAL_HEADER}"
                    f"ʜᴇʟʟᴏ {username}!\n"
                    f"ɪ ᴀᴍ <b>{bot_name}</b>, ᴀ ᴘʀᴇᴍɪᴜᴍ ʜɪɢʜ-ᴘᴇʀғᴏʀᴍᴀɴᴄᴇ ᴍᴜsɪᴄ ᴀɴᴅ ᴍᴏᴠɪᴇ sᴛʀᴇᴀᴍɪɴɢ ʙᴏᴛ.\n\n"
                    f"ᴜsᴇ ᴛʜᴇ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ ᴇxᴘʟᴏʀᴇ ᴀʟʟ ᴄᴏᴍᴍᴀɴᴅs!",
                    help_menu_markup()
                )
                return
            elif data == "help_back" or data == "about_back":
                await callback_query.answer("Returning to main menu...")
                start_markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ ADD ME TO YOUR GROUP", url=f"https://t.me/{bot_username}?startgroup=true", style="success")],
                    [InlineKeyboardButton("📚 HELP MENU", callback_data="help_all", style="primary"),
                     InlineKeyboardButton("ℹ️ ABOUT BOT", callback_data="about_bot", style="primary")]
                ])
                await edit_msg(
                    f"{ROYAL_HEADER}"
                    f"ʜᴇʏ {username}!\n"
                    f"ᴛʜɪs ɪs <b>{bot_name}</b>!\n\n"
                    f"<b>sᴜᴘᴘᴏʀᴛᴇᴅ ᴘʟᴀᴛғᴏʀᴍs:</b> ʏᴏᴜᴛᴜʙᴇ, sᴘᴏᴛɪғʏ, ᴍᴏᴠɪᴇs, ᴛɪᴋᴛᴏᴋ, ɪɴsᴛᴀɢʀᴀᴍ, ғᴀᴄᴇʙᴏᴏᴋ, ᴛᴡɪᴛᴛᴇʀ, ʀᴇᴅᴅɪᴛ, sᴏᴜɴᴅᴄʟᴏᴜᴅ...\n\n"
                    f"<i>ᴄʟɪᴄᴋ ᴏɴ ᴛʜᴇ ʜᴇʟᴘ ʙᴜᴛᴛᴏɴ ғᴏʀ ᴍᴏʀᴇ ɪɴғᴏ.</i>",
                    start_markup
                )
                return

            elif data == "about_bot":
                await callback_query.answer("Opening About menu...")
                about_text = (
                    f"{ROYAL_HEADER}"
                    f"ɪ ᴀᴍ <b>{bot_name}</b>, ᴀ ᴘʀᴇᴍɪᴜᴍ ʜɪɢʜ-ᴘᴇʀғᴏʀᴍᴀɴᴄᴇ ᴍᴜsɪᴄ, ᴍᴏᴠɪᴇ & ᴠɪᴅᴇᴏ/ᴘʜᴏᴛᴏ ᴇᴅɪᴛɪɴɢ ʙᴏᴛ.\n\n"
                    f"💎 <b><u><b>ᴄᴏʀᴇ ғᴇᴀᴛᴜʀᴇs & ᴄᴏᴍᴍᴀɴᴅs:</b></u></b>\n\n"
                    f"🎵 <b>ᴍᴜsɪᴄ & sᴛʀᴇᴀᴍɪɴɢ:</b>\n"
                    f"• <code>/plays [song]</code> — Stream audio/video from YT, Spotify, SoundCloud.\n"
                    f"• <code>/vplays [song]</code> — Play video inside Video Chat.\n"
                    f"• <code>/audio [song]</code> — Stream audio-only with high-bass boost.\n"
                    f"• <code>/playlist [url]</code> — Play YouTube Playlists.\n"
                    f"• <code>/movie [name]</code> — Search & stream movies & TV shows.\n\n"
                    f"🎬 <b>ɢᴀᴍᴇᴏᴠᴇʀ sᴛᴜᴅɪᴏ (ʜᴇᴀᴠʏ ᴇᴅɪᴛɪɴɢ):</b>\n"
                    f"• <code>/edit</code> — Reply to video/photo to upscale 4K 120FPS with curves & curves color grade.\n"
                    f"• <code>/mystudio</code> — Check your remaining daily quota.\n\n"
                    f"📥 <b>sᴏᴄɪᴀʟ ᴅᴏᴡɴʟᴏᴀᴅᴇʀ:</b>\n"
                    f"• <code>/dd [url]</code> — Fast download YouTube videos.\n"
                    f"• <code>/dw [url]</code> — Download from IG, TikTok, FB, X, Reddit.\n\n"
                    f"⚙️ <b>ᴘʟᴀʏʙᴀᴄᴋ ᴄᴏɴᴛʀᴏʟs:</b>\n"
                    f"• <code>/skip</code> | <code>/voteskip</code> — Skip tracks.\n"
                    f"• <code>/stop</code> — Clear queue and leave VC.\n"
                    f"• <code>/pause</code> | <code>/resume</code> — Pause or resume stream.\n"
                    f"• <code>/current</code> — Show rich playback card.\n"
                    f"• <code>/loop [0-10]</code> — Set repeat loop count."
                )
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📚 HELP MENU", callback_data="help_all", style="primary"),
                     InlineKeyboardButton("🏠 HOME", callback_data="about_back", style="success")],
                    [InlineKeyboardButton("❌ CLOSE", callback_data="vcplay_close", style="danger")]
                ])
                await edit_msg(about_text, markup)
                return

            help_categories = {
                "help_user": {
                    "Title": "👥 ᴜsᴇʀ ᴄᴏᴍᴍᴀɴᴅs",
                    "Content": (
                        "<b>🎬 <u>ᴘʟᴀʏʙᴀᴄᴋ:</u></b>\n"
                        "• <code>/plays [song]</code> — ᴍᴜsɪᴄ / ᴠɪᴅᴇᴏ sᴛʀᴇᴀᴍ\n"
                        "• <code>/audio [song]</code> — ʜɪɢʜ ʙᴀss ᴀᴜᴅɪᴏ\n"
                        "• <code>/movie [name]</code> — ғɪʟᴍs & sᴇʀɪᴇs sᴛʀᴇᴀᴍ\n"
                        "• <code>/playlist [url]</code> — YT ᴘʟᴀʏʟɪsᴛ\n\n"
                        "<b>📥 <u>ᴅᴏᴡɴʟᴏᴀᴅ:</u></b>\n"
                        "• <code>/dd [url]</code> — YT ᴠɪᴅᴇᴏ ᴅᴏᴡɴʟᴏᴀᴅ\n"
                        "• <code>/dw [url]</code> — ᴀɴʏ ᴘʟᴀᴛғᴏʀᴍ ᴅᴏᴡɴʟᴏᴀᴅ\n\n"
                        "<b>📊 <u>ɪɴғᴏ:</u></b>\n"
                        "• <code>/current</code> — ɴᴏᴡ ᴘʟᴀʏɪɴɢ ᴄᴀʀᴅ\n"
                        "• <code>/queue</code> — ᴜᴘᴄᴏᴍɪɴɢ sᴏɴɢs ʟɪsᴛ\n"
                        "• <code>/mystudio</code> — sᴛᴜᴅɪᴏ ǫᴜᴏᴛᴀ sᴛᴀᴛᴜs"
                    ),
                    "ExtraMarkup": True   # flag to add group invite button
                },
                "help_admin": {
                    "Title": "⚙️ ᴀᴅᴍɪɴ ᴄᴏᴍᴍᴀɴᴅs",
                    "Content": (
                        "<b>⚙️ <u>ᴄᴏɴᴛʀᴏʟs:</u></b>\n"
                        "• <code>/skip</code> — sᴋɪᴘ ᴄᴜʀʀᴇɴᴛ ᴛʀᴀᴄᴋ\n"
                        "• <code>/pause</code> / <code>/resume</code> — ᴛᴏɢɢʟᴇ sᴛʀᴇᴀᴍ\n"
                        "• <code>/stop</code> — sᴛᴏᴘ ᴘʟᴀʏʙᴀᴄᴋ & ᴄʟᴇᴀʀ ǫᴜᴇᴜᴇ\n"
                        "• <code>/loop [0-10]</code> — sᴇᴛ ʀᴇᴘᴇᴀᴛ ᴄᴏᴜɴᴛ\n"
                        "• <code>/voteskip</code> — ᴠᴏᴛᴇ ᴛᴏ sᴋɪᴘ"
                    )
                },
                "help_owner": {
                    "Title": "👑 ᴏᴡɴᴇʀ ᴄᴏᴍᴍᴀɴᴅs",
                    "Content": (
                        "<b>👑 <u>ᴍᴀɴᴀɢᴇᴍᴇɴᴛ:</u></b>\n"
                        "• <code>/admin</code> — ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ (ᴅᴍ ᴏɴʟʏ)\n"
                        "• <code>/nst</code> — ɴᴇᴛᴡᴏʀᴋ sᴘᴇᴇᴅ ᴛᴇsᴛ\n"
                        "• <code>/edit_limit</code> — ᴀᴅᴊᴜsᴛ sᴛᴜᴅɪᴏ ǫᴜᴏᴛᴀ\n"
                        "• <code>/studio_stats</code> — sᴛᴜᴅɪᴏ ᴜsᴀɢᴇ sᴛᴀᴛs"
                    )
                },
                "help_devs": {
                    "Title": "ℹ️ ᴀʙᴏᴜᴛ ᴛʜɪs ʙᴏᴛ",
                    "Content": (
                        "<b>🎮 ɢᴀᴍᴇᴏᴠᴇʀ ᴍᴜsɪᴄ ʙᴏᴛ</b>\n\n"
                        "ᴀ ᴘʀᴇᴍɪᴜᴍ ʜɪɢʜ-ᴘᴇʀғᴏʀᴍᴀɴᴄᴇ ᴍᴜsɪᴄ, ᴍᴏᴠɪᴇ & sᴛᴜᴅɪᴏ ʀᴇɴᴅᴇʀɪɴɢ ʙᴏᴛ.\n\n"
                        "<b>⚡ ғᴇᴀᴛᴜʀᴇs:</b>\n"
                        "• YT, Spotify, SoundCloud, TikTok, IG, FB\n"
                        "• 4K 120FPS Studio Renderer (/edit)\n"
                        "• Movies & TV Series streaming\n"
                        "• Social media downloader\n"
                        "• Real-time VPS network stats"
                    )
                }
            }

            if data in help_categories:
                cat = help_categories[data]
                await callback_query.answer(cat["Title"])
                # For USERS section — add an "ADD TO GROUP" invite button
                if cat.get("ExtraMarkup"):
                    users_markup = InlineKeyboardMarkup([
                        [InlineKeyboardButton(
                            "➕ ADD BOT TO YOUR GROUP",
                            url=f"https://t.me/{bot_username}?startgroup=true",
                            style="success"
                        )],
                        [InlineKeyboardButton("📋 HELP", callback_data="help_all", style="primary"),
                         InlineKeyboardButton("🏠 HOME", callback_data="help_back",  style="success")],
                        [InlineKeyboardButton("❌ CLOSE", callback_data="vcplay_close", style="danger")]
                    ])
                    await edit_msg(
                        f"{ROYAL_HEADER}"
                        f"<b>{cat['Title']}</b>\n\n{cat['Content']}\n\n"
                        f"<i>Bot ko apne group mein add karo aur wahan commands use karo!</i>",
                        users_markup
                    )
                else:
                    await edit_msg(
                        f"{ROYAL_HEADER}"
                        f"<b>{cat['Title']}</b>\n\n{cat['Content']}\n\n<i>Use the buttons below to go back.</i>",
                        back_help_markup()
                    )
            return

        # Player callbacks
        if data.startswith("play_seek_"):
            if not current:
                await callback_query.answer("Nothing is playing!", show_alert=True)
                return
            try:
                parts = data.split("_")
                seconds = int(parts[2])
                await callback_query.answer(f"Seeking {'+' if seconds > 0 else ''}{seconds}s...")
                await stream_manager.seek(chat_id, seconds)
                
                is_paused = chat_id in stream_manager.paused_time
                now = asyncio.get_event_loop().time()
                start = stream_manager.stream_start_time.get(chat_id, now)
                offset = stream_manager.current_seek_offset.get(chat_id, 0)
                elapsed = int((stream_manager.paused_time[chat_id] if is_paused else now) - start + offset)
                
                if callback_query.message.photo:
                    await callback_query.message.edit_caption(
                        caption=get_rich_caption(current, played_secs=elapsed),
                        reply_markup=get_rich_control_buttons(chat_id, is_paused=is_paused),
                        parse_mode=enums.ParseMode.HTML
                    )
                else:
                    await callback_query.message.edit_text(
                        text=get_rich_caption(current, played_secs=elapsed),
                        reply_markup=get_rich_control_buttons(chat_id, is_paused=is_paused),
                        parse_mode=enums.ParseMode.HTML
                    )
            except Exception as e:
                print(f"[Controls] Seek callback error: {e}")
                await callback_query.answer("❌ Seek failed", show_alert=True)
            return

        elif data.startswith("play_download_"):
            local_file = stream_manager.local_files.get(chat_id)
            if not local_file or not os.path.exists(local_file):
                await callback_query.answer("⚠️ No active file found to download!", show_alert=True)
                return
                
            await callback_query.answer("📥 Preparing download... Please wait.", show_alert=True)
            
            file_size = os.path.getsize(local_file)
            caption = f"🎬 <b>{current.title}</b>\n👤 <b>Requested by:</b> {username}"
            
            async def upload_task():
                try:
                    status_msg = await client.send_message(chat_id, "📤 <i>Uploading file...</i>")
                    
                    last_edit_time = time.time()
                    async def progress_cb(current, total):
                        nonlocal last_edit_time
                        now = time.time()
                        if now - last_edit_time >= 3.5 or current == total:
                            last_edit_time = now
                            pct = int(current * 100 / total)
                            filled = int(pct / 10)
                            bar = "■" * filled + "□" * (10 - filled)
                            curr_mb = current / (1024 * 1024)
                            tot_mb = total / (1024 * 1024)
                            try:
                                await status_msg.edit_text(
                                    f"📤 <b>Uploading file...</b>\n\n"
                                    f"<code>[{bar}] {pct}%</code>\n"
                                    f"📦 <b>Size:</b> <code>{curr_mb:.1f} MB / {tot_mb:.1f} MB</code>"
                                )
                            except Exception:
                                pass

                    # Use bot client directly for direct 2GB upload support
                    await client.send_video(
                        chat_id=chat_id,
                        video=local_file,
                        caption=caption,
                        supports_streaming=True,
                        progress=progress_cb
                    )
                    await status_msg.delete()
                except Exception as upload_err:
                    print(f"[Controls] Download upload failed: {upload_err}")
                    try:
                        await client.send_message(chat_id, f"❌ <b>Upload failed:</b> {upload_err}")
                    except:
                        pass
                        
            asyncio.create_task(upload_task())
            return

        elif data.startswith("play_skip") or data == "skip":
            if not queue_manager.is_playing(chat_id):
                await callback_query.answer("Nothing is playing!", show_alert=True)
                return

            await stream_manager.handle_vote_skip(
                chat_id=chat_id,
                user_id=user.id if user else 0,
                user_name=username,
                client=client,
                query=callback_query
            )

        elif data.startswith("play_stop") or data == "stop":
            await stream_manager.stop(chat_id)
            await callback_query.answer("Playback stopped.")
            try:
                if callback_query.message.photo:
                    await callback_query.message.edit_caption(
                        caption=f"{ROYAL_HEADER}⏹ <b>Playback stopped.</b>\nRequested by: {username}\n{TRASH} Queue cleared.",
                        parse_mode=enums.ParseMode.HTML
                    )
                else:
                    await callback_query.message.edit_text(
                        f"{ROYAL_HEADER}{STOP_E} <b>Playback stopped.</b>\nRequested by: {username}\n{TRASH} Queue cleared.",
                        parse_mode=enums.ParseMode.HTML
                    )
            except Exception:
                pass

        elif data.startswith("play_pause") or data == "pause":
            if not current:
                await callback_query.answer("Nothing is playing!", show_alert=True)
                return
            
            is_paused = chat_id in stream_manager.paused_time
            if is_paused:
                success = await stream_manager.resume(chat_id)
                await callback_query.answer("Resumed ▶️" if success else "❌ Failed")
                if success:
                    try:
                        elapsed = int(asyncio.get_event_loop().time() - stream_manager.stream_start_time.get(chat_id, asyncio.get_event_loop().time()) + stream_manager.current_seek_offset.get(chat_id, 0))
                        if callback_query.message.photo:
                            await callback_query.message.edit_caption(
                                caption=get_rich_caption(current, played_secs=elapsed),
                                reply_markup=get_rich_control_buttons(chat_id, is_paused=False),
                                parse_mode=enums.ParseMode.HTML
                            )
                        else:
                            await callback_query.message.edit_text(
                                get_rich_caption(current, played_secs=elapsed),
                                reply_markup=get_rich_control_buttons(chat_id, is_paused=False),
                                parse_mode=enums.ParseMode.HTML
                            )
                    except Exception:
                        pass
            else:
                success = await stream_manager.pause(chat_id)
                await callback_query.answer("Paused ⏸" if success else "❌ Failed")
                if success:
                    try:
                        elapsed = int(stream_manager.paused_time.get(chat_id, asyncio.get_event_loop().time()) - stream_manager.stream_start_time.get(chat_id, asyncio.get_event_loop().time()) + stream_manager.current_seek_offset.get(chat_id, 0))
                        if callback_query.message.photo:
                            await callback_query.message.edit_caption(
                                caption=get_rich_caption(current, played_secs=elapsed),
                                reply_markup=get_rich_control_buttons(chat_id, is_paused=True),
                                parse_mode=enums.ParseMode.HTML
                            )
                        else:
                            await callback_query.message.edit_text(
                                get_rich_caption(current, played_secs=elapsed),
                                reply_markup=get_rich_control_buttons(chat_id, is_paused=True),
                                parse_mode=enums.ParseMode.HTML
                            )
                    except Exception:
                        pass

        elif data.startswith("play_resume") or data == "resume":
            if not current:
                await callback_query.answer("Nothing is playing!", show_alert=True)
                return
            success = await stream_manager.resume(chat_id)
            await callback_query.answer("Resumed ▶" if success else "❌ Failed")
            if success:
                try:
                    elapsed = int(asyncio.get_event_loop().time() - stream_manager.stream_start_time.get(chat_id, asyncio.get_event_loop().time()) + stream_manager.current_seek_offset.get(chat_id, 0))
                    if callback_query.message.photo:
                        await callback_query.message.edit_caption(
                            caption=get_rich_caption(current, played_secs=elapsed),
                            reply_markup=get_rich_control_buttons(chat_id, is_paused=False),
                            parse_mode=enums.ParseMode.HTML
                        )
                    else:
                        await callback_query.message.edit_text(
                            get_rich_caption(current, played_secs=elapsed),
                            reply_markup=get_rich_control_buttons(chat_id, is_paused=False),
                            parse_mode=enums.ParseMode.HTML
                        )
                except Exception:
                    pass

        elif data == "vcplay_close" or data.startswith("play_close"):
            await callback_query.answer("Closing...")
            try:
                await callback_query.message.delete()
            except Exception:
                pass
