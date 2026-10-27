# NVIDIA 官方 DeepSeek Flash 开发端点

核对日期：2026-10-26。NVIDIA 的 DeepSeek-V4.1-Flash 页面提供免费原型开发端点。它需要个人 NVIDIA API Key，免费试用的范围、额度、限流和可用性由平台决定，不代表永久或无限调用。

验证状态：本地 Embedding 与检索已验证可用；2026-10-26 的 NVIDIA API 请求未完成生成，网页 Playground 也持续等待，尚未验证云端回答成功。目前保留 NVIDIA 配置，后续再重试。

## 获取并填写 Key

1. 打开 [NVIDIA 官方模型页面](https://build.nvidia.com/deepseek-ai/deepseek-v4.1-flash)。
2. 使用自己的 NVIDIA 账号登录，按页面提示选择 Generate API Key。
3. 只在本地项目根目录 `.env` 填写：

```dotenv
MODEL_API_KEY=
MODEL_BASE_URL=https://integrate.api.nvidia.com/v1
MODEL_NAME=deepseek-ai/deepseek-v4.1-flash
```

在 `MODEL_API_KEY=` 后填入刚生成的 NVIDIA Key；它与 DeepSeek、OpenRouter 的 Key 不通用。不要将真实 Key 提交 Git 或发到聊天里。

## 验证

在仓库根目录执行：

```sh
.venv/bin/python scripts/rag_demo.py --query "大馆有什么文化特色？" --use-model
```

Windows 使用 `.venv\Scripts\python.exe`。该命令会将问题与检索资料发送给 NVIDIA 开发端点，并消耗账户允许的试用额度。

`answer.mode=model` 表示本次采用了通过当前格式与引用校验的模型回答。未配置、限流、超时、接口不兼容或引用校验失败时，不应将本地回退结果报告为云端模型调用成功。

网页使用时，保存 `.env` 后重启应用，再勾选“使用大模型”。未开启时继续使用本地检索与规则演示。

## 模型版本与失败处理

- 本配置使用 DeepSeek-V4.1-Flash。它与旧的 DeepSeek-V4-Flash 不是同一模型快照；如果用于 COMP5423 正式提交，按课程最新指定版本核对。
- 当前程序沿用 OpenAI 兼容的 `/chat/completions`、Bearer 认证与工具调用格式，真实云端生成与工具循环尚未验证通过。
- 本配置只指向 NVIDIA 官方开发端点，不设置付费模型或其他平台的自动回退；外部请求失败时，已有逻辑会提示失败或回退本地资料。
- 不能直接把任意模型名加上 `:free` 当成免费服务。核对当天，OpenRouter 的两个旧 Flash 免费版本端点列表为空，未选用这两个不可用入口。

官方参考：[模型与调用示例](https://build.nvidia.com/deepseek-ai/deepseek-v4.1-flash)、[模型卡与试用说明](https://docs.api.nvidia.com/nim/reference/nvidia-deepseek-v4_1-flash)。
