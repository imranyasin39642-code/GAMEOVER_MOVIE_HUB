"""
**🎮 GameOver Music Bot — Core Player Engine (PyTgCalls Local Playback)**
Production-ready stream player manager with strict per-chat isolation.
Handles local file playback, 480p @ 60 FPS video parameters,
high-bass studio equalizer audio, and automatic cache deletion.
"""

import os
import asyncio
import time
import logging
logging.getLogger("pytgcalls").setLevel(logging.DEBUG)
logging.getLogger("ffmpeg").setLevel(logging.DEBUG)
from typing import Optional, Dict, Any, Union
from pyrogram import Client, filters as py_filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from pytgcalls import PyTgCalls, filters
from pytgcalls.types import MediaStream, VideoQuality, AudioQuality
from pytgcalls.types.raw import VideoParameters

from core.queue_manager import queue_manager, SongInfo
from core.downloader import download_song, clean_cached_file

FILE_CLEANUP_DELAY = 600  # 10 minutes in seconds

async def delayed_clean_cached_file(file_path: str, delay: int = FILE_CLEANUP_DELAY):
    """Delete a cached file after a short delay, protecting active/queued tracks."""
    await asyncio.sleep(delay)
    
    # Protect active playing files
    if file_path in list(stream_manager.local_files.values()):
        print(f"[Player] Protecting currently playing file from delayed cleanup: {file_path}")
        return
        
    # Protect queued files
    queued_ids = set()
    for chat_id, songs in list(queue_manager.queues.items()):
        for song in songs:
            clean_id = "".join(c for c in song.webpage_url.split("v=")[-1] if c.isalnum() or c in ("-", "_"))
            if clean_id:
                queued_ids.add(clean_id)
                
    filename = os.path.basename(file_path)
    is_queued = False
    for qid in queued_ids:
        if qid in filename:
            is_queued = True
            break
    if is_queued:
        print(f"[Player] Protecting queued file from delayed cleanup: {file_path}")
        return
        
    clean_cached_file(file_path)

def get_cleanup_delay(song: Optional[SongInfo]) -> int:
    """Helper to determine file cleanup delay: 24 hours to save VPS disk space while preserving cache."""
    return 86400  # 24 hours in seconds

async def start_downloads_garbage_collector():
    """Periodically purges files in downloads/ older than 24 hours, protecting active/queued tracks."""
    downloads_dir = "downloads"
    while True:
        try:
            if os.path.exists(downloads_dir):
                now = time.time()
                active_files = set(stream_manager.local_files.values())
                
                # Get all queued video IDs to protect them
                queued_ids = set()
                for chat_id, songs in list(queue_manager.queues.items()):
                    for song in songs:
                        clean_id = "".join(c for c in song.webpage_url.split("v=")[-1] if c.isalnum() or c in ("-", "_"))
                        if clean_id:
                            queued_ids.add(clean_id)
                
                for filename in os.listdir(downloads_dir):
                    file_path = os.path.join(downloads_dir, filename)
                    if os.path.isfile(file_path):
                        # Protect active files
                        if file_path in active_files:
                            continue
                            
                        # Protect queued files
                        is_queued = False
                        for qid in queued_ids:
                            if qid in filename:
                                is_queued = True
                                break
                        if is_queued:
                            continue
                            
                        # Delete if older than 24 hours
                        mtime = os.path.getmtime(file_path)
                        if now - mtime > 86400:  # 24 hours
                            try:
                                os.remove(file_path)
                                print(f"[Garbage Collector] Purged expired cached file: {file_path}")
                            except Exception as e:
                                print(f"[Garbage Collector] Error purging {file_path}: {e}")
        except Exception as e:
            print(f"[Garbage Collector] Error: {e}")
        await asyncio.sleep(1800)  # Run every 30 minutes


# ── Emojis and formatting constants ──────────────────────────────────────────
STAR   = '<tg-emoji emoji-id="5336814422276992289">🌟</tg-emoji>'
PLAY   = '<tg-emoji emoji-id="5330273431898318607">🌟</tg-emoji>'
SKIP   = '<tg-emoji emoji-id="5332522762105810091">🌟</tg-emoji>'
SLEEP  = '<tg-emoji emoji-id="5330184289852091742">🌟</tg-emoji>'
QUEUE  = '<tg-emoji emoji-id="5339492935681468850">🌟</tg-emoji>'
WAVE   = '<tg-emoji emoji-id="5332289648460853008">🌟</tg-emoji>'
CLOCK  = '<tg-emoji emoji-id="5386367538735104399">⌛</tg-emoji>'
INFO   = '<tg-emoji emoji-id="5334544901428229844">ℹ️</tg-emoji>'
USER   = '<tg-emoji emoji-id="6158690786989844701">👤</tg-emoji>'
LINK   = '<tg-emoji emoji-id="6159108940710812914">🔗</tg-emoji>'
TRASH  = '<tg-emoji emoji-id="6158751479172702139">🗑</tg-emoji>'
WARN   = '<tg-emoji emoji-id="6160934967531543039">⚠️</tg-emoji>'


