from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as MediaManager
from config_manager import ConfigManager
from itertools import permutations
from packaging import version
from datetime import datetime, timedelta, timezone
from yandex_music import Client, exceptions
try:
    # Phone mode (what plays on the phone, read from the account). Optional: without the
    # extras (betterproto, websockets) or the Ynison-capable yandex-music build the app
    # simply works without it.
    from yandex_music.ynison import YnisonClientAsync, messages as ynison_messages, utils as ynison_utils
    YNISON_AVAILABLE = True
except Exception:
    YNISON_AVAILABLE = False
from colorama import init, Fore, Style
from win32com.client import Dispatch  # Импортируем Dispatch для создания COM объекта


import concurrent.futures
import multiprocessing
import platform
import queue
import subprocess
import webbrowser
import pystray
import win32gui
import win32con
import win32console
import threading
import pypresence
from pypresence.types import ActivityType
import keyring
import requests
import asyncio
import psutil
import string
import json
import time
import re
import sys
import os
import winreg
import threading
import pythoncom
from enum import Enum
from PIL import Image
# Идентификатор клиента Discord для Rich Presence
CLIENT_ID_EN = '1269807014393942046' #Yandex Music
CLIENT_ID_RU = '1217562797999784007' #Яндекс Музыка
CLIENT_ID_RU_DECLINED = '1269826362399522849' #Яндекс Музыку (склонение для активности "Слушает")

# Версия (tag) скрипта для проверки на актуальность через Github Releases
CURRENT_VERSION = "v3.0.0"

# Ссылка на репозиторий
REPO_URL = "https://github.com/payzik/YandexMusicRPC"

# Where the small "playing"/"paused" icons shown on the Discord card are loaded from.
# Discord fetches them by URL, so this must point to a public copy of the assets folder:
# (the assets folder of this repository, which must stay public)
ASSETS_BASE_URL = "https://raw.githubusercontent.com/payzik/YandexMusicRPC/main/assets"

# Optional "support the project" link shown as a small button in the app (never as a pop-up).
SUPPORT_URL = "https://boosty.to/yandexmusicrpc"

# (Опционально) Личный токен Яндекс.Музыки с подпиской Плюс (https://github.com/MarshalX/yandex-music-api/discussions/513)
# - Используется для поиска треков которые не показываются без авторизации
# - Используется при использовании скрипта из стран где бесплатная Яндекс.Музыка не работает
ya_token = str()

# Флаг для поиска трека с 100% совпадением названия и автора. Иначе будет найден близкий результат.
strong_find = True

# Флаг для настройки автозапуска с компьютером
auto_start_windows = False

# Режим телефона: показывать в Discord, что играет на телефоне (iOS/Android), читая
# состояние плеера аккаунта через Ynison. Работает, пока запущен RPC.
phone_mode = True

# --------- Переменные ниже являются временными и не требуют изменения.
# Переменная для хранения предыдущего трека и избежания дублирования обновлений.
name_prev = str()

# Переменая для хранения полного пути к иконке
icoPath = str()

# Очередь для передачи результатов между процессами
result_queue = multiprocessing.Queue()

# Переменная для проверки необходимости запуска рестарта в главном потоке Presence
needRestart  = False

# Number of consecutive temporary media-read failures tolerated during track transitions.
# Windows Media Control can briefly expose no active session between two tracks.
media_miss_count = 0
MEDIA_MISS_GRACE = 5
# Prevent repeated Clear RPC / error spam while Windows has no usable media session.
media_session_unavailable = False

# Windows can briefly return an incomplete MediaProperties object while Yandex
# Music changes/refreshes a MediaSession. Keep the last valid track for a few
# polls instead of treating one empty sample as session loss.
media_metadata_miss_count = 0
MEDIA_METADATA_GRACE = 8
# Startup sync pulse runs at most once per RPC session.
startup_sync_attempted = False
REPEAT_POSITION_RESET_SECONDS = 5.0
REPEAT_NEAR_END_SECONDS = 2.5

# Empirical sync correction for Discord's rendered progress.
# Positive means move the calculated position backwards; negative moves it
# forwards. Calibrated from the latest observed ~13s lag.
# Do not apply a fixed timestamp correction. Windows MediaSession timestamps
# are not stable enough for a global per-machine offset.
SEEK_JUMP_DETECTION_SECONDS = 1.5
# Windows keeps the *last* timeline snapshot ("position = end of track") when a track
# loops (repeat one). Once the extrapolated position is this far past the end, the
# track is considered to have started a new lap. The margin keeps the normal ~1 s gap
# before the next track from being mistaken for a loop.
REPEAT_LOOP_TOLERANCE_SECONDS = 1.5

# The WinRT session manager/session handles can occasionally keep serving stale
# cached properties (title/artist/timeline stop updating even though playback moved
# on to a different track) until something forces Windows to hand back fresh ones.
# Re-requesting the manager on a plain schedule - independent of track position or
# end-of-track timing, so it cannot interfere with the repeat-one handling above -
# self-heals that without any special-casing of *why* it got stuck.
MEDIA_MANAGER_REFRESH_SECONDS = 20.0
_last_manager_refresh_at = 0.0

# --- Phone mode (Ynison) ---------------------------------------------------------
# Ynison device types that count as "a phone" (tablets report the same types).
PHONE_DEVICE_TYPES = {"ANDROID", "IOS"}
# A phone that still reports "playing" this long after the track should have ended is
# treated as stopped (app killed without pausing).
PHONE_END_GRACE_SECONDS = 30.0
# Ynison timestamps come from another machine. If they disagree with our own clock by
# more than this, trust the local arrival time of the frame instead.
PHONE_CLOCK_SKEW_LIMIT_MS = 5000
YNISON_DEVICE_TITLE = "WinYandexMusicRPC"
YNISON_RETRY_SECONDS = 30.0

# Poll playback state more frequently so pause/play changes reach Discord quickly.
PRESENCE_POLL_INTERVAL = 0.25

# How long a positive "Discord is running" answer is trusted (a full process scan is costly).
DISCORD_CHECK_CACHE_SECONDS = 2.0

# Hysteresis for contradictory Windows Media Control reports.
# A real pause must be reflected immediately; only override Paused -> Playing
# after the timeline has clearly advanced across multiple polls.
playing_inference_count = 0
PLAYING_INFERENCE_REQUIRED = 2

# Переменная для хранения иконки в трее
iconTray = True

# Переменная для хранения MediaManager.request_async что бы избежать лишних вызовов
media_sessions = None

# Last logged Media Session IDs, used only for troubleshooting when automatic
# Yandex filtering finds no matching session.
last_logged_session_ids = None

#Менеджер настроек
config_manager = ConfigManager()

# Enum для конфигурации кнопок
class ButtonConfig(Enum):
    YANDEX_MUSIC_WEB = 1
    YANDEX_MUSIC_APP = 2
    BOTH = 3
    NEITHER = 4

# Enum для типа активности
class ActivityTypeConfig(Enum):
    PLAYING = 0
    LISTENING = 2

# Enum для выбора языка RPC
class LanguageConfig(Enum):
    ENGLISH = 0
    RUSSIAN = 1

# Глобальные настройки для RPC. Загружаются из метода get_saves_settings()
activityType_config = None
button_config = None
language_config = None

# Enum для статуса воспроизведения мультимедийного контента.
class PlaybackStatus(Enum):
    Unknown = 0
    Closed = 1
    Opened = 2
    Paused = 3
    Playing = 4
    Stopped = 5

# Список маркеров, по которым определяется источник Яндекс Музыки.
# Это позволяет полностью игнорировать YouTube/Spotify/браузеры и другие Media Sessions.
# Known Windows AppUserModel IDs for the desktop Yandex Music client.
# Keep the exact desktop ID first so unrelated media apps (Telegram, browsers,
# Spotify, YouTube, etc.) can never be selected as the target session.
YANDEX_EXACT_SESSION_IDS = {
    "ru.yandex.desktop.music",
}

YANDEX_SESSION_MARKERS = (
    "yandexmusic",
    "yandex.music",
    "yandex-music",
    "yandex_music",
    "yandex music",
    "ru.yandex.music",
)


def is_yandex_music_session(session) -> bool:
    """Return True only for sessions that look like the Yandex Music app.

    Windows AppUserModel IDs differ between the Microsoft Store build,
    desktop/webview builds and older releases, so matching only one exact
    identifier is too brittle.  We accept common Yandex Music identifiers
    while explicitly rejecting browser/Yandex Browser style IDs.
    """
    try:
        source_id = (session.source_app_user_model_id or "").strip().lower()
    except Exception:
        return False

    if not source_id:
        return False

    # Exact known desktop package/AUMID.
    if source_id in YANDEX_EXACT_SESSION_IDS:
        return True

    # Strong positive matches for known/common Yandex Music identifiers.
    if any(marker in source_id for marker in YANDEX_SESSION_MARKERS):
        return True

    # Some builds expose a generic Yandex AUMID containing both brand and
    # product words rather than the package name.
    if "yandex" in source_id and "music" in source_id:
        return True

    # Avoid accidentally accepting Yandex Browser sessions.
    if "yandex" in source_id and "browser" in source_id:
        return False

    return False


def fold_to_lap(live_seconds, lap_seconds):
    """Position inside the current lap of a (possibly looping) track.

    live_seconds is the snapshot position advanced to "now"; it keeps growing past the
    end of the track when Windows publishes no new snapshot for a repeated lap.
    """
    if live_seconds is None or not lap_seconds or lap_seconds <= 0:
        return live_seconds
    if live_seconds < lap_seconds + REPEAT_LOOP_TOLERANCE_SECONDS:
        return min(live_seconds, lap_seconds)
    return live_seconds % lap_seconds


async def _refresh_media_manager(reason):
    """(Re)acquire the WinRT session manager and log it, but not on every call."""
    global media_sessions
    media_sessions = await MediaManager.request_async()
    log_throttled(f"media-manager-refresh:{reason}", f"{reason} Windows MediaManager...", LogType.Default, interval=3600.0)


