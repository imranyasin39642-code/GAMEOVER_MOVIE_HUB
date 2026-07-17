"""
🎬 MOVIES Engine — Video-On-Demand (VOD) Plugin
Provides interactive /movie search, season/episode choice, and buttonless auto-play.
Integrates our high-performance local caching & garbage collection engine.
"""

import os
import time
import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from config import Config
from core.queue_manager import queue_manager, SongInfo
from core.player import (
    stream_manager, STAR, SKIP, QUEUE, CLOCK, LINK, USER, WARN, INFO, WAVE
)
from core.vod_scraper import (
    Session,
    search_vod,
    search_hindi_version,
    search_english_version,
    fetch_tv_details,
    resolve_stream_link,
    SubjectType,
)
from moviebox_api.v2.models import SearchResultsItem
from core.trending_manager import get_trending_list

# Global Video-On-Demand sessions tracker
vod_sessions: dict[int, dict] = {}

# ── Royal Header Constant ─────────────────────────────────────────────────────
ROYAL_HEADER = "👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ᴍᴜsɪᴄ ʙᴏᴛ</b> 👑\n\n"


async def safe_edit(message, text, reply_markup=None):
    try:
        from bot import send_styled
        if hasattr(message, "chat"):
            chat_id = message.chat.id
            message_id = message.id
        elif isinstance(message, tuple):
            chat_id, message_id = message
        else:
            return message
            
        await send_styled(chat_id, text, markup=reply_markup, message_id=message_id)
    except Exception as e:
        print(f"[safe_edit] Error: {e}")


def chunk_buttons(buttons, n):
    return [buttons[i:i + n] for i in range(0, len(buttons), n)]


async def get_season_panel(session_data):
    title = session_data["title"]
    allowed_uid = session_data["requester_id"]
    seasons = session_data["seasons"]
    
    caption = (
        f"{ROYAL_HEADER}"
        f"📺 <b>{title}</b> ke kul <code>{len(seasons)} seasons</code> hain.\n\n"
        "Neeche se watch karne ke liye <b>Season</b> select karein:"
    )
    
    buttons = []
    for s in seasons:
        style = "success"
        buttons.append(
            InlineKeyboardButton(f"SEASON {s.se}", callback_data=f"VOD|season|{allowed_uid}|{s.se}", style=style)
        )
        
    rows = chunk_buttons(buttons, 3)
    return caption, InlineKeyboardMarkup(rows)


def get_episode_panel(session_data):
    title = session_data["title"]
    allowed_uid = session_data["requester_id"]
    season_num = session_data["chosen_season"]
    seasons = session_data["seasons"]
    
    max_ep = 1
    for s in seasons:
        if s.se == season_num:
            max_ep = s.maxEp
            break
            
    caption = (
        f"{ROYAL_HEADER}"
        f"📺 <b>{title} — Season {season_num}</b>\n\n"
        "Watch karne ke liye <b>Episode</b> select karein:"
    )
    
    buttons = []
    for ep in range(1, max_ep + 1):
        buttons.append(
            InlineKeyboardButton(f"EP {ep}", callback_data=f"VOD|episode|{allowed_uid}|{ep}", style="primary")
        )
        
    rows = chunk_buttons(buttons, 5)
    rows.append([InlineKeyboardButton("BACK TO SEASONS", callback_data=f"VOD|back_to_seasons|{allowed_uid}", style="danger")])
    return caption, InlineKeyboardMarkup(rows)


async def select_vod_item(chat_id: int, item: SearchResultsItem, status_msg, user_id: int):
    session_data = vod_sessions.get(chat_id)
    if not session_data:
        return
        
    session_data["current_item"] = item
    session_data["chosen_lang"] = "hi" if "hindi" in item.title.lower() else "en"
    session_data["title"] = item.title.replace("[Hindi]", "").replace("[English]", "").replace("[english]","").replace("[Hindi]","").strip()
        
    is_series = session_data["current_item"].subjectType == SubjectType.TV_SERIES or int(getattr(session_data["current_item"], "subjectType", 1)) == 2
    
    if is_series:
        # Fetch seasons details
        from core.vod_scraper import fetch_tv_details
        details = await fetch_tv_details(session_data["session"], session_data["current_item"])
        if details and details.resource and details.resource.seasons:
            session_data["seasons"] = details.resource.seasons
            caption, keyboard = await get_season_panel(session_data)
            await safe_edit(status_msg, caption, keyboard)
        else:
            is_series = False
            
    if not is_series:
        caption = (
            f"{ROYAL_HEADER}"
            f"🎬 <b>Selected Title:</b> <code>{session_data['title']}</code>\n\n"
            f"Movie watch karne ke liye neeche click karein:"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("PLAY MOVIE", callback_data=f"VOD|play_movie|{user_id}", style="success")
            ]
        ])
        await safe_edit(status_msg, caption, keyboard)


