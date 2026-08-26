"""36 个评测故障：24 个契约故障 + 12 个按 Defects4REST 分类复现的缺陷。"""

from __future__ import annotations

FAULTS: list[dict] = []


def _add(**item: object) -> None:
    FAULTS.append(item)


# --- 24 个可控契约故障 ---
_add(
    id="C01",
    family="contract",
    title="注册成功响应缺少 id",
    oracle="schema",
)
_add(
    id="C02",
    family="contract",
    title="注册成功返回 200 而不是 201",
    oracle="status",
)
_add(
    id="C03",
    family="contract",
    title="登录 token 类型变成整数",
    oracle="schema",
)
_add(
    id="C04",
    family="contract",
    title="书目列表项缺少 title",
    oracle="schema",
)
_add(
    id="C05",
    family="contract",
    title="图书 price 变成字符串",
    oracle="schema",
)
_add(
    id="C06",
    family="contract",
    title="创建图书返回 200 而不是 201",
    oracle="status",
)
_add(
    id="C07",
    family="contract",
    title="购物车数量为 0 仍接受（schema minimum=1）",
    oracle="should_reject",
    probe={"method": "POST", "path": "/cart/items", "json": {"book_id": 1, "quantity": 0}},
)
_add(
    id="C08",
    family="contract",
    title="订单详情缺少 items",
    oracle="schema",
)
_add(
    id="C09",
    family="contract",
    title="订单 total 变成字符串",
    oracle="schema",
)
_add(
    id="C10",
    family="contract",
    title="400 错误体缺少 detail",
    oracle="schema",
    probe={"method": "POST", "path": "/auth/login", "json": {"email": "bad", "password": "x"}},
)
_add(
    id="C11",
    family="contract",
    title="删除图书后 GET 仍 200",
    oracle="status",
)
_add(
    id="C12",
    family="contract",
    title="图书 status 不在枚举内",
    oracle="schema",
)
_add(
    id="C13",
    family="contract",
    title="列表 count 与 items 长度不一致",
    oracle="invariant",
)
_add(
    id="C14",
    family="contract",
    title="创建订单成功响应缺少 id",
    oracle="schema",
)
_add(
    id="C15",
    family="contract",
    title="401 响应体不是对象",
    oracle="schema",
    probe={"method": "GET", "path": "/auth/me", "headers": {"Authorization": "Bearer bad"}},
)
_add(
    id="C16",
    family="contract",
    title="库存为负数仍可创建图书",
    oracle="should_reject",
    probe={
        "method": "POST",
        "path": "/books",
        "json": {"title": "neg-stock", "price": 10, "stock": -3},
    },
)
_add(
    id="C17",
    family="contract",
    title="非法邮箱仍可注册",
    oracle="should_reject",
    probe={
        "method": "POST",
        "path": "/auth/register",
        "json": {"email": "not-an-email", "password": "secret12", "name": "bad"},
    },
)
_add(
    id="C18",
    family="contract",
    title="相同 Idempotency-Key 会创建两笔订单",
    oracle="invariant",
)
_add(
    id="C19",
    family="contract",
    title="limit=1 仍返回全部图书",
    oracle="invariant",
)
_add(
    id="C20",
    family="contract",
    title="created_at 不是日期时间格式",
    oracle="schema",
)
_add(
    id="C21",
    family="contract",
    title="删除成功 204 却带 JSON 体",
    oracle="status",
)
_add(
    id="C22",
    family="contract",
    title="更新图书后 price 变成字符串",
    oracle="schema",
)
_add(
    id="C23",
    family="contract",
    title="购物车 book_id 响应变成字符串",
    oracle="schema",
)
_add(
    id="C24",
    family="contract",
    title="当前用户信息缺少 email",
    oracle="schema",
)

# --- 12 个按 Defects4REST 分类复现的缺陷（不是官方项目 Docker 环境）---
# 分类来源：https://github.com/ANSWER-OSU/Defects4REST
_add(
    id="D01",
    family="d4r",
    subtype="ST4",
    title="注册时多余字段可把角色改成 admin（批量赋值）",
    oracle="invariant",
    probe={
        "method": "POST",
        "path": "/auth/register",
        "json": {
            "email": "mass@shop.local",
            "password": "secret12",
            "name": "mass",
            "role": "admin",
        },
    },
)
_add(
    id="D02",
    family="d4r",
    subtype="ST5",
    title="搜索参数 q 被忽略",
    oracle="invariant",
)
_add(
    id="D03",
    family="d4r",
    subtype="ST6",
    title="无效 token 仍能访问 /auth/me",
    oracle="should_reject",
    probe={"method": "GET", "path": "/auth/me", "headers": {"Authorization": "Bearer expired"}},
)
_add(
    id="D04",
    family="d4r",
    subtype="ST7",
    title="用户删除后 token 仍可用",
    oracle="invariant",
)
_add(
    id="D05",
    family="d4r",
    subtype="ST6",
    title="错误密码登录仍返回 token",
    oracle="should_reject",
    probe={
        "method": "POST",
        "path": "/auth/login",
        "json": {"email": "user@shop.local", "password": "wrong-password"},
    },
)
_add(
    id="D06",
    family="d4r",
    subtype="ST12",
    title="未登录可读取他人订单（IDOR）",
    oracle="should_reject",
    probe={"method": "GET", "path": "/orders/1"},
)
_add(
    id="D07",
    family="d4r",
    subtype="ST8",
    title="错误 Content-Type 导致 500 而不是 415",
    oracle="status",
    probe={
        "method": "POST",
        "path": "/auth/login",
        "content": "email=a&password=b",
        "headers": {"Content-Type": "text/plain"},
    },
)
_add(
    id="D08",
    family="d4r",
    subtype="ST10",
    title="超大 book_id 返回 500 而不是 404",
    oracle="status",
    probe={"method": "GET", "path": "/books/999999999999999999999"},
)
_add(
    id="D09",
    family="d4r",
    subtype="ST11",
    title="cover_url 路径穿越被原样保存",
    oracle="invariant",
    probe={
        "method": "POST",
        "path": "/books",
        "json": {
            "title": "evil-cover",
            "price": 1,
            "stock": 1,
            "cover_url": "../../etc/passwd",
        },
    },
)
_add(
    id="D10",
    family="d4r",
    subtype="ST12",
    title="可修改其他用户资料",
    oracle="invariant",
)
_add(
    id="D11",
    family="d4r",
    subtype="ST4",
    title="空购物车仍能下单",
    oracle="should_reject",
    probe={"method": "POST", "path": "/orders", "json": {"address": "n1"}},
)
_add(
    id="D12",
    family="d4r",
    subtype="ST7",
    title="已支付订单仍可取消",
    oracle="should_reject",
)

FAULT_BY_ID = {item["id"]: item for item in FAULTS}
CONTRACT_IDS = [item["id"] for item in FAULTS if item["family"] == "contract"]
D4R_IDS = [item["id"] for item in FAULTS if item["family"] == "d4r"]


def all_ids() -> list[str]:
    return [item["id"] for item in FAULTS]
