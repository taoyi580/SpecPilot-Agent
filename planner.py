"""从 OpenAPI 规划注册 → 登录 → 备货 → 加购 → 下单。"""

from __future__ import annotations

from validator import WRITE_METHODS


def build_plan(email: str = "user@shop.local") -> list[dict]:
    password = "secret12"
    return [
        {
            "id": "register",
            "method": "POST",
            "path": "/auth/register",
            "json": {"email": email, "password": password, "name": "演示用户"},
            "extract": {"user_id": "id"},
        },
        {
            "id": "login",
            "method": "POST",
            "path": "/auth/login",
            "json": {"email": email, "password": password},
            "extract": {"token": "token"},
        },
        {
            "id": "me",
            "method": "GET",
            "path": "/auth/me",
            "auth": True,
        },
        {
            "id": "list_books",
            "method": "GET",
            "path": "/books?limit=2",
            "extract": {"book_id": "items.0.id"},
        },
        {
            "id": "get_book",
            "method": "GET",
            "path": "/books/$book_id",
        },
        {
            "id": "add_cart",
            "method": "POST",
            "path": "/cart/items",
            "auth": True,
            "json": {"book_id": "$book_id", "quantity": 1},
        },
        {
            "id": "create_order",
            "method": "POST",
            "path": "/orders",
            "auth": True,
            "headers": {"Idempotency-Key": "order-1"},
            "json": {"address": "重庆市演示路 1 号"},
            "extract": {"order_id": "id"},
        },
        {
            "id": "get_order",
            "method": "GET",
            "path": "/orders/$order_id",
            "auth": True,
        },
        {
            "id": "pay_order",
            "method": "POST",
            "path": "/orders/$order_id/pay",
            "auth": True,
        },
    ]


def is_write(step: dict) -> bool:
    return str(step.get("method", "")).upper() in WRITE_METHODS
