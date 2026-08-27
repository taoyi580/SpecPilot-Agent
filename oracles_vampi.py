"""对照 VAmPI README 公开的 9 类问题打分。规划不读这些编号，只根据 HTTP 记录判定。"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote

CLASSES = [
    {"id": "sqli", "title": "SQLi Injection"},
    {"id": "unauth_password", "title": "Unauthorized Password Change"},
    {"id": "bola", "title": "Broken Object Level Authorization"},
    {"id": "mass_assignment", "title": "Mass Assignment"},
    {"id": "excessive_data", "title": "Excessive Data Exposure through debug endpoint"},
    {"id": "enumeration", "title": "User and Password Enumeration"},
    {"id": "redos", "title": "RegexDOS (Denial of Service)"},
    {"id": "rate_limit", "title": "Lack of Resources & Rate Limiting"},
    {"id": "jwt_weak", "title": "JWT authentication bypass via weak signing key"},
]


def _path(call: dict) -> str:
    return unquote(str(call.get("path") or call.get("url") or ""))


def _message(body: Any) -> str:
    if isinstance(body, dict):
        return str(body.get("message") or "")
    return str(body or "")


def _username_from_me(body: Any) -> str:
    if isinstance(body, dict):
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        return str(data.get("username") or "")
    return ""


def _admin_from_me(body: Any) -> bool | None:
    if isinstance(body, dict):
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        if "admin" in data:
            return bool(data.get("admin"))
    return None


def _has_password_fields(body: Any) -> bool:
    if isinstance(body, dict):
        for key, value in body.items():
            if str(key).lower() in {"password", "passwd"} and value:
                return True
            if _has_password_fields(value):
                return True
    elif isinstance(body, list):
        return any(_has_password_fields(item) for item in body)
    elif isinstance(body, str) and '"password"' in body.lower():
        return True
    return False


def _looks_like_user(body: Any) -> bool:
    if isinstance(body, dict) and (body.get("username") or (isinstance(body.get("data"), dict) and body["data"].get("username"))):
        return True
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False) if body is not None else ""
    return '"username"' in text and "not found" not in text.lower()


def score_history(
    history: list[dict],
    *,
    agent_username: str = "specpilot1",
    admin_username: str = "specpilot_admin",
    other_username: str = "name1",
) -> dict:
    hits: dict[str, dict] = {item["id"]: {"id": item["id"], "title": item["title"], "hit": False, "evidence": ""} for item in CLASSES}

    def mark(cid: str, evidence: str, call: dict | None = None) -> None:
        if hits[cid]["hit"]:
            return
        hits[cid]["hit"] = True
        hits[cid]["evidence"] = evidence
        if call:
            hits[cid]["method"] = call.get("method")
            hits[cid]["path"] = call.get("path")
            hits[cid]["status"] = call.get("status")

    login_fail_messages: list[tuple[str, dict]] = []

    for call in history:
        method = str(call.get("method") or "").upper()
        path = _path(call)
        status = int(call.get("status") or 0)
        body = call.get("body")
        payload = call.get("json") if isinstance(call.get("json"), dict) else {}

        if method == "GET" and "debug" in path.lower() and status == 200 and _has_password_fields(body):
            mark("excessive_data", "debug 接口返回了 password 字段", call)

        if method == "GET" and "/users/" in path and status == 200:
            lowered = path.lower()
            if ("'" in path or " or " in lowered) and _looks_like_user(body):
                mark("sqli", "用户名含 SQL 片段仍返回用户对象", call)

        if method == "GET" and "/books/" in path and status == 200:
            owner = ""
            secret = None
            if isinstance(body, dict):
                owner = str(body.get("owner") or body.get("user") or "")
                secret = body.get("secret")
            elif isinstance(body, list) and body and isinstance(body[0], dict):
                owner = str(body[0].get("owner") or body[0].get("user") or "")
                secret = body[0].get("secret")
            if secret and owner and owner != agent_username:
                mark("bola", f"用自己的 token 读到 {owner} 的书 secret", call)

        if method == "POST" and "register" in path.lower() and payload.get("admin") is True:
            for later in history:
                if str(later.get("method") or "").upper() != "GET":
                    continue
                if not str(later.get("path") or "").rstrip("/").endswith("/me"):
                    continue
                if int(later.get("status") or 0) != 200:
                    continue
                if _username_from_me(later.get("body")) == admin_username and _admin_from_me(later.get("body")) is True:
                    mark("mass_assignment", "注册时多传 admin=true 后 /me 显示管理员", later)

        if method == "POST" and path.rstrip("/").endswith("/login"):
            msg = _message(body)
            ok_token = isinstance(body, dict) and bool(body.get("auth_token") or body.get("token"))
            sent_user = str(payload.get("username") or "")
            sent_pass = str(payload.get("password") or "")
            if sent_user == other_username and sent_pass == "hacked-by-agent" and ok_token:
                mark("unauth_password", f"改了 {other_username} 的密码后可用新密码登录", call)
            if not ok_token and msg:
                login_fail_messages.append((msg, call))

        if method == "PUT" and path.endswith("/email") and (call.get("timeout") or float(call.get("elapsed_ms") or 0) >= 1500):
            mark("redos", f"恶意邮箱耗时 {call.get('elapsed_ms')} ms", call)

        if method == "GET" and path.rstrip("/").endswith("/me") and status == 200:
            name = _username_from_me(body)
            auth = str((call.get("headers") or {}).get("Authorization") or "")
            if name == "admin" and auth.startswith("Bearer "):
                logged_in_admin = False
                for prev in history:
                    if str(prev.get("method") or "").upper() != "POST":
                        continue
                    if "login" not in _path(prev).lower():
                        continue
                    prev_json = prev.get("json") if isinstance(prev.get("json"), dict) else {}
                    prev_body = prev.get("body")
                    if prev_json.get("username") == "admin" and isinstance(prev_body, dict) and prev_body.get("auth_token"):
                        logged_in_admin = True
                        break
                if not logged_in_admin:
                    mark("jwt_weak", "用常见弱密钥伪造的 JWT 访问 /me 成功", call)

    unique_msgs = list(dict.fromkeys(item[0] for item in login_fail_messages))
    if len(unique_msgs) >= 2:
        mark("enumeration", "错误用户名与错误密码返回了不同提示：" + " | ".join(unique_msgs[:2]), login_fail_messages[0][1])

    login_calls = [
        call
        for call in history
        if str(call.get("method") or "").upper() == "POST" and "login" in _path(call).lower()
    ]
    if len(login_calls) >= 10 and all(int(call.get("status") or 0) != 429 for call in login_calls):
        mark("rate_limit", f"连续 {len(login_calls)} 次登录均未返回 429", login_calls[-1])

    detected = [item["id"] for item in CLASSES if hits[item["id"]]["hit"]]
    return {
        "n": len(CLASSES),
        "detected": len(detected),
        "rate": round(len(detected) / len(CLASSES), 4),
        "classes": [hits[item["id"]] for item in CLASSES],
        "hit_ids": detected,
    }