# Функция для получения информации о текущем мультимедийном контенте через Windows SDK
async def get_media_info():
    global media_sessions, playing_inference_count, last_logged_session_ids, _last_manager_refresh_at
    if media_sessions is None:
        try:
            await _refresh_media_manager("Making the first request to")
            _last_manager_refresh_at = time.monotonic()  # baseline, or the next poll would refresh immediately
        except Exception as e:
            log(f"Failed to get MediaManager sessions: {e}", LogType.Error)
            return None
    else:
        now_mono = time.monotonic()
        if now_mono - _last_manager_refresh_at >= MEDIA_MANAGER_REFRESH_SECONDS:
            _last_manager_refresh_at = now_mono
            try:
                await _refresh_media_manager("Periodic refresh of")
            except Exception as e:
                # A failed periodic refresh keeps using the last known-good manager;
                # the next scheduled refresh will simply try again.
                log_throttled("media-manager-refresh-failed", f"Periodic MediaManager refresh failed: {e}", LogType.Error)

    current_session = media_sessions.get_current_session()
    all_sessions = media_sessions.get_sessions()
    selected_session_id = config_manager.get_selected_session()
    target_session = None

    if selected_session_id and selected_session_id != "Automatic":
        # Явно выбранная сессия также должна принадлежать Яндекс Музыке.
        for session in all_sessions:
            if (session.source_app_user_model_id == selected_session_id
                    and is_yandex_music_session(session)):
                target_session = session
                break

        if not target_session:
            raise Exception(
                f"Selected session '{selected_session_id}' is not a Yandex Music session or is not available."
            )
    else:
        # В автоматическом режиме НЕ используем current_session вслепую:
        # Windows часто делает YouTube/браузер текущей Media Session.
        # Сначала пробуем текущую сессию, только если это Яндекс Музыка.
        if current_session and is_yandex_music_session(current_session):
            target_session = current_session
        else:
            if current_session:
                try:
                    current_id = current_session.source_app_user_model_id or "UnknownApp"
                    if "telegram" in current_id.lower():
                        # Telegram is explicitly diagnostic-only and never selected.
                        pass
                except Exception:
                    pass
            # Если текущей сессией является YouTube/браузер, ищем Яндекс Музыку
            # среди всех доступных Media Sessions. Предпочитаем реально Playing.
            yandex_sessions = [session for session in all_sessions if is_yandex_music_session(session)]
            if yandex_sessions:
                playing_sessions = []
                for session in yandex_sessions:
                    try:
                        status = PlaybackStatus(session.get_playback_info().playback_status).name
                    except Exception:
                        status = PlaybackStatus.Unknown.name
                    if status == PlaybackStatus.Playing.name:
                        playing_sessions.append(session)
                target_session = playing_sessions[0] if playing_sessions else yandex_sessions[0]

    if target_session:
        info = await target_session.try_get_media_properties_async()
        artist = info.artist
        title = info.title

        timeline = target_session.get_timeline_properties()
        position = timeline.position

        # TimelineProperties may expose EndTime for a local/uploaded track.
        # It is not guaranteed, so keep this best-effort.
        media_duration = None
        try:
            end_time = getattr(timeline, "end_time", None)
            if end_time is not None and end_time > position:
                media_duration = end_time
        except Exception:
            media_duration = None

        playback_info = target_session.get_playback_info()
        reported_playback_status = PlaybackStatus(playback_info.playback_status).name

        # Startup synchronization:
        # Some Yandex/Windows Media Session builds expose a stale timeline right
        # after another process connects. A user-visible pause -> play refreshes
        # the session to the real position, so reproduce the same operation once
        # automatically at startup, then re-read the timeline.
        global startup_sync_attempted
        if (
            not startup_sync_attempted
            and Presence.currentTrack is None
            and reported_playback_status == PlaybackStatus.Playing.name
        ):
            # Mark before touching playback: even if MediaSession errors, this can
            # never become a repeated pause/play loop on every polling iteration.
            startup_sync_attempted = True
            try:
                log(
                    "Startup sync pulse: refreshing Yandex MediaSession position (one-shot).",
                    LogType.Update_Status
                )
                paused_ok = await target_session.try_pause_async()
                if paused_ok:
                    await asyncio.sleep(0.12)
                    played_ok = await target_session.try_play_async()

                    if played_ok:
                        await asyncio.sleep(0.08)
                        refreshed_timeline = target_session.get_timeline_properties()
                        timeline = refreshed_timeline  # keeps last_updated_time in step with position
                        position = refreshed_timeline.position
                        log(
                            f"Startup sync pulse complete: position={position.total_seconds():.2f}s",
                            LogType.Update_Status
                        )
                    else:
                        log(
                            "Startup sync pulse: Play request failed; using original timeline.",
                            LogType.Default
                        )
                else:
                    log(
                        "Startup sync pulse: Pause request failed; using original timeline.",
                        LogType.Default
                    )
            except Exception as e:
                log(f"Startup sync pulse skipped: {e}", LogType.Default)

        # Yandex Music / Windows Media Transport Controls can occasionally report
        # Paused while the track is actually continuing to play.  However, an
        # explicit real pause must take effect immediately.  Therefore we do not
        # override Paused on a single stale/advancing sample; we require the
        # timeline to advance across multiple polls before treating it as Playing.
        now = time.monotonic()
        position_seconds = position.total_seconds()
        inferred_status = reported_playback_status

        previous_position = Presence.last_media_position
        position_advanced = (
            previous_position is not None and
            position_seconds > previous_position + 0.20
        )

        if reported_playback_status == PlaybackStatus.Playing.name:
            playing_inference_count = 0
            inferred_status = PlaybackStatus.Playing.name
        elif reported_playback_status == PlaybackStatus.Paused.name:
            if position_advanced:
                playing_inference_count += 1
            else:
                playing_inference_count = 0

            if playing_inference_count >= PLAYING_INFERENCE_REQUIRED:
                inferred_status = PlaybackStatus.Playing.name
            else:
                # Honour a genuine pause immediately.
                inferred_status = PlaybackStatus.Paused.name
        else:
            # Unknown/other states can retain Playing only briefly when the
            # timeline is still moving; this prevents flicker during updates.
            if position_advanced:
                playing_inference_count = min(
                    playing_inference_count + 1,
                    PLAYING_INFERENCE_REQUIRED
                )
            else:
                playing_inference_count = 0

            if (playing_inference_count >= PLAYING_INFERENCE_REQUIRED and
                    reported_playback_status != PlaybackStatus.Closed.name):
                inferred_status = PlaybackStatus.Playing.name

        if previous_position is None or position_seconds != previous_position:
            Presence.last_media_position = position_seconds
            Presence.last_media_position_time = now
        Presence.effective_playback_status = inferred_status
        playback_status = inferred_status

        # Windows returns a timeline *snapshot*: `position` is valid at
        # `last_updated_time` and never advances by itself (it changes only on
        # play/pause/seek/track change). Extrapolate it for display purposes.
        live_position = position_seconds
        if inferred_status == PlaybackStatus.Playing.name:
            try:
                age = (datetime.now(timezone.utc) - timeline.last_updated_time).total_seconds()
                live_position += max(0.0, age) * (playback_info.playback_rate or 1.0)
            except Exception:
                pass
        Presence.live_position = live_position
        try:
            end_seconds = timeline.end_time.total_seconds()
            Presence.media_length = end_seconds if end_seconds > 0 else None
        except Exception:
            Presence.media_length = None

        session_title = info.title or "Unknown Title"
        app_name = target_session.source_app_user_model_id or "Unknown App"
        return {
            'artist': artist,
            'title': title,
            'playback_status': playback_status,
            'position': position,
            'duration': media_duration,
            'session_title': session_title,
            'app_name': app_name
        }

    try:
        # Only report Yandex candidates in normal logs. Other media apps such as
        # Telegram are intentionally ignored, not selected.
        yandex_ids = tuple(sorted({
            (session.source_app_user_model_id or "UnknownApp")
            for session in all_sessions
            if is_yandex_music_session(session)
        }))
        if yandex_ids != last_logged_session_ids:
            last_logged_session_ids = yandex_ids
            if yandex_ids:
                log("Yandex Media Sessions: " + " | ".join(yandex_ids), LogType.Default)
    except Exception:
        pass

    raise Exception('The music is not playing right now.')

async def get_session_ids(only_yandex=False):
    global media_sessions
    manager = media_sessions
    if manager is None:
        try:
            log("Making the first request to windows MediaManager...", LogType.Default)
            manager = media_sessions = await MediaManager.request_async()
        except Exception as e:
            log(f"Failed to get MediaManager sessions: {e}", LogType.Error)
            return None
    return [
        session.source_app_user_model_id or "UnknownApp"
        for session in manager.get_sessions()
        if not only_yandex or is_yandex_music_session(session)
    ]


def phone_live_position(snap, now_mono=None, now_ms=None):
    """Position (seconds) of the phone's track right now, from a Ynison snapshot.

    Ynison only sends a frame when something happens (play/pause/seek/track change),
    carrying the position at that moment, so while playing it is advanced by the elapsed
    time. The server timestamp is preferred; if it disagrees with our clock (clock skew,
    or a frame that was delayed) the local arrival time of the frame is used instead.
    """
    position_ms = float(snap['progress_ms'])
    if not snap['paused']:
        now_mono = time.monotonic() if now_mono is None else now_mono
        now_ms = time.time() * 1000 if now_ms is None else now_ms
        elapsed = (now_mono - snap['arrival']) * 1000
        ts = snap.get('ts_ms') or 0
        if ts > 0:
            by_timestamp = now_ms - ts
            if by_timestamp >= 0 and abs(by_timestamp - elapsed) <= PHONE_CLOCK_SKEW_LIMIT_MS:
                elapsed = by_timestamp
        position_ms += max(0.0, elapsed) * (snap.get('speed') or 1.0)
    return position_ms / 1000.0


