# 港慢游 · Hong Kong, your way

DSAI5205 香港旅行问答与行程规划项目。当前进度快照：**1.3.23 · 2026-10-23**。

用同一段对话查地点、选择景点、按日期规划并继续修改行程。Python / FastAPI 后端与原生网页前端，无需前端构建。无 API Key 时可运行本地检索和规划；配置后可主动开启大模型，并使用高德地点与步行路线。

![港慢游首页](docs/evidence/home-restored/static-home.png)

## 当前功能

- **地点检索**：33 条附官方来源的香港地点资料，支持 SQLite FTS5 BM25 关键词检索，以及可选的本地 BGE 中文 Embedding 混合检索；地点页统一搜索，本地未命中时可补充高德结果并标明来源。
- **多轮 Agent**：LangGraph 管理工具循环；模型结合有界历史、偏好与最新行程选择更新条件、查资料、读行程和修改行程等工具。支持连续指代、移动／替换／删除／加入地点及交换两天，修改由服务端校验。
- **完整日期规划**：起止日期计算包含首尾的完整日历，支持长行程和休息日。必去地点可多选，不再限制三个；按街区与节奏分配，容量不足时提示调整日期，不截断选择。
- **交通与地图**：OSM 行程总览；本地港铁线路、方向、换乘、出口与到站接驳参考。步行小地图展开后自动查询高德，确认同名地点或餐饮分店后展示路线图、距离时长和导航入口，图片可放大。
- **本机历史**：保存、继续聊、手动重命名、收藏、置顶及删除确认；最近对话与偏好收进“我的旅程”浮窗。
- **可审查执行**：引用来源、工具过程与停止原因可查看；真实高德失败不使用示意线冒充路线。

混合检索将 BM25 结果与本地向量的余弦相似度结果用 RRF 排名融合，保留名称优先和筛选条件。语义模型或索引不可用时回退 BM25，并在执行记录中标明原因；尚未接入神经重排，也不宣称混合检索必然提高准确率。行程排程采用约束筛选、街区分组和近邻启发式，不宣称全局最优路线。

## 本机运行

需要 Python 3.11+。在仓库根目录运行：

```sh
python3 start.py
```

首次启动安装依赖，随后打开 `http://127.0.0.1:8765`。macOS 也可双击 `启动港慢游.command`，Windows 双击 `启动港慢游.bat`。保留启动窗口；应用只监听本机。

