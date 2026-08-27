"""LangGraph 编排：OpenAPI 规划 → 写操作审批 → 执行 → 契约校验 → 失败导出。"""

from __future__ import annotations

import os
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from executor import Executor
from exporter import write_exports
from planner import build_plan, is_write
from shop import reset_store, shop
from validator import expected_status, find_operation, validate_call


class AgentState(TypedDict, total=False):
    fault: str
    spec: dict
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
    approved_ids: list
    use_contract_judge: bool
    stop_on_first: bool


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


def general_invariants(step: dict, call: dict, resources: dict, history: list) -> str | None:
    body = call.get("body")
    path = call.get("path") or ""
    status = int(call.get("status") or 0)
    if isinstance(body, dict) and "count" in body and isinstance(body.get("items"), list):
        if body.get("count") != len(body["items"]):
            return "count 与 items 长度不一致"
    limit = step.get("check_limit")
    if limit and isinstance(body, dict) and isinstance(body.get("items"), list):
        if len(body["items"]) > int(limit):
            return f"limit={limit} 仍返回 {len(body['items'])} 条"
    if step.get("check_search") and "q=" in path and isinstance(body, dict):
        needle = ""
        for part in path.split("q=", 1)[-1].split("&", 1)[:1]:
            needle = part.lower()
        items = body.get("items") or []
        if needle and items:
            texts = [str(item).lower() for item in items]
            if not all(needle in text for text in texts):
                return "搜索词被忽略"
    if step.get("check_mass_assign") and isinstance(body, dict):
        field = step["check_mass_assign"]
        sent = (step.get("json") or {}).get(field)
        if sent and body.get(field) == sent and str(sent).lower() in {"admin", "root", "superuser"}:
            return f"多余字段 {field} 被写入为 {sent}"
    if step.get("check_idempotency"):
        created = [
            item
            for item in history
            if item.get("method") == "POST"
            and str(item.get("path") or "").rstrip("/") == "/orders"
            and isinstance(item.get("body"), dict)
            and item["body"].get("id")
            and int(item.get("status") or 0) < 300
        ]
        ids = {item["body"]["id"] for item in created}
        if len(ids) >= 2:
            return "相同 Idempotency-Key 生成了不同订单"
    expect = step.get("expect_status")
    if expect and status not in expect:
        if status >= 500:
            return f"期望 {expect}，实际 {status}"
        if 200 <= status < 300:
            return f"期望 {expect}，实际 {status}"
    return None


def judge(step: dict, call: dict, spec: dict, resources: dict, history: list) -> str | None:
    status = int(call.get("status") or 0)
    body = call.get("body")
    path = (call.get("path") or "").split("?", 1)[0]
    if step.get("expect_reject"):
        if 200 <= status < 300:
            return f"应当拒绝，实际 {status}"
        if step.get("reject_5xx") and status >= 500:
            return f"非法请求返回 {status}"
        if 400 <= status < 500:
            op = find_operation(spec, call["method"], path)
            allowed = expected_status(op or {}, status) if op else set()
            if status in allowed:
                errors = validate_call(spec, call["method"], path, status, body)
                if errors:
                    return "；".join(errors[:3])
        return None
    if step.get("boundary") and 400 <= status < 500:
        return None
    errors = validate_call(spec, call["method"], path, status, body)
    if errors:
        return "；".join(errors[:3])
    return general_invariants(step, {**call, "id": step.get("id")}, resources, history)


def _capture_resources(step: dict, call: dict, resources: dict) -> None:
    body = call.get("body")
    if isinstance(body, dict):
        token = body.get("auth_token") or body.get("token")
        extract = step.get("extract") or {}
        if isinstance(token, str) and token:
            if "admin_token" in extract:
                resources["admin_token"] = token
            if "token" in extract or not extract:
                resources["token"] = token
        if extract:
            for name, dotted in extract.items():
                value = _extract(body, dotted)
                if value is not None:
                    resources[name] = value
        if step.get("extract_other_book"):
            mine = str(resources.get("username") or "")
            items = body.get("Books") or body.get("books") or body.get("items") or []
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    owner = str(item.get("user") or item.get("owner") or "")
                    title = item.get("book_title") or item.get("title")
                    if title and owner and owner != mine:
                        resources["other_book"] = title
                        resources["other_book_owner"] = owner
                        break
                if not resources.get("other_book") and items:
                    first = items[0] if isinstance(items[0], dict) else {}
                    resources["other_book"] = first.get("book_title") or first.get("title")
                    resources["other_book_owner"] = first.get("user") or first.get("owner")


