# 运行、ENV 配置和数据维护

2026-10-24。本文件描述已实现的命令；01—03 文档保留原始设计，实际差异及验证状态见 05。

## 1. 只编辑根目录 `.env`

根目录 `.env` 用于你本机运行，已被 Git 忽略；`.env.example` 是可分享的字段模板，不放真实密钥。若当前仓库已有生成的 `.env`，其中数据库密码是随机值，模型地址/密钥/名称留空。不要把它发给组员或提交到 Git。

| 字段 | 填写说明 |
| --- | --- |
| MODEL_MODE | mock=无密钥流程演示；remote=真实模型 |
| LLM_BASE_URL | 兼容 API 的基础地址，通常包含 `/v1`，不要填写到 `/chat/completions` |
| LLM_API_KEY | 问答模型密钥，仅后端使用 |
| LLM_MODEL | 供应方的准确模型 ID；需支持流式聊天和 JSON 对象输出 |
| EMBEDDING_BASE_URL | 向量 API 基础地址，不填写到 `/embeddings` |
| EMBEDDING_API_KEY | 向量服务密钥；即使同供应方，也请在此明确填写 |
| EMBEDDING_MODEL | 支持所用中英文资料的向量模型 ID |
| EMBEDDING_DIM | 模型实际输出维度；mock 默认256。修改后必须重建索引 |
| MYSQL_DATABASE / MYSQL_USER | Docker 数据库名/普通应用用户，默认 travel |
| MYSQL_PASSWORD | 应用数据库密码；首次建卷前填写 |
| MYSQL_ROOT_PASSWORD | 初始化维护密码，与应用密码不同，不注入 api |
| DATABASE_URL | 本机 Python 预览默认 SQLite；Compose 固定使用内部 MySQL，覆盖此项 |
| WEB_PORT | 默认8080；修改时同时修改 ALLOWED_ORIGINS |
| ALLOWED_ORIGINS | 逗号分隔的实际浏览器来源，包含协议与端口 |
| COOKIE_SECURE | 本机 HTTP=false；正式 HTTPS=true |
| DATA_ROOT | 通常不用填；本机默认项目 data/，Compose固定为/data |
| ENABLE_GRAPH / ENABLE_MEMORY | 默认 true；评测消融时可关闭 |
| MAX_TOOL_CALLS | 每个任务工具预算，默认6 |
| RUN_TIMEOUT_SECONDS | 整个任务时间预算，默认60秒 |
| MODEL_TIMEOUT_SECONDS | 单次模型 HTTP 等待时间，默认30秒 |
| MAX_ACTIVE_RUNS | 后端同时运行任务数上限，默认8 |
| MOCK_TOKEN_DELAY | 模拟流式每块延迟，默认0.015秒 |

适配器使用 `/embeddings` 和 `/chat/completions`。不同供应商接口若不兼容，需增加对应适配器；不能只填任意网页地址。Embedding 不强行截断到指定维度，响应尺寸不符直接报错。没有密钥时不会自动调用外部模型。

修改 `.env` 后必须重新创建相关容器。仅 `docker compose restart` 不一定更新容器环境；使用 `docker compose up -d --force-recreate api web`。修改模型/维度后先重建索引，再启动 API。

MySQL 已有数据卷时，修改 `.env` 密码不会自动修改库内账户；需要按 MySQL 账户维护流程同步，不能简单换值后预期现有卷自动更新。

## 2. Docker 首次演示

确认 Docker Desktop 引擎运行、`docker info` 成功；在项目根目录：

```bash
sh scripts/start-demo.sh
docker compose ps
docker compose logs --tail=100 api
```

访问 http://localhost:8080。三常驻容器；tools 只在迁移/导入/评测时临时运行。web 对外提供端口，MySQL/api 默认不向主机发布端口。首次拉取镜像和安装依赖需要网络；远端模型调用需要后端网络。

初始化随附的 6 个景点都是虚构夹具，前端显示警告。测试真实问答前应导入经核验的真实资料，并运行真实模型。

## 3. 导入真实资料