class SeekableMediaStream(MediaStream):
    async def check_stream(self):
        import pytgcalls.types.stream.media_stream as ms_mod
        orig_check = ms_mod.check_stream
        
        async def mock_check(ffmpeg_params, path, stream_params, before_cmds=None, headers=None):
            clean_params = None
            if ffmpeg_params:
                import shlex
                parts = shlex.split(ffmpeg_params)
                new_parts = []
                skip = False
                for part in parts:
                    if skip:
                        skip = False
                        continue
                    if part == "-ss":
                        skip = True
                        continue
                    if part == "-re":
                        continue
                    new_parts.append(part)
                clean_params = " ".join(new_parts) if new_parts else None
            return await orig_check(clean_params, path, stream_params, before_cmds, headers)
            
        ms_mod.check_stream = mock_check
        try:
            await super().check_stream()
        finally:
            ms_mod.check_stream = orig_check


class PlayerManager:
    def __init__(self):
        self._pytg: PyTgCalls = None
        self._assistant: Client = None
        self.app: Client = None   # Pyrogram bot used to send messages
        self._active_chats: set[int] = set()
        
        self.idle_timers: dict[int, asyncio.Task] = {}  # per-group idle timers
        self.stream_start_time: dict[int, float] = {}   # chat_id -> start time
        self.current_seek_offset: dict[int, int] = {}   # chat_id -> seek offset in seconds
        self.paused_time: dict[int, float] = {}         # chat_id -> pause timestamp
        self.active_message_id: dict[int, int] = {}     # chat_id -> now playing message_id
        
        # Local caching cache file path map: chat_id -> local_file_path
        self.local_files: dict[int, str] = {}
        self.skip_votes: dict[int, set[int]] = {}

    # ────────────────────────── Init ────────────────────────────────────────

    async def init(self, assistant: Client, bot: Client = None):
        """Initialise PyTgCalls and register event handlers."""
        self._assistant = assistant
        self.app = bot if bot else assistant
        self._pytg = PyTgCalls(assistant)
        
        # Start automatic 24-hour garbage collector
        asyncio.create_task(start_downloads_garbage_collector())

        from pytgcalls.types import ChatUpdate

        # ── Stream-end handler ─────────────────────────────────────────────
        @self._pytg.on_update(filters.stream_end())
        async def on_stream_end(_, update):
            try:
                chat_id = update.chat_id
                self.skip_votes.pop(chat_id, None)

                # De-duplicate: only process AUDIO end (skip VIDEO end)
                type_str = str(update.stream_type).upper()
                type_val = getattr(update.stream_type, "value", update.stream_type)
                if "VIDEO" in type_str or type_val == 2:
                    return

                print(f"\n[Player] ⏹  Audio stream ended in chat {chat_id}")
                
                current = queue_manager.get_current(chat_id)

                # Schedule file deletion after 10 minutes (not immediately)
                old_local = self.local_files.pop(chat_id, None)
                if old_local:
                    asyncio.create_task(delayed_clean_cached_file(old_local, delay=get_cleanup_delay(current)))
                    print(f"[Player] 🗑️  File queued for deletion: {old_local}")

                # ── Loop handling ──────────────────────────────────────────
                loop_remaining = queue_manager.get_loop(chat_id)
                if loop_remaining > 0:
                    if current:
                        queue_manager.decrement_loop(chat_id)
                        print(f"[Player] 🔁 Loop remaining: {queue_manager.get_loop(chat_id)} for chat {chat_id}")
                        asyncio.create_task(self._delayed_play(chat_id, current, send_card=True))
                        return

                # ── VOD Auto-Play Next Episode ──
                if current and (current.uploader == "MOVIES Engine" or current.duration == "VOD"):
                    try:
                        from plugins.movies import vod_sessions, trigger_movie_playback
                        session_data = vod_sessions.get(chat_id)
                        if session_data and session_data.get("seasons"):
                            chosen_season = session_data.get("chosen_season", 1)
                            chosen_episode = session_data.get("chosen_episode", 1)
                            seasons = session_data.get("seasons", [])
                            
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
                                print(f"[Player] 📺 VOD Auto-Play Next Episode: Season {next_season} Episode {next_episode}")
                                
                                try:
                                    await self.app.send_message(
                                        chat_id,
                                        f"⏭️ <b>ᴀᴜᴛᴏ-ᴘʟᴀʏɪɴɢ ɴᴇxᴛ ᴇᴘɪsᴏᴅᴇ</b>\n\n"
                                        f"📺 <b>Title:</b> <code>{session_data['title']} S{next_season}E{next_episode}</code>\n"
                                        f"⏳ <i>Loading next episode, please wait...</i>"
                                    )
                                except Exception as e:
                                    print(f"[Player] VOD notification failed: {e}")
                                    
                                placeholder = await self.app.send_message(chat_id, "🎬 <i>Loading...</i>")
                                
                                class DummyUser:
                                    def __init__(self, uid):
                                        self.id = uid
                                        self.first_name = "User"
                                        self.username = None
                                        
                                class DummyQuery:
                                    def __init__(self, msg, uid):
                                        self.message = msg
                                        self.from_user = DummyUser(uid)
                                    async def answer(self, *args, **kwargs):
                                        pass
                                        
                                query_obj = DummyQuery(placeholder, session_data.get("requester_id", 0))
                                asyncio.create_task(trigger_movie_playback(
                                    query_obj,
                                    session_data,
                                    season=next_season,
                                    episode=next_episode,
                                    is_next=True
                                ))
                                return
                    except Exception as vod_err:
                        print(f"[Player] Error in VOD auto-play next: {vod_err}")

                # ── Auto-Play next song ────────────────────────────────────
                if not queue_manager.is_empty(chat_id):
                    next_song = queue_manager.pop(chat_id)
                    if next_song:
                        self._cancel_idle_timer(chat_id)
                        print(f"[Player] ⏭  Auto-playing next: '{next_song.title}' in chat {chat_id}")

                        # Send auto-play notification first
                        try:
                            await self.app.send_message(
                                chat_id,
                                f"{SKIP} <b>ᴀᴜᴛᴏ-ᴘʟᴀʏɪɴɢ ɴᴇxᴛ</b>\n\n"
                                f"{LINK} <a href='{next_song.webpage_url}'>{next_song.title}</a>\n"
                                f"{CLOCK} <b>Duration:</b> {next_song.duration}\n"
                                f"{QUEUE} <b>Songs remaining:</b> {queue_manager.get_length(chat_id)}",
                                disable_web_page_preview=True
                            )
                        except Exception as e:
                            print(f"[Player] ⚠️  Auto-play notification failed: {e}")

                        asyncio.create_task(self._delayed_play(chat_id, next_song, send_card=True))
                        return

                # ── Queue is empty — start idle timer ──────────────────────
                queue_manager.clear_current(chat_id)
                print(f"[Player] 💤 Queue empty in chat {chat_id}. Starting 5-min idle timer.")
                
                # Delete active now playing message on queue completion
                old_msg_id = self.active_message_id.pop(chat_id, None)
                if old_msg_id and self.app:
                    try:
                        await self.app.delete_messages(chat_id, old_msg_id)
                    except Exception:
                        pass

                try:
                    await self.app.send_message(
                        chat_id,
                        f"{INFO} <b>ǫᴜᴇᴜᴇ ғɪɴɪsʜᴇᴅ!</b>\n\n"
                        f"Add more songs with <code>/plays &lt;song&gt;</code> {WAVE}\n"
                        f"{CLOCK} Bot will leave after <b>5 minutes</b> of inactivity."
                    )
                except Exception as e:
                    print(f"[Player] ⚠️  Queue ended notification failed: {e}")

                self.idle_timers[chat_id] = asyncio.create_task(
                    self._idle_timeout_task(chat_id)
                )

            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"[Player] ❌ Error in on_stream_end: {e}")

        # ── Voice-chat kicked / closed handlers ──
        @self._pytg.on_update(filters.chat_update(ChatUpdate.Status.KICKED))
        async def on_kicked(_, update):
            try:
                chat_id = update.chat_id
                self._cancel_idle_timer(chat_id)
                self._active_chats.discard(chat_id)
                old_local = self.local_files.pop(chat_id, None)
                if old_local:
                    current_song = queue_manager.get_current(chat_id)
                    asyncio.create_task(delayed_clean_cached_file(old_local, delay=get_cleanup_delay(current_song)))
                print(f"[Player] ⚠️ Assistant was kicked from call in chat {chat_id}.")
            except Exception as e:
                print(f"[Player] ❌ Error in on_kicked: {e}")

        @self._pytg.on_update(filters.chat_update(ChatUpdate.Status.CLOSED_VOICE_CHAT))
        async def on_closed_vc(_, update):
            try:
                chat_id = update.chat_id
                self._cancel_idle_timer(chat_id)
                queue_manager.clear(chat_id)
                self._active_chats.discard(chat_id)
                old_local = self.local_files.pop(chat_id, None)
                if old_local:
                    current_song = queue_manager.get_current(chat_id)
                    asyncio.create_task(delayed_clean_cached_file(old_local, delay=get_cleanup_delay(current_song)))
                print(f"[Player] 🔇 Voice chat closed in chat {chat_id}. State cleared.")
                try:
                    await self.app.send_message(
                        chat_id,
                        f"{WARN} <b>ᴠᴏɪᴄᴇ ᴄʜᴀᴛ ᴡᴀs ᴄʟᴏsᴇᴅ!</b>\n"
                        f"{TRASH} Queue cleared. Start the voice chat and use <code>/plays</code> to restart. {WAVE}"
                    )
                except Exception:
                    pass
            except Exception as e:
                print(f"[Player] ❌ Error in on_closed_vc: {e}")

        @self._pytg.on_update(filters.chat_update(ChatUpdate.Status.LEFT_GROUP))
        async def on_chat_update(_, update):
            try:
                chat_id = update.chat_id
                self._cancel_idle_timer(chat_id)
                queue_manager.clear(chat_id)
                self._active_chats.discard(chat_id)
                old_local = self.local_files.pop(chat_id, None)
                if old_local:
                    current_song = queue_manager.get_current(chat_id)
                    asyncio.create_task(delayed_clean_cached_file(old_local, delay=get_cleanup_delay(current_song)))
                print(f"[Player] 🔇 Assistant left call in chat {chat_id}. State cleared.")
                try:
                    await self.app.send_message(
                        chat_id,
                        f"{WARN} <b>ᴀssɪsᴛᴀɴᴛ ʟᴇғᴛ ᴛʜᴇ ᴠᴏɪᴄᴇ ᴄʜᴀᴛ!</b>\n"
                        f"{TRASH} Queue cleared. Use <code>/plays</code> to start again. {WAVE}"
                    )
                except Exception:
                    pass
            except Exception as e:
                print(f"[Player] ❌ Error in on_chat_update: {e}")

        await self._pytg.start()
        print("[Player] ✅ PyTgCalls started!")

    # ────────────────────────── Idle Timer ──────────────────────────────────

    async def _idle_timeout_task(self, chat_id: int):
        """Wait 5 minutes then leave the voice chat automatically."""
        try:
            await asyncio.sleep(300)  # 5 minutes
            print(f"[Player] 💤 5-minute idle reached for chat {chat_id}. Auto-leaving.")
            try:
                await self._pytg.leave_call(chat_id)
            except Exception:
                pass
            self._active_chats.discard(chat_id)
            queue_manager.clear(chat_id)
            try:
                await self.app.send_message(
                    chat_id,
                    f"{SLEEP} <b>ɴᴏ sᴏɴɢs ᴘʟᴀʏɪɴɢ ғᴏʀ 5 ᴍɪɴᴜᴛᴇs.</b>\n"
                    f"Leaving the voice chat to save resources. Bye! {WAVE}"
                )
            except Exception:
                pass
        except asyncio.CancelledError:
            print(f"[Player] ⏱  Idle timer cancelled for chat {chat_id}")
        finally:
            self.idle_timers.pop(chat_id, None)

    def _cancel_idle_timer(self, chat_id: int):
        task = self.idle_timers.pop(chat_id, None)
        if task and not task.done():
            task.cancel()
            print(f"[Player] ✅ Idle timer cancelled for chat {chat_id}")

    # ────────────────────────── Play ────────────────────────────────────────

    async def _delayed_play(self, chat_id: int, song: SongInfo, send_card: bool = True, delay: float = 1.0):
        """Small delay before re-playing (lets WebRTC settle after stream end)."""
        await asyncio.sleep(delay)
        await self.play(chat_id, song, send_card=send_card)

    async def play(self, chat_id: int, song: SongInfo, bot_client: Client = None, send_card: bool = True, is_seek: bool = False, force_seek: int = 0) -> bool:
        """
        Download the song video/audio locally, and start streaming via PyTgCalls.
        Uses local files to eliminate direct-link buffering issues.
        """
        try:
            self._cancel_idle_timer(chat_id)

            if not is_seek:
                self.current_seek_offset[chat_id] = force_seek
                self.stream_start_time[chat_id] = asyncio.get_event_loop().time()
                self.paused_time.pop(chat_id, None)

            # Ensure assistant is in the group
            try:
                await self._assistant.get_chat_member(chat_id, "me")
            except Exception:
                print(f"[Player] 📥 Joining chat {chat_id}...")
                _bot = bot_client or self.app
                joined = False
                if _bot:
                    try:
                        invite = await _bot.create_chat_invite_link(chat_id)
                        await self._assistant.join_chat(invite.invite_link)
                        joined = True
                    except Exception:
                        pass
                if not joined:
                    try:
                        chat = await self._assistant.get_chat(chat_id)
                        if chat.username:
                            await self._assistant.join_chat(chat.username)
                            joined = True
                    except Exception:
                        pass

            # Detect stream modes
            mode = "audio" if getattr(song, "quality", "") == "audio" else "video"
            is_vod = (song.uploader in ("GameOver Stream", "MovieBox Stream", " Movies Stream", "MOVIES Engine")) or (song.duration == "VOD")
            
            # Auto-refresh YouTube direct links before downloading
            if not is_vod and not is_seek:
                from core.youtube import extract_video_id, refresh_youtube_stream
                video_id = extract_video_id(song.webpage_url)
                if video_id:
                    # Check if file is already cached locally
                    local_filename = f"{video_id}_{mode}.mp4"
                    local_path = os.path.join("downloads", local_filename)
                    if os.path.exists(local_path) and os.path.getsize(local_path) > 100000:
                        print(f"[Player] Found cached local file for ID {video_id}. Bypassing link refresh.")
                    else:
                        print(f"[Player] Refreshing expired stream URL for YouTube ID: {video_id}...")
                        fresh_data = await refresh_youtube_stream(
                            video_id, 
                            mode=mode, 
                            quality=getattr(song, "quality", "480")
                        )
                        if fresh_data:
                            song.video_url = fresh_data["video_url"]
                            song.audio_url = fresh_data["audio_url"]
                            print(f"[Player] Stream URL refreshed successfully!")

            # Retrieve or Download local cached file
            local_file = None
            if not is_seek:
                # Update UI to downloading status
                status_msg_id = self.active_message_id.get(chat_id)
                start_time = time.time()
                last_edit_time = [0.0]
                last_pct = [-1]
                async def progress_cb(pct, down, tot):
                    print(f"[Player DEBUG] progress_cb: pct={pct}, down={down}, tot={tot}, msg_id={status_msg_id}, app={self.app is not None}")
                    now = time.time()
                    if now - last_edit_time[0] >= 3.5 or (pct - last_pct[0] >= 10 and pct > 0) or pct == 100:
                        last_edit_time[0] = now
                        last_pct[0] = pct
                        if status_msg_id and self.app:
                            elapsed = time.time() - start_time
                            if elapsed <= 0:
                                elapsed = 0.01
                            speed_bps = down / elapsed
                            speed_mb = speed_bps / (1024 * 1024)
                            down_mb = down / (1024 * 1024)
                            
                            if tot > 0:
                                tot_mb = tot / (1024 * 1024)
                                remaining_bytes = tot - down
                                seconds_left = max(0, int(remaining_bytes / speed_bps)) if speed_bps > 0 else 0
                                time_left_str = f"{seconds_left}s"
                                filled = int(pct / 10)
                                bar = "■" * filled + "□" * (10 - filled)
                                progress_str = f"<code>[{bar}] {pct}%</code>"
                                size_str = f"📦 <b>sɪᴢᴇ:</b> <code>{down_mb:.1f} MB / {tot_mb:.1f} MB</code>"
                            else:
                                time_left_str = "calculating..."
                                progress_str = "<code>[📥 DOWNLOADING...]</code>"
                                size_str = f"📦 <b>sɪᴢᴇ:</b> <code>{down_mb:.1f} MB / calculating...</code>"
                            
                            caption = (
                                "👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ᴍᴜsɪᴄ ʙᴏᴛ</b> 👑\n\n"
                                "⚡ <b>ᴘʀᴏᴄᴇssɪɴɢ ᴍᴇᴅɪᴀ...</b>\n"
                                f"📌 <b>ᴛɪᴛʟᴇ:</b> <code>{song.title}</code>\n"
                                f"{progress_str}\n"
                                f"{size_str}\n"
                                f"🚀 <b>sᴘᴇᴇᴅ:</b> <code>{speed_mb:.1f} MB/s</code>\n"
                                f"⏳ <b>ʀᴇᴍᴀɪɴɪɴɢ:</b> <code>{time_left_str}</code>"
                            )
                            try:
                                await self.app.edit_message_caption(
                                    chat_id=chat_id,
                                    message_id=status_msg_id,
                                    caption=caption,
                                    parse_mode=enums.ParseMode.HTML
                                )
                            except Exception as e_caption:
                                try:
                                    await self.app.edit_message_text(
                                        chat_id=chat_id,
                                        message_id=status_msg_id,
                                        text=caption,
                                        parse_mode=enums.ParseMode.HTML
                                    )
                                except Exception as e_text:
                                    print(f"[Player DEBUG] edit failed: caption_err={e_caption}, text_err={e_text}")
                
                local_file = await download_song(song, mode=mode, progress_callback=progress_cb)
                if not local_file:
                    raise Exception("Caching failed. Downloader could not retrieve file.")
                
                # Cleanup previous file of the group before playing
                old_local = self.local_files.pop(chat_id, None)
                if old_local:
                    asyncio.create_task(delayed_clean_cached_file(old_local, delay=get_cleanup_delay(song)))
                    
                self.local_files[chat_id] = local_file
            else:
                local_file = self.local_files.get(chat_id)
                if not local_file or not os.path.exists(local_file):
                    raise Exception("Seek failed. Local cache is missing.")

            # ── PyTgCalls Media Stream Setup ──
            seek_val = self.current_seek_offset.get(chat_id, 0)
            seek_str = f"-ss {seek_val} " if seek_val > 0 else ""

            # Locks Video Parameters: 1080p @ 60 FPS (Full HD)
            vid_params = VideoParameters(width=1920, height=1080, frame_rate=60)
            
            # ── Audio Filter Chain ───────────────────────────────────────────────
            # AUDIO-ONLY: Clean Bass Boost — Smooth, No Glitch, No Pop/Distortion
            #
            #  bass=g=4:f=100:w=0.5
            #    → Gentle +4dB bass lowshelf at 100Hz (punchy, not overloaded)
            #    → g=4 safe even at PyTgCalls volume=200 (no clipping)
            #    → w=0.5 tight band = punchy, not muddy
            #
            #  acompressor=threshold=0.5:ratio=3:attack=8:release=80:makeup=1.5
            #    → Soft smooth compression: squeezes peaks, boosts quieter parts
            #    → attack=8ms (not too fast = no pumping artifact/pop)
            #    → release=80ms (slow enough to not cause breathing/pumping)
            #    → makeup=1.5 = +3.5dB loudness gain after compression
            #    → UNLIKE dynaudnorm: no sudden volume jumps = no 'put' sound
            #
            #  alimiter=limit=0.85:level=1
            #    → Hard safety ceiling at 0.85 (-1.4dBFS)
            #    → Transparent when not limiting, catches any peaks
            #    → PREVENTS clipping/distortion even at PyTgCalls volume=200
            #
            #  aresample=48000
            #    → Hard 48kHz (Telegram required), zero sync drift
            if mode == "audio":
                audio_filter = (
                    '-af "bass=g=4:f=100:w=0.5,'
                    'acompressor=threshold=0.5:ratio=3:attack=8:release=80:makeup=1.5,'
                    'alimiter=limit=0.85:level=1,'
                    'aresample=48000"'
                )
            else:
                # Video mode (Movies & TV): Cinema sound leveling (dialogue boost, compression + volume gain, no heavy bass)
                # Lower latency, smooth release (100ms) to prevent audio/video sync desync
                audio_filter = (
                    '-af "equalizer=f=60:width_type=h:width=50:g=3,'
                    'acompressor=threshold=0.15:ratio=4:attack=5:release=100:makeup=2.0,'
                    'volume=1.8,alimiter=limit=0.90,'
                    'aresample=async=1:min_comp=0.001:max_soft_comp=5"'
                )

            def get_stream(video_required: bool = True):
                v_flags = MediaStream.Flags.REQUIRED if video_required else MediaStream.Flags.IGNORE
                if video_required:
                    # Video mode: standard threading for AV sync with real-time reading (-re) and timestamp reconstruction (-fflags +genpts)
                    base_flags = f"--base ---start {seek_str}-re -fflags +genpts -analyzeduration 10M -probesize 10M -threads 4 -thread_queue_size 2048 -vsync cfr "
                else:
                    # Audio-only: minimal FFmpeg flags — 1 thread, tiny probe, no vsync = lowest CPU + latency
                    base_flags = f"--base ---start {seek_str}-analyzeduration 2M -probesize 2M -threads 1 -thread_queue_size 256 "
                return SeekableMediaStream(
                    media_path=local_file,
                    audio_path=None,  # Single local unified container file
                    video_parameters=vid_params,
                    audio_parameters=AudioQuality.HIGH,
                    video_flags=v_flags,
                    audio_flags=MediaStream.Flags.REQUIRED,
                    headers=None,
                    ffmpeg_parameters=(
                        f"{base_flags}"
                        f"--audio ---mid {audio_filter} -max_muxing_queue_size 2048"
                    )
                )

            stream = get_stream(video_required=(mode == "video"))

            # Play Stream in PyTgCalls with auto-start retry
            try:
                try:
                    await self._pytg.unmute(chat_id)
                except Exception:
                    pass
                
                await self._pytg.play(chat_id, stream)
            except Exception as play_err:
                err_str = str(play_err).lower()
                if "no video source found" in err_str:
                    print(f"[Player] No video source found in {local_file}. Aborting play as video is strictly required.")
                    if self.app:
                        try:
                            await self.app.send_message(chat_id, "❌ <b>No video stream found in this file! Playback aborted as video is required.</b>")
                        except Exception:
                            pass
                    queue_manager.clear(chat_id)
                    # Delete the invalid file immediately
                    if os.path.exists(local_file):
                        try:
                            os.remove(local_file)
                        except Exception:
                            pass
                    return False
                else:
                    print(f"[Player] Play failed: {play_err}. Attempting to force start group call...")
                    try:
                        from pyrogram.raw.functions.phone import CreateGroupCall
                        import random
                        peer_as = await self._assistant.resolve_peer(chat_id)
                        try:
                            await self._assistant.invoke(
                                CreateGroupCall(
                                    peer=peer_as,
                                    random_id=random.randint(0, 0x7FFFFFFF)
                                )
                            )
                            print(f"[Player] Assistant auto-started group call in chat {chat_id}")
                        except Exception:
                            if self.app:
                                peer_bot = await self.app.resolve_peer(chat_id)
                                await self.app.invoke(
                                    CreateGroupCall(
                                        peer=peer_bot,
                                        random_id=random.randint(0, 0x7FFFFFFF)
                                    )
                                )
                                print(f"[Player] Bot auto-started group call in chat {chat_id}")
                        # Wait 1.5 seconds for the call to be created in Telegram servers
                        await asyncio.sleep(1.5)
                        try:
                            await self._pytg.play(chat_id, stream)
                            print("[Player] Play succeeded after auto-starting group call!")
                        except Exception as retry_play_err:
                            retry_play_err_str = str(retry_play_err).lower()
                            if "no video source found" in retry_play_err_str:
                                print(f"[Player] Retry play failed due to missing video. Trying audio-only...")
                                stream = get_stream(video_required=False)
                                await self._pytg.play(chat_id, stream)
                                print("[Player] Audio-only fallback play succeeded after retry!")
                            else:
                                raise retry_play_err
                    except Exception as retry_err:
                        print(f"[Player] Retry play failed: {retry_err}")
                        err_msg = (
                            "❌ <b>ᴠᴏɪᴄᴇ ᴄʜᴀᴛ ɴᴏᴛ ᴀᴄᴛɪᴠᴇ!</b>\n"
                            "Please start the voice/video chat in the group to begin streaming."
                        )
                        if "FLOOD_WAIT" in str(retry_err) or "flood" in str(retry_err).lower():
                            err_msg = "❌ <b>Server is busy. Please try again shortly.</b>"
                        if self.app:
                            try:
                                await self.app.send_message(chat_id, err_msg)
                            except Exception:
                                pass
                        queue_manager.clear(chat_id)
                        return False

            # Delete old Now Playing card before playing the new track
            old_msg_id = self.active_message_id.pop(chat_id, None)
            if old_msg_id and self.app and not is_seek:
                try:
                    await self.app.delete_messages(chat_id, old_msg_id)
                except Exception:
                    pass

            self._active_chats.add(chat_id)
            queue_manager.set_current(chat_id, song)

            # Send Now Playing card
            if send_card and self.app and not is_seek:
                try:
                    from plugins.controls import get_rich_control_buttons, get_rich_caption
                    # Conditionally choose cover image: YouTube uses high-speed lofi cover to bypass Pak ISP ytimg block, MovieBox uses song.thumbnail
                    is_vod = (song.uploader in ("GameOver Stream", "MovieBox Stream", " Movies Stream", "MOVIES Engine")) or (song.duration == "VOD")
                    is_youtube = not is_vod and song.thumbnail and "ytimg" in song.thumbnail
                    if is_youtube:
                        photo_url = "https://images.unsplash.com/photo-1514525253161-7a46d19cd819?q=80&w=600"
                    else:
                        photo_url = song.thumbnail if (song.thumbnail and song.thumbnail.startswith("http")) else "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?q=80&w=600"
                    
                    caption = get_rich_caption(song, played_secs=0)
                    buttons = get_rich_control_buttons(chat_id, is_paused=False)
                    try:
                        msg = await self.app.send_photo(
                            chat_id=chat_id,
                            photo=photo_url,
                            caption=caption,
                            reply_markup=buttons,
                        )
                    except Exception as photo_err:
                        print(f"[Player] ⚠️  send_photo failed: {photo_err}. Retrying text...")
                        msg = await self.app.send_message(
                            chat_id=chat_id,
                            text=caption,
                            reply_markup=buttons,
                            disable_web_page_preview=True
                        )
                    self.active_message_id[chat_id] = msg.id

                    # Re-send keyboard via Bot HTTP API to apply native colored button styles
                    await apply_styled_buttons(chat_id, msg.id, buttons)

                    asyncio.create_task(live_ui_updater(self.app, chat_id, msg.id))
                except Exception as e:
                    print(f"[Player] ⚠️  Now-playing card error: {e}")

            return True

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[Player] ❌ Play error in chat {chat_id}: {e}")
            return False

    # ────────────────────────── Change Stream ───────────────────────────────

    async def change_stream(self, chat_id: int, song: SongInfo, send_card: bool = True) -> bool:
        return await self.play(chat_id, song, send_card=send_card)

    # ────────────────────────── Controls ────────────────────────────────────

    async def stop(self, chat_id: int):
        """Stop playback, clear queue, delete local cache, and leave voice chat."""
        self.skip_votes.pop(chat_id, None)
        old_msg_id = self.active_message_id.pop(chat_id, None)
        if old_msg_id and self.app:
            try:
                await self.app.delete_messages(chat_id, old_msg_id)
            except Exception:
                pass

        self._cancel_idle_timer(chat_id)
        queue_manager.clear(chat_id)
        self._active_chats.discard(chat_id)
        
        # Garbage Collect local file
        old_local = self.local_files.pop(chat_id, None)
        if old_local:
            asyncio.create_task(delayed_clean_cached_file(old_local, delay=get_cleanup_delay(None)))
            
        try:
            await self._pytg.leave_call(chat_id)
        except Exception:
            pass

    async def skip(self, chat_id: int) -> bool:
        """Skip the current track and play the next one, or stop if queue is empty."""
        self.skip_votes.pop(chat_id, None)
        
        if not queue_manager.is_empty(chat_id):
            next_song = queue_manager.pop(chat_id)
            print(f"[Player] Skipping to next track: {next_song.title} in chat {chat_id}")
            return await self.change_stream(chat_id, next_song, send_card=True)
        else:
            print(f"[Player] Queue empty, stopping playback in chat {chat_id}")
            await self.stop(chat_id)
            return True

    async def handle_vote_skip(self, chat_id: int, user_id: int, user_name: str, client: Client, message: Message = None, query: CallbackQuery = None):
        """Processes vote skip check, handles instant overrides for admins/requesters, and tracks democratic skip votes."""
        current = queue_manager.get_current(chat_id)
        if not current:
            if query:
                await query.answer("Nothing is playing!", show_alert=True)
            elif message:
                await message.reply_text("❌ <b>Nothing is currently playing!</b>")
            return

        from config import Config
        from core.db import is_sudo_user
        # 1. VIP override check
        is_vip = False
        if user_id == Config.OWNER_ID or is_sudo_user(user_id):
            is_vip = True
        elif getattr(current, "requester_id", 0) != 0 and user_id == current.requester_id:
            is_vip = True
        else:
            try:
                member = await client.get_chat_member(chat_id, user_id)
                if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                    is_vip = True
            except Exception:
                pass

        if is_vip:
            if query:
                try:
                    await query.answer("👑 Admin/Requester override: Skipping track...")
                except Exception:
                    pass
            elif message:
                try:
                    await message.reply_text("👑 <b>Admin/Requester override: Skipping track...</b>")
                except Exception:
                    pass
            await self.skip(chat_id)
            return

        # 2. Regular member vote check
        if chat_id not in self.skip_votes:
            self.skip_votes[chat_id] = set()

        if user_id in self.skip_votes[chat_id]:
            msg = "⚠️ You have already voted to skip this track!"
            if query:
                await query.answer(msg, show_alert=True)
            elif message:
                await message.reply_text(f"❌ <b>{msg}</b>")
            return

        self.skip_votes[chat_id].add(user_id)
        current_votes = len(self.skip_votes[chat_id])

        if current_votes >= 3:
            self.skip_votes.pop(chat_id, None)
            announcement = "✅ <b>3/3 Votes reached! Skipping track...</b>"
            if query:
                try:
                    await query.answer("Votes complete! Skipping...")
                    await query.message.reply_text(announcement)
                except Exception:
                    pass
            elif message:
                try:
                    await message.reply_text(announcement)
                except Exception:
                    pass
            await self.skip(chat_id)
        else:
            feedback = (
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "   👑 <b>ɢᴀᴍᴇᴏᴠᴇʀ ᴍᴜsɪᴄ ʙᴏᴛ</b> 👑\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
                "⚠️ <b>Direct skip denied! Regular members must vote.</b>\n\n"
                f"🗳️ <b>Skip Vote Registered:</b> <code>{current_votes}/3 Votes</code>\n"
                "💡 <i>Type /vote or click SKIP NEXT to add your vote!</i>"
            )
            if query:
                try:
                    await query.answer(f"Vote registered: {current_votes}/3", show_alert=True)
                    await query.message.reply_text(feedback)
                except Exception:
                    pass
            elif message:
                try:
                    await message.reply_text(feedback)
                except Exception:
                    pass

    async def pause(self, chat_id: int) -> bool:
        try:
            await self._pytg.pause(chat_id)
            if chat_id not in self.paused_time:
                self.paused_time[chat_id] = asyncio.get_event_loop().time()
            return True
        except Exception as e:
            print(f"[Player] ⚠️  Pause error: {e}")
            return False

    async def resume(self, chat_id: int) -> bool:
        try:
            await self._pytg.resume(chat_id)
            p_time = self.paused_time.pop(chat_id, None)
            if p_time and chat_id in self.stream_start_time:
                duration = asyncio.get_event_loop().time() - p_time
                self.stream_start_time[chat_id] += duration
            return True
        except Exception as e:
            print(f"[Player] ⚠️  Resume error: {e}")
            return False

    async def seek(self, chat_id: int, seconds: int) -> bool:
        song = queue_manager.get_current(chat_id)
        if not song:
            return False
            
        loop = asyncio.get_event_loop()
        now = loop.time()
        start = self.stream_start_time.get(chat_id, now)
        offset = self.current_seek_offset.get(chat_id, 0)
        
        is_paused = chat_id in self.paused_time
        if is_paused:
            elapsed = self.paused_time[chat_id] - start + offset
        else:
            elapsed = now - start + offset
            
        target = elapsed + seconds
        duration = song.duration_secs
        
        if duration > 0:
            target = max(0, min(target, duration - 5))
        else:
            target = max(0, target)
            
        self.current_seek_offset[chat_id] = int(target)
        self.stream_start_time[chat_id] = now
        if is_paused:
            self.paused_time[chat_id] = now
            
        return await self.play(chat_id, song, is_seek=True)

    async def skip(self, chat_id: int) -> bool:
        """Skip: pop next from queue and change stream. Returns True if next song found."""
        next_song = queue_manager.pop(chat_id)
        
        # Schedule cleanup of current local file after 10 min (don't block playback)
        old_local = self.local_files.pop(chat_id, None)
        if old_local:
            current_song = queue_manager.get_current(chat_id)
            asyncio.create_task(delayed_clean_cached_file(old_local, delay=get_cleanup_delay(current_song)))
            
        if next_song:
            return await self.play(chat_id, next_song)
        else:
            await self.stop(chat_id)
            return False

    async def close(self):
        """Graceful shutdown — leave all active voice chats and delete caches."""
        if self._pytg:
            print("[Player] 🔴 Shutting down — leaving all active calls...")
            for chat_id in list(self._active_chats):
                try:
                    await asyncio.wait_for(self._pytg.leave_call(chat_id), timeout=3.0)
                except Exception:
                    pass
                old_local = self.local_files.pop(chat_id, None)
                if old_local:
                    clean_cached_file(old_local)
                    
            for chat_id in list(self.idle_timers.keys()):
                self._cancel_idle_timer(chat_id)
            self._active_chats.clear()


