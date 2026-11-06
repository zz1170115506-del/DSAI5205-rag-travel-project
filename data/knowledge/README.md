# 文档段落知识库

这是可随后端部署的数据产物，已接入条件工作流的旅游问答。BM25 在读取段落后构建；向量索引用 `python3 scripts/knowledge/build_index.py` 生成，缺失或过期时明确回退到 BM25。

## 重新生成

在应用仓库根目录运行：

```sh
python3 scripts/knowledge/build_chunks.py
.venv/bin/python -m pytest tests/test_chunking.py -q
```

仅使用 Python 标准库，无需联网或调用模型。默认读取 `知识库/documents.jsonl`，导出到本目录。也可指定任意输入和输出位置：

```sh
python3 scripts/knowledge/build_chunks.py --input documents.jsonl --output export --size 800 --overlap 100
```

同一输入及参数重复运行得到相同产物；运行会覆盖输出目录中的 `chunks.jsonl` 和 `processing_report.json`。新增文档须先完成正文提取和质量审核，再放入输入清单。文档 ID 缺失或重复时停止生成；未批准、无正文或无来源链接的文档在报告中记录排除原因。

## 文件与读取约定

- `chunks.jsonl`：UTF-8，每行一个段落对象。复制此文件到其他目录或服务器即可独立读取，不依赖原始 PDF、TXT 或开发电脑路径。
- `processing_report.json`：参数、数据版本、逐文档数量、排除原因、待审核段落、短段落及完全重复正文的统计。

未来检索程序必须仅索引 `include_in_retrieval == true` 的段落。当前的 true 仅表示通过输入审核及地点归属检查，不表示内容适用于当前日期，也不等于完成逐段人工审核。

| 字段 | 含义 |
|---|---|
| `chunk_id` / `document_id` / `chunk_index` | 段落唯一 ID、文档 ID、文档内从 0 起的序号 |
| `text` / `text_sha256` | 原文片段及其内容摘要 |
| `char_start` / `char_end` | 输入正文中的字符位置，左闭右开；定位满足 `text == 原正文[start:end]` |
| `place_id` / `place_name` | 确认的地点；多地点资料未审核时为空 |
| `candidate_place_ids` | 文档已有的候选地点列表，不保证穷尽正文全部地点 |
| `source_url` / `title` / `publisher` | 原来源链接、文档标题、发布机构 |
| `section_title` | 由显式 Markdown 或编号标题规则识别的章节；未识别留空 |
| `page_number` | PDF 从 1 开始的物理页码，沿用原提取标记；不是印刷页码。网页无页码 |
| `source_year` / `temporal_note` | 资料年份及适用时间说明，回答时必须保留其限制 |
| `quality_note` / `extraction_method` | 原文质量及提取方式 |
| `review_required` / `review_reasons` | 是否待审核及原因 |
| `include_in_retrieval` | 是否允许后续索引 |

其余来源说明（如采集时间、译文提示、使用说明）同样保留。产物只复制约定的来源字段，不复制本机原件路径。

## 切分与质量边界

按物理页和显式章节分开，优先在空行、换行及句子边界切分。默认最多 800 字符，重叠最多 100 字符；只有找到合适边界才重叠。无可用边界的长内容才按长度切分。正文保持原文，不自动润色或改写。

多地点文档全部暂缓索引，需要人工明确每段归属；不要只修改导出文件，应在后续补充可重复使用的审核规则后重新生成。目录页、封面、短片段和表格可能仍存在；报告列出短段落统计，未擅自删除资料。PDF 排版、OCR、普通文本标题识别，以及译文或近似重复证据，仍需后续审核。历史资料虽然可被索引，也不能直接支持当前开放时间或设施安排。

首批生成：20 份文档、1,178 段，其中 1,170 段允许后续索引、8 段待审核；1,116 段保留 PDF 页码，42 段短于 80 字符，无完全相同正文的重复组。已抽查网页、历史 PDF 和多地点资料；尚未逐段人工审核。
