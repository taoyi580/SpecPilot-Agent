from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agent import run_agent
from faults import FAULTS
from shop import shop

BASE = Path(__file__).resolve().parent
app = FastAPI(title="SpecPilot")
app.mount("/shop", shop)


class RunIn(BaseModel):
    fault: str = ""
    auto_approve: bool = True
    email: str = "demo@shop.local"


@app.get("/")
def home() -> FileResponse:
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/faults")
def list_faults() -> dict:
    return {"items": FAULTS, "n": len(FAULTS)}


@app.get("/api/stats")
def stats() -> dict:
    out = {}
    eval_dir = BASE / "data" / "eval"
    for name in ("vampi.json", "faults.json", "false_positive.json", "schemathesis.json"):
        path = eval_dir / name
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            data.pop("records", None)
            out[name.replace(".json", "")] = data
        path = eval_dir / name
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            data.pop("records", None)
            out[name.replace(".json", "")] = data
    return out


@app.post("/api/run")
def run(body: RunIn) -> dict:
    return run_agent(fault=body.fault, auto_approve=body.auto_approve, email=body.email)
