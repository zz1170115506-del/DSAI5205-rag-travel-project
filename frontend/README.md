# 港游前端

原生 HTML、CSS、JavaScript ES Modules，无 npm 安装或编译步骤。Docker 使用 Nginx 提供静态资源，并将同源 `/api/` 转发到后端；本机 Python 预览由 FastAPI 提供相同静态文件。

功能：景点卡片、室内外筛选、混合检索、桌面景点坐标与按需外部地图、带引用/关系路径的 SSE 聊天、历史会话、停止/纠正、偏好启用/编辑/删除。

外部 OpenStreetMap 地图与字体需联网；无网络时系统字体、景点卡片和文字功能仍可用。小屏将地图与详情放到景点列表下方，保留筛选与聊天；当前展示图片缺失时使用明确的图形占位，不伪造景点照片。

前端不接收模型或数据库密钥；所有环境配置放根目录 `.env`。见 [运行指南](../Doc/04-run-and-env.md)。

## 交互修复

示例和景点提问现在一键发送；生成过程展示状态与等待反馈，引用在本页查看证据。前端回归测试见 `tests/ui-utils.test.mjs`，有 Node.js 时执行 `node --test frontend/tests/ui-utils.test.mjs`。具体验证见 [交互修复记录](../Doc/07-frontend-interaction-fix.md)。
