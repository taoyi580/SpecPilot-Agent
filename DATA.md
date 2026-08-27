# 评测数据

成绩只采用本仓库脚本的实跑结果。公开集以 VAmPI 的 9 类已知问题为准。自建商城的注入故障只用于本地演示，不计入公开集成绩。

## 公开测试集

[VAmPI](https://github.com/erev0s/VAmPI)（MIT）。官方 OpenAPI 3，14 条路径。标准答案是 README 里写明的 9 类已知问题。

命令：

```bash
py -3.12 -m venv third_party\vampi\.venv
third_party\vampi\.venv\Scripts\python.exe -m pip install -r third_party\vampi\requirements.txt werkzeug==2.2.3
python eval_vampi.py
```

评测会克隆 VAmPI、按官方 `vulnerable=1/0` 拉起服务。规划只读公开 OpenAPI，不读 9 个漏洞编号。同一套判定规则再打 Schemathesis 的请求记录。

启动时仅把 Flask `debug` 关掉、端口改成 5055，方便评测进程管理。漏洞逻辑未改。

## 最近一次实跑

`python eval_vampi.py`（2026-08-26）

| 项目 | 口径 | 结果 |
| --- | --- | --- |
| Agent | VAmPI 官方 9 类 | **9/9** |
| 失败请求可导出 curl/pytest | 命中类的最小化请求 | 9/9 |
| Schemathesis | 同一 9 类判定，约 200 次请求、60 秒 | **1/9**（无限流） |
| 官方 `vulnerable=0` | 同一套规划再跑 | **3/9** |

`vulnerable=0` 仍命中的 3 类是：debug 接口泄露密码、没有 429 限流、JWT 弱密钥。这和 VAmPI README / `app.py` 的说明一致：关掉开关后，有的问题本来就不会消失。

开关能关掉的 6 类（SQL 注入、越权改密、BOLA、批量赋值、用户名枚举、ReDoS）在 `vulnerable=0` 时均未命中。

## 9 类明细（Agent / Schemathesis / vuln=0）

| 类别 | Agent | Schemathesis | vuln=0 |
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

Agent 实际发了 47 次请求。Schemathesis 发了 196 次、13.58 秒，只打到无限流。

## 被测服务（演示用，不算公开集成绩）

自建图书商城仍可本地演示：解析 OpenAPI、规划注册到下单、写操作可批准。那是产品演示，不是这组公开集数字。
