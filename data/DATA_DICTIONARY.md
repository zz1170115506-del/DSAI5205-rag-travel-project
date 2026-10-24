# 数据字典与文件格式

版本：设计 v1，2026-10-24。类型是拟用 MySQL 类型，尚未创建数据库。标记：必填=不可为空；可空=允许 NULL；PK=主键；FK=外键。JSON 内部结构由 Pydantic/导入器校验，不能仅依赖数据库 JSON 类型。

## 1. 通用规则

- 所有数据库表含 `created_at DATETIME(3)`、`updated_at DATETIME(3)`，必填、服务端生成、存 UTC。除另有说明外，状态默认 active，数值范围由应用和适用 CHECK 约束共同校验。
- 知识 ID 使用 `VARCHAR(64)` 稳定标识；运行数据 ID 使用服务端 UUID 的 `CHAR(36)`。ID 比较采用大小写敏感/二进制排序规则；名称字段保留 Unicode，别名另外保存规范化检索值。
- 所有表用 InnoDB、utf8mb4。字符串枚举使用 VARCHAR + 受控值校验，方便迁移；JSON 不存外部密钥。
- 所有知识表附 `dataset_version VARCHAR(64)` 必填，表示最后一次发布批次。首版维护窗口内更新，先停止检索、备份数据库与索引、导入、激活再开放；不支持同时查询多个历史知识版本。历史复现恢复完整快照，不能仅凭 version 标签恢复。
- 软删除/下线为 inactive，不级联删除仍被引用的知识；活跃索引重建后不再包含下线资料。实时票价/营业不在首版保证范围。
- CSV 模板中的 ID、名称等必填字段不能空；可空字段用空单元格。JSON 字段中的未知值用 null；不要填字符串 "NULL"。

## 2. 来源 `sources`

| 字段 | 类型 | 必填 | 定义 |
| --- | --- | --- | --- |
| source_id | VARCHAR(64) PK | 是 | 来源记录 ID，例如 src_0001 |
| title | VARCHAR(255) | 是 | 具体页面/文档标题 |
| url | VARCHAR(2048) | 否 | 具体来源页；离线资料可空但 local_path 必填 |
| local_path | VARCHAR(512) | 否 | 相对 data/raw 的文件路径；与 url 至少一项存在 |
| publisher | VARCHAR(255) | 是 | 发布机构/作者/团队编辑名称 |
| source_type | VARCHAR(24) | 是 | official/authorized/editorial/synthetic |
| language | VARCHAR(16) | 是 | zh-Hant/zh-Hans/en/mixed |
| license_note | TEXT | 是 | 授权、允许用途、署名或待核对情况；待核对不可直接发布资源 |
| retrieved_at | DATETIME(3) | 是 | 获取时间 |
| verified_at | DATETIME(3) | 否 | 人工核对时间；发布资料须完成核对 |
| content_hash | CHAR(64) | 否 | 原始内容 SHA-256，采集器生成；仅链接来源可空 |
| status | VARCHAR(16) | 是 | pending/verified/inactive |

## 3. 统一实体 `entities`

景点、地区、主题、站点和人群都使用统一实体 ID，关系两端可以有真实 FK，避免散落的字符串关系。

| 字段 | 类型 | 必填 | 定义 |
| --- | --- | --- | --- |
| entity_id | VARCHAR(64) PK | 是 | 稳定实体 ID |
| entity_type | VARCHAR(24) | 是 | attraction/district/theme/station/audience/activity |
| name_zh | VARCHAR(255) | 是 | 中文标准名称，保留来源用字 |
| name_en | VARCHAR(255) | 否 | 英文标准名称 |
| description | TEXT | 否 | 简短定义，用于消歧 |
| source_id | VARCHAR(64) FK sources | 是 | 名称/定义依据；团队主题词表使用 editorial 来源 |
| status | VARCHAR(16) | 是 | active/inactive |

为 entity_type 建索引；名称不全局唯一，不把同名实体自动合并。

### 实体别名 `entity_aliases`

| 字段 | 类型 | 必填 | 定义 |
| --- | --- | --- | --- |
| alias_id | CHAR(36) PK | 是 | 系统生成记录 ID |
| entity_id | VARCHAR(64) FK entities | 是 | 对应实体 |
| alias | VARCHAR(255) | 是 | 别名、旧名或另一语言写法 |
| language | VARCHAR(16) | 是 | zh-Hant/zh-Hans/en/mixed |
| normalized_alias | VARCHAR(255) | 是 | 导入生成，统一空白/拉丁大小写与检索繁简规范 |
| source_id | VARCHAR(64) FK sources | 是 | 别名依据 |

