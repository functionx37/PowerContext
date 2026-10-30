# 规有所依：SDD 工程上下文模块

围绕一次真实可运行的工单查询修改，完成“规格／代码／测试导入 → seekdb 检索 → 任务上下文 → 代码修改 → 测试 → PowerContext 保存与重启复用”。所有资产位于 `minimax/`；开发基线为 `2026-competition-ecosystem`，原始题面保存在 `minimax.md`。

**交付边界：当前没有 MiniMax API 密钥，提交中的业务修改为 Codex 编写的参考实现。MiniMax 接入代码已交付，但没有真实调用记录，不能据此宣称满足全部必做项或获得 20 分。** `npm run verify:live` 是配置密钥后补齐真实模型参与的入口。实际验证情况以 `evidence/verified-local/verification.json` 为准。

## 1. 快速复现（Windows PowerShell）

需要 Node.js 22+、Python 3.12、Git，以及下载依赖的网络。本次实际环境为 Windows x64、Node **24.16.0**、Python **3.12.8**。命令从本目录执行；无需 Docker、Embedding 服务或预先存在的数据库。首次安装约需数百 MB 磁盘空间。

```powershell
cd D:\Desktop\PowerContext\minimax
npm ci
uv venv --python python .venv
uv pip install --python .venv\Scripts\python.exe --cache-dir .runtime/uv-cache -r requirements-lock-windows.txt
npm test
npm run test:business
npm run verify
```

如果没有 `uv`，可用 `python -m venv .venv` 与 `.venv\Scripts\python.exe -m pip install -r requirements-lock-windows.txt` 替代。Linux/macOS 使用 `python3 -m venv .venv`、`.venv/bin/python -m pip install -r requirements.txt`。Linux/macOS 未在本机实测；需要官方 `pylibseekdb` 对应平台的 wheel。

`npm run verify` 自动在新的 `.runtime/<run-id>/` 创建数据、启动真实 seekdb 和 PowerContext、运行完整样例、重启两个服务、再次运行独立 CLI，然后停止自己启动的服务。证据写到控制台显示的 `evidence/local-<run-id>/`，这些本地重复运行记录被 Git 忽略。它不会修改交付样例。可以指定新的输出目录：

```powershell
node tools/verify.mjs --out evidence/my-verification
```

正常无密钥验证成功的退出码为 0，报告为 `local_checks_passed: true`、`live_model_verified: false`、`competition_ready: false`。这三个字段分别表示本地功能链路、真实模型参与、完整赛事条件，不能混用。`--live` 缺少密钥时直接退出 1，不会假装调用模型。

## 2. 持续使用 CLI

启动配套服务并保持窗口运行：

```powershell
.venv\Scripts\python.exe tools/services.py
```

seekdb 使用官方 **pylibseekdb 1.4.0.post2** 启动本地运行时，分配随机 loopback TCP 端口；连接信息写入 `.runtime/connection.json`，数据在 `.runtime/services/seekdb/`。模块通过官方 **seekdb JS SDK 1.4.0** 执行 MySQL 协议 SQL。PowerContext **1.4.1** 在 `http://127.0.0.1:18800` 提供官方 HTTP 接口，自身使用 SQLite 持久化。工程资料数据库仍是真实 seekdb。

第二个窗口运行：

```powershell
node src/cli.mjs import --trace .runtime/import-trace.json
node src/cli.mjs context --out .runtime/context.json --trace .runtime/context-trace.json
node src/cli.mjs test --out .runtime/tests.json
node src/cli.mjs state
```

停止并重启后，再运行 `context` 能读到之前的测试结果和已完成事项：

```powershell
.venv\Scripts\python.exe tools/services.py --stop
# 等第一个窗口退出，再重新执行 tools/services.py
```

| CLI 命令 | 输入 | 输出与副作用 |
| --- | --- | --- |
| `import` | `project.json` 列出的真实文件 | 在 seekdb 写入新一代工程索引，返回代次、来源数、指纹 |
| `context` | 任务 JSON + 当前索引 + PowerContext | 返回规格、文件、行号、正文、哈希、进度、验证结果、下一步 |
| `state` | 项目 ID、任务 ID、命名空间 | 从 PowerContext 读取完整最新检查点及记忆引用 |
| `checkpoint --state FILE` | 含 `completed/pending/validations` 数组的 JSON | 在 PowerContext 保存检查点，返回引用 |
| `test` | 任务中指定的功能及回归测试 | 实际运行测试并在 PowerContext 保存结果；失败退出 1 |
| `agent --out DIR` | 数据库检索上下文 + MiniMax 配置 | 真实请求 MiniMax，保存记录，只修改任务允许的源文件 |

公共选项：`--project DIR` 指定工程根目录，`--task FILE` 指定任务，`--namespace ID` 选择独立任务状态，`--out FILE` 保存输出，`--trace FILE` 保存实际查询和状态 API 记录。`agent` 的 `--out` 为证据目录。默认工程是 `sample/`，任务是其 `task.json`，命名空间为 `sdd-demo`。相同 namespace、项目和任务恢复同一存档，换 namespace 从空状态开始。

已有 seekdb 或 OceanBase 可通过 `.env` 的 `SEEKDB_HOST/PORT/USER/PASSWORD/DATABASE` 连接，不需要本地 seekdb 运行时；数据库账号需有建库、建表、读写权限。远程 PowerContext 使用 `POWERCONTEXT_URL`、可选 `POWERCONTEXT_TOKEN`。外部数据库部署未在本机实测。

## 3. 真实 MiniMax 开发流程

