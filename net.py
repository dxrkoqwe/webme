from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any


USER_AGENT = "KotoPotokBot/1.0 (https://github.com/dxrkoqwe/webme)"


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


def _build_url(url: str, params: dict[str, Any] | None) -> str:
    if not params:
        return url
    clean = {k: v for k, v in params.items() if v is not None and v != ""}
    if not clean:
        return url
    sep = "&" if "?" in url else "?"
    return url + sep + urllib.parse.urlencode(clean)


def _request_sync(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    form: dict[str, str] | None = None,
    files: dict[str, tuple[str, bytes, str]] | None = None,
    timeout: int = 25,
) -> dict[str, Any]:
    final_headers = {"Accept": "application/json", "Accept-Encoding": "identity", "User-Agent": USER_AGENT}
    if headers:
        final_headers.update(headers)

    body: bytes | None = None
    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        final_headers["Content-Type"] = "application/json; charset=utf-8"
    elif files:
        body, content_type = _multipart_body(form or {}, files)
        final_headers["Content-Type"] = content_type
    elif form is not None:
        body = urllib.parse.urlencode(form).encode("utf-8")
        final_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"

    req = urllib.request.Request(_build_url(url, params), data=body, headers=final_headers, method=method)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            retryable = method == "GET" and exc.code in (429, 500, 502, 503, 504)
            if retryable and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise HttpError(exc.code, detail) from exc
        except urllib.error.URLError as exc:
            if method == "GET" and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError(f"Сеть недоступна: {exc.reason}") from exc

    if not raw:
        return {}
    try:
        parsed: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Не удалось разобрать JSON: {raw[:200]!r}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Ответ API не является объектом JSON")
    return parsed


async def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    form: dict[str, str] | None = None,
    files: dict[str, tuple[str, bytes, str]] | None = None,
    timeout: int = 25,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _request_sync,
        method,
        url,
        headers=headers,
        params=params,
        json_body=json_body,
        form=form,
        files=files,
        timeout=timeout,
    )


def _multipart_body(
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    boundary = "----KotoPotok" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )
    for field_name, (filename, content, mime) in files.items():
        safe_name = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{field_name}"; filename="{safe_name}"\r\n'
                f"Content-Type: {mime}\r\n\r\n"
            ).encode("utf-8")
        )
        chunks.append(content)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class MediaTooLarge(RuntimeError):
    pass


def _download_sync(url: str, max_bytes: int, timeout: int) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                declared = resp.headers.get("Content-Length")
                if declared:
                    try:
                        if int(declared) > max_bytes:
                            raise MediaTooLarge(f"файл слишком большой: {declared} байт")
                    except ValueError:
                        pass
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise MediaTooLarge(f"файл слишком большой: >{max_bytes} байт")
                    chunks.append(chunk)
                content_type = resp.headers.get("Content-Type", "")
            return b"".join(chunks), content_type
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise HttpError(exc.code, detail) from exc
        except urllib.error.URLError as exc:
            if attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"Не удалось скачать медиа: {exc.reason}") from exc
    raise RuntimeError("Не удалось скачать медиа")


async def download_media(url: str, max_bytes: int, timeout: int = 60) -> tuple[bytes, str]:
    return await asyncio.to_thread(_download_sync, url, max_bytes, timeout)
