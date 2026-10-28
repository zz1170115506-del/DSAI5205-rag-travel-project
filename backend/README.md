# Python 后端

从仓库根目录配置 `.env`；不加载 backend/.env。Python 3.12，依赖及传递版本见 requirements.lock.txt。

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.lock.txt
cd backend
.venv/bin/python -m app.cli bootstrap --demo
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

bootstrap 迁移数据库、导入虚构资料并生成索引。已有真实资料时使用 `migrate`、`ingest --input ... --version ...`、`build-index` 分别维护，不重新 bootstrap 演示数据。运行时需单 worker。

| 路径 | 内容 |
| --- | --- |
| app/models.py、migrations/ | ORM 和 Alembic 初始迁移 |
| app/core/ | ENV 配置、数据库连接 |
| app/rag/ingestion/ | CSV/JSON 导入、校验、去重、切分 |
| app/rag/retrieval/ | 余弦、BM25、实体关系、RRF、筛选 |
| app/rag/provider.py | 真实兼容 API 和显式 mock 适配器 |
| app/agent/ | 类型化计划、意图路由、约束、预算内行程组合 |
| app/services/runs.py | 流式事件、Hook、取消、会话版本与任务状态 |
| app/memory/ | 显式偏好提取、更新和删除 |
| app/evaluation/ | 固定集检索/回答流程评测与逐条结果 |
| tests/ | 回归、接口、模型协议与交互状态测试 |

详细配置、导入与 Docker 步骤见 [运行指南](../Doc/04-run-and-env.md)。

## 根目录本机应用

另一套 FastAPI 应用使用根目录 `app.py` 与 `travel/`，通过 `python3 start.py` 启动；它不读取 `LLM_*`。请为两套应用分别安装依赖，避免 `app.py` 和本目录 `app/` 的导入冲突。见[根目录说明](../README.md)。
