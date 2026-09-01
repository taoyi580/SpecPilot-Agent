# SpecPilot

从 OpenAPI 自动规划并执行有状态接口调用，检查契约偏差和常见安全问题。写操作可批准。执行层限制 Host 白名单、单请求超时 3 秒、单执行实例限速 10 次/秒。命中后裁剪失败请求并导出 curl / pytest，便于复现。

公开集评测使用 [VAmPI](https://github.com/erev0s/VAmPI)（MIT）。标准答案是其 README 写明的 9 类已知问题。规划只读官方 OpenAPI，不读取漏洞编号。

## 它做什么

按 schema 随机发请求，很难打到「先登录、再拿别人的资源」这类问题。SpecPilot 先把文档收成可执行计划，带着会话和资源 ID 往下走，再挂上通用探针。

```text
OpenAPI 文档
    → 规划：注册 / 登录 / 资源读写 + 安全探针
    → 写操作批准
    → 受控执行（白名单 · 超时 · 限速）
    → 对照契约和不变量
    → 裁剪命中请求，导出 curl / pytest
```

探针覆盖的问题类型与 VAmPI 公开清单对齐，例如：

- SQL 注入（路径参数）
- 未授权改密
- 对象级越权（BOLA）
- 批量赋值（多余字段提升权限）
- debug 接口过度暴露
- 用户名 / 密码枚举
- 病态输入导致的 RegexDOS
- 缺少限流
- JWT 弱密钥

## 在另一台电脑运行

普通展示页面推荐使用 **Python 3.12（64 位）**，不需要模型密钥，也不需要先安装 VAmPI。

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8001
```

macOS / Linux：

```bash
python3.12 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8001
```

打开 http://127.0.0.1:8001 ，或访问 http://127.0.0.1:8001/health 检查服务状态。

## 公开集结果

被测服务是 VAmPI 官方实现，OpenAPI 3，14 条路径。同一套判定规则打三组实验，数字以 `data/eval/vampi.json` 为准（`python eval_vampi.py`，2026-08-26）。

| 实验 | 口径 | 结果 |
| --- | --- | --- |
| SpecPilot | 官方 9 类已知问题 | **9/9**（47 次请求） |
| 可导出 curl / pytest | 命中类的裁剪请求 | 9/9 |
| [Schemathesis](https://github.com/schemathesis/schemathesis) | 同一 9 类、约 200 次请求 / 60 秒 | **1/9**（196 次请求，只打到无限流） |
| 官方 `vulnerable=0` | 同一套规划再跑 | **3/9** |

`vulnerable=0` 仍命中的 3 类是 debug 泄露密码、没有 429、JWT 弱密钥。这和 VAmPI 自己的说明一致：关掉开关后，这几类本来就不会消失。开关能关掉的 6 类（SQL 注入、越权改密、BOLA、批量赋值、用户名枚举、ReDoS）在这次均未命中。

| 类别 | SpecPilot | Schemathesis | vuln=0 |
| --- | --- | --- | --- |
| SQLi Injection | 中 | — | — |
| Unauthorized Password Change | 中 | — | — |
| Broken Object Level Authorization | 中 | — | — |
| Mass Assignment | 中 | — | — |
| Excessive Data Exposure (debug) | 中 | — | 中 |
| User and Password Enumeration | 中 | — | — |
| RegexDOS | 中 | — | — |
| Lack of Resources & Rate Limiting | 中 | 中 | 中 |
| JWT weak signing key | 中 | — | 中 |

明细和判定依据见 [DATA.md](DATA.md)。

## 复现评测

VAmPI 依赖需要 **Python 3.12**。首次评测先下载公开靶场，再单独创建其虚拟环境。

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -c "from vampi_runtime import ensure_cloned; ensure_cloned()"
py -3.12 -m venv third_party\vampi\.venv
third_party\vampi\.venv\Scripts\python.exe -m pip install -r third_party\vampi\requirements.txt werkzeug==2.2.3
.\.venv\Scripts\python.exe eval_vampi.py
```

macOS / Linux：

```bash
./.venv/bin/python -c "from vampi_runtime import ensure_cloned; ensure_cloned()"
python3.12 -m venv third_party/vampi/.venv
./third_party/vampi/.venv/bin/python -m pip install -r third_party/vampi/requirements.txt werkzeug==2.2.3
./.venv/bin/python eval_vampi.py
```

需要提前安装 Git，并允许访问 GitHub。VAmPI 源码下载到 `third_party/vampi/`，不提交到本仓库。评测进程把服务端口放到 `5055`，并关掉 Flask `debug`，漏洞逻辑未改。

## 执行约束

| 约束 | 取值 |
| --- | --- |
| Host 白名单 | 仅允许评测与本机回环地址（见 `constraints.py`） |
| 单请求超时 | 3 秒 |
| 单执行实例限速 | 10 次 / 秒 |
| 写操作 | POST / PUT / PATCH / DELETE 需批准后才发出 |
| 失败导出 | 去掉无关执行字段，写成 curl 和 pytest |

## 仓库结构

| 路径 | 作用 |
| --- | --- |
| `planner_generic.py` | 从 OpenAPI 生成有状态步骤和安全探针 |
| `agent.py` | LangGraph 编排：规划 → 批准 → 执行 → 校验 → 导出 |
| `executor.py` | HTTP 执行，走白名单 / 超时 / 限速 |
| `validator.py` | 对照文档检查状态码、必填字段和基础类型 |
| `oracles_vampi.py` | 按 VAmPI 公开 9 类对请求记录打分 |
| `eval_vampi.py` | 拉起靶场，跑 Agent、Schemathesis、`vulnerable=0` |
| `exporter.py` | 失败请求裁剪并导出 |
| `vampi_runtime.py` | 评测时启动 / 停止 VAmPI |
| `data/eval/vampi.json` | 最近一次实跑结果 |
| `DATA.md` | 评测口径和 9 类明细 |

规划器按路径与方法推断注册、登录、资源读写，再挂探针；`oracles_vampi.py` 只根据 HTTP 记录判定，双方都不读取靶场的漏洞编号列表。
