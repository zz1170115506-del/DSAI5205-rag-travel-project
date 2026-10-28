# 魔搭 ModelScope DeepSeek Flash 接入

配置日期：2026-10-27。当前示例使用魔搭 API-Inference 的 `deepseek-ai/DeepSeek-V4.1-Flash-1017`。官方模型页列出了该模型的调用地址与示例；项目的真实生成、引用格式、工具循环和响应速度仍须使用自己的令牌验证。

本机验证状态（2026-10-27）：完成阿里云绑定和邮箱验证后，真实云端调用已通过。短回答约 2.6 秒；“大馆有什么文化特色？”的本地 Embedding ＋云端 RAG 回答约 10.0 秒；完整 Agent 流程约 12.8 秒，完成 3 次真实模型请求，并成功调用 `search_places` 和 `place_detail`，引用格式通过校验。检索记录为 `embedding_used: true`。见 [验证记录](evidence/modelscope-2026-10-27/verification.json)。这些是单次测试耗时，不保证固定速度，也不是模型准确率评测。

## 账号与令牌

1. 登录 [魔搭 ModelScope](https://modelscope.cn)，在 [访问令牌页](https://modelscope.cn/my/myaccesstoken) 获取自己的 Token。
2. 按平台提示完成必要的账号绑定或认证，并在模型页确认 API-Inference 可用。账号资格、免费额度、魔粒消耗及限流以 [官方使用限制](https://modelscope.cn/docs/model-service/API-Inference/limits) 和自己的账户页面为准，不承诺固定免费次数或响应速度。
3. 在项目根目录的本地 `.env` 填写以下配置。只复制令牌字符串，不复制 Python 调用示例，不复用 NVIDIA 或 DeepSeek 官方平台的 Key。

```dotenv
MODEL_API_KEY=
MODEL_BASE_URL=https://api-inference.modelscope.cn/v1
MODEL_NAME=deepseek-ai/DeepSeek-V4.1-Flash-1017
```

在 `MODEL_API_KEY=` 后填入魔搭 Token，保存后重启应用；网页勾选“使用大模型”才发起模型请求。不要将 Token 发到聊天或提交 Git。没有 Token 时仍可运行本地检索与规则演示。

## 验证

在仓库根目录执行：

```sh
.venv/bin/python scripts/rag_demo.py --query "大馆有什么文化特色？" --use-model
```

Windows 使用 `.venv\Scripts\python.exe`。这会把问题和检索资料发送到魔搭并消耗账户额度；只有 `answer.mode=model` 才表示采用了通过当前引用格式校验的模型回答。基础回答成功后仍需单独验证网页 Agent 的真实工具调用，普通模拟回归不能证明云端可用或比 NVIDIA 更快。

当前程序通过 OpenAI 兼容 `/chat/completions` 请求 JSON 回答，Agent 另发送工具定义。若接口拒绝参数、限流、超时或模型输出不合格，已有逻辑会提示失败或回退本地资料；不会自动调用另一个付费平台。不要仅为等待免费接口而无限延长请求时限。

## 与现有 RAG 的关系

本地 BGE Embedding、资料和索引继续使用原有配置，无需重建向量。更换的只是云端生成服务。旧 NVIDIA 配置说明保留在 [NVIDIA 接入说明](NVIDIA免费模型接入.md)，切回时必须同步替换地址、模型名与所属平台的 Key。

本模型是 V4.1-Flash-1017；如果用于其他课程正式提交，请另行核对指定模型版本。

官方参考：[模型与 API 示例](https://modelscope.cn/models/deepseek-ai/DeepSeek-V4.1-Flash-1017)、[API-Inference 介绍](https://modelscope.cn/docs/model-service/API-Inference/intro)、[使用限制](https://modelscope.cn/docs/model-service/API-Inference/limits)。
