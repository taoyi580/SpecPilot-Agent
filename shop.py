"""自建图书商城。故障通过请求头 X-Fault 注入，便于逐条评测。"""

from __future__ import annotations

import os
import re
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from typing import Literal

shop = FastAPI(
    title="SpecPilot Bookstore",
    version="1.0.0",
    description="本地图书商城，供 SpecPilot 解析 OpenAPI 并规划注册到下单。",
)

USERS: dict[int, dict] = {}
EMAIL_INDEX: dict[str, int] = {}
TOKENS: dict[str, int] = {}
BOOKS: dict[int, dict] = {}
CARTS: dict[int, list[dict]] = {}
ORDERS: dict[int, dict] = {}
IDEMPOTENCY: dict[str, int] = {}
SEQ = {"user": 0, "book": 0, "order": 0}


def _next(kind: str) -> int:
    SEQ[kind] += 1
    return SEQ[kind]


def reset_store() -> None:
    USERS.clear()
    EMAIL_INDEX.clear()
    TOKENS.clear()
    BOOKS.clear()
    CARTS.clear()
    ORDERS.clear()
    IDEMPOTENCY.clear()
    SEQ.update({"user": 0, "book": 0, "order": 0})
    admin_id = _next("user")
    USERS[admin_id] = {
        "id": admin_id,
        "email": "admin@shop.local",
        "password": "secret12",
        "name": "管理员",
        "role": "admin",
    }
    EMAIL_INDEX["admin@shop.local"] = admin_id
    CARTS[admin_id] = []
    book_id = _next("book")
    BOOKS[book_id] = {
        "id": book_id,
        "title": "入门 Python",
        "price": 39.9,
        "stock": 20,
        "status": "on_sale",
        "cover_url": "https://shop.local/covers/python.png",
        "created_at": "2026-08-01T00:00:00Z",
    }
    book_id2 = _next("book")
    BOOKS[book_id2] = {
        "id": book_id2,
        "title": "FastAPI 手册",
        "price": 49.0,
        "stock": 8,
        "status": "on_sale",
        "cover_url": "https://shop.local/covers/fastapi.png",
        "created_at": "2026-08-01T00:00:00Z",
    }


reset_store()


class RegisterIn(BaseModel):
    email: str = Field(examples=["user@shop.local"])
    password: str = Field(min_length=6)
    name: str


class LoginIn(BaseModel):
    email: str
    password: str


class BookIn(BaseModel):
    title: str
    price: float
    stock: int
    cover_url: str | None = None


class BookPatch(BaseModel):
    title: str | None = None
    price: float | None = Field(default=None, ge=0)
    stock: int | None = Field(default=None, ge=0)
    status: str | None = None


class CartItemIn(BaseModel):
    book_id: int
    quantity: int


class OrderIn(BaseModel):
    address: str


class UserPatch(BaseModel):
    name: str | None = None
    email: str | None = None


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str


class TokenOut(BaseModel):
    token: str
    user_id: int


class BookOut(BaseModel):
    id: int
    title: str
    price: float
    stock: int
    status: Literal["on_sale", "off_sale"]
    cover_url: str
    created_at: str = Field(json_schema_extra={"format": "date-time"})


class BookListOut(BaseModel):
    count: int
    items: list[BookOut]


class CartItemOut(BaseModel):
    book_id: int
    quantity: int


class OrderOut(BaseModel):
    id: int
    user_id: int
    items: list[CartItemOut]
    total: float
    address: str
    status: str
    created_at: str = Field(json_schema_extra={"format": "date-time"})


class ErrorOut(BaseModel):
    detail: str


def current_fault(request: Request, x_fault: str | None) -> str:
    return (x_fault or request.headers.get("x-fault") or os.getenv("SPEC_FAULT") or "").strip()


def current_user(authorization: str | None, fault: str) -> dict | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    if fault == "D03":
        return USERS.get(1) or {"id": 1, "email": "ghost@shop.local", "name": "ghost", "role": "user"}
    uid = TOKENS.get(token)
    if uid is None:
        return None
    return USERS.get(uid)


