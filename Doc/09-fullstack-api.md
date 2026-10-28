# 已实现 API

前缀 `/api/v1`，启动后 `/docs` 提供 OpenAPI。模型密钥只在后端读取。

## 身份与请求

先 POST `/auth/guest`，请求体 `{}`。响应设置 HttpOnly、SameSite=Strict 访客 Cookie。同一浏览器跨会话复用；没有跨设备账号系统。会话、任务和偏好按服务端凭证归属校验，其他用户资源统一404。

修改请求使用 `Content-Type: application/json`；浏览器 Origin 必须在根目录 ENV 的 ALLOWED_ORIGINS 中。错误体为 `{code,message}`；字段校验还含 fields。错误响应不回显密钥或原始输入。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | /auth/guest | 创建/复用访客凭证 |
| GET | /health/live、/health/ready | 存活、数据库及索引就绪 |
| GET | /attractions | district/theme/setting/limit/offset 筛选 |
| GET | /attractions/{id} | 详情、图片、实体关系与字段来源 |
| GET | /images/{id} | 本地授权 PNG/JPEG/WebP 资源 |
| POST | /search | 混合检索，需访客身份 |
| GET/POST | /sessions | 列出本人最近50会话/创建 |
| GET | /sessions/{id} | 消息、约束、状态、active_run_id |
| POST | /sessions/{id}/runs | 创建任务，重复 request_id 返回同任务 |
| GET | /runs/{id} | 状态、最终/已保存部分答案、引用、trace、usage |
| GET | /runs/{id}/events | SSE 事件，需本人凭证 |
| POST | /runs/{id}/cancel | 幂等取消，终态不再改写 |
| GET/PATCH | /me/preferences | 查看/启用/编辑本人偏好 |
| DELETE | /me/preferences/{key} | 删除并清空偏好值，旧消息不重提取 |

## 检索

```json
{"query":"和演示历史馆同主题的景点","source_entity_id":"attr_history","relation":"HAS_THEME","channels":["vector","bm25","entity","graph"],"top_k":5}
```

可选字段 district、theme 为实体ID或标准名称；setting 为 indoor/outdoor/mixed；max_price 使用 HKD，按已知参考最高票价过滤；max_minutes 为单景点游玩时长上限。latitude/longitude/radius_m 用于直线距离筛选，需要同时给出经纬度。top_k 为1—20。结果带 chunk_id、attraction_id、text、source_id/source_url、locator、verified_at、score、channels、relation_paths。得分是排名融合值，不是答案置信度。

## 流式问答

```json
{"message":"安排演示尖沙咀区的室内行程，预算50港币","request_id":"客户端唯一请求ID"}
```

创建返回 run_id，随后 GET `/runs/{run_id}/events`。POST 创建时缓冲已启动，订阅前不会丢失短时事件。事件是 `data: JSON\n\n`，含 type、run_id、seq。type=status/token/citation/done/error/cancelled；token 含 text，citation 含 number/citation，done 含 status/usage。

客户端只接收当前 run_id。补充新消息自动取消旧任务并增加会话版本；停止接口体用 `{}`。SSE 断线会取消该任务；首版不支持 Last-Event-ID 自动续流。通过任务状态或会话接口重新读取已持久化结果。

状态 queued/running/cancelling/completed/cancelled/failed/interrupted；首版取消直接事务性写入 cancelled，不要求客户端观测到 cancelling。澄清等待体现在 session.status=awaiting_input，继续输入时恢复 checkpoint；任意生成中暂停则取消本次生成，下一轮创建新任务。

## 记忆

```json
{"enabled":true,"values":{"interests":["历史文化"],"avoidances":["户外"],"budget_hkd":200,"walking_minutes":30,"language":"zh-Hans"}}
```

启用后，聊天中的“记住我喜欢……”或“记住我的预算……”才触发规则式提取。未明确授权的推测不保存。当前条件优先；偏好不覆盖硬过滤。PATCH/DELETE 会取消本人当前任务，防止旧任务用旧记忆继续提交。

## 边界

无检索证据时生成器被要求说明不足；语义忠实性仍需人工评测。无实时交通/营业数据，不承诺路线实际可行；行程工具只限制已知游玩时长和参考门票合计。模拟模式是哈希向量与资料拼接，前端明确标记。
