# main 与 fullstack 合并说明

冲突基线：fullstack 从 `915c4b3` 开始开发，main 已前进到 `42642a1`，包含另外一套根目录应用。冲突共八处：`.env.example`、`.gitignore`、根 README、backend/frontend/data/scripts README 和 `docs/api.md`。代码没有逐行冲突，但直接选一侧会丢失另一套应用的运行说明与配置。

解决策略：保留双方源码、数据和历史。根 README 列出两个入口；原 main 的 API 保留在 `docs/api.md`，六模块协议保存到 `Doc/09-fullstack-api.md`；完整 Docker 说明保留在 `Doc/10-fullstack-guide.md`。忽略规则合并，真实 ENV、数据库与用户历史不提交。

原 main 的本地 Embedding 现在优先读取 `LOCAL_EMBEDDING_MODEL`；没有配置 Docker 的 `MODEL_MODE` 时，继续兼容旧的 `EMBEDDING_MODEL`。这避免 Docker 远端模型名被误当成本地 BGE 模型。现有真实 `.env` 不改动。

根 `pytest.ini` 限定根应用的 `tests/`；六模块在 `backend/` 下运行自己的测试，避免根 `app.py` 与 `backend/app/` 相互遮蔽。两套依赖分开安装。

## 合并验证（2026-10-28）

- 六模块后端：43 项通过（独立 Python 3.12 环境，临时 SQLite、模拟模型）。
- 原 main：根目录 scripts/verify.py 全部通过，涵盖 Python 回归、资料校验、开发检索、本地 MCP、Agent 与前端；使用独立 Python 3.14 环境，从根 requirements.txt 安装依赖。
- 两套前端：25 项 Node 测试通过。
- Docker Compose 配置校验通过；相对 main 的变更文件凭证检查通过；无未解决冲突。
- 未重新调用真实模型或地图，未改变运行中的容器与真实 ENV。