def tick(state: AgentState) -> AgentState:
    spec = state.get("spec") or shop.openapi()
    state["spec"] = spec
    executor = CURRENT
    if executor is None:
        raise RuntimeError("执行器未初始化")
    plan = state["plan"]
    if (state.get("stop_on_first", True) and state.get("detected")) or state["index"] >= len(plan):
        state["done"] = True
        return state
    step = plan[state["index"]]
    resources = dict(state.get("resources") or {})
    if is_write(step) and not state.get("auto_approve"):
        approved = set(state.get("approved_ids") or [])
        if step["id"] not in approved:
            state["pending"] = step
            state["done"] = True
            return state
    headers = _fill(dict(step.get("headers") or {}), resources)
    if step.get("auth") and resources.get("token") and "Authorization" not in headers:
        headers["Authorization"] = f"Bearer {resources['token']}"
    path = _fill(step["path"], resources)
    if isinstance(path, str) and "$" in path:
        history = list(state.get("history") or [])
        history.append(
            {
                "id": step["id"],
                "method": step["method"],
                "path": path,
                "url": path,
                "status": 0,
                "body": "skipped: missing path variable",
                "headers": headers,
                "json": step.get("json"),
                "elapsed_ms": 0,
            }
        )
        state["history"] = history
        state["index"] = state["index"] + 1
        if state["index"] >= len(plan):
            state["done"] = True
        return state
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
    _capture_resources(step, call, resources)
    state["resources"] = resources
    if state.get("use_contract_judge", True):
        reason = judge(step, call, spec, resources, history)
        if reason:
            state["detected"] = True
            state["reason"] = reason
            try:
                state["export"] = write_exports(state.get("fault") or "run", call)
            except Exception:
                state["export"] = None
            if state.get("stop_on_first", True):
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
    spec = shop.openapi()
    plan = build_plan(spec, email)
    executor = Executor()
    CURRENT = executor
    writes = [step["id"] for step in plan if is_write(step)]
    state: AgentState = {
        "fault": fault,
        "spec": spec,
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
        "approved_ids": writes if auto_approve else [],
        "use_contract_judge": True,
        "stop_on_first": True,
    }
    try:
        try:
            result = GRAPH.invoke(state, {"recursion_limit": 48})
        except Exception:
            steps = 0
            while not state.get("done") and steps < 48:
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
        "writes": writes,
    }


def run_openapi_agent(
    spec: dict,
    executor,
    *,
    auto_approve: bool = True,
    username: str = "specpilot1",
    password: str = "SpecP1pass",
    email: str = "specpilot1@mail.com",
) -> dict:
    global CURRENT
    from planner_generic import build_generic_plan

    plan = build_generic_plan(spec, username=username, password=password, email=email)
    CURRENT = executor
    writes = [step["id"] for step in plan if is_write(step)]
    state: AgentState = {
        "fault": "",
        "spec": spec,
        "auto_approve": auto_approve,
        "plan": plan,
        "index": 0,
        "resources": {"username": username, "password": password, "email": email},
        "history": [],
        "pending": None,
        "detected": False,
        "reason": "",
        "export": None,
        "done": False,
        "request_count": 0,
        "approved_ids": writes if auto_approve else [],
        "use_contract_judge": False,
        "stop_on_first": False,
    }
    limit = max(96, len(plan) + 8)
    try:
        try:
            result = GRAPH.invoke(state, {"recursion_limit": limit})
        except Exception:
            steps = 0
            while not state.get("done") and steps < limit:
                state = tick(state)
                steps += 1
            result = state
    finally:
        CURRENT = None
    return {
        "detected": bool(result.get("detected")),
        "reason": result.get("reason") or "",
        "history": result.get("history") or [],
        "export": result.get("export"),
        "request_count": result.get("request_count") or 0,
        "pending": result.get("pending"),
        "plan": [step["id"] for step in plan],
        "writes": writes,
        "resources": result.get("resources") or {},
    }
