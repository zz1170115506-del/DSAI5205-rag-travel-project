# 本地 Embedding ＋云端模型接入

## 两种模型各做什么

- Embedding 模型将问题和地点资料转成向量，用于语义检索。
- 云端生成模型读取问题、检索资料和有限会话上下文，组织回答或选择工具。

当前采用本地 `BAAI/bge-small-zh-v1.5`，经 FastEmbed / ONNX 在 CPU 上生成 512 维向量。回答继续使用现有 DeepSeek 兼容接口。Embedding 无需 API Key；云端回答需要自己的 Key。

## 本地准备

在仓库根目录、现有 Python 虚拟环境中执行：

```sh
.venv/bin/python -m pip install -r requirements-embedding.txt
.venv/bin/python scripts/build_embeddings.py --download
```

Windows 将 `.venv/bin/python` 替换为 `.venv\Scripts\python.exe`。

`--download` 明确允许首次下载公开模型。之后可以去掉该参数离线重建；正常网页查询使用 `local_files_only=True`，不会自动联网下载权重。首次下载仍需要可访问模型仓库的网络。

根目录 `.env` 的配置：

```dotenv
MODEL_API_KEY=
MODEL_BASE_URL=https://integrate.api.nvidia.com/v1
MODEL_NAME=deepseek-ai/deepseek-v4.1-flash
RETRIEVAL_MODE=hybrid
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_MIN_SCORE=0.5
```

`MODEL_API_KEY` 先留空时，也可验证本地向量检索。之后在本地文件填入 Key、保存并重启应用，再勾选网页“使用大模型”。无需将 Key 发到聊天或提交仓库。

当前示例使用 NVIDIA 官方开发端点，Key 须从该平台获取；免费试用可用性和限额以平台为准，详见 [NVIDIA 接入说明](NVIDIA免费模型接入.md)。如选择 DeepSeek 官方付费服务，则同时改用其地址 `https://api.deepseek.com/v1`、模型名 `deepseek-flash` 及对应平台的 Key。

## 数据与检索流程

1. 读取并校验 `data/places.json` 的地点记录。
2. 将名称、别名、地区、标签、简介和提示组合成文档；一条地点记录对应一个知识单元。
3. 用同一个 Embedding 模型编码文档和问题。默认中文 BGE 的查询加上模型作者推荐的检索指令，文档不加指令。
4. 对归一化向量执行精确余弦检索；同时保留 BM25 关键词检索。
5. 过滤地区、室内和地点类型，用 RRF 融合两路排名并保留名称优先。
6. 沿用既有 MCP 工具和模型上下文，将真实检索资料提供给生成模型，返回答案与来源。

本次接入针对已有的结构化地点记录，没有新增 PDF 自动读取或长文切分管线。当前 33 条资料使用本地精确搜索；未部署独立向量数据库或神经重排模型。

## 如何确认确实用了 Embedding

```sh
.venv/bin/python scripts/rag_demo.py --query "想看看有历史感的建筑和艺术展览"
```

检查输出：

- `retrieval.mode` 为 `hybrid`，`embedding_used` 为 `true`：本轮执行了向量检索。
- `semantic_score`：余弦相似度；`lexical_rank`、`semantic_rank` 可在检索接口的完整地点记录中查看。
- `embedding_used` 为 `false` 且有 `fallback_reason`：本轮使用 BM25 回退，不应报告为成功的向量检索。

`EMBEDDING_MIN_SCORE` 是可调的相似度过滤阈值，不是正确率或相关性的概率；尚未经过独立数据集校准。

真实云端问答需先填写 Key，再主动执行：

```sh
.venv/bin/python scripts/rag_demo.py --query "大馆有什么文化特色？" --use-model
```

该命令会将问题和检索资料发送给配置的供应商，产生实际用量。只有 `answer.mode` 为 `model` 才表示采用了通过当前引用校验的模型回答；引用格式正确仍不保证事实完全准确。

## 缓存、更新与回退

- `work/models/`：模型缓存。
- `data/indexes/places-embeddings.json`：向量索引，保存模型名、文档指纹、查询指令、维度和地点 ID。
- 修改资料、模型名或同名模型权重后，重新运行构建命令；数据或模型名不匹配时拒绝使用旧索引。
- 缺少依赖、缓存、索引损坏或推理失败时，保留 BM25 服务，并记录公开的原因码。
- `RETRIEVAL_MODE=bm25` 可关闭向量检索。
- 向量、模型和真实 `.env` 均不上传 GitHub。组员从相同源码与资料在各自电脑构建。

普通回归固定运行 BM25 与模拟向量测试，不下载模型，也不调用云端。真实模型下载和本机向量检索需单独验证，不能把模拟测试计为模型质量评测；原有冻结保留集保持不变。

## 官方参考

- [FastEmbed 支持的模型](https://qdrant.tech/documentation/embeddings/fastembed/)
- [BGE 中文模型与查询指令](https://huggingface.co/BAAI/bge-small-zh-v1.5)
- [DeepSeek API 配置](https://api-docs.deepseek.com/)