class PhoneWatcher:
    """Follows the account's player state through Ynison to see what plays on the phone.

    Connects as a remote-controller-only device (it cannot play and never sends
    pause/next/volume commands), runs on the shared background event loop and keeps the
    newest state in `state`. The library reconnects by itself.
    """
    state = None          # latest snapshot dict, replaced atomically on every frame
    status = "off"        # off | connecting | connected | error
    last_error = None
    _client = None
    _future = None
    _next_try = 0.0

    @staticmethod
    def _snapshot(frame):
        player = frame.player_state
        status = player.status
        playable = ynison_utils.get_current_playable(frame)
        device = ynison_utils.get_active_device(frame)
        queue = player.player_queue
        options = queue.options if queue is not None else None
        return {
            'arrival': time.monotonic(),
            'paused': bool(status.paused),
            'progress_ms': int(status.progress_ms),
            'duration_ms': int(status.duration_ms),
            'ts_ms': int(status.version.timestamp_ms) if status.version is not None else 0,
            'speed': status.playback_speed or 1.0,
            'track_id': playable.playable_id if playable else None,
            'track_title': playable.title if playable else None,
            'album_id': playable.album_id_optional if playable else None,
            'repeat_one': bool(options is not None and options.repeat_mode.name == 'ONE'),
            'device_type': device.info.type.name if device else None,
            'device_title': device.info.title if device else None,
            'device_offline': bool(device.is_offline) if device else True,
        }

    @classmethod
    def _on_state(cls, frame):
        cls.state = cls._snapshot(frame)
        if cls.status != "connected":
            cls.status = "connected"
            log("Phone mode: connected to the account player state (Ynison).", LogType.Update_Status)

    @classmethod
    def _on_error(cls, error):
        cls.last_error = error
        log_throttled("ynison-error", f"Phone mode: Ynison error: {error}", LogType.Error)

    @classmethod
    async def _run(cls, token):
        client = YnisonClientAsync(
            token,
            # Per machine: two PCs on one account must not push each other out of the session.
            device_id=ynison_messages.generate_device_id(seed=f'wym-phone-mode:{token}:{platform.node()}'),
            device_title=YNISON_DEVICE_TITLE,
        )
        cls._client = client
        client.on_state(cls._on_state)
        client.on_error(cls._on_error)
        cls.status = "connecting"
        try:
            await client.connect()  # blocks: reconnects by itself until disconnect()
            cls.status = "off"
        except Exception as e:
            cls.last_error = e
            cls.status = "error"
            log_throttled("ynison-failed", f"Phone mode stopped: {e}", LogType.Error)
        finally:
            cls._client = None
            cls.state = None

    @classmethod
    def running(cls):
        return cls._future is not None and not cls._future.done()

    @classmethod
    def start(cls, token):
        cls.status = "connecting"
        cls._future = asyncio.run_coroutine_threadsafe(cls._run(token), _get_bg_loop())

    @classmethod
    def stop(cls):
        client, future = cls._client, cls._future
        cls._future = None
        if client is not None:
            try:
                asyncio.run_coroutine_threadsafe(client.disconnect(), _get_bg_loop()).result(timeout=3)
            except Exception:
                pass
        if future is not None:
            try:
                future.result(timeout=3)
            except Exception:
                future.cancel()
        cls.state = None
        cls.status = "off"

    @classmethod
    def maintain(cls):
        """Start/stop the watcher to match the setting; returns True while phone mode is wanted."""
        want = bool(phone_mode and YNISON_AVAILABLE and ya_token)
        if want and not cls.running():
            now = time.monotonic()
            if now >= cls._next_try:
                cls._next_try = now + YNISON_RETRY_SECONDS
                cls.start(ya_token)
        elif not want and (cls.running() or cls.status != "off"):
            cls.stop()
        return want

