"""从 OpenAPI 规划有状态调用：认证、资源依赖、边界值和安全探针。不按故障编号出题。"""

from __future__ import annotations

from typing import Any

from validator import WRITE_METHODS, unwrap_schema


def _ref(schema: dict | None, spec: dict) -> dict:
    return unwrap_schema(schema, spec) or {}


def operations(spec: dict) -> list[dict]:
    out: list[dict] = []
    for path, methods in (spec.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not isinstance(op, dict):
                continue
            out.append({"method": method.upper(), "path": path, "op": op})
    return out


def _params(op: dict, where: str) -> list[dict]:
    return [p for p in (op.get("parameters") or []) if (p.get("in") or "") == where]


def needs_auth(op: dict) -> bool:
    if op.get("security"):
        return True
    for item in op.get("parameters") or []:
        if str(item.get("name") or "").lower() == "authorization":
            return True
    return False


def body_schema(op: dict, spec: dict) -> dict:
    content = ((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}
    return _ref(content.get("schema"), spec)


def example_values(spec: dict) -> dict[str, list]:
    found: dict[str, list] = {"email": [], "password": []}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            examples = node.get("examples")
            if isinstance(examples, list):
                for item in examples:
                    text = str(item)
                    if "@" in text:
                        found["email"].append(text)
                    found["password"].append(text)
            example = node.get("example")
            if isinstance(example, str) and "@" in example:
                found["email"].append(example)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(spec)
    found["email"] = list(dict.fromkeys(found["email"]))
    found["password"] = list(dict.fromkeys(item for item in found["password"] if item and "@" not in item))
    return found


def _fill_body(schema: dict, spec: dict, overrides: dict | None = None) -> dict:
    schema = _ref(schema, spec)
    props = schema.get("properties") or {}
    required = schema.get("required")
    if not isinstance(required, list):
        required = list(props)
    body: dict[str, Any] = {}
    for name in required:
        child = _ref(props.get(name), spec) or {}
        body[name] = _sample(name, child)
    if overrides:
        body.update(overrides)
    return body


def _sample(name: str, schema: dict) -> Any:
    schema = schema or {}
    if name == "email":
        return "user@shop.local"
    if name == "password":
        return "secret12"
    if name == "name":
        return "演示用户"
    if name == "title":
        return "探针图书"
    if name == "address":
        return "重庆市演示路 1 号"
    expected = schema.get("type")
    if expected == "integer":
        return 1
    if expected == "number":
        return 1.0
    if expected == "boolean":
        return True
    if expected == "array":
        return []
    if expected == "object":
        return {}
    return "demo"


def _path_with_vars(template: str) -> str:
    parts = []
    for part in template.split("/"):
        if part.startswith("{") and part.endswith("}"):
            parts.append("$" + part[1:-1])
        else:
            parts.append(part)
    return "/".join(parts)


def _exact(ops: list[dict], method: str, path: str) -> dict | None:
    method = method.upper()
    path = path.rstrip("/") or "/"
    for item in ops:
        if item["method"] == method and item["path"].rstrip("/") == path:
            return item
    return None


def build_plan(spec: dict, email: str = "user@shop.local") -> list[dict]:
    ops = operations(spec)
    examples = example_values(spec)
    password = (examples.get("password") or ["secret12"])[0]
    admin_emails = [item for item in examples.get("email") or [] if "admin" in item]
    steps: list[dict] = []

    register = _exact(ops, "POST", "/auth/register")
    login = _exact(ops, "POST", "/auth/login")
    me = _exact(ops, "GET", "/auth/me")
    books = _exact(ops, "GET", "/books")
    get_book = next((item for item in ops if item["method"] == "GET" and "{book_id}" in item["path"]), None)
    add_cart = _exact(ops, "POST", "/cart/items")
    create_order = _exact(ops, "POST", "/orders")
    get_order = next((item for item in ops if item["method"] == "GET" and "{order_id}" in item["path"]), None)
    pay = next((item for item in ops if item["method"] == "POST" and item["path"].endswith("/pay")), None)
    cancel = next((item for item in ops if item["method"] == "POST" and item["path"].endswith("/cancel")), None)
    create_book = _exact(ops, "POST", "/books")
    patch_book = next((item for item in ops if item["method"] == "PATCH" and "{book_id}" in item["path"]), None)
    delete_book = next((item for item in ops if item["method"] == "DELETE" and "{book_id}" in item["path"]), None)
    delete_user = next((item for item in ops if item["method"] == "DELETE" and "/auth/users/" in item["path"]), None)
    patch_user = next((item for item in ops if item["method"] == "PATCH" and "/users/" in item["path"]), None)

    def add(step: dict) -> None:
        steps.append(step)

    if register:
        add(
            {
                "id": "register",
                "method": "POST",
                "path": register["path"],
                "json": _fill_body(body_schema(register["op"], spec), spec, {"email": email, "password": password, "name": "演示用户"}),
                "extract": {"user_id": "id"},
            }
        )
        extra = dict(steps[-1]["json"])
        extra["role"] = "admin"
        add(
            {
                "id": "register_extra_role",
                "method": "POST",
                "path": register["path"],
                "json": {**extra, "email": f"role-{email}"},
                "extract": {"role_user": "role"},
                "check_mass_assign": "role",
            }
        )
        add(
            {
                "id": "register_bad_email",
                "method": "POST",
                "path": register["path"],
                "json": _fill_body(body_schema(register["op"], spec), spec, {"email": "not-an-email", "password": password, "name": "bad"}),
                "expect_reject": True,
            }
        )
    if login:
        add(
            {
                "id": "login",
                "method": "POST",
                "path": login["path"],
                "json": {"email": email, "password": password},
                "extract": {"token": "token"},
            }
        )
        add(
            {
                "id": "login_wrong_password",
                "method": "POST",
                "path": login["path"],
                "json": {"email": email, "password": "wrong-password"},
                "expect_reject": True,
            }
        )
        add(
            {
                "id": "login_bad_type",
                "method": "POST",
                "path": login["path"],
                "content": "email=a&password=b",
                "headers": {"Content-Type": "text/plain"},
                "expect_reject": True,
                "reject_5xx": True,
            }
        )
        add(
            {
                "id": "login_bad_email_400",
                "method": "POST",
                "path": login["path"],
                "json": {"email": "bad", "password": "x"},
                "expect_reject": True,
            }
        )
    if me:
        add({"id": "me", "method": "GET", "path": me["path"], "auth": True})
        add(
            {
                "id": "me_bad_token",
                "method": "GET",
                "path": me["path"],
                "headers": {"Authorization": "Bearer expired"},
                "expect_reject": True,
            }
        )
    if books:
        names = {p.get("name") for p in _params(books["op"], "query")}
        list_path = books["path"]
        if "limit" in names:
            list_path += "?limit=1"
        add(
            {
                "id": "list_books",
                "method": "GET",
                "path": list_path,
                "extract": {"book_id": "items.0.id"},
                "check_limit": 1 if "limit" in names else None,
            }
        )
        if "q" in names:
            add(
                {
                    "id": "search_books",
                    "method": "GET",
                    "path": books["path"] + "?q=zzzz-no-such-book",
                    "check_search": True,
                }
            )
    if get_book:
        add(
            {
                "id": "get_book",
                "method": "GET",
                "path": _path_with_vars(get_book["path"]),
            }
        )
        add(
            {
                "id": "get_book_huge_id",
                "method": "GET",
                "path": get_book["path"].split("{")[0] + "999999999999999999999",
                "boundary": True,
            }
        )
    if create_order:
        add(
            {
                "id": "empty_order",
                "method": "POST",
                "path": create_order["path"],
                "auth": True,
                "json": _fill_body(body_schema(create_order["op"], spec), spec),
                "expect_reject": True,
            }
        )
    if add_cart:
        schema = body_schema(add_cart["op"], spec)
        good = _fill_body(schema, spec, {"book_id": "$book_id", "quantity": 1})
        add(
            {
                "id": "add_cart",
                "method": "POST",
                "path": add_cart["path"],
                "auth": True,
                "json": good,
            }
        )
        zero = dict(good)
        for key, child in (_ref(schema, spec).get("properties") or {}).items():
            if _ref(child, spec).get("type") == "integer" and key != "book_id":
                zero[key] = 0
                break
        add(
            {
                "id": "add_cart_zero",
                "method": "POST",
                "path": add_cart["path"],
                "auth": True,
                "json": zero,
                "expect_reject": True,
            }
        )
    if create_order:
        headers = {}
        for item in create_order["op"].get("parameters") or []:
            if str(item.get("name") or "").lower() == "idempotency-key":
                headers["Idempotency-Key"] = "order-1"
        body = _fill_body(body_schema(create_order["op"], spec), spec)
        add(
            {
                "id": "create_order",
                "method": "POST",
                "path": create_order["path"],
                "auth": True,
                "headers": headers,
                "json": body,
                "extract": {"order_id": "id"},
            }
        )
        if headers and add_cart:
            add(
                {
                    "id": "add_cart_before_retry",
                    "method": "POST",
                    "path": add_cart["path"],
                    "auth": True,
                    "json": _fill_body(body_schema(add_cart["op"], spec), spec, {"book_id": "$book_id", "quantity": 1}),
                }
            )
        if headers:
            add(
                {
                    "id": "create_order_idempotent",
                    "method": "POST",
                    "path": create_order["path"],
                    "auth": True,
                    "headers": headers,
                    "json": body,
                    "check_idempotency": True,
                }
            )
    if get_order:
        add(
            {
                "id": "get_order",
                "method": "GET",
                "path": _path_with_vars(get_order["path"]),
                "auth": True,
            }
        )
        add(
            {
                "id": "get_order_no_auth",
                "method": "GET",
                "path": _path_with_vars(get_order["path"]),
                "expect_reject": True,
            }
        )
    if pay:
        add(
            {
                "id": "pay_order",
                "method": "POST",
                "path": _path_with_vars(pay["path"]),
                "auth": True,
            }
        )
    if cancel:
        add(
            {
                "id": "cancel_paid",
                "method": "POST",
                "path": _path_with_vars(cancel["path"]),
                "auth": True,
                "expect_reject": True,
            }
        )
    if login and admin_emails:
        add(
            {
                "id": "admin_login",
                "method": "POST",
                "path": login["path"],
                "json": {"email": admin_emails[0], "password": password},
                "extract": {"admin_token": "token"},
            }
        )
    if create_book:
        schema = body_schema(create_book["op"], spec)
        good = _fill_body(schema, spec)
        add(
            {
                "id": "create_book",
                "method": "POST",
                "path": create_book["path"],
                "headers": {"Authorization": "Bearer $admin_token"},
                "json": good,
                "extract": {"new_book_id": "id"},
            }
        )
        neg = dict(good)
        for key, child in (_ref(schema, spec).get("properties") or {}).items():
            if _ref(child, spec).get("type") == "integer" and key != "id":
                neg[key] = -3
                break
        add(
            {
                "id": "create_book_negative",
                "method": "POST",
                "path": create_book["path"],
                "headers": {"Authorization": "Bearer $admin_token"},
                "json": neg,
                "expect_reject": True,
            }
        )
        traversal = dict(good)
        for key in (_ref(schema, spec).get("properties") or {}):
            if "url" in key or "path" in key or "cover" in key:
                traversal[key] = "../../etc/passwd"
        add(
            {
                "id": "create_book_traversal",
                "method": "POST",
                "path": create_book["path"],
                "headers": {"Authorization": "Bearer $admin_token"},
                "json": traversal,
                "expect_reject": True,
            }
        )
    if patch_book:
        add(
            {
                "id": "patch_book",
                "method": "PATCH",
                "path": patch_book["path"].replace("{book_id}", "$book_id"),
                "headers": {"Authorization": "Bearer $admin_token"},
                "json": {"price": 8.8},
            }
        )
    if delete_book:
        add(
            {
                "id": "delete_book",
                "method": "DELETE",
                "path": delete_book["path"].replace("{book_id}", "$book_id"),
                "headers": {"Authorization": "Bearer $admin_token"},
            }
        )
        if get_book:
            add(
                {
                    "id": "get_deleted_book",
                    "method": "GET",
                    "path": get_book["path"].replace("{book_id}", "$book_id"),
                    "expect_status": [404],
                }
            )
    if patch_user and register:
        add(
            {
                "id": "register_other",
                "method": "POST",
                "path": register["path"],
                "json": _fill_body(body_schema(register["op"], spec), spec, {"email": f"other-{email}", "password": password, "name": "other"}),
                "extract": {"other_id": "id"},
            }
        )
        add(
            {
                "id": "patch_other_user",
                "method": "PATCH",
                "path": patch_user["path"].replace("{user_id}", "$other_id"),
                "auth": True,
                "json": {"name": "hacked"},
                "expect_reject": True,
            }
        )
    if delete_user:
        add(
            {
                "id": "delete_self",
                "method": "DELETE",
                "path": delete_user["path"].replace("{user_id}", "$user_id"),
                "auth": True,
            }
        )
        if me:
            add(
                {
                    "id": "me_after_delete",
                    "method": "GET",
                    "path": me["path"],
                    "auth": True,
                    "expect_reject": True,
                }
            )
    return steps


def is_write(step: dict) -> bool:
    return str(step.get("method", "")).upper() in WRITE_METHODS