def require_user(authorization: str | None, fault: str) -> dict:
    user = current_user(authorization, fault)
    if user is None:
        if fault == "C15":
            raise HTTPException(status_code=401, detail="unauthorized")
        raise HTTPException(status_code=401, detail="未登录")
    return user


def require_admin(user: dict) -> None:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员")


@shop.middleware("http")
async def fault_middleware(request: Request, call_next):
    fault = current_fault(request, request.headers.get("x-fault"))
    request.state.fault = fault
    if fault == "D07" and request.method == "POST" and request.url.path.endswith("/auth/login"):
        return JSONResponse({"detail": "internal"}, status_code=500)
    if fault == "D08" and "/books/" in request.url.path:
        tail = request.url.path.rsplit("/", 1)[-1]
        if tail.isdigit() and len(tail) > 12:
            return JSONResponse({"detail": "boom"}, status_code=500)
    try:
        response = await call_next(request)
    except Exception:
        if fault == "D07":
            return JSONResponse({"detail": "internal"}, status_code=500)
        raise
    return response


def mutate(fault: str, path: str, method: str, status: int, body: Any) -> tuple[int, Any, bool]:
    """返回 status, body, empty_204_with_json."""
    if not fault:
        return status, body, False
    if fault == "C01" and method == "POST" and path.endswith("/auth/register") and isinstance(body, dict):
        body = dict(body)
        body.pop("id", None)
    if fault == "C02" and method == "POST" and path.endswith("/auth/register") and status == 201:
        status = 200
    if fault == "C03" and method == "POST" and path.endswith("/auth/login") and isinstance(body, dict):
        body = dict(body)
        body["token"] = 12345
    if fault == "C04" and method == "GET" and path.endswith("/books") and isinstance(body, dict):
        items = [dict(item) for item in body.get("items") or []]
        for item in items:
            item.pop("title", None)
        body = dict(body)
        body["items"] = items
    if fault == "C05" and method == "GET" and "/books/" in path and isinstance(body, dict) and "price" in body:
        body = dict(body)
        body["price"] = str(body["price"])
    if fault == "C06" and method == "POST" and path.endswith("/books") and status == 201:
        status = 200
    if fault == "C08" and method == "GET" and "/orders/" in path and isinstance(body, dict):
        body = dict(body)
        body.pop("items", None)
    if fault == "C09" and method == "GET" and "/orders/" in path and isinstance(body, dict) and "total" in body:
        body = dict(body)
        body["total"] = str(body["total"])
    if fault == "C10" and status == 400:
        body = {"message": "bad request"}
    if fault == "C12" and isinstance(body, dict) and "status" in body:
        body = dict(body)
        body["status"] = "unknown_status"
    if fault == "C12" and isinstance(body, dict) and "items" in body:
        items = [dict(item) for item in body.get("items") or []]
        for item in items:
            if "status" in item:
                item["status"] = "unknown_status"
        body = dict(body)
        body["items"] = items
    if fault == "C13" and method == "GET" and path.endswith("/books") and isinstance(body, dict):
        body = dict(body)
        body["count"] = int(body.get("count") or 0) + 5
    if fault == "C14" and method == "POST" and path.endswith("/orders") and isinstance(body, dict):
        body = dict(body)
        body.pop("id", None)
    if fault == "C15" and status == 401:
        return status, "unauthorized", False
    if fault == "C19" and method == "GET" and path.endswith("/books") and isinstance(body, dict):
        body = dict(body)
        body["items"] = list(BOOKS.values())
        body["count"] = len(body["items"])
    if fault == "C20" and isinstance(body, dict) and "created_at" in body:
        body = dict(body)
        body["created_at"] = "yesterday"
    if fault == "C21" and method == "DELETE" and status == 204:
        return 204, {"deleted": True}, True
    if fault == "C22" and method == "PATCH" and "/books/" in path and isinstance(body, dict) and "price" in body:
        body = dict(body)
        body["price"] = str(body["price"])
    if fault == "C23" and method == "POST" and path.endswith("/cart/items") and isinstance(body, dict):
        body = dict(body)
        if "book_id" in body:
            body["book_id"] = str(body["book_id"])
    if fault == "C24" and method == "GET" and path.endswith("/auth/me") and isinstance(body, dict):
        body = dict(body)
        body.pop("email", None)
    return status, body, False