唯一键 `(entity_id, normalized_alias, language)`；normalized_alias 检索索引。不同实体允许共享别名，查询时消歧。

## 4. 景点详情 `attractions`

| 字段 | 类型 | 必填 | 定义 |
| --- | --- | --- | --- |
| entity_id | VARCHAR(64) PK/FK entities | 是 | entity_type 必须为 attraction |
| category | VARCHAR(32) | 是 | museum/park/heritage/viewpoint/market/theme_park/other |
| address_zh | VARCHAR(512) | 是 | 中文地址/可定位位置 |
| address_en | VARCHAR(512) | 否 | 英文地址 |
| latitude | DECIMAL(9,6) | 是 | WGS84 纬度，[-90,90]；另校验香港合理范围 |
| longitude | DECIMAL(10,6) | 是 | WGS84 经度，[-180,180] |
| summary | TEXT | 是 | 可展示简介，有具体来源 |
| story | TEXT | 否 | 特色或历史故事，有出处；无证据不填 |
| setting | VARCHAR(16) | 是 | indoor/outdoor/mixed/unknown |
| visit_minutes | SMALLINT UNSIGNED | 否 | 建议游玩分钟数，编辑估计需说明 |
| ticket_price_min_hkd | DECIMAL(10,2) | 否 | 参考最低票价；NULL=未知，不等于免费 |
| ticket_price_max_hkd | DECIMAL(10,2) | 否 | 参考最高票价，非负且不低于最低价 |
| ticket_note | TEXT | 否 | 成人/优惠/预约/适用日期等条件 |
| opening_hours | JSON | 否 | 下述开放时间结构；缺失不代表全天开放 |
| official_url | VARCHAR(2048) | 否 | 景点官方网站 |
| primary_source_id | VARCHAR(64) FK sources | 是 | 核心介绍依据 |
| field_evidence | JSON | 是 | 字段到来源及定位的映射，见下例 |
| verified_at | DATETIME(3) | 是 | 本条详情核对时间 |

地区/主题/适合人群经 relations 关联，不再重复维护自由文本标签。category、setting 建索引。经纬度用于小规模距离计算，不额外部署 GIS 服务。

`field_evidence` 格式：`{"summary":{"source_id":"src_0001","locator":"介绍第1段"},"latitude":{"source_id":"src_0002","locator":"位置"}}`。填入的可陈述字段（地址、坐标、简介、故事、室内外、时长、票价、开放时间）应有对应依据，来源必须存在；估计类数据引用 editorial 来源并在 locator 说明估计方法。

`opening_hours` 格式：`{"timezone":"Asia/Hong_Kong","weekly":{"mon":[["10:00","18:00"]]},"exceptions":[],"note":"示例格式，不是真实营业时间"}`。星期键 mon...sun；缺失键=未知，空数组=确认关闭；跨午夜拆段并注明。无法结构化时 weekly 可为 null，保留 note，不据此保证行程可行。

## 5. 实体关系 `relations`

| 字段 | 类型 | 必填 | 定义 |
| --- | --- | --- | --- |
| relation_id | VARCHAR(64) PK | 是 | 稳定关系 ID |
| subject_id | VARCHAR(64) FK entities | 是 | 起点实体 |
| predicate | VARCHAR(32) | 是 | LOCATED_IN/HAS_THEME/NEAR_STATION/SUITABLE_FOR/SUPPORTS_ACTIVITY |
| object_id | VARCHAR(64) FK entities | 是 | 终点实体 |
| source_id | VARCHAR(64) FK sources | 是 | 关系依据；计算关系引用说明算法的 editorial 来源 |
| evidence | TEXT | 是 | 原文定位、核验说明或计算方法 |
| distance_m | INT UNSIGNED | 否 | NEAR_STATION 的直线距离，米；不是步行路线 |
| verified_at | DATETIME(3) | 是 | 核对时间 |
| status | VARCHAR(16) | 是 | active/inactive |

唯一键 `(subject_id,predicate,object_id)`；索引 `(subject_id,predicate)`、`(object_id,predicate)`。首版每个关系保留一个经核对的主要来源，更多来源可通过后续证据表扩展。领域约束：起点通常 attraction；LOCATED_IN 终点 district，HAS_THEME 终点 theme，NEAR_STATION 终点 station，SUITABLE_FOR 终点 audience，SUPPORTS_ACTIVITY 终点 activity。拒绝自环和类型不匹配；跳数限制在检索层执行。

