from pathlib import Path

import pytest

from config_manager import ConfigManager
from contracts import TrackSnapshot
from gemini_recommender import _get_recommendations_schema
from history_manager import HistoryManager


def test_config_manager_defaults_and_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cfg = ConfigManager()

    assert cfg.get_selected_session() == "Automatic"
    assert cfg.get_gemini_model() == "gemini-3.5-flash-lite"
    assert cfg.get_recommendations_count() == 6

    cfg.set_selected_session("ru.yandex.desktop.music")
    cfg.set_gemini_model("gemini-3.5-flash")
    cfg.set_recommendations_count(8)

    reloaded = ConfigManager()
    assert reloaded.get_selected_session() == "ru.yandex.desktop.music"
    assert reloaded.get_gemini_model() == "gemini-3.5-flash"
    assert reloaded.get_recommendations_count() == 8


def test_config_manager_handles_invalid_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cfg = ConfigManager()
    cfg.set_setting("GeminiSettings", "count", "not-a-number")
    assert cfg.get_recommendations_count() == 6


def test_history_manager_records_deduplicates_and_clears(tmp_path: Path) -> None:
    hm = HistoryManager(temp_dir=str(tmp_path))
    assert hm.get_total_count() == 0

    assert hm.record_track({"artist": "—", "title": "Nothing"}) is False
    assert hm.record_track({"artist": "Artist A", "title": ""}) is False

    track_a: TrackSnapshot = {
        "artist": "Artist A",
        "title": "Track 1",
        "album": "Album 1",
        "durationSec": 180,
        "source": "pc",
    }
    assert hm.record_track(track_a, min_interval_sec=45.0) is True
    # Duplicate within min_interval_sec is skipped
    assert hm.record_track(track_a, min_interval_sec=45.0) is False

    track_b: TrackSnapshot = {
        "artist": "Artist B",
        "title": "Track 2",
        "durationSec": 200,
        "source": "phone",
    }
    assert hm.record_track(track_b, min_interval_sec=45.0) is True
    assert hm.record_track(
        {"artist": "Локальный файл", "title": "song.mp3"}, min_interval_sec=45.0
    ) is True

    assert hm.get_total_count() == 3

    recent = hm.get_recent_tracks(limit=10)
    assert len(recent) == 3
    assert recent[0]["title"] == "song.mp3"
    assert recent[-1]["artist"] == "Artist A"

    top = hm.get_top_artists(limit=10)
    top_names = {item["artist"] for item in top}
    assert "Artist A" in top_names
    assert "Локальный файл" not in top_names

    assert hm.clear_history() is True
    assert hm.get_total_count() == 0


def test_recommendations_json_schema_has_expected_fields() -> None:
    pytest.importorskip("pydantic")
    schema = _get_recommendations_schema()
    assert "properties" in schema
    assert "recommendations" in schema["properties"]
    defs = schema.get("$defs", {})
    assert "TrackRecommendation" in defs
    props = defs["TrackRecommendation"]["properties"]
    assert {"artist", "title", "reason"} <= set(props)
