# DSAI5205-rag-travel-project

DSAI5205 小组项目：基于 RAG 的旅行问答与规划系统。

当前阶段：目录骨架已建立，前端源码待导入，后端业务代码待开发。启动命令和依赖会随实际代码补充。

## 目录说明

```text
DSAI5205-rag-travel-project/
├── frontend/                 前端同学的应用代码
├── backend/                  Python 后端
│   ├── app/
│   │   ├── api/              HTTP 接口
│   │   ├── core/             配置、日志等公共模块
│   │   ├── services/         旅行问答与规划业务逻辑
│   │   └── rag/
│   │       ├── ingestion/    文档读取、切分与入库
│   │       ├── retrieval/    知识检索
│   │       └── generation/   提示词、模型调用与答案生成
│   ├── tests/                后端测试
│   └── .env.example          本地配置示例
├── data/
│   ├── raw/                  原始资料
│   ├── processed/            清洗和切分后的数据
│   └── indexes/              本地检索索引
├── docs/
│   ├── api.md                前后端接口约定
│   └── development.md        开发与 Git 协作流程
├── scripts/                  数据处理、索引构建等脚本
├── .editorconfig             基础文本格式约定
└── .gitignore                本地配置、依赖和生成文件的忽略规则
```

空目录中的 `.gitkeep` 用于让 Git 保留目录；添加实际文件后可移除。

## 从哪里开始

- 前端同学：将应用源码放入 `frontend/`，参考 [前端接入说明](frontend/README.md)。
- 后端同学：参考 [后端说明](backend/README.md)，在 `backend/app/` 下实现模块。
- 开始联调前：在 [接口文档](docs/api.md) 中约定请求、响应和错误处理。
- 拉取、提交和合并：参考 [协作流程](docs/development.md)。

## 文件管理

- 依赖清单、依赖锁文件、源码和文档提交到 Git。
- 真实 API Key、`.env`、虚拟环境、`node_modules/` 和生成文件留在本地。
- 数据放置方式和共享规则见 [数据说明](data/README.md)。