## 6. 景点图片 `images`

| 字段 | 类型 | 必填 | 定义 |
| --- | --- | --- | --- |
| image_id | VARCHAR(64) PK | 是 | 图片 ID |
| attraction_id | VARCHAR(64) FK attractions.entity_id | 是 | 所属景点 |
| asset_path | VARCHAR(512) | 否 | 经过授权的本地相对文件路径 |
| remote_url | VARCHAR(2048) | 否 | 可引用远端图片，不能假定支持永久外链 |
| caption | VARCHAR(512) | 是 | 图片说明/无障碍文本 |
| source_id | VARCHAR(64) FK sources | 是 | 原始来源页及条款 |
| author | VARCHAR(255) | 否 | 作者/机构 |
| license_note | TEXT | 是 | 本图片授权与署名要求 |
| width | INT UNSIGNED | 否 | 像素宽度 |
| height | INT UNSIGNED | 否 | 像素高度 |
| sort_order | SMALLINT UNSIGNED | 是 | 展示顺序，默认 0 |

asset_path/remote_url 至少一项；禁止包含越出资源根目录的路径。不存在图片时使用前端占位图。此表不保存图片 Embedding。

## 7. 原文 `documents` 与片段 `chunks`

### documents

| 字段 | 类型 | 必填 | 定义 |
| --- | --- | --- | --- |
| document_id | VARCHAR(64) PK | 是 | 稳定文档 ID |
| attraction_id | VARCHAR(64) FK attractions.entity_id | 否 | 主关联景点；跨景点资料可空 |
| source_id | VARCHAR(64) FK sources | 是 | 来源记录 |
| title | VARCHAR(255) | 是 | 文档标题 |
| language | VARCHAR(16) | 是 | 文本语言 |
| raw_path | VARCHAR(512) | 否 | 原文件相对路径 |
| clean_text | MEDIUMTEXT | 是 | 可使用的清洗正文 |
| content_hash | CHAR(64) | 是 | 清洗正文 SHA-256，导入生成 |
| status | VARCHAR(16) | 是 | active/inactive |

### chunks

| 字段 | 类型 | 必填 | 定义 |
| --- | --- | --- | --- |
| chunk_id | VARCHAR(64) PK | 是 | 由文档版本、切分版本与序号派生，正文变化不能沿用旧 ID |
| document_id | VARCHAR(64) FK documents | 是 | 原文 |
| attraction_id | VARCHAR(64) FK attractions.entity_id | 否 | 对应景点，优先继承原文 |
| chunk_index | INT UNSIGNED | 是 | 文档内顺序，从 0 开始 |
| text | TEXT | 是 | 检索原文片段 |
| char_start | INT UNSIGNED | 是 | 在 clean_text 中的 Unicode 字符起点，含 |
| char_end | INT UNSIGNED | 是 | 终点，不含；大于 char_start |
| locator | VARCHAR(255) | 是 | 段落/标题/页码定位；网页不伪造页码 |
| content_hash | CHAR(64) | 是 | 片段文本 SHA-256 |
| splitter_version | VARCHAR(64) | 是 | 切分参数/程序版本 |

片段正文应与偏移切片对应；unique(document_id,splitter_version,chunk_index)。source_id 经 document 获取，避免重复来源指向冲突。结构化景点简介也可生成有明确来源的文档后进入同一切分链。

## 8. 运行数据表（自动生成，不需要人工采集）

### users

| 字段 | 类型 | 必填 | 定义 |
| --- | --- | --- | --- |
| user_id | CHAR(36) PK | 是 | 服务端访客 ID |
| auth_token_hash | CHAR(64) UNIQUE | 是 | 随机访客凭证的哈希，原始凭证只通过安全 Cookie 传递 |
| display_name | VARCHAR(100) | 否 | 昵称，不要求实名 |
| memory_enabled | BOOLEAN | 是 | 默认 false，用户允许后启用 |
| status | VARCHAR(16) | 是 | active/disabled |

### sessions

| 字段 | 类型 | 必填 | 定义 |
| --- | --- | --- | --- |
| session_id | CHAR(36) PK | 是 | 会话 ID |
| user_id | CHAR(36) FK users | 是 | 会话归属 |
| title | VARCHAR(255) | 否 | 会话标题 |
| constraints | JSON | 是 | 当前地区、预算、时长等临时条件，默认 {} |
| checkpoint | JSON | 否 | 澄清节点需要的状态；不保存模型内部推理 |
| version | INT UNSIGNED | 是 | 每次新请求/纠正增加，用于屏蔽旧任务提交 |
| active_run_id | CHAR(36) FK runs | 否 | 当前有效任务，终结后清空 |
| status | VARCHAR(24) | 是 | active/awaiting_input/closed |

