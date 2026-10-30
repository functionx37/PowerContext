# 知屿：浏览器本地推理 × seekdb 混合检索

**运行路径**：TXT/MD/粘贴文本 → 浏览器分块 → Web Worker 中 ONNX 推理 → 同源 Node API → seekdb。文档和查询向量均由浏览器实际计算；后端仅校验、存储和检索，无 embedding provider、云端推理、客户端检索或预计算回放。源码与启动步骤见 [README](../README.md)。

**模型与量化**：中文 BAAI/bge-small-zh-v1.5 的公开 Xenova ONNX 发布，固定 revision `75c43b069aac4d136ba6bc1122f995fedcfd2781`；512 维、CLS 池化、L2 归一化，仅查询加 BGE 检索指令。使用发布方现成的 FP16 与 INT8 权重，不声称自行训练/量化；其 `quantize_config.json` 配置 `per_channel=true`、`reduce_range=true`、`weight_type=QInt8`。下载脚本校验 ONNX 原始 SHA-256，浏览器以 `dtype: fp16/q8` 显式选择模型。

|实际文件字节口径|FP32|FP16|INT8|
|---|---:|---:|---:|
|ONNX 权重|94,851,877|47,497,427|24,010,842|
|权重压缩比|1×|1.997×|3.950×|
|权重 + 相同配置/分词文件|95,292,210|47,937,760|24,451,175|
|上述完整模型压缩比|1×|1.988×|3.897×|

**端侧运行**：Transformers.js 3.8.1，显式 `device: webgpu`，检查 GPU adapter 与 `shader-f16`。GPU 缺失、FP16 特性缺失或运行失败，自动重建 `device: wasm, dtype: q8`；界面显示实际后端、精度和原因。WASM 单线程、不依赖跨源隔离；模型驻留 Worker 并复用，切换配置释放实例。本次已真实运行 FP16/WebGPU 与 INT8/WASM。

**seekdb**：seekdb-js 1.4.0，嵌入式 seekdb 1.4.0.0。每个知识库独立 Collection，`document`/`embedding VECTOR(512)`/`metadata JSON`，HNSW cosine（m=16，ef_construction=200）+ IK smart 全文索引。`atlas_catalog` 保存名称和模型指纹，`atlas_sources` 保存完整原文。`hybridSearch({query, knn: {queryEmbeddings}, rank: {rrf: {rankConstant:60}}})` 调用数据库 `DBMS_HYBRID_SEARCH.GET_SQL` 并执行融合 SQL；服务端不合并两路排名。全连接队列保护混合检索会话变量，刷新直接调用 `dbms_index_manager.refresh()`，失败显式报告。

**状态与优化**：来源/分块使用稳定 SHA-256 ID，重试跳过已提交批次；默认按长度排序、batch=8、完成导入统一刷新。集合 ID 随请求传递，模型指纹校验，切换递增请求版本并清除旧结果。实验临时集合独立且在 finally 清理。

**实测**：2026-10-29，Windows，Ryzen 7 7840HS / Radeon 780M，物理可用总内存约 27.82 GiB，Chrome 156 内核；18 篇/18 块、12 查询、3 轮，原始数据与数据集哈希见 [evaluation.json](../reports/evaluation.json)。表内是逐轮中位数，质量为 36 次查询均值；单次数据库耗时含队列和 SDK 调用。

|配置|块/秒|整批导入 ms|seekdb 检索 ms|Recall@5 / nDCG@5|
|---|---:|---:|---:|---:|
|FP32/WASM，batch1，逐批刷新|11.84|8400.90|11.85|1.0000 / 0.9692|
|FP32/WASM，batch8，统一刷新|10.83|2161.70|11.85|1.0000 / 0.9692|
|INT8/WASM，batch8，统一刷新|18.37|1536.80|11.84|1.0000 / 0.9692|
|FP16/WebGPU，batch8，统一刷新|121.95|818.00|13.98|1.0000 / 0.9692|

量化相对 FP32 的两项质量变化均为 0 个百分点，仅对本小语料成立。批量+统一刷新使导入约快 3.89×，但 FP32 单独向量化吞吐未提高；INT8 对同 batch/后端的 FP32 吞吐约快 1.70×。FP16/WebGPU 同时改变后端与精度，不作为单项因果结论。首次加载/推理独立记录。端到端绘制代理指标约 1002 ms，受内置浏览器约 1 秒帧节流影响，不能据此判断量化延迟收益；普通 WASM 混合查询另观察到 425 ms。模型冷网络下载时长未完整记录，未捏造；完整计时和限制见 [详细报告](../reports/BENCHMARK.md)、[验证记录](VALIDATION.md)。
