# 评测数据

题目来源和口径写清楚，成绩只采用本仓库脚本实跑结果。

## 被测服务

自建图书商城（`shop.py`），FastAPI 自动生成 OpenAPI 3。主路径覆盖注册、登录、图书、购物车、下单、支付、取消。

## 36 个故障

| 类别 | 数量 | 说明 |
| --- | --- | --- |
| 契约故障 C01–C24 | 24 | 状态码、字段类型、必填项、幂等、分页等，针对本商城 OpenAPI |
| Defects4REST 分类复现 D01–D12 | 12 | 按 [Defects4REST](https://github.com/ANSWER-OSU/Defects4REST) 的 ST4–ST12 分类，在本商城中实现可触发缺陷。**不是**官方 12 个上游项目的 Docker checkout |

## 最近一次实跑

命令：`python eval_faults.py`、`python eval_false_positive.py`、`python eval_compare.py`

| 项目 | 结果 |
| --- | --- |
| Agent 检出 | 36/36 |
| 失败请求可导出 curl/pytest | 36/36 |
| 无故障 24 条误报 | 0/24 |
| Schemathesis（约 200 次请求、60 秒预算） | 2/36 |

Schemathesis 明显更低，是因为它基本不做「注册→加购→下单」这种有状态序列，多数可控故障需要特定步骤才会出现。不要把 75.0% / 50.0% / 误报 4.2% 写进简历，那不是这次脚本的结果。
