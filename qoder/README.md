# SmartStudy - 智能学习教练

基于 **PowerContext** 记忆服务的智能学习助手，帮助学习者记录学习过程、管理知识记忆、获取个性化复习建议。

## 项目简介

SmartStudy 解决的核心问题：
- **学习记录分散** — 笔记散落在各处，难以系统回顾
- **复习缺乏针对性** — 不知道哪些知识点需要重点复习
- **学习进度不可见** — 无法直观了解自己的学习轨迹和投入

通过集成 PowerContext 上下文服务，系统能够记住每位用户的学习历史，在后续复习和问答中复用这些记忆，实现"越用越懂你"的学习体验。

## 技术架构

| 组件 | 技术 | 作用 |
|------|------|------|
| 后端 | Python FastAPI | RESTful API 服务，桥接前端与 PowerContext |
| 前端 | HTML/CSS/JavaScript | 单页应用，提供学习记录、复习、问答界面 |
| 记忆服务 | PowerContext HTTP API | 存储学习记忆、语义检索、上下文组装 |
| 部署 | Qoder Sites | 项目网站发布与公开访问 |

## 环境要求

- Python 3.10+
- PowerContext 服务（本地或远程）
- 网络连接（用于访问 PowerContext API）

## 快速开始

### 1. 安装依赖

```bash
cd qoder/
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
POWERCONTEXT_URL=http://127.0.0.1:8000   # PowerContext 服务地址
POWERCONTEXT_TOKEN=your_token_here         # 认证 Token（可选）
POWERCONTEXT_SCOPE_ID=smartstudy-default   # 数据空间 ID
```

### 3. 启动 PowerContext 服务

如果尚未部署 PowerContext，请参考 [PowerContext 文档](https://powercontext.oceanbase.io/zh/docs/develop/api-quickstart/) 进行部署。

快速启动（本地模式）：

```bash
# 使用 PowerContext CLI
python -c "from powercontext.cli.app import main; main()" server run --host 127.0.0.1 --port 8000
```

### 4. 启动 SmartStudy 后端

```bash
python server.py
```

服务将在 `http://localhost:8080` 启动。

### 5. 访问应用

打开浏览器访问 `http://localhost:8080`，即可使用 SmartStudy。

## 核心功能

### 学习记录
记录每次学习的主题、时长、难度、掌握程度和笔记，数据通过 `POST /v1/memory/remember` 存入 PowerContext。

### 智能复习
输入复习关键词，系统通过 `POST /v1/memory/search` 从 PowerContext 语义检索相关学习记录，并通过 `POST /v1/context/prepare` 组装上下文。

### 学习问答
基于 PowerContext 中存储的学习记忆进行问答，系统自动检索相关上下文并提供个性化建议。

### 学习面板
可视化展示学习统计数据：总记录数、累计学习时长、学习主题分布等。

## PowerContext 集成说明

本项目使用 PowerContext 的以下 HTTP API：

| API 端点 | 用途 |
|----------|------|
| `POST /v1/memory/remember` | 存储学习记录为记忆条目 |
| `POST /v1/memory/search` | 按语义相似度检索相关学习记忆 |
| `POST /v1/context/prepare` | 组装有界上下文供问答使用 |
| `POST /v1/memory/entries/list` | 列出学习历史记录 |
| `GET /v1/scopes/{scope_id}` | 检查数据空间是否存在 |
| `POST /v1/scopes` | 创建数据空间 |
| `GET /health/live` | 健康检查 |

PowerContext 在本项目中承担的角色：
1. **持久化存储** — 所有学习记录以记忆形式存储在 PowerContext 中
2. **语义检索** — 复习和问答时，通过语义搜索找到相关学习内容
3. **上下文组装** — 将多条相关记忆组装为有界上下文，供前端展示

## 验证样例

### 样例 1：记录学习并查看统计

**初始状态**：首次启动，无学习记录

**操作步骤**：
1. 打开 `http://localhost:8080`
2. 点击「记录学习」标签
3. 填写表单：
   - 学习主题：`线性代数 - 矩阵乘法`
   - 学习时长：`45` 分钟
   - 难度：`中等`
   - 掌握程度：`7/10`
   - 笔记：`学习了矩阵乘法的基本规则，需要注意维度匹配`
4. 点击「保存学习记录」
5. 切换到「学习面板」

**预期结果**：
- 保存成功，显示绿色提示
- 学习面板显示：学习记录 1 条，累计 45 分钟，1 个主题
- PowerContext 状态显示已连接

**验证 PowerContext 作用**：
```bash
# 直接查询 PowerContext 确认记忆已存储
curl -X POST http://127.0.0.1:8000/v1/memory/search \
  -H "Content-Type: application/json" \
  -d '{"scope_id":"smartstudy-default","query":"矩阵乘法","limit":5}'
```
应返回刚记录的学习内容。

### 样例 2：智能复习检索

**前置条件**：已记录 2-3 条不同主题的学习记录

**操作步骤**：
1. 点击「智能复习」标签
2. 输入关键词：`矩阵`
3. 点击「检索复习内容」

**预期结果**：
- 显示与「矩阵」相关的学习记录
- 每条记录显示相关度百分比
- 上下文摘要区域展示 PowerContext 组装的相关记忆

### 样例 3：学习问答

**操作步骤**：
1. 点击「学习问答」标签
2. 输入问题：`我学过哪些数学相关的内容？`
3. 点击发送

**预期结果**：
- 助手回复基于 PowerContext 检索到的相关记忆
- 显示检索到的上下文信息
- 给出个性化复习建议

## API 文档

启动服务后访问 `http://localhost:8080/docs` 查看完整的 API 文档（Swagger UI）。

### 主要端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查，含 PowerContext 连接状态 |
| POST | `/api/study/record` | 记录一次学习 |
| POST | `/api/study/search` | 搜索学习记忆 |
| POST | `/api/study/review` | 获取复习建议 |
| GET | `/api/study/history` | 获取学习历史 |
| POST | `/api/chat` | 基于记忆的问答 |
| GET | `/api/stats` | 获取学习统计 |

## 项目结构

```
qoder/
├── README.md              # 本文件
├── requirements.txt       # Python 依赖
├── .env.example           # 环境变量模板
├── server.py              # FastAPI 后端（含 PowerContext 集成）
├── static/
│   ├── index.html         # 前端页面
│   ├── style.css          # 样式
│   └── app.js             # 前端逻辑
└── tests/
    └── test_server.py     # 接口测试
```

## Qoder 开发记录

本项目使用 Qoder 桌面端完成以下开发工作：

| 环节 | Qoder 完成的内容 |
|------|-----------------|
| 需求分析 | 分析竞赛要求，确定项目方向和功能范围 |
| 架构设计 | 设计前后端分离架构，规划 PowerContext API 集成方案 |
| 后端编码 | 生成 FastAPI 服务器代码，包含所有 API 端点和 PowerContext 桥接逻辑 |
| 前端编码 | 生成完整的单页应用，包含学习面板、记录表单、复习检索、问答交互 |
| 调试优化 | 修复 API 调用错误，优化前端交互体验 |
| 文档生成 | 生成 README、验证样例和运行说明 |
| 站点发布 | 通过 Qoder Sites 发布项目网站 |

## 许可证

Apache License 2.0
