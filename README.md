# SpecPilot

解析 OpenAPI，自动规划有状态调用和边界/安全探针。写操作可批准。执行层限制 Host 白名单、单请求超时 3 秒、全局限速 10 次/秒。失败请求可最小化并导出 curl / pytest。

主评测用公开靶场 [VAmPI](https://github.com/erev0s/VAmPI)，标准答案是其 README 的 9 类已知问题。规划不读取漏洞编号。

## 本地演示（自建商城）

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8001
```

打开 http://127.0.0.1:8001  
商城 OpenAPI：http://127.0.0.1:8001/shop/openapi.json

## 公开集评测

需要本机已有 **Python 3.12**（VAmPI 依赖暂不支持 3.13）：

```bash
py -3.12 -m venv third_party\vampi\.venv
third_party\vampi\.venv\Scripts\python.exe -m pip install -r third_party\vampi\requirements.txt werkzeug==2.2.3
python eval_vampi.py
```

| 项目 | 口径 | 结果 |
| --- | --- | --- |
| Agent | VAmPI README 9 类已知问题 | 9/9 |
| 可导出 curl / pytest | 命中类的最小化请求 | 9/9 |
| Schemathesis | 同一 9 类判定，约 200 次请求、60 秒 | 1/9 |
| 官方 vulnerable=0 | 同一套规划 | 3/9 |

`vulnerable=0` 仍为 3/9，对应 debug 泄露、无限流、弱 JWT，与官方说明一致。开关能关掉的 6 类在这次未命中。数字以 `data/eval/vampi.json` 为准。

自建商城带一组注入故障，用于页面演示，不计入上表公开集成绩。