复制 `data/templates/` 到 `data/raw/my-dataset/`，按字段字典填写。documents.csv 中 raw_path 是相对 DATA_ROOT 的 UTF-8 正文路径，例如 `raw/my-dataset/history.txt`；当前原文入口为文本/Markdown，PDF/图片需先提取为文本并登记来源，尚无自动 PDF/OCR 解析。目录可只含需要更新的 CSV；依赖来源/实体必须已存在或同时提供。

整批在同一事务中导入；错误会给出表名和行号。发布版本使用自己的版本名，不能沿用 demo-v1。source.status=verified 必须同时填写 verified_at；source_type=official 不能仅凭网址猜测，需核对具体页面。

维护窗口内停止 web/api，保留 mysql：

```bash
docker compose stop web api
docker compose --profile tools run --rm tools python -m app.cli validate-data --input /data/raw/my-dataset --version hk-v1
docker compose --profile tools run --rm tools python -m app.cli ingest --input /data/raw/my-dataset --version hk-v1
docker compose --profile tools run --rm tools python -m app.cli build-index
docker compose up -d --wait api web
```

validate-data 使用一次性 SQLite 进行字段/关系预检查；最终导入仍由 MySQL 外键与类型约束验证，预检查不能替代它。更新模型配置时，tools 和 api 都从同一 `.env` 读取。

导入采用 merge 更新，不隐式删除旧实体。若从演示切换为真实资料，需在新导入的 entities.csv/documents.csv 中将旧演示记录标为 inactive（提供记录原必填字段），或使用专用新数据库/索引卷。不要在有真实会话数据的环境直接删除数据库卷。若仍含合成资料，前端保留提醒。

资料/模型/分词变更必须建索引；索引校验失败时 API ready 返回503，不会静默使用错误映射。CLI 与在线 API 不支持同时修改知识库，必须遵循维护窗口步骤。

## 4. 本机调试

根目录 `.env` 保留 `DATABASE_URL=sqlite:///./travel.db`。Python3.12 下安装 lock 文件后，切换 backend 目录执行：

```bash
python -m app.cli bootstrap --demo
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1
```

上述 python 指已激活的虚拟环境解释器。根目录配置会自动加载；相对 SQLite 路径相对当前工作目录，因此这些命令始终从 backend 运行。

## 5. 评测与消融

Docker 使用 /demo 中的随附 JSONL，输出映射到本地 data/reports：

```bash
docker compose --profile tools run --rm tools python -m app.cli evaluate --input /demo/evaluation.jsonl --output /reports --split dev --channels vector,bm25,entity,graph
```

本机运行：

```bash
cd backend
python -m app.cli evaluate --input ../data/demo/evaluation.jsonl --output ../data/reports --split dev
python -m app.cli evaluate --input ../data/demo/evaluation.jsonl --output ../data/reports --split test
```

`--channels vector`、`--channels bm25`、`--channels vector,bm25,entity` 可做检索消融。关闭 ENABLE_GRAPH 后重启/重新运行评测，关系通道停用。真实数据需要自己的 JSONL、正确 chunk ID 和 dataset_version，不能对真实索引使用演示集。

报告包括逐条答案、召回、引用、关系路径、字符串事实覆盖代理指标、时延和调用信息，需人工核对语义正确性/引用是否支持结论。mock/虚构样本高召回不代表真实质量。尚未提供自动语义评委或100条人工核验真实题库。

## 6. 备份与恢复

数据库备份使用容器内环境变量，密码不写在主机命令参数中：

```bash
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysqldump --no-tablespaces --single-transaction -u "$MYSQL_USER" "$MYSQL_DATABASE"' > travel-backup.sql
```

备份同一维护窗口的数据与索引卷；索引也可由已保存原文和对应模型重建。恢复时先创建专用库并导入备份，再恢复相符索引或重新 build-index，确认 ready 后开放 web。备份内含会话和偏好，应本地保存，不提交 Git。

日常停止用 `docker compose down`，保留数据卷。API 重启将遗留未完成任务标为 interrupted，用户可重试；没有任意 Token 位置续写、跨设备登录或多副本任务协调。
