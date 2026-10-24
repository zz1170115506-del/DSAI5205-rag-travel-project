# 前端入口

当前可运行前端位于仓库根目录 [`static/`](../static/)，采用原生 HTML / CSS / JavaScript，由 FastAPI 同源提供，无需 npm 构建。

运行根目录 `python3 start.py`，打开本机页面即可。`static/app.js` 组织问答、行程与历史交互；`itinerary-map.js` 提供行程总览；`walking-map.mjs` 展示高德步行路线。

此目录保留初始仓库结构，暂未迁入第二套前端应用。接口见 [`docs/api.md`](../docs/api.md)，模型和高德密钥仅在后端配置。
