# 香港旅游 RAG Demo：设计文档

日期：2026-10-24。六模块 Demo 已实现；下方保留最初设计与实现记录，运行以实际指南为准。

本次范围包含全部六个模块：结构化知识库、混合与关系检索、Agentic RAG、可打断文字交互、长期记忆、评测迭代。分阶段开发是交付顺序，六项均属于最终范围。

| 文档 | 内容 |
| --- | --- |
| [架构设计](01-architecture.md) | 技术选型、模块协作、轻量关系检索、接口草案 |
| [Docker 部署设计](02-docker-deployment.md) | 三个常驻容器、网络、卷、配置、启动和恢复 |
| [开发与测试计划](03-development-and-tests.md) | 阶段任务、测试用例、指标、验收和交付物 |
| [数据清单](../data/DATA_INVENTORY.md) | 需要准备哪些资料、采集优先级、模板和来源台账 |
| [数据字典](../data/DATA_DICTIONARY.md) | 数据表、字段类型、含义、必填、关系和文件格式 |

现有 `docs/` 保留原 main 应用的接口和协作说明。`Doc/` 保存六模块设计、实现和验证记录；其实际 API 见 [六模块接口](09-fullstack-api.md)，早期设计草案仅供对照。

基线：本地仓库在 `feat/fullstack` 分支；检查时只有目录骨架，尚无前端依赖清单和后端应用入口。前端技术栈在源码接入后沿用；若没有可复用源码，默认考虑 React + Vite + TypeScript。现有未跟踪的 `Test.md` 属于原有文件，不作为设计生成物。

## 实现入口

六模块 Demo 已实现，代码、Docker 配置和环境变量均已加入；原始设计仍保留供对照。

- [实际启动与 ENV 填写](04-run-and-env.md)
- [实现范围与验证记录](05-validation.md)
- [项目运行入口](../README.md)

Docker 引擎与真实模型验证状态以验证记录为准；随附数据为明确标记的虚构夹具。

- [Docker 实际部署与真实模型验证记录](06-deployment-record.md)

- [前端按钮、问答反馈修复与验证](07-frontend-interaction-fix.md)

- [查询计划格式错误与受控回退修复](08-planner-format-recovery.md)

合并更新：原 main 本机应用保留 `docs/api.md`，Docker 六模块协议见 [API](09-fullstack-api.md)，两个入口见[运行说明](10-fullstack-guide.md)。
