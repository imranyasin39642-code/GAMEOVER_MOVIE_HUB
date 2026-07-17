"""
🎮 GameOver Music Bot — Upgraded Multi-Group Queue & Session Manager
Handles queues, loops, skips, skip voting, and played history with strict group isolation.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Set


@dataclass
class SongInfo:
    title: str
    video_url: str
    audio_url: str
    thumbnail: str
    duration: str
    duration_secs: int
    webpage_url: str
    uploader: str
    requested_by: str
    quality: str = "720"
    requester_id: Optional[int] = 0
    width: int = 16
    height: int = 9


class QueueManager:
    def __init__(self):
        # Strict per-chat isolation structures
        self.queues: Dict[int, List[SongInfo]] = {}      # upcoming tracks
        self._current: Dict[int, Optional[SongInfo]] = {} # now-playing track
        self._loops: Dict[int, int] = {}                  # loop counters
        self.history: Dict[int, List[SongInfo]] = {}      # history of played songs (max 10)
        self.skip_votes: Dict[int, Set[int]] = {}         # user IDs who voted to skip

    # ─────────────────────── Queue CRUD ────────────────────────────────────

    def add(self, chat_id: int, song: SongInfo) -> int:
        """Append song to queue. Returns new queue length."""
        self.queues.setdefault(chat_id, []).append(song)
        length = len(self.queues[chat_id])
        print(f"[Queue] Added '{song.title}' to chat {chat_id} | Queue size: {length}")
        return length

    def pop(self, chat_id: int) -> Optional[SongInfo]:
        """Pop next song from queue and set as current. Returns None if empty."""
        q = self.queues.setdefault(chat_id, [])
        if not q:
            return None
        song = q.pop(0)
        self._current[chat_id] = song
        # Clear votes when switching songs
        self.clear_votes(chat_id)
        print(f"[Queue] Popped '{song.title}' from chat {chat_id} | Remaining: {len(q)}")
        return song

    def peek(self, chat_id: int) -> Optional[SongInfo]:
        """Return next song without removing it."""
        q = self.queues.setdefault(chat_id, [])
        return q[0] if q else None

    def is_empty(self, chat_id: int) -> bool:
        return len(self.queues.setdefault(chat_id, [])) == 0

    def get_length(self, chat_id: int) -> int:
        return len(self.queues.setdefault(chat_id, []))

    def get_queue(self, chat_id: int) -> List[SongInfo]:
        return self.queues.setdefault(chat_id, [])

    def clear(self, chat_id: int):
        self.queues[chat_id] = []
        self._current.pop(chat_id, None)
        self._loops.pop(chat_id, None)
        self.clear_votes(chat_id)
        print(f"[Queue] Cleared all state for chat {chat_id}")

    # ─────────────────────── Current song helpers ───────────────────────────

    def set_current(self, chat_id: int, song: Optional[SongInfo]):
        self._current[chat_id] = song

    def get_current(self, chat_id: int) -> Optional[SongInfo]:
        return self._current.get(chat_id)

    def clear_current(self, chat_id: int):
        self._current.pop(chat_id, None)

    def is_playing(self, chat_id: int) -> bool:
        return self._current.get(chat_id) is not None

    # ─────────────────────── Loop helpers ───────────────────────────────────

    def set_loop(self, chat_id: int, count: int):
        self._loops[chat_id] = count

    def get_loop(self, chat_id: int) -> int:
        return self._loops.get(chat_id, 0)

    def decrement_loop(self, chat_id: int) -> int:
        val = self._loops.get(chat_id, 0)
        if val > 0:
            self._loops[chat_id] = val - 1
        return self._loops.get(chat_id, 0)

    # ─────────────────────── History helpers ────────────────────────────────

    def add_to_history(self, chat_id: int, song: SongInfo):
        hist = self.history.setdefault(chat_id, [])
        hist.append(song)
        if len(hist) > 10:
            hist.pop(0)

    def get_history(self, chat_id: int) -> List[SongInfo]:
        return self.history.setdefault(chat_id, [])

    # ─────────────────────── Vote Skip helpers ──────────────────────────────

    def get_votes(self, chat_id: int) -> Set[int]:
        return self.skip_votes.setdefault(chat_id, set())

    def add_vote(self, chat_id: int, user_id: int) -> int:
        votes = self.skip_votes.setdefault(chat_id, set())
        votes.add(user_id)
        return len(votes)

    def clear_votes(self, chat_id: int):
        self.skip_votes[chat_id] = set()


# Global singleton
queue_manager = QueueManager()
