from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import replace
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

        send_item = item
        send_content = content
        if item.kind == "video" and item.extension == ".webm":
            converted = await self._convert_webm(content)
            if converted:
                send_content, mime, extension = converted
                send_item = replace(item, mime=mime, extension=extension)
                self.log.info("WebM перекодирован в MP4 — Telegram покажет обычным видео")

        field = "video" if send_item.kind == "video" else "photo"
        filename = f"video{send_item.extension}"
        form: dict[str, str] = {
            "chat_id": self.cfg.channel_id,
            "caption": caption,
            "parse_mode": "HTML",
        }
        if send_item.kind == "video" and send_item.extension == ".mp4":
            form["supports_streaming"] = "true"
        try:
            return await self._call(
                "sendVideo" if send_item.kind == "video" else "sendPhoto",
                form=form,
                files={field: (filename, send_content, send_item.mime)},
                request_timeout=180,
            )
        except (HttpError, RuntimeError) as exc:
            if send_item.extension != ".webm" or not self._is_bad_request(exc):
                raise
            self.log.warning("Telegram не принял webm как видео: %s", exc)

        # Если ffmpeg недоступен — пробуем отправить webm как анимацию.
        animation_form = dict(form)
        animation_form.pop("supports_streaming", None)
        try:
            return await self._call(
                "sendAnimation",
                form=animation_form,
                files={"animation": (filename, send_content, send_item.mime)},
                request_timeout=180,
            )
        except (HttpError, RuntimeError) as exc:
            self.log.warning("sendAnimation тоже не принял webm, отправляю документом: %s", exc)

        doc_form = dict(form)
        doc_form.pop("supports_streaming", None)
        return await self._call(
            "sendDocument",
            form=doc_form,
            files={"document": (filename, send_content, send_item.mime)},
            request_timeout=180,
        )

    async def _convert_webm(self, content: bytes) -> tuple[bytes, str, str] | None:
        """Перекодировать VP9 WebM в H.264 MP4 через ffmpeg, если он установлен."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.log.info("ffmpeg не найден — отправляю webm как есть")
            return None
        try:
            return await asyncio.to_thread(self._convert_webm_sync, ffmpeg, content)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("Не удалось перекодировать webm в mp4: %s", exc)
            return None

    def _convert_webm_sync(self, ffmpeg: str, content: bytes) -> tuple[bytes, str, str] | None:
        with tempfile.TemporaryDirectory(prefix="kotopotok_") as tmp:
            src = os.path.join(tmp, "input.webm")
            dst = os.path.join(tmp, "output.mp4")
            with open(src, "wb") as fh:
                fh.write(content)
            cmd = [
                ffmpeg,
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-i", src,
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "28",
                "-vf", "scale='min(640,iw)':-2",
                "-c:a", "aac",
                "-b:a", "64k",
                "-movflags", "+faststart",
                dst,
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=180)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[:300])
            with open(dst, "rb") as fh:
                converted = fh.read()
        if not converted or len(converted) > 49 * 1024 * 1024:
            raise RuntimeError("перекодированный mp4 пустой или слишком большой")
        return converted, "video/mp4", ".mp4"

    @staticmethod
    def _is_bad_request(exc: Exception) -> bool:
        if isinstance(exc, HttpError):
            return exc.status == 400
        return "400" in str(exc)

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
