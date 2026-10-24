# 项目脚本

在仓库根目录使用已安装依赖的 Python 执行。

| 脚本 | 用途 |
| --- | --- |
| `verify.py` | Python、前端、资料、检索、真实本地 stdio 与 Agent 综合检查 |
| `doctor.py --mcp` | 配置与本地 MCP 诊断，不输出真实密钥 |
| `manage_data.py` | 校验候选地点资料的结构、来源和坐标 |
| `evaluate.py` | 作者编写的开发检索例题检查 |
| `evaluate_agent.py` | 本地工具流程验收；模型响应使用模拟供应商 |
| `smoke_multiturn.py --live` | 明确指定后使用自己配置的真实模型；可能产生供应商费用 |
| `evaluate_holdout.py` | 冻结保留题检查；不得据题目反复调参 |
| `package_source.py 目标.zip` | 按 Git 文件清单导出源码与哈希清单，排除环境与本机历史 |

普通验证命令见根目录 README。测试成功、真实 API 联调与正式质量评测是不同的证据。
