from __future__ import annotations

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


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/faults")
def list_faults() -> dict:
    return {"items": FAULTS, "n": len(FAULTS)}


@app.post("/api/run")
def run(body: RunIn) -> dict:
    return run_agent(fault=body.fault, auto_approve=body.auto_approve, email=body.email)