def send(request: Request, status: int, body: Any) -> Response:
    fault = getattr(request.state, "fault", "")
    path = request.url.path
    status, body, force_json_204 = mutate(fault, path, request.method, status, body)
    if status == 204 and not force_json_204:
        return Response(status_code=204)
    if isinstance(body, str):
        return Response(content=body, status_code=status, media_type="text/plain")
    return JSONResponse(body, status_code=status)


@shop.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    fault = current_fault(request, request.headers.get("x-fault"))
    if fault == "C15" and exc.status_code == 401:
        return Response(content="unauthorized", status_code=401, media_type="text/plain")
    detail = exc.detail
    body = {"detail": detail} if not isinstance(detail, dict) else detail
    if fault == "C10" and exc.status_code == 400:
        body = {"message": "bad request"}
    return JSONResponse(body, status_code=exc.status_code)


@shop.get("/health")
def health() -> dict:
    return {"ok": True}


@shop.post("/auth/register", status_code=201, responses={201: {"model": UserOut}, 400: {"model": ErrorOut}})
def register(payload: RegisterIn, request: Request, x_fault: str | None = Header(default=None)):
    fault = current_fault(request, x_fault)
    extra_role = None
    raw = getattr(request.state, "_raw", None)
    if fault == "C17":
        pass
    elif not re.match(r"^[^@]+@[^@]+\.[^@]+$", payload.email):
        return send(request, 400, {"detail": "邮箱格式不正确"})
    if payload.email in EMAIL_INDEX:
        return send(request, 400, {"detail": "邮箱已注册"})
    user_id = _next("user")
    role = "admin" if user_id == 1 else "user"
    if fault == "D01":
        role = extra_role or "admin"
        # 下面在 raw json 里看 role；FastAPI 已丢掉多余字段，用 query/header 模拟：若 name 含 admin-role
        if payload.name.endswith("#admin") or payload.email.startswith("mass"):
            role = "admin"
    user = {
        "id": user_id,
        "email": payload.email,
        "password": payload.password,
        "name": payload.name.replace("#admin", ""),
        "role": role,
    }
    USERS[user_id] = user
    EMAIL_INDEX[payload.email] = user_id
    CARTS[user_id] = []
    public = {k: user[k] for k in ("id", "email", "name", "role")}
    return send(request, 201, public)


@shop.post("/auth/login", responses={200: {"model": TokenOut}, 400: {"model": ErrorOut}})
def login(payload: LoginIn, request: Request, x_fault: str | None = Header(default=None)):
    fault = current_fault(request, x_fault)
    uid = EMAIL_INDEX.get(payload.email)
    user = USERS.get(uid) if uid else None
    if user is None:
        return send(request, 400, {"detail": "账号或密码错误"})
    if user["password"] != payload.password and fault != "D05":
        return send(request, 400, {"detail": "账号或密码错误"})
    token = f"tok-{user['id']}-{len(TOKENS) + 1}"
    TOKENS[token] = user["id"]
    return send(request, 200, {"token": token, "user_id": user["id"]})


@shop.get("/auth/me", responses={200: {"model": UserOut}, 401: {"model": ErrorOut}})
def me(request: Request, authorization: str | None = Header(default=None), x_fault: str | None = Header(default=None)):
    fault = current_fault(request, x_fault)
    user = require_user(authorization, fault)
    public = {k: user[k] for k in ("id", "email", "name", "role")}
    return send(request, 200, public)


@shop.delete("/auth/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
    x_fault: str | None = Header(default=None),
):
    fault = current_fault(request, x_fault)
    actor = require_user(authorization, fault)
    if actor["id"] != user_id and actor.get("role") != "admin":
        raise HTTPException(status_code=403, detail="不能删除他人")
    if fault == "D04":
        return send(request, 204, None)
    USERS.pop(user_id, None)
    dead = [tok for tok, uid in TOKENS.items() if uid == user_id]
    for tok in dead:
        TOKENS.pop(tok, None)
    return send(request, 204, None)


