"""Linux and SteamOS (Steam Deck) platform helpers: device detection, Discord Flatpak IPC and MPRIS."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from datetime import timedelta
from functools import cache
from pathlib import Path
from typing import Any

_STEAM_DECK_PRODUCTS = {"jupiter", "galileo"}
_FLATPAK_DISCORD_IDS = (
    "com.discordapp.Discord",
    "com.discordapp.DiscordCanary",
    "com.discordapp.DiscordPTB",
    "dev.vencord.Vesktop",
    "org.equicord.Equibop",
)
_YANDEX_MPRIS_MARKERS = (
    "yandexmusic",
    "yandex-music",
    "yandex_music",
    "yandex.music",
    "yandex music",
    "яндекс музыка",
    "яндекс.музыка",
    "ru.yandex.desktop.music",
)


def get_app_data_dir(app_name: str = "WinYandexMusicRPC") -> str:
    """Return per-user writable data directory on Windows and Linux/SteamOS."""
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return os.path.join(local_app_data, app_name)
    if sys.platform == "win32":
        return os.path.join(".", app_name)
    xdg_data = os.getenv("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(xdg_data, app_name)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""


@cache
def is_steam_deck() -> bool:
    """Return True when running on Valve Steam Deck hardware / SteamOS."""
    if sys.platform == "win32":
        return False

    product = _read_text(Path("/sys/devices/virtual/dmi/id/product_name")).lower()
    vendor = _read_text(Path("/sys/devices/virtual/dmi/id/board_vendor")).lower()
    if product in _STEAM_DECK_PRODUCTS or ("valve" in vendor and "steam" in product):
        return True

    os_release = _read_text(Path("/etc/os-release")).lower()
    return "id=steamos" in os_release or "id=\"steamos\"" in os_release


def find_discord_ipc_socket() -> str | None:
    """Locate Discord IPC socket on Linux, including Flatpak and Snap sandboxes."""
    if sys.platform == "win32":
        return None

    runtime_dir = os.getenv("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    candidates = [Path(runtime_dir) / f"discord-ipc-{i}" for i in range(10)]

    for app_id in _FLATPAK_DISCORD_IDS:
        for i in range(10):
            candidates.append(Path(runtime_dir) / "app" / app_id / f"discord-ipc-{i}")
            candidates.append(Path(runtime_dir) / ".flatpak" / app_id / "xdg-run" / f"discord-ipc-{i}")

    for i in range(10):
        candidates.append(Path(runtime_dir) / "snap.discord" / f"discord-ipc-{i}")

    for candidate in candidates:
        try:
            if candidate.exists() or candidate.is_socket():
                return str(candidate)
        except OSError:
            continue
    return None


def ensure_discord_ipc_env() -> str | None:
    """Ensure pypresence can open Discord IPC socket on SteamOS/Flatpak.

    If Discord runs inside Flatpak, its socket lives under ``$XDG_RUNTIME_DIR/app/<id>/discord-ipc-0``.
    Creating a symlink at ``$XDG_RUNTIME_DIR/discord-ipc-0`` allows unmodified pypresence to connect.
    """
    if sys.platform == "win32":
        return None

    runtime_dir = os.getenv("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    direct_socket = Path(runtime_dir) / "discord-ipc-0"
    if direct_socket.is_socket():
        return str(direct_socket)

    found = find_discord_ipc_socket()
    if not found:
        return None

    found_path = Path(found)
    if found_path == direct_socket:
        return found

    try:
        if direct_socket.is_symlink() and not direct_socket.exists():
            direct_socket.unlink()
        if not direct_socket.exists():
            direct_socket.symlink_to(found_path)
        return str(direct_socket)
    except OSError:
        return found


def is_yandex_music_mpris_player(bus_name: str, identity: str = "", desktop_entry: str = "") -> bool:
    """Return True if an MPRIS bus name/metadata identifies a Yandex Music client."""
    combined = f"{bus_name} {identity} {desktop_entry}".lower()
    if "browser" in combined and "yandex" in combined and "music" not in combined and "музыка" not in combined:
        return False
    return any(marker in combined for marker in _YANDEX_MPRIS_MARKERS)


def _gdbus_call(dest: str, obj_path: str, method: str, *args: str, timeout: float = 2.0) -> str | None:
    cmd = ["gdbus", "call", "--session", "--dest", dest, "--object-path", obj_path, "--method", method, *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _unquote_gvariant_str(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        inner = raw[1:-1]
        return inner.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")
    return raw


def _parse_gvariant_string_prop(output: str | None) -> str:
    if not output:
        return ""
    match = re.search(r"<(['\"])(.*?)\1>", output)
    if match:
        return match.group(2).replace("\\'", "'").replace('\\"', '"')
    return ""


def _parse_gvariant_int_prop(output: str | None) -> int:
    if not output:
        return 0
    match = re.search(r"<(?:int64|uint64|int32|uint32)?\s*(-?\d+)>", output)
    if match:
        return int(match.group(1))
    return 0


def parse_mpris_metadata_text(text: str) -> dict[str, Any]:
    """Parse ``gdbus`` Get('org.mpris.MediaPlayer2.Player', 'Metadata') output."""
    result: dict[str, Any] = {
        "title": "",
        "artist": "",
        "album": "",
        "length_us": 0,
        "art_url": "",
    }
    if not text:
        return result

    title_match = re.search(r"'xesam:title':\s*<(['\"])((?:\\.|(?!\1).)*)\1>", text)
    if title_match:
        result["title"] = _unquote_gvariant_str(title_match.group(1) + title_match.group(2) + title_match.group(1))

    album_match = re.search(r"'xesam:album':\s*<(['\"])((?:\\.|(?!\1).)*)\1>", text)
    if album_match:
        result["album"] = _unquote_gvariant_str(album_match.group(1) + album_match.group(2) + album_match.group(1))

    art_match = re.search(r"'mpris:artUrl':\s*<(['\"])((?:\\.|(?!\1).)*)\1>", text)
    if art_match:
        result["art_url"] = _unquote_gvariant_str(art_match.group(1) + art_match.group(2) + art_match.group(1))

    length_match = re.search(r"'mpris:length':\s*<(?:int64|uint64)?\s*(\d+)>", text)
    if length_match:
        result["length_us"] = int(length_match.group(1))

    artist_block = re.search(r"'xesam:artist':\s*<\[(.*?)\]>", text, re.DOTALL)
    if artist_block:
        artists = re.findall(r"(['\"])((?:\\.|(?!\1).)*)\1", artist_block.group(1))
        cleaned = [_unquote_gvariant_str(q + val + q) for q, val in artists if val.strip()]
        result["artist"] = ", ".join(cleaned)
    else:
        artist_str = re.search(r"'xesam:artist':\s*<(['\"])((?:\\.|(?!\1).)*)\1>", text)
        if artist_str:
            result["artist"] = _unquote_gvariant_str(artist_str.group(1) + artist_str.group(2) + artist_str.group(1))

    return result


def list_mpris_players() -> list[dict[str, str]]:
    """Return active MPRIS D-Bus players as ``[{'bus_name', 'identity', 'desktop_entry', 'playback_status'}]``."""
    if sys.platform == "win32":
        return []

    raw_names = _gdbus_call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus.ListNames")
    if not raw_names:
        return []

    bus_names = re.findall(r"'(org\.mpris\.MediaPlayer2\.[^']+)'", raw_names)
    players: list[dict[str, str]] = []
    for bus_name in bus_names:
        identity = _parse_gvariant_string_prop(
            _gdbus_call(bus_name, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties.Get",
                        "org.mpris.MediaPlayer2", "Identity")
        )
        desktop_entry = _parse_gvariant_string_prop(
            _gdbus_call(bus_name, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties.Get",
                        "org.mpris.MediaPlayer2", "DesktopEntry")
        )
        playback = _parse_gvariant_string_prop(
            _gdbus_call(bus_name, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties.Get",
                        "org.mpris.MediaPlayer2.Player", "PlaybackStatus")
        ) or "Stopped"
        players.append({
            "bus_name": bus_name,
            "identity": identity,
            "desktop_entry": desktop_entry,
            "playback_status": playback,
        })
    return players


def get_mpris_session_ids() -> list[str]:
    """Return display identifiers for available MPRIS players."""
    return [p["identity"] or p["bus_name"] for p in list_mpris_players()]


def get_mpris_media_info(selected_session: str = "Automatic") -> dict[str, Any]:
    """Read current Yandex Music track info via MPRIS on Linux/SteamOS."""
    players = list_mpris_players()
    target: dict[str, str] | None = None

    if selected_session and selected_session != "Automatic":
        for p in players:
            label = p["identity"] or p["bus_name"]
            if (p["bus_name"] == selected_session or label == selected_session) and is_yandex_music_mpris_player(
                p["bus_name"], p["identity"], p["desktop_entry"]
            ):
                target = p
                break
        if not target:
            raise RuntimeError(
                f"Selected session '{selected_session}' is not a Yandex Music MPRIS session or is not available."
            )
    else:
        ym_players = [
            p for p in players if is_yandex_music_mpris_player(p["bus_name"], p["identity"], p["desktop_entry"])
        ]
        if ym_players:
            playing = [p for p in ym_players if p["playback_status"] == "Playing"]
            target = playing[0] if playing else ym_players[0]

    if not target:
        raise RuntimeError("The music is not playing right now.")

    bus = target["bus_name"]
    meta_raw = _gdbus_call(
        bus, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties.Get",
        "org.mpris.MediaPlayer2.Player", "Metadata"
    )
    meta = parse_mpris_metadata_text(meta_raw or "")
    pos_us = _parse_gvariant_int_prop(
        _gdbus_call(bus, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties.Get",
                    "org.mpris.MediaPlayer2.Player", "Position")
    )
    status = target["playback_status"]
    if status not in ("Playing", "Paused", "Stopped"):
        status = "Unknown"

    duration_td = timedelta(microseconds=meta["length_us"]) if meta["length_us"] > 0 else None
    return {
        "artist": meta["artist"],
        "title": meta["title"],
        "album": meta["album"],
        "playback_status": status,
        "position": timedelta(microseconds=max(0, pos_us)),
        "duration": duration_td,
    }


def _autostart_desktop_path() -> Path:
    xdg_config = os.getenv("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(xdg_config) / "autostart" / "WinYandexMusicRPC.desktop"


def is_in_linux_autostart() -> bool:
    return _autostart_desktop_path().is_file()


def set_linux_autostart(enabled: bool, command_line: str) -> None:
    path = _autostart_desktop_path()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=WinYandexMusicRPC\n"
            "Comment=Yandex Music Discord Rich Presence\n"
            f"Exec={command_line}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
    elif path.exists():
        path.unlink()