### messages

| 字段 | 类型 | 必填 | 定义 |
| --- | --- | --- | --- |
| message_id | CHAR(36) PK | 是 | 消息 ID |
| session_id | CHAR(36) FK sessions | 是 | 所属会话 |
| run_id | CHAR(36) FK runs | 否 | 关联任务，创建请求期间可空 |
| role | VARCHAR(16) | 是 | user/assistant |
| content | MEDIUMTEXT | 是 | 用户文本或助手最终/部分内容 |
| status | VARCHAR(24) | 是 | submitted/completed/partial/cancelled/failed |
| citations | JSON | 是 | 默认 []，元素含 chunk_id/source_id/locator |
| memory_processed_at | DATETIME(3) | 否 | 此消息记忆提取已处理时间，禁止历史反复提取 |

### runs

| 字段 | 类型 | 必填 | 定义 |
| --- | --- | --- | --- |
| run_id | CHAR(36) PK | 是 | 任务 ID |
| session_id | CHAR(36) FK sessions | 是 | 所属会话 |
| request_id | VARCHAR(64) | 是 | 客户端幂等键，unique(session_id,request_id) |
| input_message_id | CHAR(36) FK messages | 是 | 触发任务的用户消息 |
| session_version | INT UNSIGNED | 是 | 创建任务时的会话版本 |
| status | VARCHAR(24) | 是 | queued/running/cancelling/completed/cancelled/failed/interrupted |
| cancel_requested_at | DATETIME(3) | 否 | 取消请求时间 |
| started_at | DATETIME(3) | 否 | 开始时间 |
| finished_at | DATETIME(3) | 否 | 终态时间 |
| index_version | VARCHAR(64) | 否 | 本次固定的索引版本，开始检索前确定 |
| trace | JSON | 是 | 工具名、证据 ID、路由、耗时、错误，默认 [] |
| usage | JSON | 是 | 模型调用数、Token、费用币种与估算，默认 {} |
| error_code | VARCHAR(64) | 否 | 可观察错误码，不存密钥 |

sessions / messages / runs 存在相互引用，迁移先建表再补外键。创建任务事务先建用户消息、再建 run、再回填 message.run_id 和 session.active_run_id。所有更新从同一归属会话检查；提交答案时锁定 session 并核对 run/version/取消状态。

### user_preferences

| 字段 | 类型 | 必填 | 定义 |
| --- | --- | --- | --- |
| preference_id | CHAR(36) PK | 是 | 偏好 ID |
| user_id | CHAR(36) FK users | 是 | 归属用户 |
| preference_key | VARCHAR(64) | 是 | interests/avoidances/budget_hkd/walking_minutes/language 等受控键 |
| value | JSON | 否 | 类型随 key：兴趣字符串数组、预算数值或语言字符串；删除后置 NULL |
| source_message_id | CHAR(36) FK messages | 否 | 来源消息；用户直接编辑可空 |
| origin | VARCHAR(24) | 是 | explicit_message/user_edit |
| confirmed_at | DATETIME(3) | 否 | 用户明确授权记录的时间，active 必填 |
| status | VARCHAR(16) | 是 | active/deleted；删除保留 key tombstone 防止旧来源重建 |
| deleted_at | DATETIME(3) | 否 | 删除时间；deleted 必填 |

unique(user_id,preference_key)。来源消息必须属于同一用户。删除后 value/source_message_id 清空；来源消息按会话保留策略处理，但提取器只消费新消息，不能扫描历史重新恢复。用户再次明确授权可以写入新值。

## 9. 索引文件 manifest（JSON，生成物）

| 字段 | JSON 类型 | 必填 | 定义 |
| --- | --- | --- | --- |
| schema_version | string | 是 | manifest 格式版本 |
| index_version | string | 是 | 不可变索引版本 |
| dataset_version | string | 是 | 对应知识快照 |
| embedding_model | string | 是 | 模型及供应方标识 |
| embedding_revision | string/null | 否 | 可获得的固定模型版本；未知明确为空 |
| embedding_dim | integer | 是 | 向量维度，大于 0 |
| normalized | boolean | 是 | true，入库与查询均使用相同归一化 |
| dtype | string | 是 | float32 |
| metric | string | 是 | cosine |
| chunk_ids | array[string] | 是 | 与向量矩阵行一一对应的有序 ID |
| chunk_hashes | array[string] | 是 | 同顺序片段内容哈希 |
| tokenizer_version | string | 是 | 分词、词典、繁简规范化版本 |
| splitter_version | string | 是 | 切分版本 |
| files | object | 是 | 文件名到 SHA-256 的映射，含向量与 BM25 数据 |
| built_at | string | 是 | ISO 8601 UTC 时间 |

