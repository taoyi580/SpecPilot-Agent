"""受控 HTTP 执行：白名单、超时、限速。"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from constraints import TIMEOUT_SEC, RateGate, assert_allowed_url
from shop import shop

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


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
