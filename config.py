from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_QUERIES = [
    "funny cat",
    "cat playing",
    "cute kitten",
    "cat meme",
    "cat falling",
]

DEFAULT_FUNNY_QUERIES = [
    "funny moments",
    "people laughing",
    "funny dance",
    "sports fail",
    "kids playing",
]

DEFAULT_WEBM_QUERIES = [
    "funny video",
    "funny cat",
    "funny animals",
    "funny animation",
    "funny moments",
]

DEFAULT_WEBM_KEYWORDS = [
    "funny",
    "cat",
    "cats",
    "kitten",
    "fail",
    "lol",
    "comedy",
    "meme",
    "кот",
    "коты",
    "смешн",
    "весел",
    "прикол",
]

DEFAULT_WEBM_EXCLUDE = [
    "speech",
    "speaks",
    "talk",
    "interview",
    "lecture",
    "news",
    "conference",
    "meeting",
    "announcement",
    "government",
    "president",
    "politician",
    "documentary",
    "report",
]

DEFAULT_CONTENT_MIX = {"cat": 30, "funny": 40, "webm": 30}


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "да")


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _parse_partners(raw: str | None) -> list[dict[str, str]]:
    partners: list[dict[str, str]] = []
    if not raw:
        return partners
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        for entry in parsed:
            if isinstance(entry, dict) and entry.get("url"):
                partners.append(
                    {
                        "title": str(entry.get("title") or "Полезная ссылка"),
                        "url": str(entry["url"]),
                        "note": str(entry.get("note") or ""),
                    }
                )
    if not partners:
        url = os.getenv("PARTNER_LINK_URL", "").strip()
        if url:
            partners.append(
                {
                    "title": os.getenv("PARTNER_LINK_TITLE", "Полезная ссылка").strip(),
                    "url": url,
                    "note": os.getenv("PARTNER_LINK_NOTE", "").strip(),
                }
            )
    return partners


def _parse_hours(raw: str | None, default: tuple[int, int] = (7, 23)) -> tuple[int, int]:
    if not raw:
        return default
    try:
        a, b = raw.split("-", 1)
        start, end = int(a.strip()), int(b.strip())
        if 0 <= start <= 23 and 0 <= end <= 23:
            return start, end
    except ValueError:
        pass
    return default


def parse_content_mix(raw: str | None) -> dict[str, int]:
    if not raw:
        return dict(DEFAULT_CONTENT_MIX)
    mix: dict[str, int] = {}
    for part in raw.split(","):
        if ":" not in part:
            continue
        name, value = part.split(":", 1)
        name = name.strip().lower()
        try:
            weight = int(value.strip())
        except ValueError:
            continue
        if name in ("cat", "funny", "webm") and weight >= 0:
            mix[name] = weight
    if not mix or sum(mix.values()) == 0:
        return dict(DEFAULT_CONTENT_MIX)
    return mix


@dataclass
class Config:
    bot_token: str = ""
    admin_id: int | None = None
    channel_id: str = ""

    pexels_key: str = ""
    pixabay_key: str = ""

    data_dir: Path = field(default_factory=lambda: Path("data"))
    tz_name: str = "Europe/Moscow"
    active_hours: tuple[int, int] = (7, 23)

    search_queries: list[str] = field(default_factory=lambda: list(DEFAULT_QUERIES))
    funny_queries: list[str] = field(default_factory=lambda: list(DEFAULT_FUNNY_QUERIES))
    webm_queries: list[str] = field(default_factory=lambda: list(DEFAULT_WEBM_QUERIES))
    content_mix: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_CONTENT_MIX))
    commons_enabled: bool = True
    webm_keywords: list[str] = field(default_factory=lambda: list(DEFAULT_WEBM_KEYWORDS))
    webm_exclude: list[str] = field(default_factory=lambda: list(DEFAULT_WEBM_EXCLUDE))
    max_webm_duration_sec: int = 120
    post_interval_min: int = 180
    jitter_percent: float = 20.0
    first_post_delay_sec: int = 60

    max_video_bytes: int = 45 * 1024 * 1024
    max_photo_bytes: int = 8 * 1024 * 1024
    request_timeout: int = 25

    ad_every: int = 10
    partners: list[dict[str, str]] = field(default_factory=list)

    dry_run: bool = False
    mock_mode: bool = False
    health_port: int = 8080
    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bot.db"

    @property
    def sources_configured(self) -> list[str]:
        names: list[str] = []
        if self.pexels_key:
            names.append("Pexels")
        if self.pixabay_key:
            names.append("Pixabay")
        if self.commons_enabled:
            names.append("Commons WebM")
        if self.mock_mode:
            names.append("MOCK")
        return names

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.dry_run and not self.bot_token:
            problems.append("TELEGRAM_BOT_TOKEN не задан")
        if not self.dry_run and not self.channel_id:
            problems.append("TELEGRAM_CHANNEL_ID не задан")
        has_key_sources = bool(self.pexels_key or self.pixabay_key)
        has_webm_source = self.commons_enabled and self.content_mix.get("webm", 0) > 0
        if not self.mock_mode and not has_key_sources and not has_webm_source:
            problems.append(
                "нужен PEXELS_API_KEY / PIXABAY_API_KEY или ENABLE_COMMONS_WEBM=1 с весом webm > 0"
            )
        if self.post_interval_min < 5:
            problems.append("POST_INTERVAL_MIN слишком маленький (минимум 5)")
        if self.jitter_percent < 0 or self.jitter_percent > 80:
            problems.append("JITTER_PERCENT должен быть от 0 до 80")
        return problems


