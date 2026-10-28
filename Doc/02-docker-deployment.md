# Docker Compose 部署设计

状态：部署计划；本次尚未创建 Dockerfile、Compose 文件或启动脚本，以下命令需在相应实现交付后执行。

## 1. 三个常驻服务

| 服务 | 内容 | 容器端口 | 主机端口 | 持久化 |
| --- | --- | --- | --- | --- |
| web | Nginx + 前端静态构建产物 | 80 | 默认 8080 | 前端镜像中包含资源 |
| api | FastAPI + 检索 + Agent + 记忆 | 8000 | 默认不发布 | rag-data 只读、MySQL |
| mysql | MySQL 8.4 系列 | 3306 | 默认不发布 | mysql-data |

浏览器访问 `http://localhost:8080`；`/api/` 转发到 `http://api:8000`，保留前缀。容器网络中使用 `mysql:3306` 连接数据库。浏览器不能使用 Compose 的服务名访问 API，容器内的 localhost 也不指向宿主机。

一个 Compose bridge 网络足够。Nginx 在 web 容器内，不再单独增加网关容器。正式演示部署若对外提供服务，需要配置 HTTPS 和访问控制。镜像 tag 在实施时选取并锁定经过验证的补丁版本/摘要，Python 和前端依赖提交锁文件；Mac Apple Silicon 和目标服务器架构分别检查兼容性，不默认强制 amd64。

## 2. 卷与数据职责

| 卷/挂载 | 内容 | 使用者 |
| --- | --- | --- |
| mysql-data | MySQL 数据目录 | mysql |
| rag-data | 已处理文档、向量、BM25、manifest 及已授权展示图片 | api 只读、一次性数据任务读写 |
| 主机 `data/raw/` | 待处理的原文与来源文件 | 一次性导入任务只读 |
| 主机 `data/evaluation/` | 审核通过的评测数据集 | 一次性评测任务只读 |
| 主机 `data/reports/` | 实验逐条结果与汇总 | 一次性评测任务读写 |

公开可分享的数据模板进入 Git；真实原文、用户会话、索引、实验产物默认本地保存。未来新增 `data/evaluation/`、`data/reports/` 前，明确公开样本与运行产物的忽略规则。数据库卷和索引卷备份分别管理，并通过 dataset_version / index_version 对齐。

向量与 BM25 文件使用可信本地构建的格式，例如 `.npy` + JSON；不加载来源不明的 pickle。索引以不可变版本目录存储，manifest 校验文件哈希、模型、维度和 chunk 顺序。数据库保存对应内容版本；查询仅使用匹配的活跃版本。新版本构建完成后校验、受控切换并重启 API 载入；第一版维护窗口更新数据，不做在线无缝双写。

## 3. 一次性任务

复用 api 镜像定义 `tools` profile，可执行迁移、校验、导入、索引构建和评测。它们属于临时容器，不增加长期运行的服务。迁移使用应用专用迁移账户或受控初始化账户；日常 API 账户不持有 root 权限。

首次部署的预期步骤：

1. 构建镜像，准备 `.env`、模型凭证和原始资料；先验证配置，密钥不进入镜像。
2. 启动 mysql，等待真实 healthcheck 就绪。
3. 运行迁移；创建初始数据版本，校验与导入资料。
4. 构建版本化向量/BM25 索引，验证模型维度与数据映射后激活。
5. 启动 api 与 web；完成就绪检查和端到端演示用例。

实现后命令约定如下，`app.cli` 为待开发入口：

```bash
docker compose config --quiet
docker compose up -d mysql
docker compose --profile tools run --rm tools python -m app.cli migrate
docker compose --profile tools run --rm tools python -m app.cli validate-data
docker compose --profile tools run --rm tools python -m app.cli ingest
docker compose --profile tools run --rm tools python -m app.cli build-index
docker compose up -d api web
docker compose ps
docker compose logs --tail=100 api
```

`depends_on` 必须配合 healthcheck；“容器运行中”不代表数据库可用。API live 只判断进程，ready 检查数据库、迁移版本和索引就绪；外部模型故障以单独依赖状态记录，不让网络瞬时波动触发无限重启。无索引时提供明确 not_ready 响应，不能将空数据当成已完成检索。

## 4. 配置草案

| 配置项 | 定义/默认决策 |
| --- | --- |
| MYSQL_DATABASE / MYSQL_USER / MYSQL_PASSWORD | 应用库和应用账号；示例文件仅占位符 |
| MYSQL_ROOT_PASSWORD | 仅初始化/维护使用，不注入日常 API |
| DATABASE_URL | 指向 mysql 服务，连接字符集 utf8mb4 |
| LLM_BASE_URL / LLM_API_KEY / LLM_MODEL | 外部问答模型适配器 |
| EMBEDDING_BASE_URL / EMBEDDING_API_KEY / EMBEDDING_MODEL | 资料和查询共用模型 |
| EMBEDDING_DIM | 必须与实际输出及 manifest 一致 |
| DATA_ROOT / INDEX_VERSION | 持久化根目录和激活版本 |
| SESSION_SIGNING_SECRET | 后端访客会话凭证配置 |
| MAX_TOOL_CALLS / RUN_TIMEOUT_SECONDS | 起始 6 / 60，评测后调整 |
| ENABLE_GRAPH / ENABLE_MEMORY | 默认开启；评测可关闭做消融实验 |
| UVICORN_WORKERS | 首版固定 1 |

上游访问采用异步客户端/有界线程池，CPU 检索不可长期阻塞事件循环。进程内取消注册表、会话锁和事件缓冲依赖单实例；若以后多 worker/多副本，需引入共享任务协调及跨实例取消通知，届时再评估 Redis。

## 5. 流式代理与恢复

Nginx 的 SSE 路由关闭代理缓冲，使用足够的读取超时；API 定期发送心跳并在断连后清理任务。JSON 请求和 SSE 流都需凭证归属校验，事件不记录密钥。部分回答带 cancelled/interrupted 标记，不作为完成回答写入记忆。

API 重启时，将数据库 queued/running/cancelling 的遗留任务置 interrupted；会话、已完成消息和偏好保留。数据库连接具备有界重试；不能无限重试模型调用。模型断网演示可提供显式 mock 模式用于流程测试，界面标明模拟，不能算真实 RAG 质量结果。

数据库恢复后须恢复匹配的 rag-data 快照；缺失索引时根据资料重建，版本不匹配时不提供正常检索。提供数据库导出与导入、索引快照、配置字段清单和重建说明。日常停止保留数据卷；删除数据卷只用于明确的数据重置。

## 6. 资源与验收

初步以 2—4 vCPU、4—8 GB 内存的演示机器为容量假设，使用外部模型 API，不在容器中运行大模型。该配置不是性能保证；目标机器测试并发 1 和 3 个会话，记录 CPU、内存、TTFT、总时长和错误率。

部署验收包括：空环境首次启动、健康检查、SSE 经 Nginx 不积攒输出、取消、容器重启后记忆保留、恢复中断任务状态、重建索引、备份恢复、数据库端口未对外发布、应用凭证不进入浏览器包。

参考：[Compose 启动顺序与就绪检查](https://docs.docker.com/compose/how-tos/startup-order/)、[Nginx proxy_buffering](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_buffering)、[FastAPI 流式响应](https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse)。
