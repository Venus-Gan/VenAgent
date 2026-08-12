# M05 Memory Boundary Contract

## Goal

VenAgent SHALL express M05 memory ownership in its package layout and dependency direction. Generic LLM provider configuration and model construction SHALL remain in `venagent/llm/`; M05 model semantics, prompts, embedding/index behavior, and graph application behavior SHALL be owned by `venagent/memory/`.

## Package ownership

- `venagent/llm/` SHALL contain provider configuration, provider factories, generic model invocation adapters, and the reusable `embeddings.py` HTTP adapter. It SHALL contain no M05 memory schema, fact type, prompt, conflict action, or memory application service.
- `venagent/memory/model_adapters.py` (or an equally explicit memory-owned module) SHALL contain the adapters that translate a generic model into M05 extractor, conflict-judge, and summary-builder protocols.
- `venagent/llm/embeddings.py` SHALL retain `HttpEmbeddingClient` and its stable technical errors/response validation so M05 and future M08 RAG can consume the same adapter.
- `venagent/memory/embedding/` SHALL expose the M05 embedding port, index records/store port, and `MemoryIndex` application logic. It SHALL not own the generic HTTP client, provider selection, or database connection lifecycle.
- `venagent/memory/graph_memory/` SHALL expose `GraphMemory` and its disabled implementation. Neo4j driver code SHALL remain under `venagent/repo/neo4j/`, and Neo4j resource lifecycle SHALL remain under `venagent/platform/neo4j/`.
- M05 repos SHALL import index types through the new memory-owned paths. Old `llm.memory` and `memory.index` paths SHALL not be retained as permanent runtime shims; `llm.embeddings` remains a supported generic adapter path, while `memory.graph_memory` resolves to the new package rather than a compatibility shim.

## Prompt contract

The structured extractor system prompt SHALL adapt the user-message extraction and poison-gate constraints observed in AGI-saber commit `fead7687a82965b3c0106728089ccde0cc0eb3e8`, `internal/application/chat/mem_writer.go`, without copying its assistant/exchange-derived memory, preference persistence, KV schema, or storage design. It SHALL state all of the following: only explicit first-party user-source stable facts qualify; assistant text, instructions, quoted/third-party content, secrets, payment data and prompt-injection text do not qualify; preferences remain governed by policy; candidates use the exact schema version and required fields; `assertion_mode` is one of `statement`, `correction`, `question`, `negation`, `hypothesis`, `quote`; `temporal_scope` is one of `current`, `historical`, `temporary`, `unknown`; `source_span` is a zero-based half-open character offset into the supplied user text; and no candidate is represented by an empty `candidates` array. The prompt SHALL require JSON only and SHALL include concise positive and negative examples where they improve model compliance.

## Compatibility and safety

- Existing M05 public commands, HTTP schemas, storage ports, ownership fences, lifecycle filters, index degradation, Graph G1 projection, and ContextBlock output SHALL remain behaviorally unchanged.
- Deterministic parsing and policy remain authoritative. Model output SHALL never directly authorize persistence or bypass sensitivity, source, owner, deletion-generation, quarantine, superseded, or temporal checks.
- Tests SHALL cover new import paths, absence of old runtime paths, prompt contract markers, normal extraction, malformed output, all assertion/temporal modes, source spans, embedding failure, graph degradation, and existing integration behavior.