如需手动安装与启动：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python run.py --port 8767
```

Windows 使用 `.venv\Scripts\python.exe` 替换上述 Python 路径。

## 可选配置

参考根目录 `.env.example` 在自己电脑创建 `.env`，不要提交真实密钥：

```dotenv
MODEL_API_KEY=
MODEL_BASE_URL=https://integrate.api.nvidia.com/v1
MODEL_NAME=deepseek-ai/deepseek-v4.1-flash
AMAP_API_KEY=
AMAP_ENABLED=false
```

- 没有密钥即可使用本地规则演示，网页会标明模式。
- 配置模型后，勾选“使用大模型”才发起模型请求；问题、有限上下文、偏好及相关资料会发送给所配置服务。
- 当前示例配置使用 NVIDIA 官方 DeepSeek-V4.1-Flash 免费开发端点，需要自己的 NVIDIA API Key；免费试用范围、额度与可用性以平台为准。见 [NVIDIA 接入说明](docs/NVIDIA免费模型接入.md)。不自动切换到付费模型或服务。
- 使用高德需要自己的 Web 服务 Key，并设置 `AMAP_ENABLED=true` 后重启；费用、额度和服务权限由自己的供应商账户决定。
- 历史保存于忽略的 `work/user-data/conversations.sqlite3`。单机最多 25 段对话，每段保存最近 20 轮；模型上下文有长度边界，没有无限记忆或云同步。

## 本地 Embedding 与 RAG

推荐课程演示使用“本地 Embedding ＋云端大模型”。Embedding 使用 FastEmbed / ONNX 在 CPU 上运行 `BAAI/bge-small-zh-v1.5`，生成 512 维向量；当前资料量较小，采用本地精确余弦检索。

已有项目虚拟环境后，在仓库根目录执行：

```sh
.venv/bin/python -m pip install -r requirements-embedding.txt
.venv/bin/python scripts/build_embeddings.py --download
```

首次构建下载公开模型，之后查询只读取本机缓存。模型缓存在 `work/models/`，资料向量保存在 `data/indexes/places-embeddings.json`，均由 Git 忽略。组员需在各自电脑准备一次。

在根目录 `.env` 添加以下配置，然后重启应用：

```dotenv
RETRIEVAL_MODE=hybrid
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_MIN_SCORE=0.5
```

不调用云端即可检查真实检索：

```sh
.venv/bin/python scripts/rag_demo.py --query "想了解香港历史建筑和艺术，有什么地方推荐？"
```

输出中的 `retrieval.embedding_used: true` 表示本轮确实执行了向量检索。填写 `MODEL_API_KEY` 后，可加 `--use-model` 验证一次云端 RAG 回答，或在网页勾选“使用大模型”。模型响应失败会明确回退；仅填写 Key 不表示已验证服务连通。

修改知识库或 Embedding 模型后需要重建索引。完整安装、配置、回退和演示步骤见 [Embedding 接入说明](docs/Embedding接入说明.md)。

## 演示与验证

1. 查询“中环有什么文化景点”，查看资料与出处。
2. 选择扶梯、元创方、兰芳园、动植物公园四处，告诉助手“玩两天”。
3. 在模型模式继续移动、替换地点，刷新后交换两天或回顾已排除地点。
4. 展开步行小地图；高德出现同名地点或分店时确认地址，再查看路线图。
5. 用“我的旅程”重命名、收藏、置顶和重新打开对话。

发布副本自动检查：**297 项 Python、17 项前端检查通过**，另有数据验证、开发检索、真实本地 stdio MCP 与 Agent 验收。见 [发布回归](docs/evidence/release-2026-10-23/summary.json)。

```sh
.venv/bin/python scripts/verify.py --out docs/evidence/latest
```

Node.js 可用时同时运行前端检查；否则会明确记录未运行。普通回归使用空配置或模拟供应商，不调用真实付费模型／地图。

真实网页检查另存记录，不能将它们当作独立准确率评测：

| 记录 | 验证内容 |
| --- | --- |
| [多轮网页测试](docs/evidence/floating-web-test/验收说明.md) | 连续指代、行程修改、刷新恢复与同行偏好回顾 |
| [四地点修复](docs/evidence/four-place-fix/验收说明.md) | 四处完整规划、移动、替换、排除与交换两天 |
| [高德优先小地图](docs/evidence/amap-first-walk/验收说明.md) | 自动查询、位置确认、真实静态路线图与放大 |
| [元创方到扶梯](docs/evidence/poi-name-fix/验收说明.md) | 名称格式兼容，实测 339 米、约 5 分钟 |
| [公园到兰芳园](docs/evidence/day2-walking-map/验收说明.md) | 分店确认，实测 756 米、约 11 分钟 |
| [最新简洁地图检查](docs/evidence/walk-map-only/browser-check.json) | 保留地图与导航，不显示逐步转弯文字列表 |

真实调用中出现过格式修复和查询失败，相关记录保留。少量跑通的例子不能保证任意表述、地点或网络条件都成功；距离时长是供应商估计。

## 目录与接口

```text
app.py / run.py / start.py   HTTP 应用、启动与安装入口
travel/                     Agent、会话、检索、规划、交通与地图服务
static/                     原生网页、地图组件与本地 Leaflet 依赖
data/                      地点、交通参考与开发／冻结检查题
tests/                     Python 与 Node 检查
scripts/                   验证、诊断、资料维护和源码打包
docs/                      接口、技术说明及验收证据
```

[`docs/api.md`](docs/api.md) 记录当前接口。初始仓库的 `frontend/`、`backend/` 目录仍保留，当前可运行实现位于根目录 `static/`、`travel/` 与 `app.py`，没有重复安装两套应用。协作流程见 [开发说明](docs/development.md)。

## 范围与贡献说明

本项目为 Codex 辅助开发的本地原型。港铁线路与出口为本地整理的官方资料参考，步行／乘车余量不含实时延误；未核验营业日历、天气、票务、酒店往返或完整费用预算。高德路线图使用供应商返回的 POI 坐标，不把本地近似地点坐标直接当作导航坐标。当前未提供生产部署、多用户账户或正式质量基准。

地点摘要附来源链接与核对日期，未打包第三方全文；照片仅作装饰。Leaflet 依赖保留原许可证与来源信息。请按本人实际完成、理解和验证的工作描述个人贡献。