# Global singleton player
stream_manager = PlayerManager()


async def apply_styled_buttons(chat_id: int, message_id: int, buttons):
    try:
        from config import Config
        from bot import _markup_to_bot_api_json
        import aiohttp, json
        token_val = Config.BOT_TOKEN
        if token_val:
            edit_payload = {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": json.dumps({
                    "inline_keyboard": _markup_to_bot_api_json(buttons)
                })
            }
            timeout = aiohttp.ClientTimeout(total=5.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                await session.post(
                    f"https://api.telegram.org/bot{token_val}/editMessageReplyMarkup",
                    json=edit_payload
                )
    except Exception as e:
        print(f"[Player] ⚠️ apply_styled_buttons error: {e}")


async def live_ui_updater(app, chat_id, message_id):
    """
    Updates the progress bar every second.
    """
    from plugins.controls import get_rich_control_buttons, get_rich_caption
    
    while True:
        await asyncio.sleep(5)  # Update every 5s — stays well under Telegram's 20 edits/min rate limit
        
        song = queue_manager.get_current(chat_id)
        if not song or not queue_manager.is_playing(chat_id):
            break
            
        if stream_manager.active_message_id.get(chat_id) != message_id:
            break
            
        is_paused = chat_id in stream_manager.paused_time
        if is_paused:
            continue
            
        # Calculate current elapsed seconds
        now = asyncio.get_event_loop().time()
        start = stream_manager.stream_start_time.get(chat_id, now)
        offset = stream_manager.current_seek_offset.get(chat_id, 0)
        elapsed = int(now - start + offset)
        
        # Save VOD progress dynamically
        is_vod = (getattr(song, "uploader", "") == "MOVIES Engine") or (song.duration == "VOD")
        subject_id = getattr(song, "subject_id", None)
        if is_vod and subject_id is not None:
            try:
                from core.db import set_vod_progress
                season = getattr(song, "season", 0)
                episode = getattr(song, "episode", 0)
                clean_title = getattr(song, "clean_title", song.title)
                if elapsed > 0:
                    set_vod_progress(chat_id, subject_id, clean_title, season, episode, elapsed)
            except Exception as db_err:
                print(f"[Player] Error saving VOD progress: {db_err}")
                
        new_caption = get_rich_caption(song, played_secs=elapsed)
        keyboard = get_rich_control_buttons(chat_id, is_paused=False)
        
        from pyrogram.errors import FloodWait, MessageNotModified
        try:
            try:
                await app.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=new_caption,
                    reply_markup=keyboard
                )
            except MessageNotModified:
                pass
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
            except Exception:
                try:
                    await app.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=new_caption,
                        reply_markup=keyboard,
                        disable_web_page_preview=True
                    )
                except MessageNotModified:
                    pass
                except FloodWait as e:
                    await asyncio.sleep(e.value + 1)
                    
            # Re-apply colored styled buttons so they never revert to default gray/blue
            await apply_styled_buttons(chat_id, message_id, keyboard)
            
        except Exception:
            break
