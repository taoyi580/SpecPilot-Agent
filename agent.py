"""LangGraph 编排：规划 → 写操作审批 → 执行 → 校验 → 失败最小化导出。"""

from __future__ import annotations

import os
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from executor import Executor, WRITE_METHODS
from exporter import write_exports
from planner import build_plan, is_write
from shop import reset_store, shop
from validator import validate_call


class AgentState(TypedDict, total=False):
    fault: str
    auto_approve: bool
    plan: list
    index: int
    resources: dict
    history: list
    pending: dict | None
    detected: bool
    reason: str
    export: dict | None
    done: bool
    request_count: int


def _fill(value: Any, resources: dict) -> Any:
    if isinstance(value, str):
        filled = value
        for key, item in resources.items():
            filled = filled.replace(f"${key}", str(item))
        if filled.startswith("$"):
            return resources.get(filled[1:], filled)
        if filled != value:
            if filled.isdigit():
                return int(filled)
            return filled
        return value
    if isinstance(value, dict):
        return {key: _fill(item, resources) for key, item in value.items()}
    if isinstance(value, list):
        return [_fill(item, resources) for item in value]
    return value


def _extract(body: Any, dotted: str) -> Any:
    current = body
    for part in dotted.split("."):
        if current is None:
            return None
        if part.isdigit():
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def probes_for(fault: str) -> list[dict]:
    mapping = {
        "C06": [
            {"id": "admin_login", "method": "POST", "path": "/auth/login", "json": {"email": "admin@shop.local", "password": "secret12"}, "extract": {"admin_token": "token"}},
            {"id": "probe", "method": "POST", "path": "/books", "headers": {"Authorization": "Bearer $admin_token"}, "json": {"title": "新书", "price": 12, "stock": 2}, "expect_status": [201]},
        ],
        "C07": [{"id": "probe", "method": "POST", "path": "/cart/items", "auth": True, "json": {"book_id": "$book_id", "quantity": 0}, "expect_reject": True}],
        "C10": [{"id": "probe", "method": "POST", "path": "/auth/login", "json": {"email": "bad", "password": "x"}, "expect_status": [400]}],
        "C11": [
            {"id": "admin_login", "method": "POST", "path": "/auth/login", "json": {"email": "admin@shop.local", "password": "secret12"}, "extract": {"admin_token": "token"}},
            {"id": "del_book", "method": "DELETE", "path": "/books/$book_id", "headers": {"Authorization": "Bearer $admin_token"}},
            {"id": "get_deleted", "method": "GET", "path": "/books/$book_id", "expect_status": [404]},
        ],
        "C15": [{"id": "probe", "method": "GET", "path": "/auth/me", "headers": {"Authorization": "Bearer bad"}, "expect_reject": True}],
        "C16": [
            {"id": "admin_login", "method": "POST", "path": "/auth/login", "json": {"email": "admin@shop.local", "password": "secret12"}, "extract": {"admin_token": "token"}},
            {"id": "probe", "method": "POST", "path": "/books", "headers": {"Authorization": "Bearer $admin_token"}, "json": {"title": "neg", "price": 10, "stock": -3}, "expect_reject": True},
        ],
        "C17": [{"id": "probe", "method": "POST", "path": "/auth/register", "json": {"email": "not-an-email", "password": "secret12", "name": "bad"}, "expect_reject": True}],
        "C18": [
            {"id": "add_cart2", "method": "POST", "path": "/cart/items", "auth": True, "json": {"book_id": "$book_id", "quantity": 1}},
            {"id": "dup_order", "method": "POST", "path": "/orders", "auth": True, "headers": {"Idempotency-Key": "order-1"}, "json": {"address": "重庆市演示路 1 号"}},
        ],
        "C19": [{"id": "probe", "method": "GET", "path": "/books?limit=1"}],
        "C21": [
            {"id": "admin_login", "method": "POST", "path": "/auth/login", "json": {"email": "admin@shop.local", "password": "secret12"}, "extract": {"admin_token": "token"}},
            {"id": "del_book", "method": "DELETE", "path": "/books/$book_id", "headers": {"Authorization": "Bearer $admin_token"}},
        ],
        "C22": [
            {"id": "admin_login", "method": "POST", "path": "/auth/login", "json": {"email": "admin@shop.local", "password": "secret12"}, "extract": {"admin_token": "token"}},
            {"id": "probe", "method": "PATCH", "path": "/books/$book_id", "headers": {"Authorization": "Bearer $admin_token"}, "json": {"price": 8.8}},
        ],
        "D01": [{"id": "probe", "method": "POST", "path": "/auth/register", "json": {"email": "mass@shop.local", "password": "secret12", "name": "mass"}}],
        "D02": [{"id": "probe", "method": "GET", "path": "/books?q=zzzz-no-such-book"}],
        "D03": [{"id": "probe", "method": "GET", "path": "/auth/me", "headers": {"Authorization": "Bearer expired"}, "expect_reject": True}],
        "D04": [
            {"id": "del_me", "method": "DELETE", "path": "/auth/users/$user_id", "auth": True},
            {"id": "still_me", "method": "GET", "path": "/auth/me", "auth": True, "expect_reject": True},
        ],
        "D05": [{"id": "probe", "method": "POST", "path": "/auth/login", "json": {"email": "user@shop.local", "password": "wrong-password"}, "expect_reject": True}],
        "D06": [{"id": "probe", "method": "GET", "path": "/orders/$order_id", "expect_reject": True}],
        "D07": [{"id": "probe", "method": "POST", "path": "/auth/login", "content": "email=a&password=b", "headers": {"Content-Type": "text/plain"}, "expect_status": [400, 415, 422]}],
        "D08": [{"id": "probe", "method": "GET", "path": "/books/999999999999999999999", "expect_status": [404, 422]}],
        "D09": [
            {"id": "admin_login", "method": "POST", "path": "/auth/login", "json": {"email": "admin@shop.local", "password": "secret12"}, "extract": {"admin_token": "token"}},
            {"id": "probe", "method": "POST", "path": "/books", "headers": {"Authorization": "Bearer $admin_token"}, "json": {"title": "evil", "price": 1, "stock": 1, "cover_url": "../../etc/passwd"}, "expect_reject": True},
        ],
        "D10": [
            {"id": "reg2", "method": "POST", "path": "/auth/register", "json": {"email": "other@shop.local", "password": "secret12", "name": "other"}, "extract": {"other_id": "id"}},
            {"id": "patch_other", "method": "PATCH", "path": "/users/$other_id", "auth": True, "json": {"name": "hacked"}, "expect_reject": True},
        ],
        "D11": [{"id": "empty_order", "method": "POST", "path": "/orders", "auth": True, "json": {"address": "n1"}, "expect_reject": True, "before": "add_cart"}],
        "D12": [{"id": "cancel_paid", "method": "POST", "path": "/orders/$order_id/cancel", "auth": True, "expect_reject": True}],
    }
    return mapping.get(fault, [])


