import sys
from collections.abc import Iterator
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

import pytest

import yandex_music_session as sessions


@pytest.mark.parametrize(
    ("command", "executable"),
    [
        (
            r'"C:\Program Files\YandexMusic\Яндекс Музыка.exe" "%1"',
            r"C:\Program Files\YandexMusic\Яндекс Музыка.exe",
        ),
        (r"D:\Music\Player.EXE %1", r"D:\Music\Player.EXE"),
    ],
)
def test_parses_protocol_command(command: str, executable: str) -> None:
    assert sessions._parse_protocol_executable(command) == PureWindowsPath(executable)


@pytest.mark.parametrize(
    "command",
    [
        "",
        r'Player.exe "%1"',
        r'"D:Player.exe" "%1"',
        r'"\\server\Music\Player.exe" "%1"',
        r'"\\?\D:\Music\Player.exe" "%1"',
        r'D:\Music Player\Player.exe "%1"',
        r'"D:\Music\Player?.exe" "%1"',
        '"D:\\Music\\Player\x00.exe" "%1"',
        r'"D:\Music\Player.cmd" "%1"',
        r'"D:\Music\Player.exe" --protocol "%1"',
        r'"D:\Music\Player.exe"',
    ],
)
def test_rejects_unsupported_protocol_command(command: str) -> None:
    assert sessions._parse_protocol_executable(command) is None


@dataclass
class FakeRegistry:
    command: str | None = None
    value_type: int = 0
    open_calls: int = 0

    def open_key(self, _root: int, _subkey: str) -> nullcontext[None]:
        self.open_calls += 1
        if self.command is None:
            raise FileNotFoundError
        return nullcontext()

    def query_value(self, _key: None, _value_name: str) -> tuple[str, int]:
        assert self.command is not None
        return self.command, self.value_type


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeRegistry]:
    if sys.platform != "win32":
        pytest.skip("Windows registry API required")

    import winreg

    fake = FakeRegistry()
    monkeypatch.setattr(winreg, "OpenKey", fake.open_key)
    monkeypatch.setattr(winreg, "QueryValueEx", fake.query_value)
    sessions._registered_executable.cache_clear()
    try:
        yield fake
    finally:
        sessions._registered_executable.cache_clear()


def test_missing_registry_key_uses_localized_fallback(registry: FakeRegistry) -> None:
    assert sessions.is_yandex_music_source("Яндекс Музыка.exe")
    assert not sessions.is_yandex_music_source("Other Player.exe")
    assert registry.open_calls == 1


def test_expands_and_caches_an_existing_executable(
    registry: FakeRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import winreg

    executable = tmp_path / "Localized Client.exe"
    executable.touch()
    monkeypatch.setenv("YMRPC_TEST_MUSIC_DIR", str(tmp_path))
    registry.command = r'"%YMRPC_TEST_MUSIC_DIR%\Localized Client.exe" "%1"'
    registry.value_type = winreg.REG_EXPAND_SZ

    assert sessions.is_yandex_music_source(executable.name)
    assert sessions.is_yandex_music_source(str(executable))
    assert registry.open_calls == 1


def test_ignores_registration_pointing_to_missing_executable(
    registry: FakeRegistry, tmp_path: Path
) -> None:
    import winreg

    executable = tmp_path / "Missing Client.exe"
    registry.command = f'"{executable}" "%1"'
    registry.value_type = winreg.REG_SZ

    assert not sessions.is_yandex_music_source(executable.name)


def test_accepts_known_aumid_without_registry_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_lookup() -> PureWindowsPath | None:
        pytest.fail("A known AUMID should not require a registry lookup")

    monkeypatch.setattr(sessions, "_registered_executable", unexpected_lookup)
    assert sessions.is_yandex_music_source(" RU.YANDEX.DESKTOP.MUSIC ")


@pytest.mark.parametrize(
    ("source_id", "expected"),
    [
        ("  LOCALIZED CLIENT.EXE  ", True),
        (r"d:\music\LOCALIZED CLIENT.EXE", True),
        (r"C:\Other\Localized Client.exe", False),
        ("Not Localized Client.exe", False),
        (None, False),
        ("", False),
        (" ", False),
        ("firefox.exe", False),
        ("chrome.exe", False),
        ("YandexBrowser.exe", False),
        ("Spotify.exe", False),
    ],
)
def test_matches_registered_executable_only_by_exact_name_or_path(
    monkeypatch: pytest.MonkeyPatch, source_id: str | None, expected: bool
) -> None:
    def registered_executable() -> PureWindowsPath:
        return PureWindowsPath(r"D:\Music\Localized Client.exe")

    monkeypatch.setattr(sessions, "_registered_executable", registered_executable)
    assert sessions.is_yandex_music_source(source_id) is expected


@pytest.mark.parametrize(
    ("source_id", "expected"),
    [
        ("Яндекс Музыка.EXE", True),
        ("Not Яндекс Музыка.exe", False),
        (r"C:\Other\Яндекс Музыка.exe", False),
        ("Yandex Music.exe", True),
        ("YandexMusic_abc!App", True),
        ("Yandex.Desktop.MusicPlayer", True),
    ],
)
def test_uses_localized_and_legacy_fallback_without_registration(
    monkeypatch: pytest.MonkeyPatch, source_id: str, expected: bool
) -> None:
    def no_registered_executable() -> None:
        return None

    monkeypatch.setattr(sessions, "_registered_executable", no_registered_executable)
    assert sessions.is_yandex_music_source(source_id) is expected