async def show_loading_animation(chat_id: int, base_text: str) -> tuple:
    """Creates a message and animates loading dots for smooth, responsive UX."""
    from bot import send_styled
    msg_data = await send_styled(
        chat_id=chat_id,
        text=f"{ROYAL_HEADER}🔍 <b>{base_text}</b>"
    )
    msg_id = msg_data.get("result", {}).get("message_id")
    msg_tuple = (chat_id, msg_id)
    
    # Run a quick 1.5-second dots animation
    for i in range(1, 4):
        await asyncio.sleep(0.4)
        dots = "." * i
        await safe_edit(msg_tuple, f"{ROYAL_HEADER}🔍 <b>{base_text}{dots}</b>")
        
    return msg_tuple


async def get_trending_movies_panel(allowed_uid: int) -> tuple:
    items = await get_trending_list("trending_movies")
    caption = (
        f"{ROYAL_HEADER}"
        f"🔥 <b>ᴛᴏᴘ ᴛʀᴇɴᴅɪɴɢ ᴍᴏᴠɪᴇs</b>\n"
        f"<i>Tap on a command to copy and search:</i>\n\n"
    )
    
    if not items:
        caption += "❌ <i>No trending movies found.</i>"
    else:
        for idx, item in enumerate(items, 1):
            h_tag = " [Hindi Dubbed 🇮🇳]" if item["has_hindi"] else ""
            caption += (
                f"{idx}. 🎬 <b>{item['title']}</b> ({item['release_date']}) - ⭐ {item['rating']}{h_tag}\n"
                f"   👉 <code>/movie {item['title']}</code>\n\n"
            )
            
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📺 SHOW SERIES", callback_data=f"VOD|trend_series|{allowed_uid}", style="primary"),
            InlineKeyboardButton("🇮🇳 HINDI ONLY", callback_data=f"VOD|trend_hindi|{allowed_uid}", style="success")
        ],
        [
            InlineKeyboardButton("❌ CLOSE", callback_data=f"VOD|trend_close|{allowed_uid}", style="danger")
        ]
    ])
    return caption, keyboard


async def get_trending_series_panel(allowed_uid: int) -> tuple:
    items = await get_trending_list("trending_series")
    caption = (
        f"{ROYAL_HEADER}"
        f"📺 <b>ᴛᴏᴘ ᴛʀᴇɴᴅɪɴɢ sᴇʀɪᴇs</b>\n"
        f"<i>Tap on a command to copy and search:</i>\n\n"
    )
    
    if not items:
        caption += "❌ <i>No trending series found.</i>"
    else:
        for idx, item in enumerate(items, 1):
            h_tag = " [Hindi Dubbed 🇮🇳]" if item["has_hindi"] else ""
            caption += (
                f"{idx}. 📺 <b>{item['title']}</b> ({item['release_date']}) - ⭐ {item['rating']}{h_tag}\n"
                f"   👉 <code>/movie {item['title']}</code>\n\n"
            )
            
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎥 SHOW MOVIES", callback_data=f"VOD|trend_movies|{allowed_uid}", style="primary"),
            InlineKeyboardButton("🇮🇳 HINDI ONLY", callback_data=f"VOD|trend_hindi|{allowed_uid}", style="success")
        ],
        [
            InlineKeyboardButton("❌ CLOSE", callback_data=f"VOD|trend_close|{allowed_uid}", style="danger")
        ]
    ])
    return caption, keyboard


