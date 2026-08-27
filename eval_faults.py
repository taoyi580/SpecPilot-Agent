"""逐条注入 36 个故障，看 Agent 能否检出，并统计可导出的失败请求。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from agent import run_agent
from faults import FAULTS

OUT = Path(__file__).resolve().parent / "data" / "eval" / "faults.json"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    records = []
    detected = 0
    exportable = 0
    for item in FAULTS:
        result = run_agent(fault=item["id"], auto_approve=True, email="user@shop.local")
        ok = bool(result["detected"])
        detected += int(ok)
        can_export = bool(ok and result.get("export"))
        exportable += int(can_export)
        records.append(
            {
                "id": item["id"],
                "family": item["family"],
                "title": item["title"],
                "detected": ok,
                "reason": result.get("reason"),
                "exportable": can_export,
                "request_count": result.get("request_count"),
            }
        )
        print(f"{item['id']}\t{ok}\t{result.get('reason','')[:80]}", flush=True)
    payload = {
        "n": len(FAULTS),
        "detected": detected,
        "rate": round(detected / len(FAULTS), 4),
        "exportable": exportable,
        "planner": "openapi",
        "note": "规划由 OpenAPI 生成，不读取故障编号；评测只向被测服务注入 X-Fault。",
        "records": records,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("n", "detected", "rate", "exportable")}, ensure_ascii=False))
    print(f"已写入 {OUT}")


if __name__ == "__main__":
    main()
