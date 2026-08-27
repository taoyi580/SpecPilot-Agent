"""公开集评测：VAmPI README 的 9 类已知问题，对照 Schemathesis。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx
import schemathesis

from agent import run_openapi_agent
from executor import HttpExecutor
from exporter import write_exports
from oracles_vampi import CLASSES, score_history
from vampi_runtime import PORT, start, stop

OUT = Path(__file__).resolve().parent / "data" / "eval" / "vampi.json"
BUDGET_REQUESTS = 200
BUDGET_SEC = 60
IDENTITY = {
    "username": "specpilot1",
    "password": "SpecP1pass",
    "email": "specpilot1@mail.com",
}


def load_spec(base_url: str) -> dict:
    schema = schemathesis.openapi.from_url(base_url + "/openapi.json")
    return schema.raw_schema


def run_agent_on(base_url: str, spec: dict) -> dict:
    executor = HttpExecutor(base_url)
    try:
        result = run_openapi_agent(spec, executor, auto_approve=True, **IDENTITY)
    finally:
        executor.close()
    scored = score_history(result["history"], agent_username=IDENTITY["username"])
    exportable = 0
    for item in scored["classes"]:
        if not item["hit"]:
            continue
        call = next((row for row in result["history"] if row.get("path") == item.get("path") and row.get("method") == item.get("method")), None)
        if call:
            try:
                write_exports("vampi_" + item["id"], call)
                exportable += 1
                item["exportable"] = True
            except Exception:
                item["exportable"] = False
    scored["request_count"] = result.get("request_count")
    scored["exportable"] = exportable
    scored["plan"] = result.get("plan")
    return scored


def _case_to_call(case, response) -> dict:
    path = getattr(case, "formatted_path", None) or getattr(case, "path", "")
    body: object
    try:
        body = response.json()
    except Exception:
        body = getattr(response, "text", "")
    elapsed = 0.0
    if getattr(response, "elapsed", None) is not None:
        elapsed = response.elapsed.total_seconds() * 1000
    payload = getattr(case, "body", None)
    return {
        "method": str(getattr(case, "method", "")).upper(),
        "path": path,
        "url": str(getattr(response, "url", path)),
        "status": int(getattr(response, "status_code", 0) or 0),
        "body": body,
        "json": payload if isinstance(payload, dict) else None,
        "headers": dict(getattr(case, "headers", None) or {}),
        "elapsed_ms": elapsed,
    }


def run_schemathesis(base_url: str) -> dict:
    schema = schemathesis.openapi.from_url(base_url + "/openapi.json")
    history: list[dict] = []
    used = 0
    started = time.monotonic()
    operations = []
    for item in schema.get_all_operations():
        op = item.ok() if hasattr(item, "ok") else None
        if op is None:
            continue
        operations.append(op)
    per = max(1, BUDGET_REQUESTS // max(1, len(operations)))
    for op in operations:
        for _ in range(per):
            if used >= BUDGET_REQUESTS or (time.monotonic() - started) >= BUDGET_SEC:
                break
            try:
                case = op.as_strategy().example()
            except Exception:
                case = op.Case()
            try:
                response = case.call(base_url=base_url)
                history.append(_case_to_call(case, response))
            except Exception as exc:
                history.append(
                    {
                        "method": str(op.method).upper(),
                        "path": op.path,
                        "status": 0,
                        "body": str(exc)[:200],
                        "json": None,
                        "headers": {},
                        "elapsed_ms": 0,
                    }
                )
            used += 1
        if used >= BUDGET_REQUESTS or (time.monotonic() - started) >= BUDGET_SEC:
            break
    scored = score_history(history, agent_username=IDENTITY["username"])
    scored["request_count"] = used
    scored["elapsed_sec"] = round(time.monotonic() - started, 2)
    return scored


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    payload: dict = {
        "dataset": "VAmPI",
        "source": "https://github.com/erev0s/VAmPI",
        "license": "MIT",
        "n": len(CLASSES),
        "classes": [item["title"] for item in CLASSES],
        "note": "标准答案是 VAmPI README 的 9 类已知问题。规划只读公开 OpenAPI，不读漏洞编号。",
    }
    try:
        print("启动 VAmPI vulnerable=1 ...", flush=True)
        base = start(True, PORT)
        spec = load_spec(base)
        try:
            httpx.get(base + "/createdb", timeout=10)
        except Exception:
            pass
        print(f"OpenAPI paths={len(spec.get('paths') or {})}", flush=True)
        agent = run_agent_on(base, spec)
        print("Agent", agent["detected"], "/", agent["n"], agent.get("hit_ids"), flush=True)
        schema_run = run_schemathesis(base)
        print("Schemathesis", schema_run["detected"], "/", schema_run["n"], schema_run.get("hit_ids"), flush=True)
        print("重启 VAmPI vulnerable=0 ...", flush=True)
        base = start(False, PORT)
        spec = load_spec(base)
        fp = run_agent_on(base, spec)
        print("vuln=0", fp["detected"], "/", fp["n"], fp.get("hit_ids"), flush=True)
        payload.update(
            {
                "agent": agent,
                "schemathesis": schema_run,
                "vuln0": fp,
                "budget_requests": BUDGET_REQUESTS,
                "budget_sec": BUDGET_SEC,
            }
        )
    finally:
        stop()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "agent": f"{payload['agent']['detected']}/{payload['n']}",
        "schemathesis": f"{payload['schemathesis']['detected']}/{payload['n']}",
        "vuln0": f"{payload['vuln0']['detected']}/{payload['n']}",
    }
    print(json.dumps(summary, ensure_ascii=False))
    print(f"已写入 {OUT}")


if __name__ == "__main__":
    main()