def load_config(env_path: Path | None = None) -> Config:
    path = env_path or Path(".env")
    _load_dotenv(path)

    queries_raw = os.getenv("SEARCH_QUERIES", "").strip()
    queries = [q.strip() for q in queries_raw.split("|") if q.strip()] if queries_raw else list(DEFAULT_QUERIES)

    funny_raw = os.getenv("FUNNY_QUERIES", "").strip()
    funny_queries = [q.strip() for q in funny_raw.split("|") if q.strip()] if funny_raw else list(DEFAULT_FUNNY_QUERIES)

    webm_raw = os.getenv("WEBM_QUERIES", "").strip()
    webm_queries = [q.strip() for q in webm_raw.split("|") if q.strip()] if webm_raw else list(DEFAULT_WEBM_QUERIES)

    keywords_raw = os.getenv("WEBM_KEYWORDS", "").strip()
    webm_keywords = (
        [word.strip().lower() for word in keywords_raw.split("|") if word.strip()]
        if keywords_raw
        else list(DEFAULT_WEBM_KEYWORDS)
    )

    exclude_raw = os.getenv("WEBM_EXCLUDE", "").strip()
    webm_exclude = (
        [word.strip().lower() for word in exclude_raw.split("|") if word.strip()]
        if exclude_raw
        else list(DEFAULT_WEBM_EXCLUDE)
    )

    admin_raw = os.getenv("TELEGRAM_ADMIN_ID", "").strip()
    admin_id: int | None = None
    if admin_raw:
        try:
            admin_id = int(admin_raw)
        except ValueError:
            admin_id = None

    cfg = Config(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        admin_id=admin_id,
        channel_id=os.getenv("TELEGRAM_CHANNEL_ID", "").strip(),
        pexels_key=os.getenv("PEXELS_API_KEY", "").strip(),
        pixabay_key=os.getenv("PIXABAY_API_KEY", "").strip(),
        data_dir=Path(os.getenv("DATA_DIR", "data")).expanduser(),
        tz_name=os.getenv("TZ_NAME", os.getenv("TZ", "Europe/Moscow")).strip() or "Europe/Moscow",
        active_hours=_parse_hours(os.getenv("ACTIVE_HOURS")),
        search_queries=queries,
        funny_queries=funny_queries,
        webm_queries=webm_queries,
        content_mix=parse_content_mix(os.getenv("CONTENT_MIX")),
        commons_enabled=_get_bool("ENABLE_COMMONS_WEBM", True),
        webm_keywords=webm_keywords,
        webm_exclude=webm_exclude,
        max_webm_duration_sec=_get_int("MAX_WEBM_DURATION_SEC", 120),
        post_interval_min=_get_int("POST_INTERVAL_MIN", 180),
        jitter_percent=_get_float("JITTER_PERCENT", 20.0),
        first_post_delay_sec=_get_int("FIRST_POST_DELAY_SEC", 60),
        max_video_bytes=_get_int("MAX_VIDEO_BYTES", 45 * 1024 * 1024),
        max_photo_bytes=_get_int("MAX_PHOTO_BYTES", 8 * 1024 * 1024),
        request_timeout=_get_int("REQUEST_TIMEOUT", 25),
        ad_every=_get_int("AD_EVERY", 10),
        partners=_parse_partners(os.getenv("PARTNER_LINKS")),
        dry_run=_get_bool("DRY_RUN", False),
        mock_mode=_get_bool("MOCK_MODE", False),
        health_port=_get_int("PORT", 8080),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
    )
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    return cfg
