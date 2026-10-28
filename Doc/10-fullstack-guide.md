# 港游 · Hong Kong RAG Travel Lab

DSAI5205 小组 Demo，包含结构化知识库、向量/BM25/实体/关系混合检索、受控 Agent 多轮问答、文字停止与纠正、长期偏好记忆、离线评测六个模块。

**随附数据为 6 个虚构景点，默认是模拟模型。** 用来验证工程流程，不可作为真实旅行建议。填入模型配置并导入核验资料后，可切换到真实模型运行。

## 快速开始：Docker

1. 打开 Docker Desktop，确认 `docker info` 可以连接引擎。
2. 编辑根目录 `.env`。若尚无此文件，先 `cp .env.example .env`，并替换两项数据库密码。模型未配置时可保留 `MODEL_MODE=mock`。
3. 在仓库根目录执行：

```bash
sh scripts/start-demo.sh
```

浏览器打开 [http://localhost:8080](http://localhost:8080)。默认三个常驻容器：web（Nginx+静态前端）、api（FastAPI）、mysql。初始化和评测通过 tools 临时容器运行。

脚本会重新导入/激活虚构演示数据；已有真实资料的环境不要再运行此脚本，使用运行指南中的真实数据更新步骤。

## 配置与开发说明

- [启动、ENV 填写、真实模型与数据导入](04-run-and-env.md)
- [已执行验证与尚待验证项](05-validation.md)
- [架构与原始设计](README.md)
- [数据清单](../data/DATA_INVENTORY.md)、[字段字典](../data/DATA_DICTIONARY.md)、[空采集模板](../data/templates/)
- [API](09-fullstack-api.md)、[Git 协作](../docs/development.md)

前端使用原生 ES Modules + CSS，无 Node 构建依赖；后端使用 Python 3.12。MySQL 保存实体关系，向量与 BM25 在后端运行，未引入独立向量库/图数据库。本实现从初始骨架独立开发；合并后的仓库也保留根目录 static/、travel/ 应用，二者使用各自的接口和启动入口。

## 本机 Python 快速预览

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.lock.txt
cd backend
.venv/bin/python -m app.cli bootstrap --demo
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

根目录 `.env` 中 `DATABASE_URL=sqlite:///./travel.db` 仅供本机预览；Docker 运行时显式使用 MySQL。浏览器地址相同。本机 SQLite 检查不能替代真实 MySQL 集成测试。

## 测试

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

若测试真实 MySQL，设置 `TEST_DATABASE_URL` 指向专门的 `*_test` 数据库；测试会清空该测试数据库的本项目表，禁止使用业务库。详见验证说明。

本机实际部署状态见 [Docker 部署与真实模型验证记录](06-deployment-record.md)。
