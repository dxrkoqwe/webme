from __future__ import annotations

import asyncio
import html
import logging
import time
from datetime import datetime, time as dt_time, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import Config, parse_content_mix
from health import HealthServer
from publisher import build_caption, jittered_interval, prepare_media
from sources import SourceManager
from storage import Storage
from telegram_api import TelegramApi


class ContentBot:
    def __init__(
        self,
        cfg: Config,
        storage: Storage,
        sources: SourceManager,
        telegram: TelegramApi,
        log: logging.Logger,
    ):
        self.cfg = cfg
        self.storage = storage
        self.sources = sources
        self.telegram = telegram
        self.log = log
        self.paused = bool(storage.get_state("paused", False))
        self.admin_id: int | None = cfg.admin_id or storage.get_state("admin_id")

        stored_interval = storage.get_state("post_interval_min")
        if isinstance(stored_interval, int) and stored_interval >= 5:
            cfg.post_interval_min = stored_interval
        stored_mix = storage.get_state("content_mix")
        if isinstance(stored_mix, dict) and stored_mix:
            raw = ",".join(f"{key}:{value}" for key, value in stored_mix.items())
            cfg.content_mix = parse_content_mix(raw)

        self._tz = self._make_timezone()

    def _make_timezone(self) -> tzinfo:
        try:
            return ZoneInfo(self.cfg.tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            self.log.warning("Часовой пояс %s не найден, использую UTC+3", self.cfg.tz_name)
            return timezone(timedelta(hours=3))

    def _local_now(self) -> datetime:
        return datetime.now(self._tz)

    def _is_active_now(self) -> bool:
        start, end = self.cfg.active_hours
        if start == end:
            return True
        hour = self._local_now().hour
        if end > start:
            return start <= hour < end
        return hour >= start or hour < end

    def _seconds_until_active(self) -> float:
        now = self._local_now()
        start, end = self.cfg.active_hours
        if start == end:
            return 60.0
        if end > start:
            target_day = now.date() if now.hour < start else now.date() + timedelta(days=1)
        else:
            target_day = now.date() if start > now.hour else now.date() + timedelta(days=1)
        target = datetime.combine(target_day, dt_time(start, 0), tzinfo=self._tz)
        return max(60.0, (target - now).total_seconds())

    def _fmt_time(self, ts: float | int | None) -> str:
        if not ts:
            return "—"
        return datetime.fromtimestamp(float(ts), self._tz).strftime("%d.%m %H:%M")

    def _mix_text(self) -> str:
        mix = self.cfg.content_mix
        total = sum(mix.values())
        if total <= 0:
            return "—"
        return (
            f"коты {round(mix.get('cat', 0) * 100 / total)}% · "
            f"смешное {round(mix.get('funny', 0) * 100 / total)}% · "
            f"вебмы {round(mix.get('webm', 0) * 100 / total)}%"
        )

    def stats(self) -> dict[str, Any]:
        base = self.storage.stats()
        next_post = self.storage.get_state("next_post")
        base.update(
            {
                "paused": self.paused,
                "next_post_ts": next_post,
                "next_post_local": self._fmt_time(next_post),
                "active_now": self._is_active_now(),
                "active_hours": f"{self.cfg.active_hours[0]:02d}-{self.cfg.active_hours[1]:02d}",
                "sources": self.cfg.sources_configured,
                "queries": len(self.cfg.search_queries),
                "funny_queries": len(self.cfg.funny_queries),
                "webm_queries": len(self.cfg.webm_queries),
                "content_mix": self.cfg.content_mix,
                "content_mix_text": self._mix_text(),
                "partners": len(self.cfg.partners),
                "admin_configured": self.admin_id is not None,
            }
        )
        return base

    async def run_once(self) -> bool:
        """Один цикл: проверить Telegram и опубликовать один пост. Для GitHub Actions."""
        try:
            me = await self.telegram.get_me()
            username = (me.get("result") or {}).get("username")
            if username:
                self.log.info("Бот: @%s", username)
        except Exception as exc:  # noqa: BLE001
            self.log.error("Не удалось связаться с api.telegram.org: %s", exc)
            return False

        self.log.info("Микс контента: %s", self._mix_text())
        if self.paused:
            self.log.info("Постинг на паузе — пропускаю")
            return False
        if not self._is_active_now():
            self.log.info("Сейчас не активные часы (%02d-%02d) — пропускаю", *self.cfg.active_hours)
            return False
        return await self.post_one()

    async def run(self) -> None:
        try:
            me = await self.telegram.get_me()
            username = (me.get("result") or {}).get("username")
            if username:
                self.log.info("Бот: @%s", username)
        except Exception as exc:  # noqa: BLE001
            self.log.error("Не удалось связаться с api.telegram.org: %s", exc)
            self.log.error(
                "Проверь интернет/VPN/прокси на этом ПК или перенеси бота в облако — "
                "без доступа к Telegram API бот не сможет получать команды и публиковать посты."
            )

        if self.storage.get_state("next_post") is None:
            self.storage.set_state("next_post", time.time() + max(1, self.cfg.first_post_delay_sec))

        health = HealthServer(self.cfg.health_port, self.stats, self.log)
        await health.start()

        self.log.info("Микс контента: %s", self._mix_text())

        if self.admin_id is None and not self.cfg.dry_run:
            self.log.info("Админ не задан — напиши боту /start в личку, чтобы он запомнил твой ID")

        try:
            await asyncio.gather(self._command_loop(), self._post_loop())
        finally:
            await health.stop()

    async def _command_loop(self) -> None:
        offset = int(self.storage.get_state("tg_offset", 0) or 0)
        while True:
            try:
                updates = await self.telegram.get_updates(offset, timeout=10)
                for update in updates:
                    uid = update.get("update_id")
                    if isinstance(uid, int):
                        offset = max(offset, uid + 1)
                    await self._handle_update(update)
                self.storage.set_state("tg_offset", offset)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.log.warning("Ошибка опроса команд: %s", exc)
                await asyncio.sleep(10)
            await asyncio.sleep(0.2)

    async def _handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or update.get("edited_message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat") or {}
        if chat.get("type") != "private":
            return
        text = str(message.get("text") or "").strip()
        if not text:
            return
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            return

        if self.admin_id is None:
            self.admin_id = chat_id
            self.storage.set_state("admin_id", chat_id)
            await self.telegram.send_message(
                chat_id,
                "✅ Запомнил тебя как администратора.\n\n" + self._help_text(),
            )
            self.log.info("Администратор установлен: %s", chat_id)
            return

        if chat_id != self.admin_id:
            await self.telegram.send_message(chat_id, "⛔ Нет доступа.")
            return

        command = text.split(maxsplit=1)[0].split("@", 1)[0].lower()
        if command in ("/start", "/help"):
            await self.telegram.send_message(chat_id, self._help_text())
        elif command == "/status":
            await self.telegram.send_message(chat_id, self._status_text())
        elif command == "/stats":
            await self.telegram.send_message(chat_id, self._stats_text())
        elif command == "/pause":
            self.paused = True
            self.storage.set_state("paused", True)
            await self.telegram.send_message(chat_id, "⏸ Автопостинг остановлен.")
        elif command == "/resume":
            self.paused = False
            self.storage.set_state("paused", False)
            self.storage.set_state("next_post", time.time() + 30)
            await self.telegram.send_message(chat_id, "▶️ Автопостинг возобновлён.")
        elif command == "/now":
            asyncio.create_task(self._forced_post())
            await self.telegram.send_message(chat_id, "🚀 Запускаю публикацию...")
        elif command == "/interval":
            parts = text.split()
            if len(parts) < 2 or not parts[1].isdigit():
                await self.telegram.send_message(chat_id, "Использование: /interval 120\n (минуты)")
                return
            minutes = max(5, min(10080, int(parts[1])))
            self.cfg.post_interval_min = minutes
            self.storage.set_state("post_interval_min", minutes)
            self.storage.set_state("next_post", time.time() + minutes * 60)
            await self.telegram.send_message(chat_id, f"✅ Интервал: {minutes} мин.")
        elif command == "/sources":
            names = ", ".join(self.cfg.sources_configured) or "нет"
            queries = ", ".join(self.cfg.search_queries)
            funny_queries = ", ".join(self.cfg.funny_queries)
            webm_queries = ", ".join(self.cfg.webm_queries)
            await self.telegram.send_message(
                chat_id,
                f"📡 Источники: <b>{html.escape(names)}</b>\n"
                f"🐾 Коты: {html.escape(queries)}\n"
                f"😂 Смешное: {html.escape(funny_queries)}\n"
                f"🎬 Вебмы: {html.escape(webm_queries)}",
            )
        elif command == "/mix":
            parts = text.split()
            if len(parts) < 2:
                await self.telegram.send_message(chat_id, "Использование: /mix cat:30,funny:40,webm:30")
                return
            new_mix = parse_content_mix(parts[1])
            self.cfg.content_mix = new_mix
            self.storage.set_state("content_mix", new_mix)
            await self.telegram.send_message(chat_id, f"✅ Микс контента: {self._mix_text()}")
        else:
            await self.telegram.send_message(chat_id, "Не понимаю команду. Напиши /help.")

    def _help_text(self) -> str:
        return (
            "<b>KotoPotok — управление</b>\n\n"
            "/status — состояние бота\n"
            "/stats — статистика постов\n"
            "/now — опубликовать прямо сейчас\n"
            "/pause — поставить на паузу\n"
            "/resume — продолжить\n"
            "/interval 120 — менять интервал (минуты)\n"
            "/mix cat:30,funny:40,webm:30 — доли контента\n"
            "/sources — источники и запросы\n"
            "/help — эта справка\n\n"
            "Бот работает сам: чередует котов, смешные моменты и вебмы."
        )

    def _status_text(self) -> str:
        s = self.stats()
        state = "⏸ пауза" if s["paused"] else "▶️ работает"
        activity = "сейчас активен" if s["active_now"] else "вне активных часов"
        last = s.get("last_post") or {}
        last_ts = last.get("posted_at")
        return (
            f"<b>Состояние</b>\n"
            f"Режим: {state}\n"
            f"Расписание: {activity} ({s['active_hours']})\n"
            f"Следующий пост: {s['next_post_local']}\n"
            f"Всего постов: {s['total']}\n"
            f"За 24ч: {s['last24h']}\n"
            f"Микс: {s['content_mix_text']}\n"
            f"Последний: {html.escape(str(last.get('source', '—')))} — {self._fmt_time(last_ts)}\n"
            f"Источники: {html.escape(', '.join(s['sources']) or 'нет')}"
        )

    def _stats_text(self) -> str:
        s = self.stats()
        lines = [
            "<b>Статистика</b>",
            f"Всего: {s['total']}",
            f"За 24ч: {s['last24h']}",
            f"Видео: {s['by_kind'].get('video', 0)}",
            f"Фото: {s['by_kind'].get('photo', 0)}",
            f"Коты: {s['by_topic'].get('cat', 0)} · Смешное: {s['by_topic'].get('funny', 0)} · Вебмы: {s['by_topic'].get('webm', 0)}",
            f"Партнёрских ссылок: {s['partners']}",
            "",
            "Последние посты:",
        ]
        for item in self.storage.recent(5):
            lines.append(
                f"• {html.escape(item['source'])} / {item['topic']} — {self._fmt_time(item['posted_at'])}"
            )
        return "\n".join(lines)

    async def _forced_post(self) -> None:
        try:
            ok = await self.post_one()
            if self.admin_id:
                text = "✅ Пост опубликован." if ok else "⚠️ Нового подходящего поста не нашёл."
                await self.telegram.send_message(self.admin_id, text)
        except Exception as exc:  # noqa: BLE001
            self.log.exception("Ошибка ручной публикации")
            await self._notify_error(f"Ошибка ручной публикации: {exc}")

    async def _post_loop(self) -> None:
        while True:
            try:
                next_ts = float(self.storage.get_state("next_post", time.time() + 60) or 0)
                while next_ts - time.time() > 0 and not self.paused:
                    await asyncio.sleep(min(30.0, next_ts - time.time()))
                    next_ts = float(self.storage.get_state("next_post", next_ts) or next_ts)
                if self.paused:
                    await asyncio.sleep(30)
                    continue
                if not self._is_active_now():
                    wait = self._seconds_until_active()
                    self.storage.set_state("next_post", time.time() + wait)
                    await asyncio.sleep(min(60.0, wait))
                    continue

                await self.post_one()
                self.storage.set_state("next_post", time.time() + jittered_interval(self.cfg))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.log.exception("Ошибка цикла публикации")
                await self._notify_error(f"Ошибка публикации: {exc}")
                self.storage.set_state("next_post", time.time() + 300)
                await asyncio.sleep(30)

    async def post_one(self) -> bool:
        candidates = await self.sources.fetch_candidates(limit=12)
        fresh = [item for item in candidates if not self.storage.was_posted(item.identity)]
        if not fresh:
            self.log.warning("Все найденные медиа уже публиковались")
            self.storage.set_state("next_post", time.time() + 600)
            return False

        attempts = fresh[:5]
        last_error: Exception | None = None
        for index, item in enumerate(attempts):
            try:
                content = await prepare_media(item, self.cfg, self.log)
                post_number = int(self.storage.stats()["total"]) + 1
                caption = build_caption(item, self.cfg, post_number)
                await self.telegram.send_media(item, content, caption)
                self.storage.mark_posted(item, caption)
                self.log.info("Опубликовано: %s (%s, %s)", item.display_title, item.source, item.extension)
                return True
            except Exception as exc:  # noqa: BLE001 - пробуем следующий ролик
                last_error = exc
                self.log.warning(
                    "Не удалось опубликовать '%s': %s", item.display_title[:60], exc
                )
                if index < len(attempts) - 1:
                    await asyncio.sleep(3)

        if last_error:
            raise last_error
        return False

    async def _notify_error(self, message: str) -> None:
        if not self.admin_id:
            return
        now = time.time()
        last = float(self.storage.get_state("last_error_notify", 0) or 0)
        if now - last < 3600:
            return
        self.storage.set_state("last_error_notify", now)
        await self.telegram.send_message(
            self.admin_id,
            f"⚠️ <b>KotoPotok</b>\n{html.escape(message[:600])}",
        )