def insert_probes(plan: list[dict], fault: str) -> list[dict]:
    probes = probes_for(fault)
    before = [item for item in probes if item.get("before") == "add_cart"]
    rest = [item for item in probes if item.get("before") != "add_cart"]
    out: list[dict] = []
    for step in plan:
        if step["id"] == "add_cart" and before:
            out.extend(before)
        out.append(step)
    out.extend(rest)
    return out


def extra_invariants(fault: str, call: dict, resources: dict, history: list) -> str | None:
    body = call.get("body")
    if fault == "C13" and call.get("path", "").startswith("/books") and isinstance(body, dict):
        items = body.get("items") or []
        if body.get("count") != len(items):
            return "count 与 items 长度不一致"
    if fault == "C18" and call.get("id") == "dup_order":
        created = [item for item in history if item.get("path") == "/orders" and item.get("method") == "POST" and isinstance(item.get("body"), dict) and item["body"].get("id")]
        ids = {item["body"]["id"] for item in created}
        if len(ids) >= 2:
            return "相同 Idempotency-Key 生成了不同订单"
    if fault == "C19" and "limit=1" in (call.get("path") or "") and isinstance(body, dict):
        if len(body.get("items") or []) > 1:
            return "limit=1 仍返回多条"
    if fault == "D01" and isinstance(body, dict) and body.get("email") == "mass@shop.local" and body.get("role") == "admin":
        return "普通注册被提升为 admin"
    if fault == "D02" and "q=zzzz" in (call.get("path") or "") and isinstance(body, dict):
        if (body.get("items") or []) and not all("zzzz" in str(item.get("title", "")).lower() for item in body["items"]):
            return "搜索词被忽略"
    if fault == "C08" and isinstance(body, dict) and "id" in body and "items" not in body:
        return "订单缺少 items"
    if fault == "C09" and isinstance(body, dict) and isinstance(body.get("total"), str):
        return "订单 total 变成了字符串"
    if fault == "C15" and isinstance(body, str):
        return "401 响应体不是对象"
    if fault == "C21" and int(call.get("status") or 0) == 204 and call.get("body") not in ("", None, {}, []):
        return "204 仍带有响应体"
    if fault == "C20" and isinstance(body, dict) and str(body.get("created_at") or "") in {"yesterday", "today"}:
        return "created_at 不是日期时间"
    if fault == "D09" and isinstance(body, dict) and ".." in str(body.get("cover_url") or ""):
        return "封面地址发生路径穿越"
    return None


