"""无故障场景：24 条正常注册到下单，统计误报。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from agent import run_agent

OUT = Path(__file__).resolve().parent / "data" / "eval" / "false_positive.json"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    false_hits = 0
    records = []
    for i in range(24):
        email = f"fp{i}@shop.local"
        result = run_agent(fault="", auto_approve=True, email=email)
        bad = bool(result["detected"])
        false_hits += int(bad)
        records.append({"email": email, "false_positive": bad, "reason": result.get("reason")})
        print(f"{i}\t{bad}\t{result.get('reason','')[:60]}", flush=True)
    payload = {
        "n": 24,
        "false_positives": false_hits,
        "rate": round(false_hits / 24, 4),
        "records": records,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("n", "false_positives", "rate")}, ensure_ascii=False))
    print(f"已写入 {OUT}")


if __name__ == "__main__":
    main()
