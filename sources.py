from __future__ import annotations

import base64
import hashlib
import html
import logging
import random
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from config import Config
from net import request_json


CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
COMMONS_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

MOCK_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII="
)

Provider = Callable[[str], Awaitable[list["MediaItem"]]]


@dataclass
class MediaItem:
    identity: str
    kind: str  # "video" or "photo"
    url: str
    page_url: str
    source: str
    title: str
    author: str
    mime: str
    extension: str
    duration: int | None = None
    data: bytes | None = None
    topic: str = "cat"  # "cat" или "webm"
    license: str = ""

    @property
    def display_title(self) -> str:
        if self.title.strip():
            return self.title.strip()
        if self.topic == "webm":
            return "Вирусный момент"
        if self.topic == "funny":
            return "Смешной момент"
        return "Смешной кот" if self.kind == "video" else "Котик"


def _identity(source: str, raw_id: Any, url: str) -> str:
    basis = f"{source}:{raw_id}" if raw_id not in (None, "") else url
    return hashlib.sha256(str(basis).encode("utf-8")).hexdigest()[:24]


def _strip_html(value: Any) -> str:
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    return " ".join(html.unescape(text).split())


def _extract_extension(url: str, fallback: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    for ext in (".mp4", ".webm", ".jpg", ".jpeg", ".png", ".gif", ".webp"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return fallback


def _is_too_old(cfg: Config, date_text: str) -> bool:
    if cfg.webm_max_age_days <= 0 or not date_text:
        return False
    match = COMMONS_DATE_RE.search(str(date_text))
    if not match:
        return False
    try:
        created = datetime.strptime(match.group(1), "%Y-%m-%d")
    except ValueError:
        return False
    return (datetime.now() - created).days > cfg.webm_max_age_days


def webm_is_relevant(cfg: Config, haystack: str, date_text: str = "") -> bool:
    """Отсечь разговоры, старые ролики и всё не про кошек/мемы до публикации."""
    text = haystack.lower()
    # Старые фильмы 1900-х — это не виральный контент.
    if re.search(r"\b(18\d{2}|19[0-4]\d)\b", text):
        return False
    if _is_too_old(cfg, date_text):
        return False
    if any(word in text for word in cfg.webm_exclude):
        return False
    if cfg.webm_require_words and not any(word in text for word in cfg.webm_require_words):
        return False
    if cfg.webm_keywords and not any(word in text for word in cfg.webm_keywords):
        return False
    return True


def parse_manual_memes(path: Path) -> list[MediaItem]:
    """Свежие мемы, которые пользователь добавил сам: URL | Название | Автор."""
    if not path.exists():
        return []
    items: list[MediaItem] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        url = parts[0]
        if not url.startswith(("http://", "https://")):
            continue
        title = parts[1] if len(parts) > 1 and parts[1] else url.rsplit("/", 1)[-1]
        author = parts[2] if len(parts) > 2 else ""
        extension = _extract_extension(url, ".mp4")
        is_photo = extension in (".jpg", ".jpeg", ".png", ".gif", ".webp")
        items.append(
            MediaItem(
                identity=f"manual:{url}",
                kind="photo" if is_photo else "video",
                url=url,
                page_url=url,
                source="Ручная подборка",
                title=title,
                author=author,
                mime="image/jpeg" if is_photo else "video/mp4",
                extension=extension,
                topic="webm",
            )
        )
    return items


def prefer_russian_items(items: list[MediaItem]) -> list[MediaItem]:
    """Русскоязычные ролики идут первыми, остальные остаются как запасной вариант."""
    russian = [item for item in items if CYRILLIC_RE.search(item.title)]
    if not russian:
        return items
    other = [item for item in items if not CYRILLIC_RE.search(item.title)]
    random.shuffle(russian)
    random.shuffle(other)
    return russian + other


class SourceManager:
    def __init__(self, cfg: Config, log: logging.Logger):
        self.cfg = cfg
        self.log = log
        self._mock_counter = 0

    def choose_topic(self) -> str:
        mix = self.cfg.content_mix
        names = [name for name in ("cat", "funny", "webm") if mix.get(name, 0) > 0]
        if not names:
            return "cat"
        weights = [mix[name] for name in names]
        return random.choices(names, weights=weights, k=1)[0]

    async def fetch_candidates(self, limit: int = 10) -> list[MediaItem]:
        if self.cfg.mock_mode:
            self._mock_counter += 1
            topic = self.choose_topic()
            return [
                MediaItem(
                    identity=f"mock:{topic}:{self._mock_counter}",
                    kind="video" if topic == "webm" else "photo",
                    url="",
                    page_url="",
                    source="MOCK",
                    title=(
                        f"Тестовый котик #{self._mock_counter}"
                        if topic == "cat"
                        else f"Тестовый вебм #{self._mock_counter}"
                        if topic == "webm"
                        else f"Тестовый смешной момент #{self._mock_counter}"
                    ),
                    author="KotoPotok",
                    mime="video/webm" if topic == "webm" else "image/png",
                    extension=".webm" if topic == "webm" else ".png",
                    data=base64.b64decode(MOCK_PNG_BASE64),
                    topic=topic,
                )
            ]

        topic = self.choose_topic()
        self.log.info("Выбран тип контента: %s", topic)
        manual = parse_manual_memes(self.cfg.manual_memes_file)
        if manual:
            random.shuffle(manual)
            self.log.info("Ручная подборка: %s ссылок", len(manual))
        attempts = [topic] + [name for name in ("cat", "funny", "webm") if name != topic]
        errors: list[str] = []

        for attempt in attempts:
            providers, queries = self._setup_attempt(attempt)
            if not providers and not manual:
                continue
            items, attempt_errors = (
                await self._collect(providers, queries, limit, attempt) if providers else ([], [])
            )
            errors.extend(attempt_errors)
            combined = manual + items
            if combined:
                return combined[:limit]
            if attempt == attempts[-1]:
                break

        details = "; ".join(errors[-3:]) if errors else "источники вернули пустой результат"
        raise RuntimeError(f"Не удалось найти медиа: {details}")

    def _setup_attempt(self, topic: str) -> tuple[list[tuple[str, Provider]], list[str]]:
        providers: list[tuple[str, Provider]] = []
        if topic == "webm":
            if self.cfg.commons_enabled:
                providers.append(("Commons", self._commons))
            queries = list(self.cfg.webm_queries)
        else:
            if self.cfg.pexels_key:
                providers.append(("Pexels", self._pexels))
            if self.cfg.pixabay_key:
                providers.append(("Pixabay", self._pixabay))
            queries = list(self.cfg.funny_queries if topic == "funny" else self.cfg.search_queries)

        random.shuffle(providers)
        random.shuffle(queries)
        if topic == "webm" and self.cfg.webm_russian_prefer and self.cfg.webm_russian_queries:
            russian_query = random.choice(self.cfg.webm_russian_queries)
            queries = [russian_query] + [q for q in queries if q != russian_query]
        return providers, queries[:3]

    async def _collect(
        self,
        providers: list[tuple[str, Provider]],
        queries: list[str],
        limit: int,
        topic: str,
    ) -> tuple[list[MediaItem], list[str]]:
        errors: list[str] = []
        merged: list[MediaItem] = []
        seen: set[str] = set()
        for provider_name, provider in providers:
            for query in queries:
                try:
                    items = await provider(query)
                except Exception as exc:  # noqa: BLE001 - один источник не должен ронять бота
                    msg = f"{provider_name}: {exc}"
                    errors.append(msg)
                    self.log.warning("Ошибка источника %s: %s", provider_name, exc)
                    continue
                for item in items:
                    if item.identity in seen or not item.url:
                        continue
                    seen.add(item.identity)
                    item.topic = topic
                    merged.append(item)
                if len(merged) >= limit:
                    break
            if len(merged) >= limit:
                break
        if topic == "webm" and self.cfg.webm_russian_prefer:
            merged = prefer_russian_items(merged)
        else:
            random.shuffle(merged)
        return merged[:limit], errors

    async def _pexels(self, query: str) -> list[MediaItem]:
        headers = {"Authorization": self.cfg.pexels_key}
        items: list[MediaItem] = []
        video_payload = await request_json(
            "GET",
            "https://api.pexels.com/videos/search",
            headers=headers,
            params={"query": query, "per_page": 12},
            timeout=self.cfg.request_timeout,
        )
        for video in video_payload.get("videos", []):
            file = self._pick_pexels_video(video)
            if not file or not file.get("link"):
                continue
            duration = video.get("duration")
            if isinstance(duration, int) and not (2 <= duration <= 90):
                continue
            url = str(file["link"])
            items.append(
                MediaItem(
                    identity=_identity("pexels-video", video.get("id"), url),
                    kind="video",
                    url=url,
                    page_url=str(video.get("url") or ""),
                    source="Pexels",
                    title=str(video.get("user", {}).get("name") or video.get("image") or ""),
                    author=str(video.get("user", {}).get("name") or ""),
                    mime="video/mp4",
                    extension=_extract_extension(url, ".mp4"),
                    duration=duration if isinstance(duration, int) else None,
                )
            )

        photo_payload = await request_json(
            "GET",
            "https://api.pexels.com/v1/search",
            headers=headers,
            params={"query": query, "per_page": 8, "orientation": "landscape"},
            timeout=self.cfg.request_timeout,
        )
        for photo in photo_payload.get("photos", []):
            src = photo.get("src") or {}
            url = str(src.get("large2x") or src.get("large") or src.get("medium") or "")
            if not url:
                continue
            items.append(
                MediaItem(
                    identity=_identity("pexels-photo", photo.get("id"), url),
                    kind="photo",
                    url=url,
                    page_url=str(photo.get("url") or ""),
                    source="Pexels",
                    title=str(photo.get("alt") or ""),
                    author=str(photo.get("photographer") or ""),
                    mime="image/jpeg",
                    extension=_extract_extension(url, ".jpg"),
                )
            )
        return items

    @staticmethod
    def _pick_pexels_video(video: dict[str, Any]) -> dict[str, Any] | None:
        files = [f for f in (video.get("video_files") or []) if isinstance(f, dict) and f.get("link")]
        mp4 = [
            f
            for f in files
            if str(f.get("file_type") or "").lower() == "video/mp4"
            or str(f.get("link") or "").lower().split("?")[0].endswith(".mp4")
        ]
        if not mp4:
            return None
        mp4.sort(key=lambda f: abs(int(f.get("width") or 1280) - 1280))
        return mp4[0]

    async def _pixabay(self, query: str) -> list[MediaItem]:
        key = self.cfg.pixabay_key
        items: list[MediaItem] = []

        video_payload = await request_json(
            "GET",
            "https://pixabay.com/api/videos/",
            params={
                "key": key,
                "q": query,
                "video_type": "film",
                "per_page": 12,
                "safesearch": "true",
            },
            timeout=self.cfg.request_timeout,
        )
        for hit in video_payload.get("hits", []):
            url = self._pick_pixabay_video(hit)
            if not url:
                continue
            duration = hit.get("duration")
            if isinstance(duration, int) and not (2 <= duration <= 90):
                continue
            items.append(
                MediaItem(
                    identity=_identity("pixabay-video", hit.get("id"), url),
                    kind="video",
                    url=url,
                    page_url=str(hit.get("pageURL") or ""),
                    source="Pixabay",
                    title=str(hit.get("tags") or ""),
                    author=str(hit.get("user") or ""),
                    mime="video/mp4",
                    extension=_extract_extension(url, ".mp4"),
                    duration=duration if isinstance(duration, int) else None,
                )
            )

        photo_payload = await request_json(
            "GET",
            "https://pixabay.com/api/",
            params={
                "key": key,
                "q": query,
                "image_type": "photo",
                "per_page": 8,
                "safesearch": "true",
            },
            timeout=self.cfg.request_timeout,
        )
        for hit in photo_payload.get("hits", []):
            url = str(hit.get("webformatURL") or hit.get("largeImageURL") or "")
            if not url:
                continue
            items.append(
                MediaItem(
                    identity=_identity("pixabay-photo", hit.get("id"), url),
                    kind="photo",
                    url=url,
                    page_url=str(hit.get("pageURL") or ""),
                    source="Pixabay",
                    title=str(hit.get("tags") or ""),
                    author=str(hit.get("user") or ""),
                    mime="image/jpeg",
                    extension=_extract_extension(url, ".jpg"),
                )
            )
        return items

    @staticmethod
    def _pick_pixabay_video(hit: dict[str, Any]) -> str:
        videos = hit.get("videos") or {}
        if not isinstance(videos, dict):
            return ""
        for quality in ("medium", "large", "small"):
            block = videos.get(quality) or {}
            if isinstance(block, dict) and block.get("url"):
                return str(block["url"])
        return ""

    async def _commons(self, query: str) -> list[MediaItem]:
        payload = await request_json(
            "GET",
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": f"filetype:video {query}",
                "gsrnamespace": 6,
                "gsrlimit": 20,
                "gsrsort": "relevance",
                "prop": "videoinfo|imageinfo",
                "viprop": "derivatives|url|size",
                "iiprop": "extmetadata",
                "format": "json",
            },
            timeout=self.cfg.request_timeout,
        )

        items: list[MediaItem] = []
        pages = (payload.get("query") or {}).get("pages") or {}
        for page_id, page in pages.items():
            if not isinstance(page, dict):
                continue
            video_info = (page.get("videoinfo") or [{}])[0]
            image_info = (page.get("imageinfo") or [{}])[0]
            try:
                duration = float(video_info.get("duration") or 0)
            except (TypeError, ValueError):
                continue
            if not (2 <= duration <= self.cfg.max_webm_duration_sec):
                continue

            derivative = self._pick_commons_derivative(video_info.get("derivatives") or [], duration)
            if not derivative:
                continue
            url = str(derivative.get("src") or "")
            if not url:
                continue

            meta = image_info.get("extmetadata") or {}
            author = _strip_html(
                (meta.get("Attribution") or {}).get("value")
                or (meta.get("Artist") or {}).get("value")
            )
            license_name = _strip_html((meta.get("LicenseShortName") or {}).get("value"))
            if author and license_name:
                author = f"{author} · {license_name}"
            elif license_name:
                author = license_name

            raw_title = str(page.get("title") or "")
            title = _strip_html((meta.get("ObjectName") or {}).get("value")) or raw_title.removeprefix("File:")

            description = _strip_html((meta.get("ImageDescription") or {}).get("value"))
            categories = _strip_html((meta.get("Categories") or {}).get("value"))
            created = _strip_html((meta.get("DateTime") or {}).get("value"))
            haystack = f"{title} {description} {categories}".lower()
            if not webm_is_relevant(self.cfg, haystack, created):
                continue

            items.append(
                MediaItem(
                    identity=_identity("commons", page_id or page.get("title"), raw_title or url),
                    kind="video",
                    url=url,
                    page_url=str(video_info.get("descriptionurl") or ""),
                    source="Wikimedia Commons",
                    title=title,
                    author=author,
                    mime="video/webm",
                    extension=".webm",
                    duration=int(round(duration)),
                    topic="webm",
                    license=license_name,
                )
            )
        return items

    def _pick_commons_derivative(self, derivatives: Any, duration: float) -> dict[str, Any] | None:
        if not isinstance(derivatives, list):
            return None
        ranks = {
            "480p.vp9.webm": 0,
            "360p.vp9.webm": 1,
            "720p.vp9.webm": 2,
            "240p.vp9.webm": 3,
            "1080p.vp9.webm": 4,
        }
        candidates: list[tuple[int, int, dict[str, Any]]] = []
        for derivative in derivatives:
            if not isinstance(derivative, dict):
                continue
            key = str(derivative.get("transcodekey") or "")
            src = str(derivative.get("src") or "")
            if "webm" not in key and not src.lower().endswith(".webm"):
                continue
            try:
                bandwidth = int(derivative.get("bandwidth") or 0)
            except (TypeError, ValueError):
                bandwidth = 0
            if bandwidth * duration > self.cfg.max_video_bytes:
                continue
            rank = ranks.get(key, 5)
            candidates.append((rank, -bandwidth, derivative))
        if not candidates:
            return None
        candidates.sort(key=lambda entry: (entry[0], entry[1]))
        return candidates[0][2]
