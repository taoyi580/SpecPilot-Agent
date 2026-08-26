"""执行层约束：Host 白名单、单请求超时 3 秒、全局限速 10 次/秒。"""

from __future__ import annotations

import time
from urllib.parse import urlparse


ALLOWED_HOSTS = {"127.0.0.1:8001", "localhost:8001", "shop.local", "testserver"}
TIMEOUT_SEC = 3.0
RATE_PER_SEC = 10


class ConstraintError(RuntimeError):
    pass


class RateGate:
    def __init__(self, per_sec: int = RATE_PER_SEC):
        self.per_sec = per_sec
        self.hits: list[float] = []

    def check(self) -> None:
        now = time.monotonic()
        self.hits = [item for item in self.hits if now - item < 1.0]
        if len(self.hits) >= self.per_sec:
            time.sleep(max(0.05, 1.0 - (now - self.hits[0])))
            now = time.monotonic()
            self.hits = [item for item in self.hits if now - item < 1.0]
        self.hits.append(now)


def assert_allowed_url(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if not host:
        raise ConstraintError("地址不完整")
    if host not in ALLOWED_HOSTS:
        raise ConstraintError(f"Host 不在白名单：{host}")
