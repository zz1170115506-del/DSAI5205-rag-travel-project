# 应用目录与开发入口

当前架构改造以 `app.py + travel/ + static/` 为主线。启动使用 `python3 start.py`，公网入口为 `scripts/serve_public.py`。两者均运行根目录的 `app:app`，浏览器调用 `/api/` 接口。

## 当前文件结构

```text
DSAI5205-rag-travel-project/
├── app.py                         # FastAPI 组装与应用入口
├── start.py / run.py               # 本机启动
├── travel/
│   ├── api/                       # HTTP 接口、流式响应
│   ├── core/                      # 配置、访问控制、显示语言
│   ├── session/                   # 会话存储、有限历史、地点上下文
│   ├── workflows/                 # 条件路由、Agentic RAG；保留兼容 Agent
│   ├── rag/                       # 来源资料、检索、证据回答、地图补充
│   │   └── ingestion/chunking.py  # 离线文档切块算法
│   ├── itinerary/                 # 旅行条件、日期、规划、编辑、交通和只读价格
│   └── tools/                     # MCP 客户端/服务端与地图适配
├── static/
│   ├── index.html                 # 页面结构
│   ├── js/app.js                  # 页面初始化、事件与状态连接
│   ├── js/core/                   # API 响应、语言和日期公共函数
│   ├── js/chat/                   # 聊天内容与引用显示
│   ├── js/itinerary/              # 地图、步行指引、草案缓存与价格显示
│   ├── css/                       # 基础样式和独立的同屏 workspace.css
│   ├── assets/                    # 图片与图标
│   ├── locales/                   # 显示语言资源
│   └── vendor/                    # 已固定的第三方浏览器资源
├── scripts/
│   ├── knowledge/build_chunks.py  # 切块导出命令
│   ├── knowledge/build_index.py   # 段落向量索引构建
│   └── ...                        # 验证、建索引、演示与部署脚本
├── data/                          # 可部署资料与数据规范
│   └── knowledge/                 # 段落、处理报告及字段说明
├── tests/                         # 主应用 Python 与前端测试
├── docs/                          # 当前主应用说明
│   └── implementation/            # 独立实施日志
├── work/                          # 忽略的缓存、私有历史、本机验证产物
├── backend/ + frontend/           # 保留的另一套 Docker 实现
└── Doc/                           # Docker 实现配套说明与历史验证
```

## 代码职责

- 接口层验证请求并保存结果，不承担检索算法或规划算法。工作流层负责路由、条件与循环，领域代码分别位于 `rag/` 和 `itinerary/`。
- 旅行条件及校验统一放在 `itinerary/preferences.py`；会话数据保存在 `session/`，不能从聊天文本推测或覆盖当前行程。
- 价格定义、已知小计和待核实项目位于 `itinerary/pricing.py`，只读展示，不参与筛选或金额优化。
- 当前主流程为 `workflows/conditional.py`，旅游问答循环为 `workflows/rag.py`，结构化模型适配为 `core/model.py`，段落检索为 `rag/documents.py`。`workflows/agent.py` 和 `itinerary/journey.py` 保留兼容能力与复用工具。
- 行程显示与会话状态模块分别为 `js/itinerary/render.mjs`、`workspace.mjs`，布局为 `css/workspace.css`。前端新模块按职责放入 `js/chat/`、`js/itinerary/` 或 `js/core/`，不能继续把所有新功能堆在 `app.js` 中。入口模块负责连接页面与业务组件。
- 跨包导入使用完整的 `travel.<职责>.<模块>` 路径。MCP 服务端命令为 `python -m travel.tools.mcp_server`。

## 两套实现的边界

`backend/ + frontend/ + compose.yaml` 是保留的 MySQL/Docker 实现，接口为 `/api/v1/`，配套说明在 `Doc/`。它与当前演示的会话、配置和启动方式不同。此次目录整理没有搬动这套实现；客户金额上限功能按用户要求也从该实现中移除，避免继续提供旧入口。

## 数据处理与验证

在仓库根目录运行：

```sh
python3 scripts/knowledge/build_chunks.py
.venv/bin/python -m pytest -q
node --test tests/*.test.mjs
```

切块命令默认读取仓库旁的 `知识库/documents.jsonl`，也可用 `--input` 指定其他输入。导出内容不包含原件绝对路径，部署时直接使用 `data/knowledge/`；服务器无需访问开发电脑。外层 `知识库/build_chunks.py` 保留原命令的转发入口，算法仅维护仓库内的一份。

新日志存入 `docs/implementation/`，大体积的验证输出存入 `work/`。外层用户维护的“11.6改进流程”仅在用户明确授权时修改。
