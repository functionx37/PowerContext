# 验证记录与剩余验收项

验证日期：2026-10-29（Asia/Shanghai）。运行环境：Windows、Python 3.12.8、官方 PowerContext 1.4.1，具体 Python 依赖见 `requirements-lock-windows.txt`。

## 已实际完成

| 证据 | 实际覆盖范围 |
| --- | --- |
| `powercontext-smoke.json` | 执行规则版 DSL 原样提取的 Code 代码，通过真实 HTTP 调用桥接和官方 PowerContext；完整六回合、记忆召回、关系修复、徽章解锁、请求幂等、玩家隔离、401/409、拒绝写入后的状态核对，共 12 项检查 |
| `persistence.json` | 在隔离的数据目录启动真实服务，写入恶作剧；停止 PowerContext 和桥接两个进程后重新启动，核对状态及 ArtifactRef 完全一致 |
| `deployment-check.json` | 使用 Dify 1.9.1 官方节点数据类校验 19 个节点（框架依赖使用替身，并非完整引擎）；官方 Compose 与作品覆盖配置通过 `config --quiet` 检查 |

另已执行关键规则测试（资源上下界、无钱送礼、20 回合上限、输入限制、模型失败回退、JSON 编码）及 DSL 节点引用、语法和凭据占位检查。所有记忆引用均来自真实 PowerContext 返回，没有捏造 Dify run ID 或模型回答。

复现：先按 README 启动服务，再运行 `tools/verify.py`、`tools/check_persistence.py`。验证器每次使用新的玩家编号；无需预置数据，也不会覆盖其他玩家存档。本次证据的 UUID、Scope、ArtifactRef 每次运行会不同，状态变化应一致。

可选的官方契约预检：`python tools/check_contracts.py`（首次需网络下载官方固定标签的数据类）。完成 Dify 部署准备后，可加 `--compose-dir .runtime/dify-upstream/docker` 同时验证官方 Compose 和作品覆盖配置。

## 待配置环境后补齐

当前没有可用 Dify 实例及模型服务，因此以下三项尚未验证：

1. 在官方 Dify 1.9.1 中实际导入两份 DSL。
2. 使用已发布 Dify Workflow API 完成六回合；保存 `dify_runtime_verified: true` 的报告及节点详情截图。
3. 配置实际模型服务，记录服务版本与模型标识，确认 `live_model_verified: true`；不能用规则回退结果替代模型运行证据。

Dify 目标版本：1.9.1。实际 Dify 版本：待填写。模型服务/版本：待填写。模型标识：待填写。最终 Workflow 运行证据：待补充。

本目录证明已完成的真实组件测试，不能代替赛事要求的 Dify 导入与完整应用验收。完整复现步骤和自动验收入口均已提供。
