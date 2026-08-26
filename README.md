# SpecPilot

解析自建图书商城的 OpenAPI，自动规划「注册 → 登录 → 加购 → 下单」。写操作可批准。执行层限制 Host 白名单、单请求超时 3 秒、全局限速 10 次/秒。失败请求可最小化并导出 curl / pytest。

## 本地运行

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000  
商城 OpenAPI：http://127.0.0.1:8000/shop/openapi.json

## 评测（本仓库实跑）

```bash
python eval_faults.py
python eval_false_positive.py
python eval_compare.py
```

| 项目 | 口径 | 结果 |
| --- | --- | --- |
| Agent 检出 | 24 个契约故障 + 12 个按 Defects4REST 分类复现的缺陷 | 36/36 |
| 可导出 curl / pytest | 最小化失败请求 | 36/36 |
| 误报 | 24 条无故障注册到下单 | 0/24 |
| Schemathesis | 约 200 次请求、60 秒 | 2/36 |

12 个「真实缺陷」是按 Defects4REST 分类在本商城复现的，不是官方项目的 Docker 环境。数字以 `data/eval/` 为准。