async def get_trending_hindi_panel(allowed_uid: int) -> tuple:
    movies = await get_trending_list("trending_movies")
    series = await get_trending_list("trending_series")
    
    hindi_items = []
    for m in movies:
        if m["has_hindi"]:
            hindi_items.append((m, "🎬"))
    for s in series:
        if s["has_hindi"]:
            hindi_items.append((s, "📺"))
            
    caption = (
        f"{ROYAL_HEADER}"
        f"🇮🇳 <b>ʜɪɴᴅɪ ᴅᴜʙʙᴇᴅ ᴛʀᴇɴᴅɪɴɢ</b>\n"
        f"<i>Tap on a command to copy and search:</i>\n\n"
    )
    
    if not hindi_items:
        caption += "❌ <i>No Hindi dubbed trending titles found.</i>"
    else:
        for idx, (item, icon) in enumerate(hindi_items, 1):
            caption += (
                f"{idx}. {icon} <b>{item['title']}</b> ({item['release_date']}) - ⭐ {item['rating']}\n"
                f"   👉 <code>/movie {item['title']}</code>\n\n"
            )
            
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎥 SHOW MOVIES", callback_data=f"VOD|trend_movies|{allowed_uid}", style="primary"),
            InlineKeyboardButton("📺 SHOW SERIES", callback_data=f"VOD|trend_series|{allowed_uid}", style="primary")
        ],
        [
            InlineKeyboardButton("❌ CLOSE", callback_data=f"VOD|trend_close|{allowed_uid}", style="danger")
        ]
    ])
    return caption, keyboard