class Presence:
    client = None
    currentTrack = None
    rpc = None
    running = False
    paused = False
    paused_time = 0
    last_media_position = None
    last_media_position_time = 0.0
    live_position = None  # snapshot position advanced to "now", in seconds
    media_length = None   # track length reported by Windows (end_time), in seconds
    effective_playback_status = PlaybackStatus.Unknown.name
    last_presence_position = None
    last_presence_track = None
    exe_names = ["Discord.exe", "DiscordCanary.exe", "DiscordPTB.exe", "Vesktop.exe"]
    # "stopped" | "waiting" (waiting for Discord) | "running"; read by the GUI.
    state = "stopped"
    last_source = None  # "pc" | "phone": where the published card comes from
    _discord_seen_at = 0.0

    @staticmethod
    def is_discord_running() -> bool:
        # The main loop asks this ~4 times per second; scanning every process each
        # time is expensive, so a positive answer is trusted for a couple of seconds.
        now = time.monotonic()
        if now - Presence._discord_seen_at < DISCORD_CHECK_CACHE_SECONDS:
            return True
        names = {n.lower() for n in Presence.exe_names}
        try:
            found = any(
                (p.info.get("name") or "").lower() in names
                for p in psutil.process_iter(["name"])
            )
        except Exception:
            # A process vanishing mid-scan must not kill the polling loop.
            return Presence._discord_seen_at > 0 and now - Presence._discord_seen_at < 10.0
        if found:
            Presence._discord_seen_at = now
        return found

    @staticmethod
    def _sleep_while_running(seconds: float) -> None:
        end = time.monotonic() + seconds
        while Presence.running and time.monotonic() < end:
            time.sleep(0.1)

    @staticmethod
    def connect_rpc():
        try:
            client_id = CLIENT_ID_EN if language_config == LanguageConfig.ENGLISH else \
                CLIENT_ID_RU_DECLINED if activityType_config == ActivityTypeConfig.LISTENING else CLIENT_ID_RU
            rpc = pypresence.Presence(client_id)
            rpc.connect()
            return rpc
        except pypresence.exceptions.DiscordNotFound:
            log("Pypresence - Discord not found.", LogType.Error)
            return None
        except pypresence.exceptions.InvalidID:
            log("Pypresence - Incorrect CLIENT_ID", LogType.Error)
            return None
        except Exception as e:
            log(f"Discord is not ready for a reason: {e}", LogType.Error)
            return None

    @staticmethod
    def discord_available() -> bool:
        """Block until Discord accepts an RPC connection.

        Returns False if stop() was called while waiting, so the wait can be cancelled.
        """
        while Presence.running:
            if Presence.is_discord_running():
                rpc = Presence.connect_rpc()
                if rpc:
                    if not Presence.running:  # stopped while connecting
                        rpc.close()
                        return False
                    Presence.rpc = rpc
                    log("Discord is ready for Rich Presence")
                    return True
                log_throttled("discord-not-ready", "Discord is launched but not ready for Rich Presence. Try again...", LogType.Error)
            else:
                log_throttled("discord-not-launched", "Discord is not launched", LogType.Error)
            Presence._sleep_while_running(3)
        return False

    @staticmethod
    def _reset_track_state() -> None:
        global name_prev
        Presence.currentTrack = None
        Presence.paused = False
        Presence.last_media_position = None
        Presence.last_media_position_time = 0.0
        Presence.live_position = None
        Presence.media_length = None
        Presence.last_presence_position = None
        Presence.last_presence_track = None
        Presence.last_source = None
        name_prev = None

    @staticmethod
    def stop() -> None:
        Presence.running = False
        rpc, Presence.rpc = Presence.rpc, None
        try:
            if rpc:
                rpc.close()
        finally:
            Presence._reset_track_state()

    @staticmethod
    def need_restart() -> None:
        log("Restarting RPC because settings have been changed...", LogType.Update_Status)
        global needRestart
        needRestart = True

    @staticmethod
    def restart() -> None:
        global media_miss_count, media_session_unavailable
        Presence.currentTrack = None
        Presence.paused = False
        media_miss_count = 0
        media_session_unavailable = False
        Presence.last_media_position = None
        Presence.last_media_position_time = 0.0
        Presence.effective_playback_status = PlaybackStatus.Unknown.name
        # startup_sync_attempted is deliberately NOT reset here: the pause/play "sync pulse"
        # belongs to the first start only, otherwise every settings change would interrupt
        # the user's music.
        global playing_inference_count
        playing_inference_count = 0
        global name_prev
        name_prev = None
        if Presence.rpc:
            Presence.rpc.close()
            Presence.rpc = None
        Presence._sleep_while_running(3)
        Presence.discord_available()

    @staticmethod
    def discord_was_closed() -> None:
        log("Discord was closed. Waiting for restart...", LogType.Error)
        Presence.currentTrack = None
        Presence._discord_seen_at = 0.0
        global name_prev
        name_prev = None
        Presence.discord_available()

    @staticmethod
    def _finish() -> None:
        """Common shutdown path: runs when the polling loop exits for any reason."""
        Presence.running = False
        Presence.state = "stopped"
        try:
            PhoneWatcher.stop()
        except Exception:
            pass
        rpc, Presence.rpc = Presence.rpc, None
        try:
            if rpc:
                rpc.close()
        except Exception:
            pass
        Presence._reset_track_state()

    @staticmethod
    def _playing_presence(ongoing_track):
        # Use the actual current MediaSession position. No fixed correction is
        # applied here; Discord's timestamp is derived directly from this value.
        position_seconds = float(ongoing_track["start-time"].total_seconds())
        sync_time = time.time()
        start_time = sync_time - position_seconds
        args = {
            "activity_type": ActivityType(activityType_config.value),
            "details": ongoing_track["title"],
            "state": ongoing_track["artist"],
            "start": start_time,
            "large_image": ongoing_track.get("og-image") or "YMRPC",
        }
        if ongoing_track["durationSec"] > 0:  # unknown length: no progress bar instead of an empty one
            args["end"] = start_time + ongoing_track["durationSec"]
        if ongoing_track["album"] != ongoing_track["title"]:
            args["large_text"] = ongoing_track["album"]
        if (
            button_config != ButtonConfig.NEITHER
            and ongoing_track.get("link")
        ):
            args["buttons"] = build_buttons(ongoing_track["link"])
        if activityType_config == ActivityTypeConfig.LISTENING:
            args["small_image"] = f"{ASSETS_BASE_URL}/Playing.png"
            args["small_text"] = "Playing" if language_config == LanguageConfig.ENGLISH else "Проигрывается"
        if ongoing_track.get("source") == "phone":
            if Presence._name_override_active():
                args["name"] = Presence._phone_card_name()
            device = ongoing_track.get("device") or ("phone" if language_config == LanguageConfig.ENGLISH else "телефоне")
            args["small_image"] = f"{ASSETS_BASE_URL}/Playing.png"
            args["small_text"] = (f"Listening on {device}" if language_config == LanguageConfig.ENGLISH
                                  else f"Слушает на {device}")
        return args

    @staticmethod
    def _phone_card_name():
        """Header of the Discord card while listening on the phone ("Слушает <name>").

        On the PC no name is sent at all, so Discord shows the plain application name.
        """
        if language_config == LanguageConfig.ENGLISH:
            return "Yandex Music (on phone)"
        if activityType_config == ActivityTypeConfig.LISTENING:
            return "Яндекс Музыку (на телефоне)"  # "Слушает Яндекс Музыку (на телефоне)"
        return "Яндекс Музыка (на телефоне)"

    # The custom card name is a recent Discord feature, so a failed update is retried without
    # it. One failure must not switch the feature off for good (a rate limit or a hiccup is
    # not a refusal): only repeated failures pause it, and only for a while.
    _name_fail_streak = 0
    _name_disabled_until = 0.0
    _name_retry_at = 0.0
    NAME_FAILS_TO_PAUSE = 3
    NAME_PAUSE_SECONDS = 600.0
    NAME_RETRY_SECONDS = 5.0

    @staticmethod
    def _name_override_active():
        return time.monotonic() >= Presence._name_disabled_until

    @staticmethod
    def _update(**args):
        """rpc.update() that still publishes the card when Discord fails on the custom name."""
        try:
            Presence.rpc.update(**args)
            if 'name' in args:
                Presence._name_fail_streak = 0
            return
        except pypresence.exceptions.PipeClosed:
            raise
        except Exception as e:
            if 'name' not in args:
                raise
            Presence._name_fail_streak += 1
            now = time.monotonic()
            if Presence._name_fail_streak >= Presence.NAME_FAILS_TO_PAUSE:
                Presence._name_fail_streak = 0
                Presence._name_disabled_until = now + Presence.NAME_PAUSE_SECONDS
                log(f"Discord keeps failing with the custom card name ({e}); standard name for "
                    f"{int(Presence.NAME_PAUSE_SECONDS // 60)} min.", LogType.Error)
            else:
                log_throttled("name-update-failed", f"Discord update with the custom card name failed ({e}); retrying without it.", LogType.Error)
                Presence._name_retry_at = now + Presence.NAME_RETRY_SECONDS
            args.pop('name', None)
            Presence.rpc.update(**args)  # this update still goes out, just without the name

    @staticmethod
    def _paused_presence(ongoing_track, current_pos):
        presence_args = {
            'activity_type': ActivityType(activityType_config.value),
            'details': ongoing_track['title'],
            'state': ongoing_track['artist'],
            'large_image': ongoing_track.get('og-image') or "YMRPC",
            'large_text': ongoing_track['album'],
            'small_image': f"{ASSETS_BASE_URL}/Paused.png",
            'small_text': "On pause" if language_config == LanguageConfig.ENGLISH else "На паузе"
        }
        if (
            button_config != ButtonConfig.NEITHER
            and ongoing_track.get('link')
        ):
            presence_args['buttons'] = build_buttons(ongoing_track['link'])
        paused_text = format_duration(int(current_pos * 1000))
        if current_pos > 0:
            presence_args['large_text'] = f"{'On pause' if language_config == LanguageConfig.ENGLISH else 'На паузе'} {paused_text} / {ongoing_track['formatted_duration']}"
            presence_args['small_text'] = presence_args['large_text']
        if ongoing_track.get('source') == 'phone':
            if Presence._name_override_active():
                presence_args['name'] = Presence._phone_card_name()
            if ongoing_track.get('device'):
                presence_args['small_text'] = f"{presence_args['small_text']} · {ongoing_track['device']}"[:128]
        return presence_args

    # Метод для запуска Rich Presence.
    @staticmethod
    def start() -> None:
        """Run the Rich Presence loop (blocking) until stop() is called."""
        Presence.running = True
        Presence.state = "waiting"
        try:
            Presence._run()
        finally:
            Presence._finish()

    @staticmethod
    def _run() -> None:
        global ya_token
        global needRestart
        if not Presence.discord_available():
            return  # cancelled while waiting for Discord
        Presence.state = "running"
        if not Presence.client:
            Presence.client = Client().init()
        global media_miss_count, media_session_unavailable
        global name_prev, playing_inference_count
        Presence.currentTrack = None
        Presence.paused = False
        media_miss_count = 0
        media_session_unavailable = False
        Presence.last_media_position = None
        Presence.last_media_position_time = 0.0
        Presence.effective_playback_status = PlaybackStatus.Unknown.name
        Presence.last_presence_position = None
        Presence.last_presence_track = None
        global startup_sync_attempted
        startup_sync_attempted = False
        playing_inference_count = 0
        # Forget the previously resolved track, otherwise stop -> start on the same
        # track leaves getTrack() returning success=False forever (currentTrack is None).
        name_prev = None
        error_streak = 0
        while Presence.running:
            if not Presence.is_discord_running():
                Presence.discord_was_closed()
                if not Presence.running:
                    break
            if needRestart:
                needRestart = False
                Presence.restart()
                if not Presence.running:
                    break
            try:
                # The PC wins whenever Yandex Music on it is really playing. Only when it is
                # not, a phone that plays (the account's active device) is the source; a paused
                # phone card is shown only if the PC has nothing at all.
                phone_track = Presence.getPhoneTrack() if PhoneWatcher.maintain() else None
                source = 'pc'
                if (
                    phone_track is not None
                    and phone_track['playback'] == PlaybackStatus.Playing.name
                    and not Presence._pc_playing()
                ):
                    ongoing_track = phone_track
                    source = 'phone'
                    name_prev = None  # the PC cache must not leak into the next PC track
                else:
                    ongoing_track = Presence.getTrack()
                    if (not ongoing_track or not ongoing_track.get('success')) and phone_track is not None:
                        ongoing_track = phone_track
                        source = 'phone'
                        name_prev = None
                    elif ongoing_track and ongoing_track.get('source') == 'phone':
                        # getTrack() reused a phone card as its cache: it is the PC's now.
                        ongoing_track = dict(ongoing_track)
                        ongoing_track.pop('source', None)
                if source != Presence.last_source:
                    Presence.last_source = source
                    if source == 'phone':
                        log(f"Source: phone ({ongoing_track.get('device') or 'unknown device'})", LogType.Update_Status)
                    else:
                        log("Source: this PC", LogType.Update_Status)

                # During a track transition Windows Media Control may temporarily
                # return no active media session. Do not clear Discord RPC on the
                # first few misses; wait for the next track to appear.
                if not ongoing_track or not ongoing_track.get('success'):
                    media_miss_count += 1

                    # A long-idle Media Session can disappear from Windows completely.
                    # During that state, do not repeatedly clear RPC or spam the console.
                    # Clear once after the normal transition grace period, then remain quiet
                    # until a real Yandex Music session becomes available again.
                    if media_miss_count >= MEDIA_MISS_GRACE:
                        if not media_session_unavailable:
                            if Presence.rpc:
                                Presence.rpc.clear()
                            log(
                                "Media session unavailable; RPC cleared once. "
                                "Waiting for Yandex Music to become available again."
                            )
                            media_session_unavailable = True

                        Presence.currentTrack = None
                        Presence.paused = False
                        name_prev = None
                        Presence.last_media_position = None
                        Presence.last_media_position_time = 0.0
                        media_miss_count = MEDIA_MISS_GRACE

                    time.sleep(PRESENCE_POLL_INTERVAL)
                    continue

                # A valid track/session is back. Resume normal handling and allow
                # a future long-idle disappearance to clear RPC once again.
                media_miss_count = 0
                media_session_unavailable = False

                # Compare only track identity; position changes do not create a new track.
                same_track = (
                    Presence.currentTrack is not None
                    and Presence.currentTrack.get("label") == ongoing_track.get("label")
                    and Presence.currentTrack.get("source") == ongoing_track.get("source")
                )
                snapshot_pos = float(ongoing_track["start-time"].total_seconds())
                previous_pos = Presence.last_presence_position
                duration_seconds = float(ongoing_track.get("durationSec", 0) or 0)

                # Windows only publishes position snapshots (play/pause/seek/track change),
                # so use the snapshot advanced to "now", folded into the current lap. That
                # also covers "repeat one": there the last snapshot stays at the end of the
                # track and the new lap is never announced, which used to freeze Discord.
                current_pos = snapshot_pos
                if (
                    source != 'phone'  # a phone card already carries its own live position
                    and ongoing_track.get("playback") == PlaybackStatus.Playing.name
                    and Presence.live_position is not None
                ):
                    current_pos = fold_to_lap(Presence.live_position, Presence.media_length or duration_seconds)
                    if abs(current_pos - snapshot_pos) > 0.01:
                        ongoing_track = ongoing_track.copy()
                        ongoing_track["start-time"] = timedelta(seconds=current_pos)

                # Same metadata + a large backward position jump means the track
                # restarted (repeat-one) or the user performed a backwards seek.
                rewind_detected = (
                    same_track
                    and previous_pos is not None
                    and previous_pos > REPEAT_POSITION_RESET_SECONDS
                    and current_pos + REPEAT_POSITION_RESET_SECONDS < previous_pos
                )
                repeated_same_track = rewind_detected
                seeked = (
                    same_track and previous_pos is not None
                    and abs(current_pos - previous_pos) >= SEEK_JUMP_DETECTION_SECONDS
                    and not repeated_same_track
                )

                if repeated_same_track:
                    log(
                        f"Detected repeat restart: {ongoing_track['label']} "
                        f"{previous_pos:.2f}s -> {current_pos:.2f}s",
                        LogType.Update_Status
                    )

                if not same_track or repeated_same_track:
                    if ongoing_track['success']:
                        if Presence.currentTrack is not None and Presence.currentTrack.get('label'):
                            if ongoing_track['label'] != Presence.currentTrack['label']:
                                log(f"Changed track to {ongoing_track['label']}", LogType.Update_Status)
                        else:
                            log(f"Changed track to {ongoing_track['label']}", LogType.Update_Status)
                        if repeated_same_track and current_pos <= REPEAT_NEAR_END_SECONDS:
                            ongoing_track = ongoing_track.copy()
                            ongoing_track["playback"] = PlaybackStatus.Playing.name
                        Presence.paused = ongoing_track['playback'] != PlaybackStatus.Playing.name
                        Presence.paused_time = 0
                        if Presence.paused:
                            # Already paused when it appeared: a running timer would be a lie
                            # (and the pause branch below would never fire, `paused` is set).
                            Presence._update(**Presence._paused_presence(ongoing_track, current_pos))
                        else:
                            Presence._update(**Presence._playing_presence(ongoing_track))
                    Presence.currentTrack = ongoing_track
                else:
                    if ongoing_track['success'] and ongoing_track["playback"] != PlaybackStatus.Playing.name and not Presence.paused:
                        Presence.paused = True
                        log(f"Track {ongoing_track['label']} on pause", LogType.Update_Status)
                        Presence._update(**Presence._paused_presence(ongoing_track, current_pos))
                    elif ongoing_track['success'] and ongoing_track["playback"] == PlaybackStatus.Playing.name and Presence.paused:
                        log(f"Track {ongoing_track['label']} off pause.", LogType.Update_Status)
                        Presence.paused = False
                        Presence._update(**Presence._playing_presence(ongoing_track))
                    elif ongoing_track['success'] and ongoing_track["playback"] == PlaybackStatus.Playing.name and seeked:
                        # Force a fresh timestamp update immediately on each seek.
                        Presence._update(**Presence._playing_presence(ongoing_track))

                if (
                    Presence._name_retry_at
                    and time.monotonic() >= Presence._name_retry_at
                    and ongoing_track.get('source') == 'phone'
                ):
                    Presence._name_retry_at = 0.0
                    if Presence._name_override_active():
                        if ongoing_track['playback'] == PlaybackStatus.Playing.name:
                            Presence._update(**Presence._playing_presence(ongoing_track))
                        else:
                            Presence._update(**Presence._paused_presence(ongoing_track, current_pos))

                # Keep the published state fresh (position, playback status) so that
                # readers such as the GUI do not see the values from the track start.
                if Presence.running:
                    Presence.currentTrack = ongoing_track
                Presence.last_presence_position = current_pos
                Presence.last_presence_track = ongoing_track.get('label')
                error_streak = 0
                time.sleep(PRESENCE_POLL_INTERVAL)
            except pypresence.exceptions.PipeClosed:
                Presence.discord_was_closed()
            except Exception as e:
                # Back off instead of retrying every iteration: without a sleep here a
                # persistent failure spun the CPU at 100% and flooded the log.
                error_streak += 1
                if error_streak == 1 or error_streak % 40 == 0:
                    log(f"Presence class stopped for a reason: {e}", LogType.Error)
                time.sleep(min(5.0, PRESENCE_POLL_INTERVAL * (2 ** min(error_streak, 5))))
        # Cleanup (rpc close, state reset) happens in Presence._finish() via start().

    # Метод для получения информации о текущем треке.
    @staticmethod
    def _build_local_media_track(artist, title, position, playback, duration=None):
        """
        Build a Discord presence directly from Windows MediaSession metadata.
        Used for personal/uploaded Yandex Music tracks that are not found in the
        public Yandex catalog search.
        """
        duration_seconds = 0
        try:
            if duration is not None:
                duration_seconds = max(
                    0,
                    int(duration.total_seconds())
                )
        except Exception:
            duration_seconds = 0

        # We cannot turn a MediaSession thumbnail into a Discord-hosted asset
        # without an upload server. The generic paused/playing indicator remains
        # truthful; if the track is also present in the public catalog, the normal
        # path above still provides the real Yandex artwork.
        local_track = {
            'success': True,
            'title': Single_char(TrimString(title, 40)),
            'artist': Single_char(TrimString(artist, 40)),
            'album': Single_char(TrimString(title, 25)),
            'label': TrimString(f"{artist} - {title}", 50),
            'link': '',
            'durationSec': duration_seconds,
            'formatted_duration': format_duration(duration_seconds * 1000)
                if duration_seconds > 0 else "--:--",
            'start-time': position,
            'playback': playback,
            'og-image': None,
            'local_media': True
        }
        # Must be the module-level variable, otherwise getTrack() re-searches the
        # Yandex catalog on every poll for tracks that are not in it.
        global name_prev
        name_prev = f"{artist} - {title}"
        return local_track

    _phone_cache = {}

    @staticmethod
    def _resolve_phone_track(snap):
        """Catalog data (artist, album, cover, link) for the phone's current track, cached."""
        track_id = snap['track_id']
        entry = Presence._phone_cache.get(track_id)
        now = time.monotonic()
        if entry is not None and (not entry.get('retry_at') or now < entry['retry_at']):
            return entry['info']

        info = None
        try:
            tracks = Presence.client.tracks([track_id]) if Presence.client else None
            track = tracks[0] if tracks else None
            if track is not None:
                artists = ', '.join(track.artists_name())
                album = track.albums[0] if track.albums else None
                link = ''
                try:
                    ids = track.trackId.split(":")
                    if len(ids) > 1:
                        link = f"https://music.yandex.ru/album/{ids[1]}/track/{ids[0]}/"
                except Exception:
                    pass
                info = {
                    'success': True,
                    'title': Single_char(TrimString(track.title, 40)),
                    'artist': Single_char(TrimString(artists, 40)) if artists else
                              ("Unknown artist" if language_config == LanguageConfig.ENGLISH else "Неизвестный исполнитель"),
                    'album': Single_char(TrimString(album.title, 25)) if album else Single_char(TrimString(track.title, 25)),
                    'label': TrimString(f"{artists} - {track.title}", 50),
                    'link': link,
                    'durationSec': (track.duration_ms or 0) // 1000,
                    'formatted_duration': format_duration(track.duration_ms or 0),
                    'og-image': ("https://" + track.og_image[:-2] + "400x400") if track.og_image else None,
                }
        except Exception as e:
            log_throttled(f"phone-resolve:{track_id}", f"Phone mode: could not look up track {track_id} in the catalog: {e}", LogType.Default)

        retry_at = None
        if info is None:
            # Not in the public catalog (or the lookup failed): publish what Ynison gave us
            # and try the catalog again in a while.
            title = snap.get('track_title') or "Unknown title"
            duration = int(snap['duration_ms'] // 1000)
            info = {
                'success': True,
                'title': Single_char(TrimString(title, 40)),
                'artist': "Unknown artist" if language_config == LanguageConfig.ENGLISH else "Неизвестный исполнитель",
                'album': Single_char(TrimString(title, 25)),
                'label': TrimString(title, 50),
                'link': '',
                'durationSec': duration,
                'formatted_duration': format_duration(duration * 1000) if duration > 0 else "--:--",
                'og-image': None,
            }
            retry_at = now + 15.0

        if len(Presence._phone_cache) > 50:
            Presence._phone_cache.clear()
        Presence._phone_cache[track_id] = {'info': info, 'retry_at': retry_at}
        return info

    @staticmethod
    def _pc_playing() -> bool:
        """True if Yandex Music on this PC is playing right now (Windows Media Session)."""
        try:
            info = run_async(get_media_info(), timeout=10)
            return bool(info) and info.get('playback_status') == PlaybackStatus.Playing.name
        except Exception:
            return False

    @staticmethod
    def getPhoneTrack():
        """The track playing on the phone in the same shape as getTrack(), or None.

        None when phone mode is off/unavailable, the active device is not a phone, it is
        offline, or it claims to be playing long after the track must have ended.
        """
        snap = PhoneWatcher.state
        if (
            not snap
            or not snap['track_id']
            or snap['device_type'] not in PHONE_DEVICE_TYPES
            or snap['device_offline']
        ):
            return None

        position = phone_live_position(snap)
        duration = snap['duration_ms'] / 1000.0
        paused = snap['paused']
        if not paused and duration > 0:
            if snap['repeat_one']:
                position = fold_to_lap(position, duration)
            elif position > duration + PHONE_END_GRACE_SECONDS:
                return None  # nobody is really playing any more
            else:
                position = min(position, duration)

        track = dict(Presence._resolve_phone_track(snap))
        if not track.get('durationSec') and duration > 0:
            track['durationSec'] = int(duration)
            track['formatted_duration'] = format_duration(int(duration * 1000))
        track.update({
            'start-time': timedelta(seconds=position),
            'playback': PlaybackStatus.Paused.name if paused else PlaybackStatus.Playing.name,
            'source': 'phone',
            'device': snap.get('device_title') or '',
        })
        return track

    @staticmethod
    def getTrack() -> dict:
        global name_prev, strong_find
        try:
            current_media_info = run_async(get_media_info(), timeout=10)

            if not current_media_info:
                log("No media information returned from get_media_info", LogType.Error)
                return {'success': False}
            global media_metadata_miss_count
            artist = current_media_info.get("artist", "").strip()
            title = current_media_info.get("title", "").strip()
            position = current_media_info['position']

            # On startup Windows Media Session can briefly expose a stale 0:00
            # timeline even though Yandex Music is already playing further into
            # the track. Do not publish that stale position as the Discord start.
            # Take one fresh timeline sample before the first-ever RPC update.
            if (
                Presence.currentTrack is None
                and current_media_info.get("playback_status") == PlaybackStatus.Playing.name
                and position.total_seconds() <= 1.0
            ):
                try:
                    # getTrack() is synchronous, so this MUST NOT use `await`.
                    # Windows Media Session may need a short moment to expose the
                    # real position of an already-playing Yandex Music track.
                    time.sleep(0.45)
                    fresh_media_info = run_async(get_media_info(), timeout=10)
                    if fresh_media_info:
                        fresh_position = fresh_media_info.get("position")
                        fresh_status = fresh_media_info.get("playback_status")
                        if (
                            fresh_position is not None
                            and fresh_status == PlaybackStatus.Playing.name
                            and fresh_position.total_seconds() > position.total_seconds()
                        ):
                            position = fresh_position
                            current_media_info["playback_status"] = fresh_status
                            log(
                                f"Startup timeline refreshed: {position.total_seconds():.2f}s",
                                LogType.Update_Status
                            )
                except Exception as e:
                    log(f"Startup timeline refresh skipped: {e}", LogType.Default)

            if not artist or not title:
                media_metadata_miss_count += 1

                # One or several empty Windows metadata samples are normal during
                # Yandex Music transitions. Keep the last valid RPC instead of
                # clearing it or producing an error on every poll.
                if media_metadata_miss_count < MEDIA_METADATA_GRACE:
                    if Presence.currentTrack is not None:
                        currentTrack_copy = Presence.currentTrack.copy()
                        currentTrack_copy["start-time"] = position
                        currentTrack_copy["playback"] = current_media_info.get(
                            "playback_status",
                            PlaybackStatus.Paused.name
                        )
                        return currentTrack_copy

                    return {'success': False}

                # Only log after the grace period is exceeded, and don't spam:
                log(
                    "Yandex MediaProperties still incomplete after "
                    f"{MEDIA_METADATA_GRACE} polls; keeping the last valid state. "
                    f"Active app={current_media_info.get('app_name', 'Unknown App')} "
                    f"title={current_media_info.get('session_title', 'Unknown Title')}",
                    LogType.Default
                )
                if Presence.currentTrack is not None:
                    currentTrack_copy = Presence.currentTrack.copy()
                    currentTrack_copy["start-time"] = position
                    currentTrack_copy["playback"] = current_media_info.get(
                        "playback_status",
                        PlaybackStatus.Paused.name
                    )
                    return currentTrack_copy
                return {'success': False}

            media_metadata_miss_count = 0
            name_current = artist + " - " + title
            if str(name_current) != name_prev:
                log("Now listening to " + name_current)
            else: #Если песня уже играет, то не нужно ее искать повторно. Просто вернем её с актуальным статусом паузы и позиции.
                if Presence.currentTrack is None:
                    return {'success': False}
                currentTrack_copy = Presence.currentTrack.copy()
                currentTrack_copy["start-time"] = position
                currentTrack_copy["playback"] = current_media_info['playback_status']
                return currentTrack_copy

            # Store the name only after a track was successfully resolved.
            # This allows retries when Windows briefly reports an incomplete/new session.
            # Первая попытка — без апострофа
            search = Presence.client.search(name_current.replace("'", " "), True, "all", 0, False)

            # Если не нашли — вторая попытка с оригинальным именем
            if search.tracks is None:
                search = Presence.client.search(name_current, True, "all", 0, False)
            if search.tracks is None:
                # The track can be a personal/uploaded Yandex Music file that is
                # not present in Yandex's public catalog search. In that case we
                # still have valid Windows MediaSession metadata and should publish
                # it instead of clearing the RPC.
                log(
                    f"Track not found in Yandex catalog; using MediaSession metadata: "
                    f"{artist} - {title}",
                    LogType.Default
                )
                return Presence._build_local_media_track(
                    artist=artist,
                    title=title,
                    position=position,
                    playback=current_media_info['playback_status'],
                    duration=current_media_info.get('duration')
                )

            finalTrack = None
            debugStr = []
            for index, trackFromSearch in enumerate(search.tracks.results[:5], start=1): #Из поиска проверяем первые 5 результатов
                if trackFromSearch.type not in ['music', 'track', 'podcast_episode']:
                    debugStr.append(f"[WinYandexMusicRPC] -> The result #{index} has the wrong type.")

                # Авторы могут отличатся положением, поэтому делаем все возможные варианты их порядка.
                artists = trackFromSearch.artists_name()
                if len(artists) <= 4:
                    all_variants = [list(variant) for variant in permutations(artists)]
                    findTrackNames = []
                    for variant in all_variants:
                        findTrackNames.append(', '.join([str(elem) for elem in variant]) + " - " + trackFromSearch.title)
                else:
                    findTrackNames = []
                    findTrackNames.append(', '.join(artists) + " - " + trackFromSearch.title)

                # Также может отличаться регистр, так что приведём всё в один регистр.
                boolNameCorrect = any(name_current.lower() == element.lower() for element in findTrackNames)

                if strong_find and not boolNameCorrect: #если strong_find и название трека не совпадает, продолжаем поиск
                    findTrackName = ', '.join([str(elem) for elem in trackFromSearch.artists_name()]) + " - " + trackFromSearch.title
                    debugStr.append(f"[WinYandexMusicRPC] -> The result #{index} has the wrong title. Now play: {name_current}. But we find: {findTrackName}")
                    continue
                else: #иначе трек найден
                    finalTrack = trackFromSearch
                    break

            if finalTrack is None:
                print('\n'.join(debugStr))
                log(
                    f"Can't find the song in Yandex catalog (strong_find): {name_current}. "
                    "Falling back to Windows MediaSession metadata.",
                    LogType.Default
                )
                return Presence._build_local_media_track(
                    artist=artist,
                    title=title,
                    position=position,
                    playback=current_media_info['playback_status'],
                    duration=current_media_info.get('duration')
                )

            name_prev = str(name_current)
            track = finalTrack
            trackId = track.trackId.split(":")
            if track:
                return {
                    'success': True,
                    'title': Single_char(TrimString(track.title, 40)),
                    'artist': Single_char(TrimString(f"{', '.join(track.artists_name())}",40)),
                    'album':    Single_char(TrimString(track.albums[0].title,25)),
                    'label': TrimString(f"{', '.join(track.artists_name())} - {track.title}",50),
                    'link': f"https://music.yandex.ru/album/{trackId[1]}/track/{trackId[0]}/",
                    'durationSec': track.duration_ms // 1000,
                    'formatted_duration': format_duration(track.duration_ms),
                    'start-time': position,
                    'playback': current_media_info['playback_status'],
                    'og-image': "https://" + track.og_image[:-2] + "400x400"
                }
        except asyncio.TimeoutError:
            log("Timeout: get_media_info() took more than 10 seconds", LogType.Error)
        except Exception as exception:
            Handle_exception(exception)
            return {'success': False}

def format_duration(duration_ms):
    total_seconds = duration_ms // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60

    # Форматирование строки
    return f"{minutes}:{seconds:02}"

# ВНИМАНИЕ!
# ДЛЯ ТЕКСТА КНОПКИ ЕСТЬ ОГРАНИЧЕНИЕ В 32 БАЙТА. КИРИЛЛИЦА СЧИТАЕТСЯ ЗА 2 БАЙТА.
# ЕСЛИ ПРЕВЫСИТЬ ЛИМИТ ТО DISCORD RPC НЕ БУДЕТ ВИДЕН ДРУГИМ ПОЛЬЗОВАТЕЛЯМ!
def build_buttons(url):
    buttons = []
    if button_config == ButtonConfig.YANDEX_MUSIC_WEB:
        buttons.append({'label': 'Listen on Yandex Music' if language_config == LanguageConfig.ENGLISH else 'Откр. в браузере', 'url': url})
    elif button_config == ButtonConfig.YANDEX_MUSIC_APP:
        deep_link = extract_deep_link(url)
        buttons.append({'label': 'Listen on Yandex Music (in App)' if language_config == LanguageConfig.ENGLISH else 'Откр. в прилож.', 'url': deep_link})
    elif button_config == ButtonConfig.BOTH:
        buttons.append({'label': 'Listen on Yandex Music (Web)' if language_config == LanguageConfig.ENGLISH else 'Откр. в браузере', 'url': url})
        deep_link = extract_deep_link(url)
        buttons.append({'label': 'Listen on Yandex Music (App)' if language_config == LanguageConfig.ENGLISH else 'Откр. в прилож.', 'url': deep_link})

    for button in buttons:
        label = button['label']
        if len(label.encode('utf-8')) > 32:
            raise ValueError(f"Label '{label}' exceeds 32 bytes")
    return buttons

def extract_deep_link(url):
    pattern = r"https://music.yandex.ru/album/(\d+)/track/(\d+)"
    match = re.match(pattern, url)

    if match:
        album_id, track_id = match.groups()
        share_track_path = f"album/{album_id}/track/{track_id}"
        deep_share_track_url = "yandexmusic://" + share_track_path
        return deep_share_track_url
    else:
        return None

def Handle_exception(exception): # Обработка json ошибок из Yandex Music
    # When Windows temporarily exposes no Media Session (especially after long
    # idle periods), get_media_info() raises this expected condition on every poll.
    # Do not spam the console; Presence.start() handles the transition once.
    if str(exception) == 'The music is not playing right now.':
        return

    # The same failure repeats on every poll (4 times a second); report it once in a while.
    _log = lambda text, type=LogType.Default: log_throttled(f"exc:{exception}", text, type)

    json_str = str(exception).replace("'", '"')
    match = re.search(r'({.*?})', json_str)
    if match:
        json_str = match.group(1)

    try:
        data = json.loads(json_str)
        error_name = data.get('name')
        if error_name:
            if error_name == 'Unavailable For Legal Reasons':
                _log("You are using Yandex music in a country where it is not available without authorization! Turn off VPN or login using a Yandex token.", LogType.Error)
            elif error_name == 'session-expired':
                _log("Your Yandex token is out of date or incorrect, login again.", LogType.Error)
            else:
                _log(f"Something happened: {exception}", LogType.Error)
        else:
            _log(f"Something happened: {exception}", LogType.Error)
    except Exception:
        _log(f"Something happened: {exception}", LogType.Error)

def WaitAndExit():
    if Is_run_by_exe():
        win32gui.ShowWindow(window, win32con.SW_SHOW)
    Presence.stop()
    input("Press Enter to close the program.\n")
    if Is_run_by_exe():
        win32gui.PostMessage(window, win32con.WM_CLOSE, 0, 0)
    else:
        sys.exit(0)

def TrimString(string, maxChars):
    if len(string) > maxChars:
        return string[:maxChars] + "..."
    else:
        return string

def Single_char(s):
    if len(s) == 1:
        return f'"{s}"'
    return s

class LogType(Enum):
    Default = 0
    Notification = 1
    Error = 2
    Update_Status = 3

_colorama_ready = False
_throttle_last = {}

def log_throttled(key, text, type = None, interval = 60.0):
    """log() that stays silent for `interval` seconds after the same `key` was last logged."""
    now = time.monotonic()
    if now - _throttle_last.get(key, -1e9) >= interval:
        _throttle_last[key] = now
        log(text, LogType.Default if type is None else type)

def log(text, type = LogType.Default):
    global _colorama_ready
    if not _colorama_ready:
        init() #Инициализация colorama (once, not on every message)
        _colorama_ready = True
    # Цвета текста
    red_text = Fore.RED
    yellow_text = Fore.YELLOW
    blue_text = Fore.CYAN
    reset_text = Style.RESET_ALL

    if type == LogType.Notification:
        message_color = yellow_text
    elif type == LogType.Error:
        message_color = red_text
    elif type == LogType.Update_Status:
        message_color = blue_text
    else:
        message_color = reset_text

    print(f"{red_text}[WinYandexMusicRPC] -> {message_color}{text}{reset_text}")


def GetLastVersion(repoUrl):
    try:
        global CURRENT_VERSION
        response = requests.get(repoUrl + '/releases/latest', timeout=5)
        response.raise_for_status()
        latest_version = response.url.split('/')[-1]

        if version.parse(CURRENT_VERSION) < version.parse(latest_version):
            log(f"A new version has been released on GitHub. You are using - {CURRENT_VERSION}. A new version - {latest_version}, you can download it at {repoUrl + '/releases/tag/' + latest_version}", LogType.Notification)
        elif version.parse(CURRENT_VERSION) == version.parse(latest_version):
            log(f"You are using the latest version of the script")
        else:
            log(f"You are using the beta version of the script", LogType.Notification)

    except requests.exceptions.RequestException as e:
        log(f"Error getting latest version: {e}", LogType.Error)


# Функция для переключения состояния strong_find
def toggle_strong_find():
    global strong_find
    strong_find = not strong_find
    config_manager.set_setting('UserSettings', 'strong_find', str(strong_find))  # Сохраняем новое значение
    log(f'Bool strong_find set state: {strong_find}')

def _autostart_command():
    """(target, arguments) that Windows should run at logon."""
    if getattr(sys, 'frozen', False):
        return sys.executable, "--run-through-startup"
    # Running from source: the target must be an interpreter, not the .py file itself.
    script = os.path.abspath(sys.argv[0])
    pythonw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    interpreter = pythonw if os.path.exists(pythonw) else sys.executable
    return interpreter, f'"{script}" --run-through-startup'

# Функция для переключения состояния auto_start_windows
def toggle_auto_start_windows():
    global auto_start_windows
    auto_start_windows = not auto_start_windows
    log(f'Bool auto_start_windows set state: {auto_start_windows}')

    def create_shortcut(target, shortcut_path, description="", arguments=""):
        pythoncom.CoInitialize()  # Инициализируем COM библиотеки
        shell = Dispatch('WScript.Shell')  # Создаем объект для работы с ярлыками
        shortcut = shell.CreateShortcut(shortcut_path)  # Создаем ярлык
        shortcut.TargetPath = target  # Устанавливаем путь к исполняемому файлу
        shortcut.WorkingDirectory = os.path.dirname(target)  # Устанавливаем рабочую директорию
        shortcut.Description = description  # Устанавливаем описание ярлыка
        shortcut.Arguments = arguments
        shortcut.Save()  # Сохраняем ярлык

    def change_setting(tglle: bool): # Выношу в отдельную функцию, чтобы иметь возможность запустить в отдельном потоке,
        if tglle:# ДВА способа добавления в автозапуск. Первый через добавление программы в папку автостарта. Второй через изменение реестра. Оба не требуют админских прав.
            try: # Автозапуск через добавление в папку автозапуска
                exe_path, exe_args = _autostart_command()  # Что именно запускать при входе в Windows
                shortcut_path = os.path.join(os.getenv('APPDATA'), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup', 'YaMusicRPC.lnk')  # Определяем путь для ярлыка в автозагрузке
                create_shortcut(exe_path, shortcut_path, arguments=exe_args)  # Создаем ярлык в автозагрузке
            except: # Автозапуск через изменение в реестре
                exe_path = f'"{_autostart_command()[0]}" {_autostart_command()[1]}'
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run', 0, winreg.KEY_SET_VALUE)  # Открываем ключ реестра для автозапуска программ
                winreg.SetValueEx(key, 'YaMusicRPC', 0, winreg.REG_SZ, exe_path)  # Устанавливаем новый параметр в реестре с именем 'YaMusicRPC' и значением пути к исполняемому файлу
                winreg.CloseKey(key)  # Закрываем ключ реестра
        else: # Удаляем оба метода
            # Удаляем ярлык из автозагрузки
            shortcut_path = os.path.join(os.getenv('APPDATA'), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup', 'YaMusicRPC.lnk')
            if os.path.exists(shortcut_path):
                os.remove(shortcut_path)
            # Удаляем запись из реестра
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run', 0, winreg.KEY_ALL_ACCESS)
                winreg.DeleteValue(key, 'YaMusicRPC')
                winreg.CloseKey(key)
            except FileNotFoundError:
                pass


    # COM needs its own thread, but wait for it: callers re-read the autostart state
    # right after this returns and would otherwise see the old value.
    worker = threading.Thread(target=change_setting, args=[auto_start_windows])
    worker.start()
    worker.join(10)

def is_in_autostart(): # Функция, которая при запуске программы проверяет, есть ли программа в автозапуске. Используется при подгрузке стартовых параметров

    def is_in_startup():
        shortcut_path = os.path.join(os.getenv('APPDATA'), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup', 'YaMusicRPC.lnk')  # Определяем путь к ярлыку
        return os.path.exists(shortcut_path)  # Проверяем, существует ли ярлык в папке автозагрузки

    def is_in_registry():
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_READ)  # Открываем ключ реестра для чтения
            winreg.QueryValueEx(key, 'YaMusicRPC')  # Проверяем, существует ли параметр в реестре
            winreg.CloseKey(key)  # Закрываем ключ реестра
            return True
        except FileNotFoundError:
            return False  # Если параметр не найден, возвращаем False

    return is_in_startup() or is_in_registry()  # Возвращаем True, если программа присутствует в автозапуске


def toggle_console():
    if win32gui.IsWindowVisible(window):
        win32gui.ShowWindow(window, win32con.SW_HIDE)
    else:
        Show_Console_Permanent()

# Действия для кнопок
def tray_click(icon, query):
    match str(query):
        case "GitHub":
            webbrowser.open(REPO_URL,  new=2)

        case "Exit":
            Presence.stop()
            icon.stop()
            win32gui.PostMessage(window, win32con.WM_CLOSE, 0, 0)

def get_account_name():
    try:
        user_info = Presence.client.me.account
        account_name = user_info.display_name
        if not account_name:
            return f"None"
        return account_name
    except exceptions.UnauthorizedError:
        return "Invalid token."

    except exceptions.NetworkError:
        return "Network error."

    except Exception as e:
        return f"None"

# Функция для загрузки сохраненных настроек. Если настройки отсутствуют, используются значения по умолчанию из fallback.
def get_saves_settings(fromStart = False):
    global activityType_config
    global button_config
    global language_config
    global auto_start_windows
    global strong_find
    global phone_mode

    auto_start_windows = is_in_autostart()
    activityType_config = config_manager.get_enum_setting('UserSettings', 'activity_type', ActivityTypeConfig, fallback=ActivityTypeConfig.LISTENING)
    button_config = config_manager.get_enum_setting('UserSettings', 'buttons_settings', ButtonConfig, fallback=ButtonConfig.BOTH)
    language_config = config_manager.get_enum_setting('UserSettings', 'language', LanguageConfig, fallback=LanguageConfig.RUSSIAN)

    # Загрузка значения strong_find из конфигурации
    strong_find_str = config_manager.get_setting('UserSettings', 'strong_find', fallback='True')  # По умолчанию 'True'
    strong_find = strong_find_str.lower() == 'true'  # Преобразуем строку в булевое значение
    phone_mode = config_manager.get_setting('UserSettings', 'phone_mode', fallback='True').lower() == 'true'

    if fromStart:
        log(f"Loaded settings: {Style.RESET_ALL}activityType_config = {activityType_config.name}, button_config = {button_config.name}, language_config = {language_config.name}, strong_find = {strong_find}, phone_mode = {phone_mode}, selected_session = {config_manager.get_selected_session()}", LogType.Update_Status)

_bg_loop = None
_bg_loop_lock = threading.Lock()

def _get_bg_loop():
    """One long-lived event loop in a daemon thread, shared by every run_async() caller.

    Creating a fresh loop per call (4 per second) was wasteful and, worse, made the
    timeout impossible to enforce.
    """
    global _bg_loop
    with _bg_loop_lock:
        if _bg_loop is None or _bg_loop.is_closed():
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, name="wym-asyncio", daemon=True).start()
            _bg_loop = loop
        return _bg_loop

def run_async(coro, timeout=15):
    """
    Безопасно запускает асинхронную корутину из синхронного контекста.
    Raises asyncio.TimeoutError if it does not finish within `timeout` seconds.
    """
    future = asyncio.run_coroutine_threadsafe(coro, _get_bg_loop())
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        future.cancel()
        raise asyncio.TimeoutError()

def create_session_toggle_menu(icon):
    try:
        session_ids = run_async(get_session_ids(), timeout=10)
    except Exception as e:
        log(f"Failed to get session IDs for tray menu: {e}", LogType.Error)
        session_ids = []

    menu_items = []

    # Кнопка обновления
    menu_items.append(
        pystray.MenuItem(
            'Update List',
            lambda item: update_tray()
        )
    )

    menu_items.append(pystray.Menu.SEPARATOR)

    selected_session = config_manager.get_selected_session()
    session_ids_set = set(session_ids)

    def set_automatic(item):
        log("Selected session: Automatic", LogType.Default)
        config_manager.set_selected_session("Automatic")

    def is_automatic(item):
        return config_manager.get_selected_session() == "Automatic"

    menu_items.append(
        pystray.MenuItem(
            "Automatic",
            set_automatic,
            checked=is_automatic,
            radio=True
        )
    )

    # Добавляем активные сессии
    for session_id in session_ids:
        def make_action(sid):
            def action(item):
                log(f"Selected session: {sid}", LogType.Default)
                config_manager.set_selected_session(sid)
            return action

        def make_checked(sid):
            return lambda item: config_manager.get_selected_session() == sid

        menu_items.append(
            pystray.MenuItem(
                session_id,
                make_action(session_id),
                checked=make_checked(session_id),
                radio=True
            )
        )

    # Если сохранённая сессия отсутствует в текущем списке - добавить её как "inactive"
    if selected_session and selected_session not in session_ids_set and selected_session != "Automatic":
        def make_action_inactive():
            return lambda item: config_manager.set_selected_session(selected_session)

        def make_checked_inactive():
            return lambda item: config_manager.get_selected_session() == selected_session

        menu_items.append(
            pystray.MenuItem(
                f"{selected_session} (inactive)",
                make_action_inactive(),
                checked=make_checked_inactive(),
                radio=True
            )
        )

    return pystray.Menu(*menu_items)


# Функция для создания меню на основе переданных параметров
def create_enum_menu(enum_class, get_setting_func, set_setting_func):
    return pystray.Menu(
        *(pystray.MenuItem(value.name,
                           lambda item, value=value: set_setting_func(value),
                           checked=lambda item, value=value: get_setting_func('UserSettings', enum_class) == value)
          for value in enum_class)
    )

def convert_to_enum(enum_class, value):
    value_str = str(value)
    try:
        return enum_class[value_str]
    except KeyError:
        log(f"Invalid type: {value_str}")
        return None

# Функции для установки значений
def set_activity_type(value):
    value = convert_to_enum(ActivityTypeConfig, value)
    config_manager.set_enum_setting('UserSettings', 'activity_type', value)
    log(f"Setting has been changed : activity_type to {value.name}")
    get_saves_settings()
    Presence.need_restart()

def set_button_config(value):
    value = convert_to_enum(ButtonConfig, value)
    config_manager.set_enum_setting('UserSettings', 'buttons_settings', value)
    log(f"Setting has been changed : buttons_settings to {value.name}")
    get_saves_settings()
    Presence.need_restart()

def set_language_config(value):
    value = convert_to_enum(LanguageConfig, value)
    config_manager.set_enum_setting('UserSettings', 'language', value)
    log(f"Setting has been changed : language to {value.name}")
    get_saves_settings()
    Presence.need_restart()

# Функция для создания настроек меню RPC
def create_rpc_settings_menu():
    activity_type_menu = create_enum_menu(ActivityTypeConfig, lambda section, enum_type: config_manager.get_enum_setting(section, 'activity_type', enum_type), set_activity_type)
    button_config_menu = create_enum_menu(ButtonConfig, lambda section, enum_type: config_manager.get_enum_setting(section, 'buttons_settings', enum_type), set_button_config)
    language_config_menu = create_enum_menu(LanguageConfig, lambda section, enum_type: config_manager.get_enum_setting(section, 'language', enum_type), set_language_config)

    return pystray.Menu(
        pystray.MenuItem('Activity Type', activity_type_menu),
        pystray.MenuItem('RPC Buttons', button_config_menu),
        pystray.MenuItem("RPC Language", language_config_menu),
    )

# Функция для создания иконки с меню
def build_tray_menu(icon=None):
    account_name = get_account_name()
    rpcSettingsMenu = create_rpc_settings_menu()

    settingsMenu = pystray.Menu(
        pystray.MenuItem(f"Logged in as - {account_name}", lambda: None, enabled=False),
        pystray.MenuItem('Login to account...', lambda: Init_yaToken(True)),
        pystray.MenuItem('Toggle strong_find', toggle_strong_find, checked=lambda item: strong_find),
    )

    return pystray.Menu(
        pystray.MenuItem("Hide/Show Console", toggle_console, default=True),
        pystray.MenuItem('Start with Windows', toggle_auto_start_windows, checked=lambda item: auto_start_windows),
        pystray.MenuItem("Yandex settings", settingsMenu),
        pystray.MenuItem("RPC settings", rpcSettingsMenu),
        pystray.MenuItem("Select Application", create_session_toggle_menu(icon) if icon else pystray.MenuItem("Loading...", lambda: None, enabled=False)),
        pystray.MenuItem("GitHub", tray_click),
        pystray.MenuItem("Exit", tray_click)
    )

def update_tray():
    global iconTray
    # iconTray is `True` until tray_thread() creates the icon (and stays so in the GUI,
    # which has no pystray icon); assigning .menu on a bool raised AttributeError.
    if isinstance(iconTray, pystray.Icon):
        iconTray.menu = build_tray_menu(iconTray)

# Функция для запуска иконки
def tray_thread(initial_menu):
    global iconTray
    tray_image = Image.open(Get_IconPath())
    icon = pystray.Icon("WinYandexMusicRPC", tray_image, "WinYandexMusicRPC", menu=initial_menu)
    iconTray = icon

    icon.run_detached()
    update_tray()

def Is_already_running():
    hwnd = win32gui.FindWindow(None, "WinYandexMusicRPC - Console")
    if hwnd:
        return True
    return False

def Is_windows_11():
    return sys.getwindowsversion().build >= 22000


def Check_conhost():
    if Is_windows_11():  # Windows 11 имеет консоль, которую нельзя свернуть в трей, поэтому мы используем conhost
        if '--run-through-conhost' not in sys.argv:  # Запущен ли скрипт уже через conhost
            Run_by_startup_without_conhost()
            print("Wait a few seconds for the script to load...")
            script_path = os.path.abspath(sys.argv[0])
            first_pid = os.getpid()
            subprocess.Popen(['start', '/min', 'conhost.exe', script_path, '--run-through-conhost', str(first_pid)] + sys.argv[1:], shell=True)
            event = threading.Event()
            event.wait()

    if '--run-through-launcher' in sys.argv or '--run-through-conhost' in sys.argv:  # Запущен ли скрипт уже через conhost или лаунчер
        if len(sys.argv) > 2:
            first_pid = int(sys.argv[2])
            try:
                parent_process = psutil.Process(first_pid)
                for child in parent_process.children(recursive=True):
                    child.terminate()
                parent_process.terminate()
                parent_process.wait(timeout=3)
            except Exception:
                print(f"Couldnt close the process: {first_pid}")

def Show_Console_Permanent():
    try:
        win32gui.ShowWindow(window, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(window)
    except Exception as e:
        log(f"We cant show the window {e}",LogType.Error)

def Check_run_by_startup():
    # Если приложение запущено через автозагрузку, скрываем окно консоли сразу.
    # Если приложение запущено вручную, показываем окно консоли на 3 секунды и затем сворачиваем.
    if window:
        if '--run-through-startup' not in sys.argv:
            Show_Console_Permanent()
            log("Minimize to system tray in 3 seconds...")
            time.sleep(3)
        win32gui.ShowWindow(window, win32con.SW_HIDE)
    else:
        log("Console window not found", LogType.Error)

def Run_by_startup_without_conhost():
    # Функция для автозагрузки без лаунчера (Windows 11), скрывает окно консоли при запуске через автозагрузку.
    window = win32console.GetConsoleWindow()
    if window:
        if '--run-through-startup' in sys.argv:
            win32gui.ShowWindow(window, win32con.SW_HIDE)
    else:
        log("Console window not found", LogType.Error)

def Disable_close_button():
    hwnd = win32console.GetConsoleWindow()
    if hwnd:
        hMenu = win32gui.GetSystemMenu(hwnd, False)
        if hMenu:
            win32gui.DeleteMenu(hMenu, win32con.SC_CLOSE, win32con.MF_BYCOMMAND)

def Set_ConsoleMode():
    hStdin = win32console.GetStdHandle(win32console.STD_INPUT_HANDLE)
    mode = hStdin.GetConsoleMode()
    # Отключить ENABLE_QUICK_EDIT_MODE, чтобы запретить выделение текста
    new_mode = mode & ~0x0040
    hStdin.SetConsoleMode(new_mode)

def Is_run_by_exe():
    script_path = os.path.abspath(sys.argv[0])
    if script_path.endswith('.exe'):
        return True
    else:
        return False

def Blur_string(s: str) -> str:
    """Describe a secret for the journal without revealing any part of it."""
    if not s:
        return ''
    return f"<hidden, {len(s)} characters>"

def Remove_yaToken_From_Memmory():
    if keyring.get_password('WinYandexMusicRPC', 'token') is not None:
        keyring.delete_password('WinYandexMusicRPC', 'token')
        log("Old token has been removed from memory.", LogType.Update_Status)

def update_token_task(icon_path, result_queue):
    # Imported here, in the login child process only: it drags in Qt WebEngine, which
    # the main process (and the GUI's startup time / memory) does not need.
    import getToken
    result = getToken.get_yandex_music_token(icon_path)
    result_queue.put(result)

def Init_yaToken(forceGet = False):
    global ya_token
    token = str()

    # Already logged in with a saved token: do not repeat the network round trip.
    if not forceGet and ya_token and Presence.client:
        return

    if forceGet:
        try:
            # The old token stays in the keyring until a new one is really received:
            # cancelling or failing the login must not leave the user without a token.
            process = multiprocessing.Process(target=update_token_task, args=(Get_IconPath(), result_queue))
            process.start()
            process.join()
            try:
                token = result_queue.get(timeout=5)
            except queue.Empty:
                token = None
            if token is not None and len(token) > 10:
                keyring.set_password('WinYandexMusicRPC', 'token', token)
                log(f"Successfully received the token: {Blur_string(token)}", LogType.Update_Status)
            else:
                log("Login was cancelled or no token was received; the saved token is unchanged.", LogType.Error)
        except Exception as exception:
            log(f"Something happened when trying to initialize token: {exception}", LogType.Error)
    else:
        if not ya_token:
            try:
                token = keyring.get_password('WinYandexMusicRPC', 'token')
                if token:
                    log(f"Loaded token: {Blur_string(token)}", LogType.Update_Status)
            except Exception as exception:
                log(f"Something happened when trying to initialize token: {exception}", LogType.Error)
        else:
            token = ya_token
            log(f"Loaded token from script: {Blur_string(token)}", LogType.Update_Status)

    if token is not None and len(token) > 10:
        ya_token = token
        try:
            Presence.client = Client(token=ya_token).init()
            log(f"Logged in as - {get_account_name()}", LogType.Update_Status)
            if Is_run_by_exe():
                update_tray()
        except Exception as exception:
            Handle_exception(exception)
    if not Presence.client:
        log("Continue without a token...", LogType.Default)



def Get_IconPath():
    try:
        # Установка пути к ресурсам
        if getattr(sys, 'frozen', False):  # Запуск с помощью PyInstaller
            resources_path = sys._MEIPASS
        else:
            resources_path = os.path.dirname(os.path.abspath(__file__))

        return f"{resources_path}/assets/YMRPC_ico.ico"
    except Exception:
        return None



if __name__ == '__main__':
    multiprocessing.freeze_support()
    try:
        if Is_run_by_exe():
            Check_conhost()
            Set_ConsoleMode()
            log("Launched. Check the actual version...")
            GetLastVersion(REPO_URL)
            # Загрузка настроек
            get_saves_settings(True)
            # Запуск потока для трея
            mainMenu = build_tray_menu()
            icon_thread = threading.Thread(target=tray_thread, args=(mainMenu,))
            icon_thread.daemon = True
            icon_thread.start()

            # Получение окна консоли
            window = win32console.GetConsoleWindow()

            if Is_already_running():
                log("WinYandexMusicRPC is already running.", LogType.Error)
                Show_Console_Permanent()
                WaitAndExit()

            # Установка заголовка окна консоли
            win32console.SetConsoleTitle("WinYandexMusicRPC - Console")

            # Отключение кнопки закрытия консоли
            Disable_close_button()
            Check_run_by_startup()
        else: # Запуск без exe (например в visual studio code)
            get_saves_settings(True) # Загрузка настроек
            log("Launched without minimizing to tray and other and other gui functions")

        # Проверка наличия токена в памяти
        Init_yaToken(False)

        # Запуск Presence
        Presence.start()

    except KeyboardInterrupt:
        log("Keyboard interrupt received, stopping...")
        Presence.stop()
