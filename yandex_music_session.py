"""Recognize Yandex Music desktop sessions without relying on the UI language."""

import re
import sys
from functools import cache
from pathlib import Path, PureWindowsPath

_APP_ID = "ru.yandex.desktop.music"
_LOCALIZED_EXE = "яндекс музыка.exe"
_PROTOCOL_COMMAND_KEY = r"yandexmusic\shell\open\command"
# Require an executable path followed by the URL placeholder. Ignore extra
# arguments and ambiguous unquoted paths containing spaces.
_PROTOCOL_COMMAND = re.compile(r'\s*(?:"([^"\r\n]+)"|([^\s"]+))\s+(?:"%1"|%1)\s*')
_LEGACY_MARKERS = (
    "yandexmusic",
    "yandex.music",
    "yandex-music",
    "yandex_music",
    "yandex music",
    "ru.yandex.music",
)


def _parse_protocol_executable(command: str) -> PureWindowsPath | None:
    match = _PROTOCOL_COMMAND.fullmatch(command)
    if match is None:
        return None

    path = match[1] or match[2]
    executable = PureWindowsPath(path)
    # Only accept ordinary drive-letter paths, not relative, UNC or device paths.
    if not executable.is_absolute() or not re.fullmatch(r"[A-Za-z]:", executable.drive):
        return None
    if re.search(r'[<>:"|?*\x00-\x1f]', path[2:]):
        return None
    return executable if executable.suffix.lower() == ".exe" else None


@cache
def _registered_executable() -> PureWindowsPath | None:
    """Cache the registered yandexmusic:// executable for this RPC process."""
    if sys.platform != "win32":
        return None

    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, _PROTOCOL_COMMAND_KEY) as key:
            command, value_type = winreg.QueryValueEx(key, "")
        if not isinstance(command, str) or value_type not in (
            winreg.REG_SZ,
            winreg.REG_EXPAND_SZ,
        ):
            return None
        if value_type == winreg.REG_EXPAND_SZ:
            command = winreg.ExpandEnvironmentStrings(command)

        executable = _parse_protocol_executable(command)
        if executable is not None and Path(executable).is_file():
            return executable
    except OSError:
        # Missing registration, denied access, or an unavailable executable.
        return None
    return None


def is_yandex_music_source(source_id: str | None) -> bool:
    """Match a GSMTC source ID, not an executable signature or browser tab."""
    normalized = (source_id or "").strip().lower()
    if not normalized:
        return False
    if normalized == _APP_ID:
        return True

    source = PureWindowsPath(normalized)
    if source.suffix == ".exe":
        registered = _registered_executable()
        if registered is not None:
            if source.is_absolute() and source == registered:
                return True
            if normalized == registered.name.lower():
                return True
        if normalized == _LOCALIZED_EXE:
            return True

    # Keep compatibility with IDs accepted before the registry lookup.
    return any(marker in normalized for marker in _LEGACY_MARKERS) or (
        "yandex" in normalized and "music" in normalized
    )
