import os
import json
import urllib.parse
from typing import List, Dict, Optional, Any
import keyring
from pydantic import BaseModel, Field

from history_manager import history_manager

KEYRING_SERVICE = 'WinYandexMusicRPC'
KEYRING_GEMINI_KEY = 'gemini_api_key'
DEFAULT_MODEL = 'gemini-3.5-flash-lite'

class TrackRecommendation(BaseModel):
    artist: str = Field(description="Имя исполнителя или название группы")
    title: str = Field(description="Название трека или песни")
    reason: str = Field(description="Краткое объяснение на русском языке (1-2 предложения), почему этот трек рекомендуется и чем он интересен")

class RecommendationsPayload(BaseModel):
    recommendations: List[TrackRecommendation]


def get_gemini_api_key() -> str:
    """Retrieves the Gemini API key from Windows Credential Manager or environment."""
    try:
        stored = keyring.get_password(KEYRING_SERVICE, KEYRING_GEMINI_KEY)
        if stored and stored.strip():
            return stored.strip()
    except Exception:
        pass
    return (os.environ.get('GEMINI_API_KEY') or '').strip()


def set_gemini_api_key(api_key: str) -> bool:
    """Saves the Gemini API key into Windows Credential Manager."""
    try:
        cleaned = api_key.strip()
        if cleaned:
            keyring.set_password(KEYRING_SERVICE, KEYRING_GEMINI_KEY, cleaned)
        else:
            delete_gemini_api_key()
        return True
    except Exception:
        return False


def delete_gemini_api_key() -> bool:
    """Removes the Gemini API key from Windows Credential Manager."""
    try:
        if keyring.get_password(KEYRING_SERVICE, KEYRING_GEMINI_KEY) is not None:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_GEMINI_KEY)
        return True
    except Exception:
        return False


def get_yandex_client(token: Optional[str] = None):
    """Initializes a Yandex Music client using the provided or saved token."""
    try:
        import yandex_music
        if not token:
            token = keyring.get_password('WinYandexMusicRPC', 'token')
        if token:
            return yandex_music.Client(token).init()
        return yandex_music.Client().init()
    except Exception:
        return None


