# 当前 HTTP 接口

本地地址默认 `http://127.0.0.1:8765`，网页与 API 同源。应用仅监听回环地址，校验 Host 与写请求 Origin；当前没有多用户账户系统。普通 JSON 请求一次返回，不是流式响应。

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/status` | 本地功能、模型及高德配置状态，不返回密钥 |
| `POST /api/chat` | 问答、规划、连续修改与本机历史保存 |
| `GET /api/history` | 最近对话列表 |
| `POST /api/history/read` | 读取指定历史 |
| `POST /api/history/update` | 更新 favorite / pinned |
| `POST /api/history/rename` | 手动重命名 |
| `POST /api/history/delete` | 删除指定历史，网页先确认 |
| `GET /api/places` | 地点目录与本地检索 |
| `POST /api/places/search` | 本地搜索，未命中时可补充高德候选 |
| `POST /api/places/resolve` | 名称精确匹配，未命中时查询地图 |
| `POST /api/transit/route` | 港铁起点／景点到景点的本地交通参考 |
| `POST /api/walking-map` | 邻近步行两地点的高德路线图；支持 POI 确认 |
| `POST /api/amap/route` | 2–6 个规范地点的高德步行参考 |
| `POST /api/ask`、`/api/plan`、`/api/agent` | 历史兼容入口 |

## 连续对话

```json
{
  "question": "请按已选偏好安排两天行程",
  "use_model": false,
  "trip": {
    "days": 2,
    "must_visit": ["escalator", "pmq", "lan-fong-yuen", "zoological-gardens"],
    "only_selected": true
  }
}
```

首轮返回 `conversation_id`，继续同一段对话时带回该字段。结果还包含 `trip`、`answer`、`plan`、`sources`、`trace`、`stop_reason` 与 `metrics` 等。`answer.mode` 区分本地与模型，`stop_reason` 区分完成、工具冲突、调用上限和请求失败；不得只看 HTTP 200 就断言规划成功。

按日期请求可在 trip 中传 `start_date`、`end_date`；包含首尾当天。地点 ID 来自 `data/places.json`，不能提交任意坐标或未知 ID 替代。

模型读取有界历史、规范选择、偏好与最新行程。`use_model=true` 需要本机配置模型服务，否则返回明确错误；未开启时不调用模型。

相对天数修改以本轮开始时的旅行总天数为基准：“再多加一天”增加一天，“少玩一天”减少一天，“改成一天”设置为一天，同时更新已有结束日期。模型的 `update_trip` 工具新增 `day_change: {"operation":"increase","amount":1}`，也支持 `decrease` 和 `set`；不能与 `changes.days/start_date/end_date` 混用。原天数未知或调整后超出 1–366 天时保留原条件并要求澄清；本地模式的停止原因是 `clarify_days`。

### 地图补充检索

本地搜索未命中、明确指定未收录的地点名称，或商场／博物馆推荐缺少足够的同类候选时，问答可按需查询高德香港 POI。语义相似但类别不符的结果不能满足推荐需求。“九龙有哪些商场”整理为“香港 九龙 商场”；地图补充本身不修改行程条件。类别推荐默认目标三个、最多五个候选，不保证全量覆盖。需配置 `AMAP_API_KEY` 和 `AMAP_ENABLED=true`；模型模式还会将实际返回的有限地图字段发送给所配置的模型生成回答。`external_lookup` 保留候选与来源、查询时间和 `coverage`；`trace` 包含 `map_search`，发起地图资料生成时还包含 `map_rag_answer`。

地图生成成功时，`answer.mode=model`、`answer.retrieval_source=amap`、`metrics.map_rag_used=true`；正文 `[map-1]` 等编号对应 `external_lookup.results[].citation_id`，前端链接到服务端构建的高德地点页。地图查询使用供应商的关键词搜索，不宣称使用了 Embedding。`sources` 仍只用于本地规范地点，外部 POI 不会成为自动行程的地点 ID。详见 [地图补充检索说明](地图补充检索.md)。

类别检索为空时 Agent 以 `map_needed` 提前交给地图层，避免重复模型／本地工具请求；纯检索的 `repeat/limit` 也可回退。补充后的 `stop_reason` 表示最终结果，原停止原因见 `metrics.agent_stop_reason`。工具冲突、天数澄清和总超时不通过此回退绕过。

## 步行小地图

```json
{"origin_id":"zoological-gardens","destination_id":"lan-fong-yuen"}
```

可选字段 `origin_poi_id`、`destination_poi_id` 必须来自本次供应商候选，服务端会重查核验。响应模式包括 `live`、`ambiguous_location`、`invalid_selection`、`disabled`、`not_configured`、`unavailable`。候选必须确认后才算路，餐饮分店不自动猜选。

成功结果有高德 `map_image`（PNG data URL）、距离时长、文字步骤及 `navigation_url`；当前网页只展示路线图、距离时长与导航入口，不展开逐步转弯列表。图片服务不可用时不伪造底图。密钥只在服务端使用，不返回供应商带 Key 的请求 URL。

## 错误与资料

- 参数或地点条件无效：422；错误 JSON 使用 `detail`。
- 无本地资料或外部查询失败：使用明确的模式与说明，不冒充已检索到资料。
- 工具或模型中断：保留明确停止原因；失败不宣称本轮修改完成。
- 资料引用采用规范地点 ID，并可从 `sources` 读取官方链接。引用编号通过校验不代表模型事实必然正确。

详细参数与约束以 `travel/chat.py`、`travel/agent.py`、`app.py` 的 Pydantic 模型为准。当前接口没有生产鉴权、订票或实时交通承诺。

## Docker 六模块接口

`frontend/` 与 `backend/` 使用独立的 `/api/v1/` 协议，见[六模块 API](../Doc/09-fullstack-api.md)。本文接口只适用于根目录 `app.py` 应用。
