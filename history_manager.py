import os
import sqlite3
import time
from typing import List, Dict, Optional, Any

class HistoryManager:
    """Manages the user's listening history in a local SQLite database."""

    def __init__(self, temp_dir: Optional[str] = None):
        if not temp_dir:
            temp_dir = os.path.join(os.getenv('LOCALAPPDATA', '.'), 'WinYandexMusicRPC')
        os.makedirs(temp_dir, exist_ok=True)
        self.db_path = os.path.join(temp_dir, 'history.db')
        self._last_recorded: Optional[tuple] = None
        self._last_record_time: float = 0.0
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS listening_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    artist TEXT NOT NULL,
                    title TEXT NOT NULL,
                    album TEXT,
                    duration_sec REAL,
                    source TEXT,
                    played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_history_played_at 
                ON listening_history(played_at DESC)
            ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_history_artist 
                ON listening_history(artist)
            ''')
            conn.commit()

    def record_track(self, track: Dict[str, Any], min_interval_sec: float = 45.0) -> bool:
        """
        Records a track if it's valid and wasn't recorded very recently.
        Returns True if recorded, False if skipped.
        """
        if not track or not isinstance(track, dict):
            return False

        title = (track.get('title') or '').strip()
        artist = (track.get('artist') or '').strip()
        album = (track.get('album') or '').strip()
        duration_sec = float(track.get('durationSec', 0) or 0)
        source = str(track.get('source') or 'pc')

        if not title or not artist or title == '—' or artist == '—':
            return False

        # Don't record placeholder or local label as real artist
        current_identity = (artist.lower(), title.lower())
        now = time.monotonic()

        if self._last_recorded == current_identity and (now - self._last_record_time) < min_interval_sec:
            return False

        self._last_recorded = current_identity
        self._last_record_time = now

        try:
            with self._get_connection() as conn:
                conn.execute('''
                    INSERT INTO listening_history (artist, title, album, duration_sec, source)
                    VALUES (?, ?, ?, ?, ?)
                ''', (artist, title, album, duration_sec, source))
                conn.commit()
            return True
        except Exception:
            return False

    def get_recent_tracks(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Returns the most recently played tracks."""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute('''
                    SELECT id, artist, title, album, duration_sec, source, played_at
                    FROM listening_history
                    ORDER BY id DESC
                    LIMIT ?
                ''', (limit,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception:
            return []

    def get_top_artists(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Returns the top listened artists and their play counts."""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute('''
                    SELECT artist, COUNT(*) as play_count
                    FROM listening_history
                    WHERE artist != 'Локальный файл' AND artist != 'Local file'
                    GROUP BY artist
                    ORDER BY play_count DESC
                    LIMIT ?
                ''', (limit,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception:
            return []

    def get_total_count(self) -> int:
        """Returns the total number of recorded tracks in history."""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute('SELECT COUNT(*) FROM listening_history')
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception:
            return 0

    def clear_history(self) -> bool:
        """Clears all history records."""
        try:
            with self._get_connection() as conn:
                conn.execute('DELETE FROM listening_history')
                conn.commit()
            self._last_recorded = None
            self._last_record_time = 0.0
            return True
        except Exception:
            return False

history_manager = HistoryManager()
