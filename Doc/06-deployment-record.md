# Docker 实际部署记录

日期：2026-10-24（Asia/Shanghai）。本记录更新先前尚未执行的容器/真实模型验证状态。

## 当前访问地址

- 页面：http://localhost:8080 或 http://127.0.0.1:8080
- 就绪检查：http://localhost:8080/api/v1/health/ready
- API 文档：后端 `/docs` 未通过当前 Nginx `/api/` 路由对外代理；接口说明见 Doc/09-fullstack-api.md。

三个常驻容器：`web`（Nginx）、`api`（FastAPI）、`mysql`（MySQL 8.4）。MySQL 和 API 已通过容器健康检查，前端页面与同源接口已通过实际访问。容器有 unless-stopped 重启策略；退出/重启 Docker Desktop 后需要先恢复引擎。

## Docker 启动故障与修复

Docker 后端日志明确报告：启动 Apple Virtualization Framework 时安装 Rosetta 失败，导致 Engine 未运行，但 Desktop 进程仍在，CLI 因此误导性地显示“already running”。

处理：备份设置，结束卡住的 Docker 进程，将 `UseVirtualizationFrameworkRosetta` 设为 false 后启动。项目镜像使用当前机器原生 aarch64 架构。修复后 Engine 实际响应版本29.7.2。

设置备份保存在本机 `/private/tmp/rag-docker-settings-before-repair.json`。未删除原有容器、镜像或数据卷，未执行恢复出厂设置。

参考：[Docker Desktop 的 Rosetta 设置](https://docs.docker.com/desktop/settings-and-maintenance/settings/)。

## 镜像构建网络

首次构建时 Docker Hub auth.docker.io 连接超时；本机系统代理为 127.0.0.1:10910。构建时临时设置命令环境代理后，官方 Python/Nginx 镜像和依赖安装成功。没有更改全局网络配置。

如果本机再次遇到相同构建认证超时，可在确认10910代理仍运行后执行：

```bash
HTTP_PROXY=http://127.0.0.1:10910 HTTPS_PROXY=http://127.0.0.1:10910 NO_PROXY=localhost,127.0.0.1 docker compose build api web
```

## 真实模型配置

- 已用实际接口验证聊天和 Embedding 请求成功，均返回HTTP200。
- `.env` 运行模式为 remote；Embedding 实测输出1024维，已修正原256维设置并重新建索引。
- 后端就绪接口返回 model_mode=remote；浏览器显示“真实模型”。
- 密钥未写入报告或聊天；修改前配置备份为被Git忽略的 `.env.before-deployment`。

## 实际验证结果

| 检查 | 结果 |
| --- | --- |
| MySQL 初始化、Alembic 迁移、资料导入 | 成功 |
| 使用真实 Embedding 构建并加载索引 | 成功，1024维 |
| 三容器部署、Nginx页面和API入口 | 成功 |
| 经Nginx调用真实模型流式问答 | 完成，142个文本事件，1个证据引用 |
| 回答正确标明虚构资料 | 通过 |
| 偏好保存、跨会话读取、删除 | 通过 |
| 取消任务 | 通过，终态cancelled |
| 真实MySQL回归测试 | 31 passed，2项依赖弃用提示，5.73秒 |
| API容器重启后的会话/偏好/索引恢复 | 实际检查通过，见随附检查摘要 |

MySQL回归使用独立 `travel_rag_deploy_test` 库，未清空业务库；测试模型为mock，不把协议回归等同于真实模型质量。另有通过真实供应商接口的部署检查，摘要见 `validation/deployment-real-check.json`。

## 日常操作

在项目根目录执行：

```bash
docker compose ps
docker compose logs --tail=100 api
docker compose stop web api
docker compose up -d --wait api web
```

模型或环境变量调整后，使用 `docker compose up -d --force-recreate api web`。Embedding模型/维度变化还需先重建索引。已有真实资料后不要再次执行 `bootstrap --demo`，以免重新激活演示数据。

## 数据边界

当前使用真实模型，但知识库仍是6个明确标记为虚构的演示景点。本次部署并不包含真实香港景点采集；真实出行前需按 data/ 中的字段与来源规范导入真实资料。
