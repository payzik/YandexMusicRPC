"""Typed data contracts shared between RPC tracking, history and recommendations."""

from typing import TypedDict


class TrackSnapshot(TypedDict, total=False):
    """Track payload recorded into listening history and passed to AI context."""

    artist: str
    title: str
    album: str
    durationSec: float | int
    source: str


class HistoryEntry(TypedDict):
    """Single listening history row returned from SQLite."""

    id: int
    artist: str
    title: str
    album: str
    duration_sec: float
    source: str
    played_at: str


class ArtistStat(TypedDict):
    """Aggregated artist play count returned from listening history."""

    artist: str
    play_count: int


class RecommendationItem(TypedDict):
    """Single recommended track enriched with Yandex Music catalog metadata."""

    artist: str
    title: str
    reason: str
    url: str
    cover_url: str | None
    available_on_yandex: bool
    track_id: str | None


class RecommendationsResult(TypedDict):
    """Structured response returned by ``gemini_recommender.fetch_recommendations``."""

    success: bool
    recommendations: list[RecommendationItem]
    error: str | None
    mode_title: str