复制 `.env.example` 为 `.env`，填写 `MINIMAX_API_KEY`，按账号支持范围选择 `MINIMAX_MODEL` 和 `MINIMAX_BASE_URL`。配置示例默认使用 MiniMax 官方 Anthropic 兼容接口 `https://api.minimax.cn/anthropic`、模型 `MiniMax-M3.1-Flash`；订阅实际可用模型以账号为准。不要提交 `.env`。

```powershell
npm run verify:live
```

该命令在独立工程副本中还原修改前代码，查询真实上下文，再发送给 MiniMax。模型只返回 `summary` 和 `files[{path,content}]` JSON；只允许修改 `src/tickets.mjs`。应用前核对源文件指纹、检查 JavaScript 语法，功能与回归测试保持原样。真实输出不正确时验收退出 1；不会改断言或改用参考答案兜底。

输出目录的 `minimax/` 包含任务和完整上下文请求、模型标识、响应 ID、用量、公开文本、应用前后哈希和代码。鉴权头及模型私有思考块不落盘。根目录包含 `before.mjs`、`after.mjs`、`change.diff` 和同一测试集的日志。模型不必生成与参考实现逐字相同的补丁。

**用于正式提交时**，真实验收成功后，将该目录内 `after.mjs` 复制到 `sample/src/tickets.mjs`，并将整套真实验收记录审阅后保存到 `evidence/verified-live/`；再次运行 `npm run test:business`，确保交付源码与真实模型修改的哈希一致。不要用本地参考实现的记录替代模型记录。

手动使用模型入口时，应先将样例代码恢复为 `evidence/before/tickets.mjs`，再 `import → context → agent → import → test`。模型应用代码后，重新导入才能构造新上下文。

## 4. 文件与提交材料

| 路径 | 内容 |
| --- | --- |
| `src/indexer.mjs`、`store.mjs`、`context.mjs` | 文档导入、seekdb 查询和上下文构建 |
| `src/state.mjs` | PowerContext Scope、记忆写入、分页恢复 |
| `src/agent.mjs`、`cli.mjs` | MiniMax 开发助手与调用入口 |
| `sample/` | 自包含业务模块、规格、初始数据、固定任务、功能与回归测试 |
| `tools/services.py`、`powercontext_service.py` | 真实服务启动、隔离运行目录、优雅停止 |
| `tools/verify.mjs` | 从空状态端到端验收和证据生成 |
| `docs/VALIDATION.md` | 要改什么、兼容行为、必要来源、预期结果、重置方法 |
| `docs/TECHNICAL.md` | 一页技术说明 |
| `evidence/before/tickets.mjs` | 修改前代码快照 |
| `evidence/verified-local/` | 本次实际本地验收记录；模型参与字段明确为 false |
| `requirements-lock-windows.txt`、`package-lock.json` | 本次安装依赖的固定版本 |

## 5. 边界与排错

- 每个任务只支持一个写入者；PowerContext 不提供本模块的跨进程检查点比较交换。发现重复 revision 会报错。不同任务或 namespace 可分别使用。
- 当前是任务描述、规格编号与符号关系驱动的确定性 SQL 检索，不使用语义向量。`project.json` 显式维护文件和符号关系；正文关键词用于补充召回。模块级代码／测试以完整文件为检索单元，规格按 `## R-NNN` 分段。
- 未重新导入的来源变更会报 `Sources changed`；重新导入发布完整新代次，旧片段不参与新检索。来源文件不存在、越界、哈希不符、必要来源缺失、数据库或记忆失败都中止，不返回固定上下文。
- 保存的验证结果绑定工程指纹；规格或代码变化后仍展示历史结果，但 `validation_current` 为 false，并提示重新验证。
- 默认服务仅供本机可信开发与评审使用。PowerContext 无访问令牌，seekdb 为本地 root；不要直接开放到公网。
- Node 原生 embedded 适配器在本机首次初始化未能就绪，正式复现使用已实测的 Python 官方运行时 + TCP SQL 路径。`SEEKDB_MODE=embedded` 是可选兼容入口，未完成本机验证，不用于提交证据。
- 启动失败检查运行目录中的 `services/powercontext/server.log` 和 `services/seekdb/log/`。端口占用时选择 `tools/services.py --port 新端口`，同时修改客户端 `POWERCONTEXT_URL`。不要结束其他工程服务。
- 验收默认查找本目录 `.venv` 的 Python；可通过 `PC_PYTHON` 指定另一个安装了相同依赖的解释器。无需作者机器其他目录中的环境。

## 6. 来源与接口依据

业务样例、规格、测试和上下文模块为本作品编写，没有复制外部业务工程。第三方组件及其接口依据：

- [PowerContext 1.4.1 源码](https://github.com/oceanbase/powercontext/tree/powercontext-v1.4.1)，Apache-2.0；使用该版本官方 `/v1/scopes`、`/v1/memory/remember`、`/v1/atomic-memory/list`。
- [seekdb JS SDK](https://github.com/oceanbase/seekdb-js)，Apache-2.0；使用 1.4.0 的 `SeekdbClient.execute` 和数据库管理接口。
- [seekdb Python bindings](https://github.com/oceanbase/seekdb-bindings/tree/main/python)，Apache-2.0；使用 1.4.0.post2 的 `open`、`connection_options`、`close`。
- [MiniMax Anthropic 兼容接口](https://platform.minimax.cn/docs/api-reference/text-anthropic-api)，使用 HTTP `POST /v1/messages`；默认接口及模型标识据 2026-10-30 查询的官方文档配置。本次未完成真实调用。

依赖按其原有许可证使用；本目录不重新分发第三方服务源码或原生二进制。
