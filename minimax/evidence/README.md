# 实际验证记录

记录日期：2026-10-30（Asia/Shanghai）。实际运行详情见 [`verified-local/verification.json`](verified-local/verification.json)。本次完整运行：北京时间 **10:12:00–10:12:24**。

| 题面必做项 | 本次状态 | 可核对证据 |
| --- | --- | --- |
| 能够运行 | 本地通过 | 独立安装依赖，从新目录、新数据库、新 namespace 启动；报告 `runnable_from_empty_state=true` |
| MiniMax 实际参与 | **未通过／待补齐** | 用户暂无密钥，没有请求模型，`live_model_verified=false`；业务修改明确标为 Codex 参考实现 |
| 上下文正确 | 本地通过 | `context-before.json` 的七项必要来源；`context-spec-updated.json` 的更新条款、新代次、变化后验证过期 |
| 数据库实际参与 | 本地通过 | `database-trace.json` 的真实 seekdb 版本、SQL、绑定参数和结果来源 ID；正文见对应 context 文件 |
| 状态能够复用 | 本地通过 | `powercontext-trace.json` 写入 revision 1、2；独立 CLI 和服务重启后的 `context-recovered.json`、`context-recovered-trace.json` |
| 代码修改有效 | 本地通过 | `before-target.log` 7 项业务断言失败、`after-target.log` 8 项通过；回归前后 9 项通过；测试文件哈希一致 |

由于题目采用全部通过制，**当前不能宣称获得 20 分**。取得凭据后按主 README 第 3 节运行真实 MiniMax 流程，并将提交源码与真实模型输出对齐。

## 版本与命令

Windows x64；Node 24.16.0；Python 3.12.8；PowerContext 1.4.1；pylibseekdb 1.4.0.post2；seekdb JS SDK 1.4.0；数据库返回 `5.7.25-OceanBase seekdb-v1.4.0.0`。依赖固定在两个 lock 文件中。

完整验收命令（本次使用同版本 Node 的实际可执行文件）：

```text
node tools/verify.mjs --out evidence/verified-local
exit_code=0
```

目标与回归测试的逐次命令、退出码、工程版本指纹与测试文件 SHA-256 均写在各阶段 `.json` 和 `.log` 中。模块测试为 `node --test tests/*.test.mjs`，交付的 `module-tests.json` 与 `.log` 记录实际结果。

## 证据导航

- `before/tickets.mjs`：原始可运行代码；`verified-local/before.mjs` 与之对应。
- `verified-local/after.mjs`：修改后的代码，与 `sample/src/tickets.mjs` 一致；`change.diff` 给出可阅读差异。
- `before-target.*`、`after-target.*`、`before-regression.*`、`after-regression.*`：同一组测试的实测。
- `context-before.json`：从真实数据库检索，任务状态为空。
- `context-resumed-before.json`：新的 CLI 进程恢复 revision 1，继续未完成事项。
- `context-recovered.json`：两个服务已停止重启，新的 CLI 恢复 revision 2、验证结果和记忆引用；`next_action` 根据读取的成功验证改变。
- `context-spec-updated.json`：更新 R-001、重新导入后的真实结果；旧测试结果被标为过期。
- `database-trace.json`：按阶段保存查询与代次发布记录，真实正文由 context 输出交叉核对。
- `powercontext-trace.json`、`*-trace.json`：官方 API 的请求体和响应，包含写入引用和随后读取的相同记忆；不含鉴权头。

记录中的随机端口、进程编号、Scope 和 Artifact ID 是本次实际服务返回值，复现时会变化；这不影响断言。时间字段使用 UTC ISO 格式，正文日期按北京时间说明。

运行数据、虚拟环境、缓存与原生二进制均不交付，评审可按 README 从空状态重建。`source-manifest.json` 用于核对提交源码和文档的 SHA-256，不替代实际执行测试。
