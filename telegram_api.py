from __future__ import annotations

import logging
from typing import Any

from config import Config
from net import HttpError, request_json
from sources import MediaItem


class TelegramApi:
    def __init__(self, cfg: Config, log: logging.Logger):
        self.cfg = cfg
        self.log = log
        self._base = f"https://api.telegram.org/bot{cfg.bot_token}" if cfg.bot_token else ""
        self._dry_counter = 0

    async def get_me(self) -> dict[str, Any]:
        if self.cfg.dry_run or not self._base:
            return {"ok": True, "result": {"username": "dry_run_bot"}}
        return await self._call("getMe")

    async def get_updates(self, offset: int, timeout: int = 10) -> list[dict[str, Any]]:
        if self.cfg.dry_run or not self._base:
            return []
        payload = await self._call("getUpdates", params={"offset": offset, "timeout": timeout}, request_timeout=timeout + 12)
        updates = payload.get("result", [])
        return [u for u in updates if isinstance(u, dict)]

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        disable_preview: bool = True,
    ) -> bool:
        if self.cfg.dry_run or not self._base:
            self.log.info("[DRY] сообщение в %s: %s", chat_id, text.replace("\n", " | ")[:300])
            return True
        try:
            await self._call(
                "sendMessage",
                form={
                    "chat_id": str(chat_id),
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": "true" if disable_preview else "false",
                },
            )
            return True
        except Exception as exc:  # noqa: BLE001
            self.log.warning("Не удалось отправить сообщение в Telegram: %s", exc)
            return False

    async def send_media(self, item: MediaItem, content: bytes, caption: str) -> dict[str, Any]:
        if self.cfg.dry_run or not self._base:
            self._dry_counter += 1
            self.log.info(
                "[DRY] пост #%s: %s (%s, %s байт)\n%s",
                self._dry_counter,
                item.display_title,
                item.kind,
                len(content),
                caption,
            )
            return {"ok": True, "result": {"message_id": self._dry_counter}}

        field = "video" if item.kind == "video" else "photo"
        filename = f"kotopotok{item.extension}"
        form: dict[str, str] = {
            "chat_id": self.cfg.channel_id,
            "caption": caption,
            "parse_mode": "HTML",
        }
        if item.kind == "video":
            form["supports_streaming"] = "true"
        try:
            return await self._call(
                "sendVideo" if item.kind == "video" else "sendPhoto",
                form=form,
                files={field: (filename, content, item.mime)},
                request_timeout=180,
            )
        except HttpError as exc:
            if item.extension != ".webm" or exc.status != 400:
                raise
            self.log.warning("Telegram не принял webm как видео, отправляю документом: %s", exc)
            doc_form = dict(form)
            doc_form.pop("supports_streaming", None)
            return await self._call(
                "sendDocument",
                form=doc_form,
                files={"document": (filename, content, item.mime)},
                request_timeout=180,
            )

    async def _call(
        self,
        method: str,
        *,
        params: dict[str, Any] | None = None,
        form: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        request_timeout: int = 30,
    ) -> dict[str, Any]:
        payload = await request_json(
            "POST" if (form or files) else "GET",
            f"{self._base}/{method}",
            params=params,
            form=form,
            files=files,
            timeout=request_timeout,
        )
        if not payload.get("ok"):
            description = payload.get("description", "неизвестная ошибка Telegram")
            raise RuntimeError(f"Telegram {method}: {description}")
        return payload