BM25 保存 tokenizer 后的 token 序列和参数供可信代码重建，避免依赖未校验的二进制对象反序列化。加载时检查 IDs、哈希、维度、文件数和行数一致。

## 10. 评测数据 JSONL

每行一条样本，表内字段全部定义；可选字段仍建议显式填空数组/空对象。虚构格式例子见 `templates/evaluation.schema-example.json`，该例子不能用于真实质量评分。

| 字段 | JSON 类型 | 必填 | 定义 |
| --- | --- | --- | --- |
| case_id | string | 是 | 唯一样本 ID |
| group_id | string | 是 | 同题改写/同一会话归组，整组分配 split |
| category | string | 是 | fact/alias/filter/graph/planning/multiturn/unanswerable/memory |
| split | string | 是 | dev/test |
| dataset_version | string | 是 | 样本对应知识快照 |
| question | string | 是 | 本轮用户输入 |
| history | array[object] | 是 | 每项 role/content，默认 [] |
| profile | object | 是 | 虚构用户偏好，默认 {}；不使用真实用户记录 |
| relevant_entity_ids | array[string] | 是 | 标注相关实体，默认 [] |
| relevant_chunk_ids | array[string] | 是 | 相关证据 chunk，默认 [] |
| expected_facts | array[string] | 是 | 应包含的事实要点，默认 [] |
| constraints | object | 是 | 必须满足的地区/预算/排除项等 |
| answerable | boolean | 是 | 现有快照是否足以回答 |
| expected_behavior | string | 是 | answer/clarify/abstain/apply_current_constraint 等受控验收标签 |
| rubric | object | 是 | 判分项与权重，需固定版本 |
| synthetic | boolean | 是 | 是否虚构测试夹具；真实事实评测为 false |
| verified_by | string | 是 | 核对者代号，不要求实名 |
| verified_at | string | 是 | 核对时间，ISO 8601 |

多轮可逐轮记录相同 group_id。取消/并发场景用测试代码控制时序，不靠 JSONL 文本模拟时间。无答案样本不计算无定义的 Recall@K，单独报告正确拒答/澄清率。

## 11. 实验结果 JSONL 与配置 JSON

结果每条至少包含 experiment_id、case_id、answer、retrieved_chunk_ids、citations、relation_paths、scores、latency_ms（ttft/total/retrieval）、usage、error、run_status。scores 为具名数值/布尔项；error 可空；同时保存评分器版本及人工复核标记。检索为空时保留空数组，不能省略失败样本。

实验配置包含 git_commit（若 dirty 则另记差异哈希）、dataset_version、index_version、llm_model/revision、embedding_model/revision、prompt_version、tokenizer_version、检索 Top-K/融合参数、工具预算、各模块开关、评测样本哈希、运行环境、开始结束时间及随机参数。供应方不支持固定版本或种子时如实记录。

## 12. 人工模板与自动字段对应

`templates/*.csv` 是采集交换格式，不等同于数据库 dump。sources 模板已包含采集/核对时间，source hash 自动生成；entities 模板对应实体核心字段；attractions 的 field_evidence/opening_hours 为 JSON 列；别名 normalized_alias 和 alias_id 自动生成；relations/images 的稳定 ID 人工分配；documents 的 clean_text/content_hash 从 raw_path 对应正文生成。模板均省略 created_at/updated_at/dataset_version，由导入批次注入。运行表、片段表、索引和实验结果不由人工 CSV 填写。

## 实现对照补充

ORM 与初始迁移见 `backend/app/models.py` 和 `backend/migrations/versions/`。created_at/updated_at 在 MySQL 中实现为 DATETIME(6)，其余时间字段采用通用 DATETIME；所有时间按 UTC 保存。sessions.active_run_id 和 messages.run_id 的循环关联使用应用事务校验，其他字典列出的 FK 由数据库约束维护。manifest 另含 model_mode（mock/remote）、corpus_hash，用来拒绝模拟/真实模型或数据库内容错配。尚不提供自动 PDF/OCR 读取。