def register(app: Client):

    @app.on_message(filters.command(["trending", "latest"]) & (filters.group | filters.private))
    async def trending_command(client: Client, message: Message):
        chat_id = message.chat.id
        user = message.from_user
        user_id = user.id if user else 0
        print(f"[MOVIES Engine] Trending command triggered by user {user_id} in chat {chat_id}")
        status_msg = await show_loading_animation(chat_id, "Fetching Trending List")
        try:
            caption, keyboard = await get_trending_movies_panel(user_id)
            await safe_edit(status_msg, caption, keyboard)
        except Exception as e:
            print(f"[MOVIES Engine] Trending command error: {e}")
            await safe_edit(status_msg, f"{ROYAL_HEADER}❌ <b>Error:</b> <code>{str(e)}</code>")

    @app.on_message(filters.command(["movie", "vod"]) & filters.group)
    async def movie_command(client: Client, message: Message):
        chat_id = message.chat.id
        user = message.from_user
        user_id = user.id if user else 0

        if len(message.command) < 2:
            caption = (
                f"{ROYAL_HEADER}"
                "🎬 <b>GameOver Movie Search Panel</b>\n\n"
                "Aapne movie ya series ka naam nahi likha. Movie play karne ke liye `/movie Name` type karein.\n\n"
                "Ya fir niche diye button par click karke <b>Trending & Latest Movies</b> check karein 👇"
            )
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔥 TRENDING MOVIES & SERIES", callback_data=f"VOD|trend_movies|{user_id}", style="success")
                ]
            ])
            from bot import send_styled
            await send_styled(chat_id=chat_id, text=caption, markup=keyboard)
            return

        query = " ".join(message.command[1:])
        print(f"[MOVIES Engine] Search request: '{query}' by user {user_id}")

        status_msg = await show_loading_animation(chat_id, "Searching")

        try:
            # Auto-Append Hindi behind the scenes
            search_query = f"{query} Hindi"
            print(f"[MOVIES Engine] Fetching Hindi results for: '{search_query}'")
            hindi_items = await search_vod(query, language="hi")

            # Check if the top result clearly has 'Hindi' in the title (Title check is the only reliable way)
            has_hindi = False
            if hindi_items:
                top_item = hindi_items[0]
                title_lower = top_item.title.lower()
                if "hindi" in title_lower:
                    has_hindi = True

            session = Session()

            if has_hindi:
                print(f"[MOVIES Engine] Smart Check: Top result clearly has Hindi. Auto-playing...")
                # Initialize session tracker
                vod_sessions[chat_id] = {
                    "query": query,
                    "requester_id": user_id,
                    "requester_name": user.first_name if user and user.first_name else (f"@{user.username}" if user and user.username else str(user_id)),
                    "search_results": hindi_items,
                    "session": session,
                    "seasons": [],
                    "chosen_season": 1,
                    "chosen_episode": 1,
                    "current_item": hindi_items[0],
                    "chosen_lang": "hi",
                    "title": hindi_items[0].title.replace("[Hindi]", "").replace("[English]", "").replace("[english]","").replace("[Hindi]","").strip()
                }
                session_data = vod_sessions[chat_id]
                current_item = hindi_items[0]
                is_series = current_item.subjectType == SubjectType.TV_SERIES or int(getattr(current_item, "subjectType", 1)) == 2

                if is_series:
                    await select_vod_item(chat_id, current_item, status_msg, user_id)
                else:
                    await trigger_movie_playback(status_msg, session_data, season=0, episode=0)
                return

            # Fallback Option: Hindi not found. Search for English/Original version
            print(f"[MOVIES Engine] Hindi version not found. Fetching English/Original results...")
            english_items = await search_vod(query, language="en")
            if not english_items:
                await safe_edit(
                    status_msg,
                    f"{ROYAL_HEADER}"
                    f"❌ <b>Humein '{query}' ke naam se koi movie ya series nahi mili!</b>\n"
                    "Please spelling check karein aur dobara try karein."
                )
                return

            # Store English/Original version in session tracker
            vod_sessions[chat_id] = {
                "query": query,
                "requester_id": user_id,
                "requester_name": user.first_name if user and user.first_name else (f"@{user.username}" if user and user.username else str(user_id)),
                "search_results": english_items,
                "session": session,
                "seasons": [],
                "chosen_season": 1,
                "chosen_episode": 1,
                "current_item": english_items[0],
                "chosen_lang": "en",
                "title": english_items[0].title.replace("[Hindi]", "").replace("[English]", "").replace("[english]","").replace("[Hindi]","").strip()
            }

            # Prompt the user that Hindi is not available, offer playing English/Original version
            caption = (
                f"{ROYAL_HEADER}"
                f"⚠️ <b>Ye movie/series Hindi audio mein available nahi hai!</b>\n\n"
                f"Kya aap ise 🇺🇸 <b>English / Original</b> audio mein play karna chahte hain?"
            )
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🇺🇸 PLAY IN ENGLISH/ORIGINAL", callback_data=f"VODLANG_PLAY|{user_id}", style="success"),
                    InlineKeyboardButton("❌ CANCEL", callback_data=f"vcplay_close", style="danger")
                ]
            ])
            await safe_edit(status_msg, caption, keyboard)

        except Exception as e:
            print(f"[MOVIES Engine] Error in /movie command: {e}")
            await safe_edit(
                status_msg,
                f"{ROYAL_HEADER}"
                f"❌ <b>Kuch error aaya hai:</b> <code>{str(e)}</code>"
            )

    @app.on_callback_query(filters.regex(r"^VODLANG_PLAY\|"))
    async def vodlang_play_callback(client: Client, query: CallbackQuery):
        chat_id = query.message.chat.id
        parts = query.data.split("|")
        allowed_uid = int(parts[1])
        
        try:
            await query.answer()
        except:
            pass
            
        requester_id = query.from_user.id if query.from_user else 0
        if allowed_uid != 0 and requester_id != allowed_uid:
            await query.answer("⚠️ Sirf wahi click kar sakta hai jisne search start kiya tha!", show_alert=True)
            return
            
        session_data = vod_sessions.get(chat_id)
        if not session_data:
            await safe_edit(query.message, f"{ROYAL_HEADER}❌ <b>Error: Session expired. Search again.</b>")
            return
            
        current_item = session_data["current_item"]
        is_series = current_item.subjectType == SubjectType.TV_SERIES or int(getattr(current_item, "subjectType", 1)) == 2
        
        if is_series:
            await select_vod_item(chat_id, current_item, query.message, allowed_uid)
        else:
            await trigger_movie_playback(query, session_data, season=0, episode=0)

    @app.on_callback_query(filters.regex(r"^VODLANG\|"))
    async def vodlang_callback(client: Client, query: CallbackQuery):
        chat_id = query.message.chat.id
        data = query.data
        parts = data.split("|")
        
        try:
            await query.answer()
        except:
            pass
            
        if len(parts) < 4:
            return
            
        lang = parts[1]
        movie_query = parts[2]
        allowed_uid = int(parts[3])
        
        requester_id = query.from_user.id if query.from_user else 0
        if allowed_uid != 0 and requester_id != allowed_uid:
            await query.answer("⚠️ Sirf wahi click kar sakta hai jisne search start kiya tha!", show_alert=True)
            return
            
        await safe_edit(query.message, f"{ROYAL_HEADER}🔍 <b>Searching for {lang.upper()} version...</b>\n⏳ <i>Please wait...</i>")
        
        try:
            items = await search_vod(movie_query, language=lang)
            if not items:
                await safe_edit(query.message, f"{ROYAL_HEADER}❌ <b>Humein is query ka koi {lang.upper()} version nahi mila!</b>")
                return
                
            session = Session()
            vod_sessions[chat_id] = {
                "query": movie_query,
                "requester_id": allowed_uid,
                "requester_name": query.from_user.first_name if query.from_user and query.from_user.first_name else str(allowed_uid),
                "search_results": items,
                "session": session,
                "seasons": [],
                "chosen_season": 1,
                "chosen_episode": 1,
                "current_item": items[0],
                "chosen_lang": lang,
                "title": items[0].title.replace("[Hindi]", "").replace("[English]", "").replace("[english]","").replace("[Hindi]","").strip()
            }
            session_data = vod_sessions[chat_id]
            current_item = items[0]
            is_series = current_item.subjectType == SubjectType.TV_SERIES or int(getattr(current_item, "subjectType", 1)) == 2
            
            if is_series:
                await select_vod_item(chat_id, current_item, query.message, allowed_uid)
            else:
                await trigger_movie_playback(query, session_data, season=0, episode=0)
        except Exception as e:
            print(f"[MOVIES Engine] Callback lang error: {e}")
            await safe_edit(query.message, f"{ROYAL_HEADER}❌ <b>Error:</b> <code>{str(e)}</code>")

    @app.on_callback_query(filters.regex(r"^VOD\|"))
    async def vod_callback(client: Client, query: CallbackQuery):
        chat_id = query.message.chat.id
        data = query.data
        parts = data.split("|")
        print(f"[MOVIES Engine DEBUG] Received callback: data='{data}', chat_id={chat_id}")
        
        try:
            await query.answer()
        except Exception as q_ans_err:
            print(f"[MOVIES Engine DEBUG] query.answer() failed: {q_ans_err}")
            
        if len(parts) < 3:
            print(f"[MOVIES Engine DEBUG] parts length too small: {len(parts)}")
            return

        action = parts[1]
        try:
            allowed_uid = int(parts[2])
        except Exception as val_err:
            print(f"[MOVIES Engine DEBUG] Parse allowed_uid failed: {val_err}")
            return
            
        requester_id = query.from_user.id if query.from_user else 0
        print(f"[MOVIES Engine DEBUG] action={action}, allowed_uid={allowed_uid}, requester_id={requester_id}")

        if allowed_uid != 0 and requester_id != allowed_uid:
            print(f"[MOVIES Engine DEBUG] Access denied: requester_id {requester_id} != allowed_uid {allowed_uid}")
            await query.answer("⚠️ Sirf wahi click kar sakta hai jisne search start kiya tha!", show_alert=True)
            return

        # Handle trending actions first (they don't require VOD search session data)
        if action == "trend_movies":
            caption, keyboard = await get_trending_movies_panel(allowed_uid)
            await safe_edit(query.message, caption, keyboard)
            return

        elif action == "trend_series":
            caption, keyboard = await get_trending_series_panel(allowed_uid)
            await safe_edit(query.message, caption, keyboard)
            return

        elif action == "trend_hindi":
            caption, keyboard = await get_trending_hindi_panel(allowed_uid)
            await safe_edit(query.message, caption, keyboard)
            return

        elif action == "trend_close":
            try:
                await query.message.delete()
            except Exception:
                pass
            return

        session_data = vod_sessions.get(chat_id)
        if not session_data:
            await safe_edit(query.message, f"{ROYAL_HEADER}❌ <b>Error: Session expired. Please search again.</b>")
            return

        if action == "select":
            subject_id = int(parts[3])
            items = session_data.get("search_results", [])
            item = next((x for x in items if x.subjectId == subject_id), None)
            if not item:
                await query.answer("❌ Movie details not found. Search again.", show_alert=True)
                return
            await select_vod_item(chat_id, item, query.message, allowed_uid)

        elif action == "play_movie":
            await trigger_movie_playback(query, session_data, season=0, episode=0)

        elif action == "season":
            season_num = int(parts[3])
            session_data["chosen_season"] = season_num
            await query.answer(f"Selected Season {season_num}")
            
            caption, keyboard = get_episode_panel(session_data)
            await safe_edit(query.message, caption, keyboard)

        elif action == "episode":
            ep_num = int(parts[3])
            session_data["chosen_episode"] = ep_num
            await trigger_movie_playback(query, session_data, season=session_data["chosen_season"], episode=ep_num)

        elif action == "back_to_seasons":
            await query.answer("Returning...")
            caption, keyboard = await get_season_panel(session_data)
            await safe_edit(query.message, caption, keyboard)


    @app.on_callback_query(filters.regex(r"^VODNEXT\|"))
    async def vod_next_callback(client: Client, query: CallbackQuery):
        try:
            await query.answer()
        except:
            pass
        chat_id = query.message.chat.id
        data = query.data
        parts = data.split("|")
        
        if len(parts) < 4:
            return
            
        target_chat_id = int(parts[1])
        next_season = int(parts[2])
        next_episode = int(parts[3])
        
        session_data = vod_sessions.get(chat_id)
        if not session_data:
            await query.answer("❌ Session expired. Search again.", show_alert=True)
            return
            
        allowed_uid = session_data.get("requester_id", 0)
        requester_id = query.from_user.id if query.from_user else 0
        if requester_id != allowed_uid:
            await query.answer("⚠️ Only the requester can load the next episode!", show_alert=True)
            return
            
        await trigger_movie_playback(query, session_data, season=next_season, episode=next_episode, is_next=True)

    @app.on_callback_query(filters.regex(r"^VODRESUME\|"))
    async def vod_resume_callback(client: Client, query: CallbackQuery):
        chat_id = query.message.chat.id
        data = query.data
        parts = data.split("|")
        
        try:
            await query.answer()
        except:
            pass
            
        if len(parts) < 5:
            return
            
        allowed_uid = int(parts[1])
        season = int(parts[2])
        episode = int(parts[3])
        progress = int(parts[4])
        
        requester_id = query.from_user.id if query.from_user else 0
        if allowed_uid != 0 and requester_id != allowed_uid:
            try:
                member = await client.get_chat_member(chat_id, requester_id)
                if member.status not in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                    await query.answer("⚠️ Sirf wahi click kar sakta hai jisne search start kiya tha!", show_alert=True)
                    return
            except Exception:
                await query.answer("⚠️ Sirf wahi click kar sakta hai jisne search start kiya tha!", show_alert=True)
                return
                
        session_data = vod_sessions.get(chat_id)
        if not session_data:
            await safe_edit(query.message, f"{ROYAL_HEADER}❌ <b>Session expired. Please search again.</b>")
            return
            
        await trigger_movie_playback(query, session_data, season=season, episode=episode, force_seek=progress)

    @app.on_callback_query(filters.regex(r"^VODSTARTOVER\|"))
    async def vod_startover_callback(client: Client, query: CallbackQuery):
        chat_id = query.message.chat.id
        data = query.data
        parts = data.split("|")
        
        try:
            await query.answer()
        except:
            pass
            
        if len(parts) < 4:
            return
            
        allowed_uid = int(parts[1])
        season = int(parts[2])
        episode = int(parts[3])
        
        requester_id = query.from_user.id if query.from_user else 0
        if allowed_uid != 0 and requester_id != allowed_uid:
            try:
                member = await client.get_chat_member(chat_id, requester_id)
                if member.status not in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                    await query.answer("⚠️ Sirf wahi click kar sakta hai jisne search start kiya tha!", show_alert=True)
                    return
            except Exception:
                await query.answer("⚠️ Sirf wahi click kar sakta hai jisne search start kiya tha!", show_alert=True)
                return
                
        session_data = vod_sessions.get(chat_id)
        if not session_data:
            await safe_edit(query.message, f"{ROYAL_HEADER}❌ <b>Session expired. Please search again.</b>")
            return
            
        # Clear progress from db
        from core.db import clear_vod_progress
        subject_id = int(session_data["current_item"].subjectId)
        clear_vod_progress(chat_id, subject_id, season, episode)
        
        await trigger_movie_playback(query, session_data, season=season, episode=episode, force_seek=0)


