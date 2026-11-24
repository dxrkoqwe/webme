from __future__ import annotations

import html
import logging
import random

from config import Config
from net import download_media
from sources import MediaItem


TOPIC_HASHTAGS = {
    "cat": "#коты #мемы #котик",
    "funny": "#смешное #мемы #видео",
    "webm": "#вебм #мемы #виральное",
}

TOPIC_EMOJI = {
    "cat": "🐾",
    "funny": "😂",
    "webm": "🎬",
}


def build_caption(item: MediaItem, cfg: Config, post_number: int) -> str:
    emoji = TOPIC_EMOJI.get(item.topic, TOPIC_EMOJI["cat"])
    title = html.escape(item.display_title[:120])
    lines = [f"{emoji} {title}"]

    author = html.escape(item.author[:100]) if item.author else ""
    if author:
        lines.append(f"Автор: {author} · {item.source}")
    elif item.source:
        lines.append(f"Источник: {item.source}")

    if cfg.ad_every > 0 and post_number % cfg.ad_every == 0 and cfg.partners:
        partner = cfg.partners[(post_number // cfg.ad_every - 1) % len(cfg.partners)]
        partner_title = html.escape(partner["title"][:80])
        partner_url = html.escape(partner["url"], quote=True)
        note = html.escape(partner["note"][:100]) if partner.get("note") else ""
        promo = f'🔧 {partner_title}: <a href="{partner_url}">перейти</a>'
        if note:
            promo += f" — {note}"
        lines.append("")
        lines.append(promo)

    lines.append("")
    lines.append(TOPIC_HASHTAGS.get(item.topic, TOPIC_HASHTAGS["cat"]))

    caption = "\n".join(lines)
    return caption[:1024]


async def prepare_media(item: MediaItem, cfg: Config, log: logging.Logger) -> bytes:
    if item.data is not None:
        return item.data
    limit = cfg.max_video_bytes if item.kind == "video" else cfg.max_photo_bytes
    log.info("Скачиваю %s из %s...", item.kind, item.source)
    content, content_type = await download_media(item.url, limit, timeout=90)
    if content_type.startswith("image/") and item.kind == "video":
        log.warning("Источник вернул изображение вместо видео: %s", item.url)
    if not content:
        raise RuntimeError("источник вернул пустой файл")
    return content


def jittered_interval(cfg: Config) -> float:
    base = cfg.post_interval_min * 60
    spread = base * cfg.jitter_percent / 100.0
    return max(5 * 60, base + random.uniform(-spread, spread))
