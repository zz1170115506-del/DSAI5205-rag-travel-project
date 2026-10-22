# 后端

先按 Python 项目划分模块。Web 框架、模型服务、检索方案和依赖清单将在实现时确定。

| 目录 | 职责 |
| --- | --- |
| `app/api/` | 接收请求、校验参数、组织响应 |
| `app/core/` | 配置读取、日志和公共设置 |
| `app/services/` | 组织旅行问答与规划等业务流程 |
| `app/rag/ingestion/` | 读取资料、切分文本、生成向量并建立索引 |
| `app/rag/retrieval/` | 检索与问题相关的知识片段 |
| `app/rag/generation/` | 构造提示词、调用模型、整理答案与来源 |
| `tests/` | 后续功能的测试 |

## 本地配置

从仓库根目录执行：

```bash
cp -n backend/.env.example backend/.env
```

`.env.example` 目前是配置草案；应用入口与配置加载逻辑尚未实现。这一步仅创建本地配置文件。

后续确定 Python 版本和依赖管理方式时，应提交相应的依赖清单，补充安装与启动步骤。虚拟环境可放在 `backend/.venv/`。

## 开发顺序

1. 与前端约定 `../docs/api.md` 中的接口。
2. 实现应用入口、配置读取与基础接口。
3. 接入资料处理、检索和模型生成流程。
4. 补充关键功能测试和可复现的运行说明。

数据目录约定见 `../data/README.md`。访问数据时应明确按项目根目录解析路径，避免依赖启动终端所在的位置。

# 后端

技术栈：Python 3.11、FastAPI、Uvicorn。

当前已实现健康检查接口；旅游攻略生成、RAG 检索和外部 LLM 调用尚未实现。

# From NuieHytoilee, 10.23

## 首次配置

我的本地环境配置使用 Anaconda Prompt，进入项目根目录后执行：

```bat
conda create -n rag-backend python=3.11 pip
conda activate rag-backend
python -m pip install -r backend\requirements.txt
```

## 本地启动

(Anaconda Prompt)
在项目根目录执行：

```bat
conda activate rag-backend
python -m uvicorn app.main:app --app-dir backend --reload
```

服务运行时保持终端打开，按 Ctrl+C 停止。

## 验证

- 健康检查：http://127.0.0.1:8000/api/health
- 接口文档：http://127.0.0.1:8000/docs

健康检查成功时返回 HTTP 200：

```json
{"status":"ok"}
```

当前已实现：
- GET /api/health：健康检查。
- POST /api/travel/plan：校验旅游需求并返回 mock 示例行程。

旅游接口已通过正常请求、简单非法参数检查和天数上下限的本地验证。
RAG 检索和外部 LLM 调用尚未实现。