# SmartStudy — 智能学习教练

记录学习主题、时长、掌握程度和笔记，用 PowerContext 保存历史，在复习和问答时重新检索这些记录。主要功能包括学习记录、学习面板、复习检索和基于记忆的学习建议。

## 本次修复与验证范围

已用 **Python 3.12.8 + 官方 PowerContext 1.4.1** 实测完整 HTTP 流程，并停止、重新启动两个服务后核对记录和检索结果。回归测试 18 项通过，覆盖真实集成、分页、输入校验、服务中断和错误反馈。运行证据见 [`evidence/verification.json`](evidence/verification.json)，修复前实际失败响应见 [`evidence/before.json`](evidence/before.json)。

修复的主要问题：

- 原代码把创建 Scope 的幂等键当成真实 Scope ID，保存时报 `scope_not_found`。现在使用服务返回的 `scope_id`，重启时通过相同幂等键找回同一空间；创建参数与旧版本保持一致，兼容旧版本已经创建的空间。
- 历史列表改用 `/v1/atomic-memory/list`，读取 `items` 和 `artifact`，完整遍历分页，再按时间排序。统计不再请求超出上限的单页数据，也不会把笔记中的“时长”误算为学习时间。
- 上下文读取真实返回字段 `content`，完整保留服务生成的引用和边界；修复复习主题解析，问答优先提示掌握程度较低的记录。
- 上游连接、鉴权和接口错误不再伪装成空结果；页面展示可操作的错误信息。
- 补齐 PowerContext 和测试依赖、本地双服务启动器、自动验收脚本。

`static/` 是完整应用，必须通过后端访问。`web/` 是 Qoder Sites 展示页的静态演示源码，使用示例数据，不写入真实记忆。本次同时纠正了演示页中错误的“已写入 PowerContext”等提示；本地改动尚需在 Qoder Sites 重新发布才会更新线上展示页。

## 从零运行（Windows PowerShell）

需要 Python **3.11+**；本次验证版本为 3.12.8。所有命令从仓库的 `qoder` 目录执行。首次安装需要网络；默认本地运行不需要模型 API Key、Docker 或独立数据库。

```powershell
cd qoder
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe tools\run_local.py
```

打开 **http://127.0.0.1:8080**。启动器会先启动官方 PowerContext，再启动 SmartStudy，检查连接及数据空间是否就绪。页面右上角应显示“PowerContext 已连接”。接口文档位于 http://127.0.0.1:8080/docs。

默认端口：PowerContext `8000`、SmartStudy `8080`。发生冲突时可指定：

```powershell
.venv\Scripts\python.exe tools\run_local.py --pc-port 18000 --port 18080
```

此时打开 http://127.0.0.1:18080。启动器只监听本机地址，数据和日志保存在 `qoder/.runtime/`，包括官方 PowerContext 的 SQLite 数据库 `state.db`。按 Ctrl+C 停止，或从另一个终端执行：

```powershell
.venv\Scripts\python.exe tools\run_local.py --stop
```

重新运行原启动命令会保留学习历史。使用自定义 `--data-dir` 时，停止和再次启动也传入相同目录。启动器不会复用或终止其他应用占用的端口。

Linux/macOS：`python3 -m venv .venv`，安装和运行时将上述 Python 路径换成 `.venv/bin/python`。这些系统未在本次机器上实测。

### 接入已经运行的 PowerContext

已有服务时无需使用双服务启动器。复制配置并只启动后端：

```powershell
Copy-Item .env.example .env
# 编辑 .env，填写现有服务的地址；没有启用认证时 Token 留空
.venv\Scripts\python.exe server.py
```

```dotenv
POWERCONTEXT_URL=http://127.0.0.1:8000
POWERCONTEXT_TOKEN=
POWERCONTEXT_SCOPE_ID=smartstudy-default
```

`.env` 始终从 `qoder/.env` 读取，不依赖启动命令的当前目录。`POWERCONTEXT_SCOPE_ID` 可以是真实存在的 Scope ID，也可以是稳定的创建幂等键。默认 `smartstudy-default` 是幂等键，实际 ID 可通过 `/api/health` 查看。保持相同的键和 PowerContext 数据库，才能恢复原记录。此版本使用一个配置空间，面向个人本地使用。

双服务启动器会使用自己的本地服务地址、空 Token 和隔离的数据库设置；接入远程服务请使用上面的 `server.py` 方式。

## 按步骤验证主要功能

初始状态：新数据目录、面板 0 条学习记录。

