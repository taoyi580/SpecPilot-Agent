# SpecPilot

解析自建图书商城的 OpenAPI，自动规划「注册 → 登录 → 加购 → 下单」，写操作可人工批准。执行层限制 Host 白名单、3 秒超时、10 次/秒限速。失败请求可最小化并导出 curl / pytest。

评测数字以 `data/eval/` 里脚本实跑结果为准。

## 本地运行

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000

图书商城 OpenAPI：http://127.0.0.1:8000/shop/openapi.json

## 评测

```bash
python eval_faults.py
python eval_false_positive.py
python eval_compare.py
```

- 24 个契约故障 + 12 个按 [Defects4REST](https://github.com/ANSWER-OSU/Defects4REST) 分类在本商城复现的缺陷（不是官方 12 个上游项目的 Docker 环境）
- Schemathesis 对照预算：200 次请求、60 秒
