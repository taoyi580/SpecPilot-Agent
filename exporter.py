"""把失败请求收成最短 curl / pytest。"""

from __future__ import annotations

import json
from pathlib import Path

EXPORT_DIR = Path(__file__).resolve().parent / "exports"


def minimize(call: dict) -> dict:
    headers = {
        key: value
        for key, value in (call.get("headers") or {}).items()
        if key.lower() in {"authorization", "content-type", "idempotency-key", "x-fault"}
    }
    return {
        "method": call.get("method"),
        "url": call.get("url"),
        "headers": headers,
        "json": call.get("json"),
        "status": call.get("status"),
    }


def to_curl(call: dict) -> str:
    item = minimize(call)
    parts = [f"curl -sS -X {item['method']}"]
    for key, value in (item.get("headers") or {}).items():
        parts.append(f"-H {json.dumps(f'{key}: {value}')}")
    if item.get("json") is not None:
        parts.append(f"-d {json.dumps(json.dumps(item['json'], ensure_ascii=False))}")
    parts.append(json.dumps(item["url"]))
    return " ".join(parts)


def to_pytest(call: dict) -> str:
    item = minimize(call)
    return (
        "import httpx\n\n"
        "def test_replay_minimized_failure():\n"
        f"    response = httpx.request({item['method']!r}, {item['url']!r}, "
        f"headers={item.get('headers') or {}}, json={item.get('json')}, timeout=3)\n"
        f"    assert response.status_code == {item.get('status')}\n"
    )


def write_exports(fault_id: str, call: dict) -> dict:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    curl = to_curl(call)
    pytest_src = to_pytest(call)
    (EXPORT_DIR / f"{fault_id}.curl.sh").write_text(curl + "\n", encoding="utf-8")
    (EXPORT_DIR / f"{fault_id}.py").write_text(pytest_src, encoding="utf-8")
    return {"curl": curl, "pytest": pytest_src, "minimized": minimize(call)}
