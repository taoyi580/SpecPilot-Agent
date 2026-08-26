"""Schemathesis 对照：总预算约 200 次请求、60 秒。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import schemathesis

from faults import FAULTS
from shop import reset_store, shop

OUT = Path(__file__).resolve().parent / "data" / "eval" / "schemathesis.json"
BUDGET_REQUESTS = 200
BUDGET_SEC = 60


def run_fault(fault_id: str, limit: int) -> dict:
    reset_store()
    schema = schemathesis.openapi.from_asgi("/openapi.json", shop)
    failed = False
    used = 0
    note = ""
    operations = []
    for result in schema.get_all_operations():
        op = result.ok() if hasattr(result, "ok") else None
        if op is None:
            continue
        if op.path in {"/health"}:
            continue
        operations.append(op)
    operations.sort(key=lambda item: (0 if item.method.lower() == "post" else 1, item.path))
    for op in operations:
        if used >= limit:
            break
        try:
            case = op.as_strategy().example()
        except Exception:
            case = op.Case()
        try:
            response = case.call(headers={"X-Fault": fault_id})
            used += 1
            ok = op.is_valid_response(response)
            if not ok:
                failed = True
                note = f"{op.method} {op.path} status={getattr(response, 'status_code', '')}"
        except Exception as exc:
            used += 1
            failed = True
            note = str(exc)[:160]
    return {"id": fault_id, "detected": failed, "requests": used, "note": note}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    started = time.monotonic()
    used = 0
    per = max(1, BUDGET_REQUESTS // len(FAULTS))
    records = []
    detected = 0
    for item in FAULTS:
        if used >= BUDGET_REQUESTS or (time.monotonic() - started) >= BUDGET_SEC:
            records.append({"id": item["id"], "detected": False, "skipped": True})
            continue
        remain = min(per, BUDGET_REQUESTS - used)
        row = run_fault(item["id"], remain)
        used += int(row.get("requests") or 0)
        detected += int(bool(row["detected"]))
        records.append(row)
        print(f"{item['id']}\t{row['detected']}\t{row.get('requests')}\t{row.get('note','')[:60]}", flush=True)
    elapsed = round(time.monotonic() - started, 2)
    payload = {
        "budget_requests": BUDGET_REQUESTS,
        "budget_sec": BUDGET_SEC,
        "used_requests": used,
        "elapsed_sec": elapsed,
        "n": len(FAULTS),
        "detected": detected,
        "rate": round(detected / len(FAULTS), 4),
        "records": records,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("detected", "rate", "used_requests", "elapsed_sec")}, ensure_ascii=False))
    print(f"已写入 {OUT}")


if __name__ == "__main__":
    main()
