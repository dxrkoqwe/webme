from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from bot import ContentBot
from config import load_config
from sources import SourceManager
from storage import Storage
from telegram_api import TelegramApi


async def main() -> None:
    env_file = Path(os.getenv("KOTOPOTOK_ENV", str(Path(__file__).parent / ".env")))
    cfg = load_config(env_file)
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log = logging.getLogger("kotopotok")

    if os.getenv("HTTPS_PROXY") or os.getenv("https_proxy"):
        log.info("HTTPS-прокси задан через переменные окружения")

    problems = cfg.validate()
    if problems:
        for problem in problems:
            log.error("Проверка конфигурации: %s", problem)
        log.error("Заполни .env по образцу .env.example и запусти снова.")
        return

    if cfg.dry_run:
        log.warning("DRY_RUN включён — посты не уходят в Telegram")
    if cfg.mock_mode:
        log.warning("MOCK_MODE включён — используется тестовый котик вместо API")

    storage = Storage(cfg.db_path)
    telegram = TelegramApi(cfg, log)
    sources = SourceManager(cfg, log)
    bot = ContentBot(cfg, storage, sources, telegram, log)

    if "--once" in sys.argv[1:]:
        log.info("Разовый запуск: один пост по расписанию GitHub Actions")
        try:
            ok = await bot.run_once()
        finally:
            storage.close()
        log.info("Разовый запуск завершён: %s", "пост опубликован" if ok else "пост не опубликован")
        return

    log.info(
        "Запуск KotoPotok: интервал=%s мин, активные часы=%02d-%02d, источники=%s",
        cfg.post_interval_min,
        cfg.active_hours[0],
        cfg.active_hours[1],
        ", ".join(cfg.sources_configured),
    )
    try:
        await bot.run()
    except KeyboardInterrupt:
        log.info("Остановка по Ctrl+C")
    finally:
        storage.close()


if __name__ == "__main__":
    if sys.platform.startswith("win") and sys.version_info < (3, 14):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