@shop.get("/books", responses={200: {"model": BookListOut}})
def list_books(request: Request, limit: int = 20, q: str | None = None, x_fault: str | None = Header(default=None)):
    fault = current_fault(request, x_fault)
    items = list(BOOKS.values())
    if q and fault != "D02":
        needle = q.lower()
        items = [item for item in items if needle in item["title"].lower()]
    if fault != "C19":
        items = items[: max(1, min(limit, 100))]
    body = {"count": len(items), "items": items}
    return send(request, 200, body)


@shop.get("/books/{book_id}", responses={200: {"model": BookOut}, 404: {"model": ErrorOut}})
def get_book(book_id: int, request: Request, x_fault: str | None = Header(default=None)):
    book = BOOKS.get(book_id)
    if book is None:
        return send(request, 404, {"detail": "图书不存在"})
    return send(request, 200, book)


@shop.post("/books", status_code=201, responses={201: {"model": BookOut}})
def create_book(
    payload: BookIn,
    request: Request,
    authorization: str | None = Header(default=None),
    x_fault: str | None = Header(default=None),
):
    fault = current_fault(request, x_fault)
    user = require_user(authorization, fault)
    require_admin(user)
    if payload.stock < 0 and fault != "C16":
        return send(request, 400, {"detail": "库存不能为负"})
    cover = payload.cover_url or "https://shop.local/covers/default.png"
    if fault != "D09" and ".." in cover:
        return send(request, 400, {"detail": "封面地址不合法"})
    book_id = _next("book")
    book = {
        "id": book_id,
        "title": payload.title,
        "price": payload.price,
        "stock": payload.stock,
        "status": "on_sale",
        "cover_url": cover,
        "created_at": "2026-08-26T00:00:00Z",
    }
    BOOKS[book_id] = book
    return send(request, 201, book)


@shop.patch("/books/{book_id}", responses={200: {"model": BookOut}})
def patch_book(
    book_id: int,
    payload: BookPatch,
    request: Request,
    authorization: str | None = Header(default=None),
    x_fault: str | None = Header(default=None),
):
    fault = current_fault(request, x_fault)
    user = require_user(authorization, fault)
    require_admin(user)
    book = BOOKS.get(book_id)
    if book is None:
        return send(request, 404, {"detail": "图书不存在"})
    data = payload.model_dump(exclude_unset=True)
    book.update(data)
    return send(request, 200, book)


@shop.delete("/books/{book_id}", status_code=204)
def delete_book(
    book_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
    x_fault: str | None = Header(default=None),
):
    fault = current_fault(request, x_fault)
    user = require_user(authorization, fault)
    require_admin(user)
    if book_id not in BOOKS:
        return send(request, 404, {"detail": "图书不存在"})
    if fault == "C11":
        return send(request, 204, None)
    BOOKS.pop(book_id, None)
    return send(request, 204, None)


@shop.get("/cart")
def get_cart(request: Request, authorization: str | None = Header(default=None), x_fault: str | None = Header(default=None)):
    fault = current_fault(request, x_fault)
    user = require_user(authorization, fault)
    items = CARTS.get(user["id"], [])
    return send(request, 200, {"items": items, "count": len(items)})


@shop.post("/cart/items", status_code=201, responses={201: {"model": CartItemOut}})
def add_cart(
    payload: CartItemIn,
    request: Request,
    authorization: str | None = Header(default=None),
    x_fault: str | None = Header(default=None),
):
    fault = current_fault(request, x_fault)
    user = require_user(authorization, fault)
    if payload.quantity < 1 and fault != "C07":
        return send(request, 400, {"detail": "数量至少为 1"})
    if payload.book_id not in BOOKS:
        return send(request, 400, {"detail": "图书不存在"})
    item = {"book_id": payload.book_id, "quantity": payload.quantity}
    CARTS.setdefault(user["id"], []).append(item)
    return send(request, 201, item)


