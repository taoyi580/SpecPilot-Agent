"""受控 HTTP 执行：白名单、超时、限速。"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from fastapi.testclient import TestClient

from constraints import TIMEOUT_SEC, RateGate, assert_allowed_url
from shop import shop

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def encode_path(path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    query = ""
    if "?" in path:
        path, query = path.split("?", 1)
        query = "?" + query
    parts = []
    for part in path.split("/"):
        parts.append(quote(part, safe="") if part else "")
    return "/".join(parts) + query


class Executor:
    def __init__(self, base_url: str = "http://testserver"):
        self.base_url = base_url.rstrip("/")
        self.gate = RateGate()
        self.client = TestClient(shop)

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict | None = None,
        json: Any = None,
        content: str | None = None,
        fault: str | None = None,
    ) -> dict:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        assert_allowed_url(url)
        self.gate.check()
        hdrs = dict(headers or {})
        if fault:
            hdrs["X-Fault"] = fault
        kwargs: dict[str, Any] = {"headers": hdrs}
        if content is not None:
            kwargs["content"] = content.encode("utf-8") if isinstance(content, str) else content
        elif json is not None:
            kwargs["json"] = json
        response = self.client.request(method.upper(), path, **kwargs)
        try:
            body = response.json()
        except Exception:
            body = response.text
        return {
            "method": method.upper(),
            "path": path,
            "url": url,
            "headers": hdrs,
            "json": json,
            "status": response.status_code,
            "body": body,
            "elapsed_ms": 0,
        }


class HttpExecutor:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.gate = RateGate()
        self.client = httpx.Client(timeout=TIMEOUT_SEC, follow_redirects=True)

    def close(self) -> None:
        self.client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict | None = None,
        json: Any = None,
        content: str | None = None,
        fault: str | None = None,
    ) -> dict:
        encoded = encode_path(path)
        url = encoded if encoded.startswith("http") else f"{self.base_url}{encoded}"
        parsed = urlparse(url)
        assert_allowed_url(f"{parsed.scheme}://{parsed.netloc}/")
        self.gate.check()
        hdrs = dict(headers or {})
        kwargs: dict[str, Any] = {"headers": hdrs}
        if content is not None:
            kwargs["content"] = content.encode("utf-8") if isinstance(content, str) else content
        elif json is not None:
            kwargs["json"] = json
        started = time.perf_counter()
        try:
            response = self.client.request(method.upper(), url, **kwargs)
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            try:
                body = response.json()
            except Exception:
                body = response.text
            return {
                "method": method.upper(),
                "path": path,
                "url": str(response.url),
                "headers": hdrs,
                "json": json,
                "status": response.status_code,
                "body": body,
                "elapsed_ms": elapsed,
                "timeout": False,
            }
        except httpx.TimeoutException:
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            return {
                "method": method.upper(),
                "path": path,
                "url": url,
                "headers": hdrs,
                "json": json,
                "status": 0,
                "body": "timeout",
                "elapsed_ms": elapsed,
                "timeout": True,
            }