def fetch_recommendations(
    mode: str = "recent",
    current_track: Optional[Dict[str, Any]] = None,
    ya_client=None,
    model: str = DEFAULT_MODEL,
    limit: int = 6
) -> Dict[str, Any]:
    """
    Calls Gemini to generate music recommendations, then verifies track availability on Yandex Music.
    Returns:
      {
        "success": bool,
        "recommendations": List[Dict],
        "error": Optional[str],
        "mode_title": str
      }
    """
    api_key = get_gemini_api_key()
    if not api_key:
        return {
            "success": False,
            "recommendations": [],
            "error": "API ключ Gemini не настроен. Пожалуйста, укажите его во вкладке «Настройки».",
            "mode_title": ""
        }

    from google import genai

    recent_tracks = history_manager.get_recent_tracks(20)
    top_artists = history_manager.get_top_artists(10)

    # Build context and prompt depending on mode
    mode_titles = {
        "recent": "На основе недавних треков",
        "current": "Похожее на текущий трек",
        "discovery": "Музыкальные открытия",
        "energy": "Энергичное и драйвовое",
        "chill": "Спокойное и атмосферное",
    }
    mode_title = mode_titles.get(mode, "Рекомендации")

    context_lines = []
    if current_track and current_track.get('title') and current_track.get('title') != '—':
        context_lines.append(f"Сейчас играет: {current_track.get('artist')} - {current_track.get('title')}")

    if recent_tracks:
        recent_str = ", ".join(f"{t['artist']} — «{t['title']}»" for t in recent_tracks[:12])
        context_lines.append(f"Недавно прослушанные треки: {recent_str}")

    if top_artists:
        artists_str = ", ".join(f"{a['artist']} ({a['play_count']} раз)" for a in top_artists[:8])
        context_lines.append(f"Любимые артисты пользователя: {artists_str}")

    context_text = "\n".join(context_lines) if context_lines else "История пользователя пока пуста."

    mode_instructions = {
        "recent": (
            f"Проанализируй музыкальный вкус пользователя по его недавним трекам и любимым артистам. "
            f"Порекомендуй ровно {limit} композиций, которые гармонично дополнят его текущую волну, "
            f"но не дублируют уже прослушанные треки."
        ),
        "current": (
            f"Сфокусируйся на треке, который играет прямо сейчас: "
            f"«{current_track.get('artist', '')} - {current_track.get('title', '')}». "
            f"Порекомендуй {limit} песен с похожим саундом, темпом, гармонией, настроением или инструментовкой."
            if (current_track and current_track.get('title') and current_track.get('title') != '—')
            else f"Порекомендуй {limit} ярких и качественных музыкальных треков разных жанров."
        ),
        "discovery": (
            f"Опираясь на вкус пользователя, порекомендуй {limit} необычных, глубоких или малоизвестных треков, "
            f"которые помогут ему открыть для себя новые музыкальные горизонты и интересные поджанры."
        ),
        "energy": (
            f"Порекомендуй {limit} энергичных, ритмичных, вдохновляющих или драйвовых треков "
            f"с учетом любимых жанров и исполнителей пользователя."
        ),
        "chill": (
            f"Порекомендуй {limit} спокойных, мелодичных, расслабляющих или атмосферных треков "
            f"(lo-fi, indie, ambient, acoustic, chillout), сочетающихся с музыкальным вкусом пользователя."
        )
    }

    instruction = mode_instructions.get(mode, mode_instructions["recent"])

    prompt = f"""
Ты — профессиональный музыкальный куратор и эксперт с безупречным вкусом.
Твоя задача — подобрать персональные музыкальные рекомендации для слушателя.

Контекст прослушиваний пользователя:
{context_text}

Инструкция:
{instruction}

Требования к рекомендациям:
1. Предлагай реально существующие официальные треки известных или признанных артистов.
2. Не включай треки, которые уже перечислены в недавних треках пользователя.
3. Поле 'reason' обязательно пиши на естественном, живом русском языке (1-2 емких предложения), объясняя, чем трек цепляет и почему он понравится.
4. Верни ровно {limit} рекомендаций.
"""

    models_to_try = [model]
    for alt in ['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite', 'gemini-3.5-flash', 'gemini-3.8-flash']:
        if alt not in models_to_try:
            models_to_try.append(alt)

    client = genai.Client(api_key=api_key)
    candidates = []
    last_error = None

    for candidate_model in models_to_try:
        try:
            response = client.models.generate_content(
                model=candidate_model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_json_schema": RecommendationsPayload.model_json_schema(),
                }
            )
            response_text = response.text or ""
            parsed = json.loads(response_text)
            candidates = parsed.get("recommendations", [])
            if candidates:
                break
        except Exception as e:
            last_error = e
            continue

    if not candidates and last_error:
        return {
            "success": False,
            "recommendations": [],
            "error": f"Ошибка запроса к Gemini: {last_error}",
            "mode_title": mode_title
        }

    # Verify candidates with Yandex Music
    if ya_client is None:
        ya_client = get_yandex_client()

    final_results = []
    for cand in candidates:
        artist_name = (cand.get("artist") or "").strip()
        title_name = (cand.get("title") or "").strip()
        reason = (cand.get("reason") or "").strip()

        if not artist_name or not title_name:
            continue

        item_data = {
            "artist": artist_name,
            "title": title_name,
            "reason": reason,
            "url": f"https://music.yandex.ru/search?text={urllib.parse.quote(f'{artist_name} {title_name}')}",
            "cover_url": None,
            "available_on_yandex": False,
            "track_id": None
        }

        if ya_client:
            try:
                search_query = f"{artist_name} - {title_name}"
                res = ya_client.search(search_query, type_='track')
                if res and res.tracks and res.tracks.results:
                    found_track = res.tracks.results[0]
                    item_data["available_on_yandex"] = True
                    item_data["title"] = found_track.title
                    item_data["artist"] = ", ".join(a.name for a in found_track.artists)
                    item_data["track_id"] = str(found_track.id)

                    album_id = found_track.albums[0].id if found_track.albums else None
                    if album_id:
                        item_data["url"] = f"https://music.yandex.ru/album/{album_id}/track/{found_track.id}"
                    else:
                        item_data["url"] = f"https://music.yandex.ru/track/{found_track.id}"

                    try:
                        cover_uri = getattr(found_track, 'cover_uri', None)
                        if cover_uri:
                            item_data["cover_url"] = f"https://{cover_uri.replace('%%', '200x200')}"
                        elif hasattr(found_track, 'get_cover_url'):
                            item_data["cover_url"] = found_track.get_cover_url(size="200x200")
                    except Exception:
                        item_data["cover_url"] = None
            except Exception:
                # If network or region error occurs on Yandex search, fallback to search URL
                pass

        final_results.append(item_data)

    return {
        "success": True,
        "recommendations": final_results,
        "error": None,
        "mode_title": mode_title
    }