@shop.post("/orders", status_code=201, responses={201: {"model": OrderOut}, 400: {"model": ErrorOut}})
def create_order(
    payload: OrderIn,
    request: Request,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_fault: str | None = Header(default=None),
):
    fault = current_fault(request, x_fault)
    user = require_user(authorization, fault)
    if idempotency_key and idempotency_key in IDEMPOTENCY and fault != "C18":
        existing = ORDERS[IDEMPOTENCY[idempotency_key]]
        return send(request, 201, existing)
    items = list(CARTS.get(user["id"], []))
    if not items and fault != "D11":
        return send(request, 400, {"detail": "购物车为空"})
    total = 0.0
    order_items = []
    for item in items:
        book = BOOKS.get(item["book_id"])
        if book is None:
            continue
        total += float(book["price"]) * int(item["quantity"])
        order_items.append({**item, "title": book["title"], "price": book["price"]})
    order_id = _next("order")
    order = {
        "id": order_id,
        "user_id": user["id"],
        "items": order_items,
        "total": round(total, 2),
        "address": payload.address,
        "status": "created",
        "created_at": "2026-08-26T00:00:00Z",
    }
    ORDERS[order_id] = order
    if idempotency_key:
        IDEMPOTENCY[idempotency_key] = order_id
    CARTS[user["id"]] = []
    return send(request, 201, order)


@shop.get("/orders")
def list_orders(request: Request, authorization: str | None = Header(default=None), x_fault: str | None = Header(default=None)):
    fault = current_fault(request, x_fault)
    user = require_user(authorization, fault)
    items = [order for order in ORDERS.values() if order["user_id"] == user["id"]]
    return send(request, 200, {"count": len(items), "items": items})


@shop.get("/orders/{order_id}", responses={200: {"model": OrderOut}, 401: {"model": ErrorOut}, 404: {"model": ErrorOut}})
def get_order(
    order_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
    x_fault: str | None = Header(default=None),
):
    fault = current_fault(request, x_fault)
    order = ORDERS.get(order_id)
    if order is None:
        return send(request, 404, {"detail": "订单不存在"})
    if fault != "D06":
        user = require_user(authorization, fault)
        if order["user_id"] != user["id"] and user.get("role") != "admin":
            return send(request, 403, {"detail": "不能查看他人订单"})
    return send(request, 200, order)


@shop.post("/orders/{order_id}/pay")
def pay_order(
    order_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
    x_fault: str | None = Header(default=None),
):
    fault = current_fault(request, x_fault)
    user = require_user(authorization, fault)
    order = ORDERS.get(order_id)
    if order is None:
        return send(request, 404, {"detail": "订单不存在"})
    if order["user_id"] != user["id"]:
        return send(request, 403, {"detail": "不能支付他人订单"})
    order["status"] = "paid"
    return send(request, 200, order)


@shop.post("/orders/{order_id}/cancel")
def cancel_order(
    order_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
    x_fault: str | None = Header(default=None),
):
    fault = current_fault(request, x_fault)
    user = require_user(authorization, fault)
    order = ORDERS.get(order_id)
    if order is None:
        return send(request, 404, {"detail": "订单不存在"})
    if order["user_id"] != user["id"]:
        return send(request, 403, {"detail": "不能取消他人订单"})
    if order["status"] == "paid" and fault != "D12":
        return send(request, 400, {"detail": "已支付订单不能取消"})
    order["status"] = "cancelled"
    return send(request, 200, order)


@shop.patch("/users/{user_id}")
def patch_user(
    user_id: int,
    payload: UserPatch,
    request: Request,
    authorization: str | None = Header(default=None),
    x_fault: str | None = Header(default=None),
):
    fault = current_fault(request, x_fault)
    actor = require_user(authorization, fault)
    if actor["id"] != user_id and actor.get("role") != "admin" and fault != "D10":
        return send(request, 403, {"detail": "不能修改他人资料"})
    target = USERS.get(user_id)
    if target is None:
        return send(request, 404, {"detail": "用户不存在"})
    data = payload.model_dump(exclude_unset=True)
    if "email" in data and data["email"]:
        EMAIL_INDEX.pop(target["email"], None)
        EMAIL_INDEX[data["email"]] = user_id
        target["email"] = data["email"]
    if "name" in data and data["name"]:
        target["name"] = data["name"]
    public = {k: target[k] for k in ("id", "email", "name", "role")}
    return send(request, 200, public)
