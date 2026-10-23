# 后端入口

当前后端入口在仓库根目录 [`app.py`](../app.py)，业务模块在 [`travel/`](../travel/)，采用 FastAPI、LangGraph 与官方 MCP SDK。Python 依赖清单及锁文件均在根目录。

在根目录执行 `python3 start.py`。完整运行与验证方法见根目录 README。配置使用根目录 `.env.example`；此目录原 `.env.example` 为初始方案草稿，当前应用不读取其中的 `LLM_*` 变量。

`travel/chat.py` 处理统一对话与历史；`agent.py` 管理模型工具循环；`retrieval.py` 处理词法召回和特征重排；`planner.py` 与 `itinerary_edits.py` 规划和修改行程；`maps.py` 适配高德 Web 服务。

此目录保留初始仓库骨架，当前实现没有重复复制到 `backend/app/`。新增功能请先约定实际文件路径，避免两套实现分叉。