async def trigger_movie_playback(msg_or_query, session_data: dict, season: int = 0, episode: int = 0, is_next: bool = False, force_seek: int = -1):
    if hasattr(msg_or_query, "message"):
        message = msg_or_query.message
        chat_id = message.chat.id
    else:
        message = msg_or_query
        if hasattr(message, "chat"):
            chat_id = message.chat.id
        elif isinstance(message, tuple):
            chat_id = message[0]

    current_item = session_data["current_item"]
    is_series = current_item.subjectType == SubjectType.TV_SERIES or int(getattr(current_item, "subjectType", 1)) == 2
    subject_id = int(current_item.subjectId)

    # ── VOD Playback Resume Gate ──
    if force_seek == -1 and not is_next:
        from core.db import get_vod_progress
        saved_progress = get_vod_progress(chat_id, subject_id, season, episode)
        if saved_progress and saved_progress > 10:
            from plugins.controls import format_seconds
            pos_str = format_seconds(saved_progress)
            
            allowed_uid = session_data.get("requester_id", 0)
            lang = session_data.get("chosen_lang", "en")
            lang_tag = "[Hindi]" if lang == "hi" else ""
            title_suffix = f" S{season}E{episode}" if season > 0 else ""
            display_title = f"{session_data['title']}{title_suffix} {lang_tag}"
            
            caption = (
                f"{ROYAL_HEADER}"
                f"⚠️ <b>sᴀᴠᴇᴅ ᴘʀᴏɢʀᴇss ғᴏᴜɴᴅ!</b>\n\n"
                f"🎬 <b>Title:</b> <code>{display_title}</code>\n"
                f"⏱ <b>Saved Position:</b> <code>{pos_str}</code>\n\n"
                f"Kya aap wahan se <b>Resume</b> karna chahte hain ya shuru se <b>Start Over</b>?"
            )
            
            # Setup Inline Buttons with green/red styling (success/danger)
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("▶️ RESUME PLAY", callback_data=f"VODRESUME|{allowed_uid}|{season}|{episode}|{saved_progress}", style="success"),
                    InlineKeyboardButton("🔄 START OVER", callback_data=f"VODSTARTOVER|{allowed_uid}|{season}|{episode}", style="danger")
                ],
                [
                    InlineKeyboardButton("❌ CLOSE", callback_data="vcplay_close", style="danger")
                ]
            ])
            
            if hasattr(msg_or_query, "message"):
                await safe_edit(msg_or_query.message, caption, reply_markup=keyboard)
            else:
                await safe_edit(msg_or_query, caption, reply_markup=keyboard)
            return

    # If force_seek is >= 0, we use it, otherwise use 0
    seek_offset = force_seek if force_seek >= 0 else 0
    session_data["force_seek"] = seek_offset

    await safe_edit(message, f"{ROYAL_HEADER}🎬 <b>Fetching Movie...</b>\n⏳ <i>Server se connection kiya ja raha hai...</i>")
    
    try:
        # Resolve stream link directly from current selected item
        result = await resolve_stream_link(
            session_data["session"],
            current_item,
            season=season,
            episode=episode,
            quality="720"
        )
        
        lang = session_data["chosen_lang"]
        lang_tag = "[Hindi]" if lang == "hi" else ""
        title_suffix = f" S{season}E{episode}" if is_series else ""
        display_title = f"{session_data['title']}{title_suffix} {lang_tag}"
        
        song = SongInfo(
            title=display_title,
            video_url=result["url"],
            audio_url=result["url"],
            thumbnail=str(current_item.cover.url) if (current_item.cover and current_item.cover.url) else "",
            duration="VOD",
            duration_secs=0,
            webpage_url=result["url"],
            uploader="MOVIES Engine",
            requested_by=session_data.get("requester_name", "Someone"),
            quality="720",
            requester_id=session_data.get("requester_id", 0)
        )
        song.subject_id = subject_id
        song.season = season
        song.episode = episode
        song.clean_title = session_data.get("title", song.title)
        
        # Check if already playing - Queue if needed
        is_playing = queue_manager.is_playing(chat_id)
        if is_playing and not is_next:
            start_time = time.time()
            last_edit_time = [0.0]
            last_pct = [-1]
            async def progress_cb(pct, downloaded, total_size):
                now = time.time()
                if now - last_edit_time[0] >= 3.5 or (pct - last_pct[0] >= 10 and pct > 0) or pct == 100:
                    last_edit_time[0] = now
                    last_pct[0] = pct
                    elapsed = time.time() - start_time
                    if elapsed == 0:
                        elapsed = 0.01
                    speed_bps = downloaded / elapsed
                    speed_mb = speed_bps / (1024 * 1024)
                    downloaded_mb = downloaded / (1024 * 1024)
                    
                    if total_size > 0:
                        total_size_mb = total_size / (1024 * 1024)
                        remaining_bytes = total_size - downloaded
                        seconds_left = max(0, int(remaining_bytes / speed_bps)) if speed_bps > 0 else 0
                        time_left_str = f"{seconds_left}s"
                        filled = int(pct / 10)
                        bar = "■" * filled + "□" * (10 - filled)
                        progress_str = f"<code>[{bar}] {pct}%</code>"
                        size_str = f"📦 <b>sɪᴢᴇ:</b> <code>{downloaded_mb:.1f} MB / {total_size_mb:.1f} MB</code>"
                    else:
                        time_left_str = "calculating..."
                        progress_str = "<code>[📥 DOWNLOADING...]</code>"
                        size_str = f"📦 <b>sɪᴢᴇ:</b> <code>{downloaded_mb:.1f} MB / calculating...</code>"
                        
                    try:
                        await safe_edit(
                            message,
                            f"{ROYAL_HEADER}"
                            f"⚡ <b>ᴘʀᴏᴄᴇssɪɴɢ ᴍᴇᴅɪᴀ (ǫᴜᴇᴜᴇ)...</b>\n"
                            f"📌 <b>ᴛɪᴛʟᴇ:</b> <code>{song.title}</code>\n"
                            f"{progress_str}\n"
                            f"{size_str}\n"
                            f"🚀 <b>sᴘᴇᴇᴅ:</b> <code>{speed_mb:.1f} MB/s</code>\n"
                            f"⏳ <b>ʀᴇᴍᴀɪɴɪɴɢ:</b> <code>{time_left_str}</code>"
                        )
                    except Exception:
                        pass

            from core.downloader import download_song
            local_file = await download_song(song, mode="video", progress_callback=progress_cb)
            if not local_file:
                await safe_edit(
                    message,
                    f"{ROYAL_HEADER}❌ <b>Error: Failed to download track cache.</b>"
                )
                return
                
            stream_manager.local_files[chat_id] = local_file
            pos = queue_manager.add(chat_id, song)
            from plugins.controls import control_buttons
            await safe_edit(
                message,
                f"{ROYAL_HEADER}"
                f"{QUEUE} <b><u>ᴜᴘᴄᴏᴍɪɴɢ ᴠᴏᴅ ᴛʀᴀᴄᴋ: #{pos}</u></b>\n\n"
                f"{LINK} <b>Title:</b> <code>{song.title}</code>\n"
                f"{CLOCK} <b>Duration:</b> {song.duration}\n"
                f"{USER} <b>Requested by:</b> {song.requested_by}",
                reply_markup=control_buttons()
            )
            return

        if is_series:
            session_data["chosen_season"] = season
            session_data["chosen_episode"] = episode

        if hasattr(msg_or_query, "message"):
            stream_manager.active_message_id[chat_id] = msg_or_query.message.id
        elif isinstance(msg_or_query, tuple):
            stream_manager.active_message_id[chat_id] = msg_or_query[1]
        force_seek = session_data.get("force_seek", 0)
        success = await stream_manager.play(chat_id, song, send_card=True, force_seek=force_seek)
        if success:
            try:
                if hasattr(msg_or_query, "message"):
                    await msg_or_query.message.delete()
                elif hasattr(msg_or_query, "delete"):
                    await msg_or_query.delete()
                elif isinstance(msg_or_query, tuple) and stream_manager._app:
                    await stream_manager._app.delete_messages(msg_or_query[0], msg_or_query[1])
            except Exception:
                pass
        else:
            queue_manager.clear(chat_id)
            await safe_edit(
                message,
                f"{ROYAL_HEADER}"
                f"❌ <b>Stream start karne mein error aaya!</b>\n\nEnsure group voice chat is active."
            )
            
    except Exception as e:
        queue_manager.clear(chat_id)
        print(f"[MOVIES Engine] Playback error: {e}")
        await safe_edit(message, f"{ROYAL_HEADER}❌ **Error resolving stream:** {str(e)}")
