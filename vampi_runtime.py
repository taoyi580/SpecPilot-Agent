"""拉起本地 VAmPI（公开靶场），供评测脚本调用。"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
VAMPI_DIR = ROOT / "third_party" / "vampi"
PORT = int(os.getenv("SPECPILOT_VAMPI_PORT", "5055"))
VAMPI_REPO = "https://github.com/erev0s/VAmPI.git"

_PROC: subprocess.Popen | None = None


def python_bin() -> Path:
    return VAMPI_DIR / ".venv" / "Scripts" / "python.exe"


def ensure_cloned() -> None:
    if (VAMPI_DIR / "app.py").exists():
        return
    VAMPI_DIR.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "clone", "--depth", "1", VAMPI_REPO, str(VAMPI_DIR)])


def patch_runner() -> None:
    path = VAMPI_DIR / "app.py"
    text = path.read_text(encoding="utf-8")
    old = "vuln_app.run(host='0.0.0.0', port=5000, debug=True)"
    new = "vuln_app.run(host='127.0.0.1', port=int(os.getenv('PORT', '5000')), debug=False)"
    if old in text:
        path.write_text(text.replace(old, new), encoding="utf-8")


def pids_on_port(port: int) -> list[int]:
    try:
        raw = subprocess.check_output(["netstat", "-ano"], text=True, errors="ignore")
    except Exception:
        return []
    pids: list[int] = []
    needle = f":{port} "
    for line in raw.splitlines():
        if needle not in line or "LISTENING" not in line.upper():
            continue
        parts = line.split()
        try:
            pid = int(parts[-1])
        except Exception:
            continue
        if pid > 0:
            pids.append(pid)
    return list(dict.fromkeys(pids))


def kill_port(port: int) -> None:
    for pid in pids_on_port(port):
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)


def wait_up(base_url: str, seconds: float = 30) -> None:
    deadline = time.time() + seconds
    last = ""
    while time.time() < deadline:
        try:
            response = httpx.get(base_url + "/", timeout=2)
            if response.status_code < 500:
                return
            last = str(response.status_code)
        except Exception as exc:
            last = str(exc)
        time.sleep(0.4)
    raise RuntimeError(f"VAmPI 未在 {seconds}s 内启动：{last}")


def start(vulnerable: bool, port: int = PORT) -> str:
    global _PROC
    ensure_cloned()
    patch_runner()
    py = python_bin()
    if not py.exists():
        raise RuntimeError(f"请先用 Python 3.12 安装 VAmPI 依赖：{py}")
    stop()
    kill_port(5000)
    kill_port(port)
    env = os.environ.copy()
    env["vulnerable"] = "1" if vulnerable else "0"
    env["tokentimetolive"] = "600"
    env["PORT"] = str(port)
    log = VAMPI_DIR / "_eval.err.log"
    _PROC = subprocess.Popen(
        [str(py), "app.py"],
        cwd=str(VAMPI_DIR),
        env=env,
        stdout=log.open("w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        wait_up(base)
    except Exception:
        stop()
        raise
    return base


def stop() -> None:
    global _PROC
    if _PROC is not None:
        _PROC.terminate()
        try:
            _PROC.wait(timeout=5)
        except Exception:
            _PROC.kill()
        _PROC = None
    kill_port(PORT)