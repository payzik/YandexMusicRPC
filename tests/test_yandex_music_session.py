import sys
import unittest
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory
from unittest.mock import patch

from yandex_music_session import (
    _parse_protocol_executable,
    _registered_executable,
    is_yandex_music_source,
)


class ProtocolCommandTests(unittest.TestCase):
    def test_accepts_quoted_localized_path(self) -> None:
        executable = r"C:\Program Files\YandexMusic\Яндекс Музыка.exe"
        self.assertEqual(
            _parse_protocol_executable(f'"{executable}" "%1"'),
            PureWindowsPath(executable),
        )

    def test_accepts_unquoted_path_without_spaces(self) -> None:
        executable = r"D:\Music\Player.EXE"
        self.assertEqual(
            _parse_protocol_executable(f"{executable} %1"), PureWindowsPath(executable)
        )

    def test_rejects_unsupported_commands(self) -> None:
        for command in (
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
        ):
            with self.subTest(command=command):
                self.assertIsNone(_parse_protocol_executable(command))


@unittest.skipUnless(sys.platform == "win32", "Windows registry API required")
class RegisteredExecutableTests(unittest.TestCase):
    def setUp(self) -> None:
        _registered_executable.cache_clear()
        self.addCleanup(_registered_executable.cache_clear)

    def test_missing_registry_key_uses_localized_fallback(self) -> None:
        with patch("winreg.OpenKey", side_effect=FileNotFoundError) as open_key:
            self.assertTrue(is_yandex_music_source("Яндекс Музыка.exe"))
            self.assertFalse(is_yandex_music_source("Other Player.exe"))
            open_key.assert_called_once()

    def test_expands_and_caches_an_existing_executable(self) -> None:
        import winreg

        with TemporaryDirectory() as directory:
            executable = Path(directory) / "Localized Client.exe"
            executable.touch()
            raw_command = r'"%MUSIC_DIR%\Localized Client.exe" "%1"'
            with (
                patch("winreg.OpenKey") as open_key,
                patch(
                    "winreg.QueryValueEx",
                    return_value=(raw_command, winreg.REG_EXPAND_SZ),
                ),
                patch(
                    "winreg.ExpandEnvironmentStrings",
                    return_value=f'"{executable}" "%1"',
                ) as expand,
            ):
                self.assertTrue(is_yandex_music_source(executable.name))
                self.assertTrue(is_yandex_music_source(str(executable)))
                expand.assert_called_once_with(raw_command)
                open_key.assert_called_once()

    def test_ignores_registration_pointing_to_missing_executable(self) -> None:
        import winreg

        with TemporaryDirectory() as directory:
            executable = Path(directory) / "Missing Client.exe"
            with (
                patch("winreg.OpenKey"),
                patch(
                    "winreg.QueryValueEx",
                    return_value=(f'"{executable}" "%1"', winreg.REG_SZ),
                ),
            ):
                self.assertFalse(is_yandex_music_source(executable.name))


class YandexMusicSourceTests(unittest.TestCase):
    def test_accepts_known_aumid_without_registry_lookup(self) -> None:
        with patch("yandex_music_session._registered_executable") as lookup:
            self.assertTrue(is_yandex_music_source(" RU.YANDEX.DESKTOP.MUSIC "))
            lookup.assert_not_called()

    def test_matches_registered_executable_by_name_or_path(self) -> None:
        registered = PureWindowsPath(r"D:\Music\Localized Client.exe")
        with patch(
            "yandex_music_session._registered_executable", return_value=registered
        ):
            self.assertTrue(is_yandex_music_source("  LOCALIZED CLIENT.EXE  "))
            self.assertTrue(is_yandex_music_source(r"d:\music\LOCALIZED CLIENT.EXE"))
            self.assertFalse(is_yandex_music_source(r"C:\Other\Localized Client.exe"))
            self.assertFalse(is_yandex_music_source("Not Localized Client.exe"))

    def test_accepts_exact_localized_name_without_registration(self) -> None:
        with patch("yandex_music_session._registered_executable", return_value=None):
            self.assertTrue(is_yandex_music_source("Яндекс Музыка.EXE"))
            self.assertFalse(is_yandex_music_source("Not Яндекс Музыка.exe"))
            self.assertFalse(is_yandex_music_source(r"C:\Other\Яндекс Музыка.exe"))

    def test_preserves_legacy_identifiers(self) -> None:
        with patch("yandex_music_session._registered_executable", return_value=None):
            for source_id in (
                "Yandex Music.exe",
                "YandexMusic_abc!App",
                "Yandex.Desktop.MusicPlayer",
            ):
                with self.subTest(source_id=source_id):
                    self.assertTrue(is_yandex_music_source(source_id))

    def test_rejects_unrelated_and_empty_identifiers(self) -> None:
        registered = PureWindowsPath(r"D:\Music\Localized Client.exe")
        with patch(
            "yandex_music_session._registered_executable", return_value=registered
        ):
            for source_id in (
                None,
                "",
                " ",
                "firefox.exe",
                "chrome.exe",
                "YandexBrowser.exe",
                "Spotify.exe",
            ):
                with self.subTest(source_id=source_id):
                    self.assertFalse(is_yandex_music_source(source_id))
