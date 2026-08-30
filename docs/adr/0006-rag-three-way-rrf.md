# ADR-0006: RAG 三路 RRF 检索架构

M08 RAG 检索 = Milvus dense + Elasticsearch BM25 + Neo4j 图三路召回，RRF 融合（固定权重照搬 AGI-saber），可选 LLM rerank，small-to-big 父子上下文，证据引用回答。驱动用 pymilvus / elasticsearch-py（按 AGI-saber Go 驱动模式），compose 增加 Milvus + ES 服务（参照根 compose.yaml 的 Neo4j 先例）；逐路降级参照 `docs/wayfinder/assets/final-rag-降级参考.md`（提炼自 final/internal/rag/hybrid.py，final/ 已删除，git 历史可恢复原文件）。

embedding 复用独立通用 port（`llm/embeddings.py`）：M05 记忆与 M08 RAG 共享技术 port，不共享事实 / 索引 / 生命周期。RAG 完成标准含真实 Milvus/ES 集成测试。

**明确推翻** `docs/reference/agi-saber-design-reference.md` 原 Do-not-copy 条目"不迁移 Milvus/ES 驱动与固定 RRF 权重"（用户拍板迁移）。

rerank 与 rewrite 环节的模型可通过顶层 `rerank_model` / `rewrite_model` 段独立覆盖，默认复用主模型；三档语义（留空 / 只填 model 继承主 LLM 连接 / 独立 profile）与 `memory_extractor` 一致。

来源：Wayfinder 票 `剩余功能规划` Q5（resolved）。
