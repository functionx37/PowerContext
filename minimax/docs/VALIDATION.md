# 验证样例：查询工单时默认隐藏归档

## 任务与兼容契约

修改 `sample/src/tickets.mjs` 的 `listTickets`：默认隐藏 `archived === true` 的工单，显式 `includeArchived === true` 才包含。字符串 `"true"`、数字 `1` 等不视为 true；历史记录没有 archived 字段时继续显示。

必须保留状态／标签筛选交集、输入顺序、limit 校验与切片、不修改输入、非法 status 抛出 RangeError，以及独立的工单创建行为。规格文件 R-001～R-003 是本任务有效规格；R-099 是回归范围中的工单创建契约，不属于本次编辑范围。

## 来源核对

上下文必须包含下表七个来源。这些 ID 写在 `sample/task.json.required_sources`，只用于检查召回完整性，不用于填充虚构内容。

| 来源 ID（工程相对路径） | 评审应看到的内容 |
| --- | --- |
| `specs/tickets.md#R-001` | 归档可见性及严格布尔规则 |
| `specs/tickets.md#R-002` | status/tag 组合及错误校验 |
| `specs/tickets.md#R-003` | limit、顺序、不修改输入 |
| `src/tickets.mjs` | listTickets 实际实现 |
| `tests/archive.test.mjs` | 8 项目标功能测试 |
| `tests/regression.test.mjs` | 9 项兼容回归测试 |
| `data/tickets.json` | 五条初始工单 |

输出逐条给出 `path/start_line/end_line/body/sha256`。行号对应输出所属导入代次的真实文件；规格更新后的行号可能变化。因为任务包含 `status` 等词，补充召回可能包含其他相关代码，不要求只返回这七项。

## 初始数据与预期结果

| ID | status | tag | archived |
| --- | --- | --- | --- |
| T1 | open | api | false |
| T2 | open | api | true |
| T3 | closed | web | false |
| T4 | closed | web | true |
| T5 | in_progress | api | 未设置 |

| 查询 | 修改后的返回 ID |
| --- | --- |
| 不传 options／空 options | T1、T3、T5 |
| includeArchived=true | T1、T2、T3、T4、T5 |
| includeArchived=false/"true"/1/null | T1、T3、T5 |
| status=open | T1 |
| tag=web | T3 |
| limit=2 | T1、T3，先过滤再截取 |
| status=in_progress | T5 |
| limit=0／空输入 | 空数组 |
| status=unknown／非法 limit | RangeError |

## 自动操作步骤

运行 `npm run verify`。它会：

1. 复制完整 `sample/` 到新的隔离目录，将查询代码替换为修改前快照。所有测试及初始数据保持相同。
2. 实际运行目标测试，核对失败为业务断言失败，同时回归测试通过；报告包含命令、退出码、工程指纹及每个测试文件哈希。
3. 从空目录启动 seekdb 与 PowerContext，导入真实资料，再以 SQL 实际返回的片段构建上下文。首次读取任务状态 revision=0。
4. 在 PowerContext 写入已完成事项、剩余工作、修改前测试结果，再启动独立 CLI，读取 revision=1，输出恢复后的待办。
5. 无密钥模式应用交付的参考实现；`--live` 模式把同一上下文提交给 MiniMax，再应用模型返回的允许文件。
6. 用原样测试集验证修改后 8 项目标和 9 项回归全部通过；保存修改前后快照与差异，并在 PowerContext 保存 revision=2 的验证结果。
7. 停止、重新启动两个真实服务，在新的 CLI 进程中重新查询 seekdb 并恢复 PowerContext：revision=2、pending=[]、validation_current=true，下一步为审阅已成功验证的记录。
8. 更新 R-001 增加“includeArchived 不改变 status 的错误校验”条款。未导入时拒绝构造过时上下文；导入后读到新条款、新代次和对应行号，已有验证因指纹变化标为过期。

## 修改前失败标准

修改前快照有完整可用的筛选函数，不会因缺依赖或无法启动失败。预期目标测试 **7 失败、1 通过**；回归 **9 通过**。修改后目标 **8 通过**、回归 **9 通过**。测试集在两个阶段的 SHA-256 必须一致，无 skip。精确实测见交付日志。

## 重置

自动验证每次使用新目录、新数据库、新 namespace，无需删除存量数据。手动流程可使用 `--namespace judge-new` 得到独立任务状态；工程资料重新 `import` 会发布新一代索引。要再次验证修改前行为，只在自己的工程副本中把 `evidence/before/tickets.mjs` 复制到 `src/tickets.mjs`。交付 `sample/` 保存修改后的实现。

实际 MiniMax 调用缺失时，即使其他项全通过，赛事完整验收仍不通过。这是题面要求的全部通过制，不应将本地技术验证等同于总分验收。
