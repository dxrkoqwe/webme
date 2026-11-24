from __future__ import annotations

import asyncio
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable


class HealthServer:
    def __init__(self, port: int, stats_provider: Callable[[], dict[str, Any]], log: logging.Logger):
        self.port = port
        self.stats_provider = stats_provider
        self.log = log
        self._server: ThreadingHTTPServer | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(asyncio.to_thread(self._serve_forever))
        self.log.info("Health endpoint: http://0.0.0.0:%s/health", self.port)

    def _serve_forever(self) -> None:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                outer.log.debug("health %s - %s", self.client_address[0], fmt % args)

            def _send(self, status: int, body: bytes, content_type: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                path = self.path.split("?", 1)[0]
                if path in ("/health", "/stats"):
                    try:
                        payload = {"ok": True, **outer.stats_provider()}
                    except Exception as exc:  # noqa: BLE001
                        payload = {"ok": False, "error": str(exc)}
                    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
                    self._send(200 if payload.get("ok") else 500, body, "application/json; charset=utf-8")
                    return
                if path == "/":
                    body = (
                        "<h1>KotoPotok</h1>"
                        "<p>Autoposter is running.</p>"
                        '<p><a href="/health">/health</a> · <a href="/stats">/stats</a></p>'
                    ).encode("utf-8")
                    self._send(200, body, "text/html; charset=utf-8")
                    return
                self._send(404, b"not found", "text/plain; charset=utf-8")

        self._server = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        self._server.serve_forever()

    async def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._task:
            self._task.cancel()