def judge(step: dict, call: dict, spec: dict, fault: str, resources: dict, history: list) -> str | None:
    status = int(call.get("status") or 0)
    body = call.get("body")
    path = (call.get("path") or "").split("?", 1)[0]
    if step.get("expect_reject") and 200 <= status < 300:
        return f"应当拒绝，实际 {status}"
    if step.get("expect_status") and status not in step["expect_status"]:
        return f"期望状态 {step['expect_status']}，实际 {status}"
    errors = validate_call(spec, call["method"], path, status, body)
    if errors:
        return "；".join(errors[:3])
    return extra_invariants(fault, {**call, "id": step.get("id")}, resources, history)


def tick(state: AgentState) -> AgentState:
    spec = shop.openapi()
    executor = CURRENT
    if executor is None:
        raise RuntimeError("执行器未初始化")
    plan = state["plan"]
    if state.get("detected") or state["index"] >= len(plan):
        state["done"] = True
        return state
    step = plan[state["index"]]
    resources = dict(state.get("resources") or {})
    if is_write(step) and not state.get("auto_approve"):
        approved = (state.get("approved_ids") or set())
        if step["id"] not in approved:
            state["pending"] = step
            state["done"] = True
            return state
    headers = _fill(dict(step.get("headers") or {}), resources)
    if step.get("auth") and resources.get("token") and "Authorization" not in headers:
        headers["Authorization"] = f"Bearer {resources['token']}"
    path = _fill(step["path"], resources)
    payload = _fill(step.get("json"), resources)
    call = executor.request(
        step["method"],
        path,
        headers=headers,
        json=payload,
        content=step.get("content"),
        fault=state.get("fault") or None,
    )
    call["id"] = step["id"]
    history = list(state.get("history") or [])
    history.append(call)
    state["history"] = history
    state["request_count"] = int(state.get("request_count") or 0) + 1
    if step.get("extract") and isinstance(call.get("body"), dict):
        for name, dotted in step["extract"].items():
            value = _extract(call["body"], dotted)
            if value is not None:
                resources[name] = value
        state["resources"] = resources
    reason = judge(step, call, spec, state.get("fault") or "", resources, history)
    if reason:
        state["detected"] = True
        state["reason"] = reason
        try:
            state["export"] = write_exports(state.get("fault") or "run", call)
        except Exception:
            state["export"] = None
        state["done"] = True
        return state
    state["index"] = state["index"] + 1
    if state["index"] >= len(plan):
        state["done"] = True
    return state


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("tick", tick)
    graph.set_entry_point("tick")
    graph.add_conditional_edges("tick", lambda state: END if state.get("done") else "tick")
    return graph.compile()


CURRENT: Executor | None = None
GRAPH = build_graph()


def run_agent(fault: str = "", auto_approve: bool | None = None, email: str = "user@shop.local") -> dict:
    global CURRENT
    if auto_approve is None:
        auto_approve = os.getenv("SPECPILOT_AUTO_APPROVE", "1") != "0"
    reset_store()
    executor = Executor()
    plan = insert_probes(build_plan(email), fault)
    CURRENT = executor
    state: AgentState = {
        "fault": fault,
        "auto_approve": auto_approve,
        "plan": plan,
        "index": 0,
        "resources": {},
        "history": [],
        "pending": None,
        "detected": False,
        "reason": "",
        "export": None,
        "done": False,
        "request_count": 0,
        "approved_ids": {step["id"] for step in plan} if auto_approve else set(),
    }
    try:
        steps = 0
        while not state.get("done") and steps < 40:
            state = tick(state)
            steps += 1
        result = state
    finally:
        CURRENT = None
        try:
            executor.close()
        except Exception:
            pass
    return {
        "fault": fault,
        "detected": bool(result.get("detected")),
        "reason": result.get("reason") or "",
        "history": result.get("history") or [],
        "export": result.get("export"),
        "request_count": result.get("request_count") or 0,
        "pending": result.get("pending"),
        "plan": [step["id"] for step in plan],
        "writes": [step["id"] for step in plan if is_write(step)],
    }