1. 点击“记录学习”，输入主题 `线性代数 - 矩阵乘法`、45 分钟、掌握程度 7/10、笔记 `需要注意矩阵维度匹配`。保存后应显示成功。
2. 打开“学习面板”，应显示 1 条记录、45 分钟、1 个主题；最近学习展示正确的主题名称。
3. 再记录主题 `线性代数 - 矩阵求逆`、30 分钟、掌握程度 3/10。面板变为 2 条记录、75 分钟、2 个主题。
4. 在“智能复习”查询 `矩阵`，应出现两条真实记录和完整上下文，包含 `Scope`、`Artifact` 来源引用及结束标记。界面展示匹配排序；PowerContext 的原始排序分值不是概率。
5. 在“学习问答”输入 `矩阵`，回复应提及这两条记录，并建议优先复习“矩阵求逆”（3/10）。输入 `我学过哪些内容？` 可以查看学习概况。
6. 停止并重新运行原启动命令，面板和复习检索应仍可读到相同记录。

问答根据检索到的主题和掌握程度生成规则式建议，未调用外部大模型。PowerContext 搜索使用 `auto`；默认无嵌入模型时使用全文检索，不能将其声称为已验证的向量语义检索。返回的上下文以安全纯文本展示。

### 自动验收

```powershell
.venv\Scripts\python.exe -m pytest tests -v
.venv\Scripts\python.exe tools\verify.py
```

无需预先启动任何服务。测试/验收各自自动选择空闲端口和独立数据目录，不修改日常使用的学习数据。`verify.py` 会启动真实的官方 PowerContext，验证初始空状态、两条中文学习记录的保存、历史/统计、检索、完整上下文引用、问答与无匹配结果，之后重启两个服务再核对持久化。只有断言全部通过才输出 `PASS`，并写入 `evidence/verification.json`。

直接核对指定技术的作用，可先打开 `/api/health` 获取真实 `scope_id`，再向 PowerContext 发送以下 JSON：

```http
POST /v1/atomic-memory/list
Content-Type: application/json

{"scope_id":"替换为实际返回的 scope_id","kind":"study-session","states":["active"],"limit":100}
```

应返回 `items`，其中 `text` 是实际学习内容，`artifact` 与保存响应的记忆引用一致。检索使用 `/v1/memory/search`，上下文使用 `/v1/context/prepare`，同样传入真实 Scope ID。

## API 与结构

| 方法 | SmartStudy 路径 | 功能 |
| --- | --- | --- |
| GET | `/api/health` | 检查 PowerContext 就绪和空间可访问性，返回真实 Scope ID |
| POST | `/api/study/record` | 保存学习记忆，返回真实 Artifact 引用 |
| GET | `/api/study/history?limit=50` | 最近学习及总记录数 |
| GET | `/api/stats` | 全量统计、时长与主题分布 |
| POST | `/api/study/search` | 检索命中和完整上下文 |
| POST | `/api/study/review` | 复习主题、掌握程度及完整上下文 |
| POST | `/api/chat` | 基于真实记忆的规则式学习建议 |

PowerContext 使用的实际接口：`GET /health/ready`、`GET /v1/scopes/{scope_id}`、`POST /v1/scopes`、`POST /v1/memory/remember`、`POST /v1/atomic-memory/list`、`POST /v1/memory/search`、`POST /v1/context/prepare`。所有学习记录均由 PowerContext 持久化，没有另建学习数据数据库或以本地示例数据兜底。

```text
qoder/
  server.py               FastAPI 后端及 PowerContext 桥接
  requirements.txt        固定主要运行与测试依赖
  .env.example            已有 PowerContext 服务的配置模板
  static/                 完整应用页面、样式和交互
  web/                    Qoder Sites 静态展示演示
  tools/run_local.py      双服务启动、停止和持久化配置
  tools/verify.py         真实 HTTP 流程和重启验收
  tests/test_server.py    自动化回归测试
  evidence/               修复前失败响应和修复后真实验收报告
  qoder.md                原始赛题
```

## 开发记录与赛事材料

原版本 README 记录了 Qoder 参与需求分析、架构设计、后端与前端生成、调试、文档和站点发布。本次可运行性修复由 Codex 完成，不能作为新增 Qoder 使用记录。赛事要求的 Qoder UID、原始对话截图/录屏及公开站点访问验证，仍应以参赛者已有的真实材料提交；自动测试不替代这些证明。

许可证：Apache License 2.0。
