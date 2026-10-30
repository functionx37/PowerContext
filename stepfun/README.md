# 知屿 Local Atlas · seekdb × 阶跃星辰

浏览器本地向量化、seekdb 数据库内混合检索的中文知识库。全部项目资产位于 `stepfun/`，开发基于 `2026-competition-ecosystem` 分支。

## 快速运行

需要 Node.js 22+、最新版 Chrome / Edge。默认使用 seekdb 嵌入式引擎，首次启动需下载官方原生组件；支持 Windows x64、Linux x64/arm64、macOS arm64。建议至少 8 GB 可用内存，无需推理 API Key。

```powershell
cd stepfun
npm ci
Copy-Item .env.example .env
npm run model:fetch
npm run dev
```

打开 `http://localhost:3000`。首次建库可能需要几十秒，就绪后点击“重试”。点击“试用 18 篇示例资料”，或导入 UTF-8 TXT / Markdown、粘贴文本。界面显示向量化、写入、索引刷新进度。刷新完成后输入问题，结果可查看完整原文。

无法访问 Hugging Face 时可使用镜像，仍固定原始 commit 并校验 ONNX 的 SHA-256：

```powershell
$env:HF_ENDPOINT='https://hf-mirror.com'
npm run model:fetch
```

Linux/macOS 用 `cp .env.example .env`；镜像用 `HF_ENDPOINT=https://hf-mirror.com npm run model:fetch`。中断后重运行支持 ONNX 断点续传。脚本只下载公开文件，不执行推理。浏览器只从本机 `/models/` 加载权重，运行时 WASM 由 Vite 打包，不上传原文或查询给模型服务。

## 本地 Server 备用方案

启动 Docker Desktop / Engine，分配至少 2 GB 内存：

```powershell
docker compose up -d --wait
```

把 `.env` 的 `SEEKDB_MODE` 改为 `server`，保留 `SEEKDB_HOST=127.0.0.1`、`SEEKDB_PORT=2881`、`SEEKDB_DATABASE=stepfun`，重启应用。可用 `SEEKDB_IMAGE=quay.io/oceanbase/seekdb:latest` 切换官方镜像站。

Compose 要求 seekdb 1.4+，使用 `/var/lib/seekdb` 和 Docker volume；1.3.x 的旧持久化路径不同。嵌入式与 Server 的数据独立。严格复现时运行 `docker image inspect oceanbase/seekdb:latest --format '{{index .RepoDigests 0}}'` 获取 digest，并将 `SEEKDB_IMAGE` 固定为 `image@sha256:...`。本次实测使用嵌入式 1.4.0.0，不依赖 Docker 的可变标签。

## 功能与实现

- 左侧 `+` 创建独立知识库。每次请求携带集合名，切换清空旧结果，请求版本防止异步旧结果回写。
- 180 个 Unicode 字符分块、30 字符重叠，优先句末切分，token 上限 256；完整原文、片段、来源、标题、向量均存于 seekdb。
- 文件名与正文的 SHA-256 作为来源 ID，片段 ID 包含来源、编号和内容。重复导入跳过已有块；同名但内容变化保留为新版本。
- 默认 FP16 + WebGPU；GPU 不可用、不支持 `shader-f16`、初始化或推理失败时自动切换 INT8 + WASM，显示实际后端和原因。可手动强制 WASM；FP32 供基线评测。
- 默认批大小 8，按长度排序减少 padding，完成导入后调用 `dbms_index_manager.refresh()`。刷新失败明确报告未完成，重试写入幂等。不会将 SDK 的静默刷新 no-op 当作成功。
- 模型实例驻留 Worker，查询与导入复用；修改后端/精度会释放旧实例。数据库连接操作串行化，保护混合检索的 SQL 会话变量。

默认只监听本机回环地址，是单用户本地应用。原文与向量会发送到配置的 seekdb；模型计算留在浏览器。没有用户认证或多用户权限系统。

## 验证与评测

```powershell
npm test
npm run build
# 应用保持运行，另开终端做真实 HTTP + seekdb 集成测试
npm run test:db
# 构建后的生产运行方式（先停止 dev，避免端口冲突）
npm start
```

“性能实验室 → 运行完整评测”固定 18 篇资料、12 个相关性标注查询、每配置 3 轮。比较 FP32/WASM 逐条、FP32/WASM 批量、INT8/WASM 批量、FP16/WebGPU 批量。创建并自动清理临时集合，不修改个人知识库；不可用配置如实记录错误。保持页面前台以减少浏览器节流。

“导出原始报告”保存 JSON，复制到 `reports/evaluation.json`，运行：

```powershell
npm run report -- reports/evaluation.json
```

报告保留全部逐次计时、排名、实际后端/精度、数据哈希、浏览器和数据库版本；汇总采用中位数与平均 Recall@5 / nDCG@5。模型加载统计本地资源读取和 session 创建；模型网络下载是独立准备阶段，未记录完整冷下载耗时，不能用缓存读取替代该数值。绘制回调在某些自动化浏览器受约 1 秒节流，本次原始数据保留该影响，详见验证记录。

本次真实结果见 [一页技术说明（A4 打印版）](docs/TECHNICAL.html)、[技术说明 Markdown](docs/TECHNICAL.md)、[实测表](reports/BENCHMARK.md)、[验证记录](docs/VALIDATION.md)。原始语料和标注在 `shared/corpus.ts`，模型实际字节数及哈希在 `reports/model-manifest.json`。

## 源码结构

|目录|内容|
|---|---|
|`src/`|界面、Worker 本地推理、浏览器评测|
|`server/`|同源 API、seekdb-js 数据层|
|`shared/`|固定模型、分块、质量指标、测试语料|
|`scripts/`|权重下载校验、真数据库测试、报告生成|
|`tests/`|分块、幂等 ID、指标、向量验证、并发连接测试|
|`reports/`|真实模型清单、逐次实验数据和汇总|

依赖固定版本并提供 lockfile。`.npmrc` 的 `legacy-peer-deps` 跳过未使用的服务端 embedding peer，避免其发布包中的 `workspace:*` 导致安装失败；应用从不使用服务端 embedding provider。

## 官方来源

- [seekdb-js](https://github.com/oceanbase/seekdb-js)：Schema、显式向量、hybridSearch、数据库内 RRF。
- [seekdb Docker](https://github.com/oceanbase/docker-images/blob/main/seekdb/README.md)。
- [BGE 原始模型](https://huggingface.co/BAAI/bge-small-zh-v1.5)、[固定 ONNX 版本](https://huggingface.co/Xenova/bge-small-zh-v1.5/tree/75c43b069aac4d136ba6bc1122f995fedcfd2781)。
- [Transformers.js 精度选项](https://huggingface.co/docs/transformers.js/v3.8.1/en/guides/dtypes)。
