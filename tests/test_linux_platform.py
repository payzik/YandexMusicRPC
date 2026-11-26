from pathlib import Path

import pytest

import linux_platform as lp


def test_parse_mpris_metadata_extracts_fields() -> None:
    sample = (
        "({'xesam:title': <'Ты так красива'>, "
        "'xesam:artist': <['Quest Pistols']>, "
        "'xesam:album': <'Singles'>, "
        "'mpris:length': <int64 233230000>, "
        "'mpris:artUrl': <'https://avatars.yandex.net/get-music-content/1/200x200'>},)"
    )
    parsed = lp.parse_mpris_metadata_text(sample)
    assert parsed["title"] == "Ты так красива"
    assert parsed["artist"] == "Quest Pistols"
    assert parsed["album"] == "Singles"
    assert parsed["length_us"] == 233230000
    assert parsed["art_url"].startswith("https://")


def test_parse_mpris_metadata_handles_multiple_artists() -> None:
    sample = "({'xesam:title': <'Friends'>, 'xesam:artist': <['Marshmello', 'Anne-Marie']>},)"
    parsed = lp.parse_mpris_metadata_text(sample)
    assert parsed["artist"] == "Marshmello, Anne-Marie"


@pytest.mark.parametrize(
    ("bus", "identity", "desktop", "expected"),
    [
        ("org.mpris.MediaPlayer2.yandex-music", "Яндекс Музыка", "yandex-music", True),
        ("org.mpris.MediaPlayer2.chromium.instance123", "Яндекс Музыка", "", True),
        ("org.mpris.MediaPlayer2.firefox.instance99", "Mozilla Firefox", "firefox", False),
        ("org.mpris.MediaPlayer2.vlc", "VLC media player", "vlc", False),
        ("org.mpris.MediaPlayer2.yandex-browser", "Yandex Browser", "yandex-browser", False),
    ],
)
def test_is_yandex_music_mpris_player(
    bus: str, identity: str, desktop: str, expected: bool
) -> None:
    assert lp.is_yandex_music_mpris_player(bus, identity, desktop) is expected


def test_get_app_data_dir_uses_xdg_when_no_localappdata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(lp.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert lp.get_app_data_dir("WinYandexMusicRPC") == str(tmp_path / "WinYandexMusicRPC")


def test_is_steam_deck_detects_jupiter_and_galileo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lp.is_steam_deck.cache_clear()
    monkeypatch.setattr(lp.sys, "platform", "linux")

    def fake_read_text(path: Path) -> str:
        s = str(path).replace("\\", "/")
        if s.endswith("/product_name"):
            return "Galileo"
        if s.endswith("/board_vendor"):
            return "Valve"
        return ""

    monkeypatch.setattr(lp, "_read_text", fake_read_text)
    assert lp.is_steam_deck() is True
    lp.is_steam_deck.cache_clear()


def test_find_discord_ipc_socket_detects_flatpak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lp.sys, "platform", "linux")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    flatpak_sock = tmp_path / "app" / "com.discordapp.Discord" / "discord-ipc-0"
    flatpak_sock.parent.mkdir(parents=True)
    flatpak_sock.touch()
    assert lp.find_discord_ipc_socket() == str(flatpak_sock)
