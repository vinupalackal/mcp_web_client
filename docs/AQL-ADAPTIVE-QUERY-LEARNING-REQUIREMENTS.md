# Adaptive Query Learning (AQL) — Requirements

**Feature**: Adaptive Query Learning  
**Version**: 0.1.0  
**Date**: April 3, 2026  
**Status**: Requirements Approved  
**HLD**: `docs/AQL-ADAPTIVE-QUERY-LEARNING-HLD.md`  
**Parent Requirements**: `docs/REQUIREMENTS.md`  
**Baseline Tag**: `v0.9.0-adaptive-cache-routing`

**Per-phase companion docs**:
- `docs/AQL-P1-SCHEMA-CONFIG-STORE-REQUIREMENTS.md`
- `docs/AQL-P1-SCHEMA-CONFIG-STORE-HLD.md`
- `docs/AQL-P1-SCHEMA-CONFIG-STORE-IMPLEMENTATION-SPEC.md`
- `docs/AQL-P2-PASSIVE-QUALITY-RECORDING-REQUIREMENTS.md`
- `docs/AQL-P2-PASSIVE-QUALITY-RECORDING-HLD.md`
- `docs/AQL-P2-PASSIVE-QUALITY-RECORDING-IMPLEMENTATION-SPEC.md`
- `docs/AQL-P3-CORRECTION-PATCHING-REQUIREMENTS.md`
- `docs/AQL-P3-CORRECTION-PATCHING-HLD.md`
- `docs/AQL-P3-CORRECTION-PATCHING-IMPLEMENTATION-SPEC.md`
- `docs/AQL-P4-QUALITY-REPORT-API-REQUIREMENTS.md`
- `docs/AQL-P4-QUALITY-REPORT-API-HLD.md`
- `docs/AQL-P4-QUALITY-REPORT-API-IMPLEMENTATION-SPEC.md`

**Per-phase execution workflow**:
- Treat each AQL phase as a doc-backed mini-project: requirements → HLD → implementation spec → implementation → test development → focused validation → full test execution.
- Do not treat a phase as complete after docs alone; the expected execution order is phase docs, code implementation, test updates/additions, focused test runs, and then full regression execution.
- For Phase 2 and later, do not start code from only the parent AQL docs when the repo is following a per-phase documentation workflow.

---

## 1. Context

Every completed chat turn already produces rich execution signals — which tools were selected,
which succeeded or failed, how many LLM turns were consumed, and whether the user accepted the
response. These signals are currently logged and discarded.

Adaptive Query Learning (AQL) captures those signals in a dedicated Milvus collection
(`tool_execution_quality_v1`) and feeds them back into four decision points:

1. **Tool routing** — semantically similar future queries reuse the tool set that worked before,
   reducing LLM round-trips.
2. **Cache policy** — tools that produce stale results when cached are surfaced as freshness-keyword
   candidates for operator review.
3. **Split-phase ordering** — tool chunks are reordered so historically high-yield tools appear in
   chunk 1, reducing multi-chunk LLM calls.
4. **Quality visibility** — an admin report surfaces routing accuracy, failure rates, and token cost
   trends.

AQL is additive and non-breaking. All new routing paths are gated behind a master switch
(`enable_adaptive_learning`) and confidence thresholds. When conditions are not met the system
silently falls back to existing LLM-based routing.

---

## 2. Functional Requirements

### 2.1 Execution Quality Recording

#### FR-AQL-01 — Quality record written per turn
The system shall write one quality record to `tool_execution_quality_v1` at the end of every
successfully completed chat turn when `enable_adaptive_learning = true`.

#### FR-AQL-02 — Quality record content
Each quality record shall capture:
- query text and its vector embedding
- domain tags and issue classification
- tools selected, tools succeeded, tools failed
- tools freshness-bypassed, tools cache-hit
- per-chunk yield data `[{chunk, offered, selected}]` for split-phase turns
- LLM turn count, synthesis token count, routing mode used
- session ID, Unix timestamp, and TTL-based `expires_at`
- `user_corrected` flag (default `false`, patched retroactively)
- `follow_up_gap_s` (seconds until next user message; −1 if none)

#### FR-AQL-03 — Async write
The quality record write shall execute asynchronously **after** the HTTP response is returned
to the client. It shall not contribute to end-to-end response latency visible to the user.

#### FR-AQL-04 — Write failure isolation
If the quality record write fails (Milvus unreachable, embedding error, or any exception),
the failure shall be logged at WARNING level and silently suppressed. The current chat turn
and all future turns shall be unaffected.

#### FR-AQL-05 — TTL and expiry
Quality records shall have a configurable TTL (`aql_quality_retention_days`, default 30 days).
Expired records shall be purged by the existing expiry-cleanup mechanism alongside
`conversation_memory` and `tool_cache`.

---

### 2.2 Correction Signal Detection

#### FR-AQL-06 — Heuristic correction detection
At the start of each new user message, the system shall evaluate whether the message is a
correction of the immediately preceding assistant response, using a configurable list of
regex patterns (e.g. `wrong`, `actually`, `no,`, `not right`, `that's not`).

#### FR-AQL-07 — Retroactive patch
If a correction is detected, the system shall retroactively update the previous turn's quality
record by setting `user_corrected = true` via a Milvus upsert.

#### FR-AQL-08 — No LLM call for correction detection
Correction detection shall be regex-only and shall not trigger an additional LLM call.

#### FR-AQL-09 — Configurable patterns
The correction pattern list shall be overridable via `MilvusConfig.aql_correction_patterns`
or the `AQL_CORRECTION_PATTERNS` environment variable without requiring a code change.

---

### 2.3 Tool Affinity Routing

#### FR-AQL-10 — Affinity resolution method
`MemoryService` shall expose `resolve_tools_from_quality_history(query, domain_tags)` returning
`AffinityRouteResult(tool_names, confidence, record_count)`.

#### FR-AQL-11 — Minimum record guard
Affinity routing shall return `confidence = 0.0` and an empty tool list when the quality
collection contains fewer than `aql_min_records_for_routing` (default 20) records with
overlapping domain tags. A WARNING shall be logged.

#### FR-AQL-12 — Affinity scoring
Each candidate quality record shall be scored using the formula:

```
affinity = (0.5 × similarity)
         + (0.3 × success_rate)
         − (0.1 × bypass_rate)
         − (0.3 × user_corrected_flag)
```

All four weights shall be configurable via `MilvusConfig.aql_affinity_weights`.

#### FR-AQL-13 — Corrected records excluded
Records where `user_corrected = true` shall be excluded from the Milvus search filter before
scoring. They shall never contribute to affinity routing decisions.

#### FR-AQL-14 — Activation conditions
The affinity route shall activate only when all of the following hold:
- `enable_adaptive_learning = true`
- `direct_tool_route` returned no match
- memory tool route confidence is below `MEMORY_ROUTE_CONFIDENCE_THRESHOLD`
- affinity result confidence ≥ `aql_affinity_confidence_threshold` (default 0.65)

#### FR-AQL-15 — Soft prior, not LLM bypass
The affinity route shall narrow the tool set offered to the LLM. It shall **not** bypass the
LLM call. The LLM receives the narrowed tool list and makes the final tool selection.

#### FR-AQL-16 — Logging
The system shall log when affinity routing is applied, including confidence, record count,
and the tool names selected.

---

### 2.4 Split-Phase Chunk Reordering

#### FR-AQL-17 — Reorder based on affinity
When an `AffinityRouteResult` is available with confidence ≥ `aql_chunk_reorder_threshold`
(default 0.70), the system shall reorder the domain-narrowed tool list so that affinity tools
appear at the front of chunk 1.

#### FR-AQL-18 — Chunk size preserved
Chunk reordering shall only change the position of tools within the list. Chunk size
(`tools_split_limit`) shall remain unchanged.

#### FR-AQL-19 — Reorder logged
The system shall log when chunk reordering is applied, including the number of tools moved
and their names.

---

### 2.5 Freshness Keyword Candidates

#### FR-AQL-20 — Candidate generation
The system shall compute freshness keyword candidates from quality records using the following
signals:
- Tool appears in `tools_bypassed` in > 60% of turns where it was selected.
- Tool appears in `tools_failed` in > 30% of turns AND also appears in `tools_cache_hit` for
  those same turns (i.e. cached result caused failure).
- Correlation between `tools_cache_hit` containing the tool and `user_corrected = true`
  exceeds Pearson r > 0.4.

#### FR-AQL-21 — Candidates are recommendations only
The system shall never automatically modify `tool_cache_freshness_keywords`. Candidates shall
be surfaced via the admin API only. The operator applies changes to `milvus_config.json`.

---

### 2.6 Admin API Endpoints

#### FR-AQL-22 — Quality report endpoint
The system shall expose `GET /api/admin/memory/quality-report` accepting optional `days`
(default 7) and `domain` query parameters.

The response shall include:
- total turns, average tools per turn, average LLM turns
- average synthesis tokens
- correction rate
- top succeeded tools and top failed tools (ranked by frequency)
- freshness keyword candidates
- routing mode distribution (direct / affinity / memory / llm_fallback)

#### FR-AQL-23 — Freshness candidates endpoint
The system shall expose `GET /api/admin/memory/freshness-candidates` returning a ranked list
of tool name patterns with associated signal type and score, and the current configured
keywords for comparison.

#### FR-AQL-24 — Endpoint availability guard
Both admin endpoints shall return `503 Service Unavailable` with a descriptive message when
Milvus is unreachable, consistent with the pattern used by existing admin endpoints.

---

## 3. Non-Functional Requirements

#### NFR-AQL-01 — Zero response latency impact
The quality record write shall not block or delay the HTTP response. End-to-end response
latency for a chat turn shall not increase as a result of AQL.

#### NFR-AQL-02 — Affinity lookup latency
`resolve_tools_from_quality_history()` including embedding generation and Milvus ANN search
shall complete within 200 ms under normal operating conditions.

#### NFR-AQL-03 — Graceful degradation
All AQL code paths shall degrade to existing LLM-based routing silently when:
- `enable_adaptive_learning = false`
- Milvus is unreachable
- The quality collection is empty or below the minimum record threshold
- Any exception occurs during embedding or search

No error shall be surfaced to the end user.

#### NFR-AQL-04 — No new infrastructure
All AQL persistence shall use the existing Milvus instance. No additional databases, queues,
or services are introduced.

#### NFR-AQL-05 — Additive and non-breaking
No existing API contracts, request/response shapes, routing behaviours, or test assertions
shall be changed by AQL. All changes are additions.

#### NFR-AQL-06 — Logging convention
All new Milvus transactions shall follow the existing dual-logger `START / END` boundary
pattern using `mcp_client.external` and `mcp_client.internal` loggers.

#### NFR-AQL-07 — Collection capacity
The quality collection shall support a minimum of 10,000 records before requiring compaction
or additional Milvus configuration.

#### NFR-AQL-08 — Test coverage
Unit tests shall cover: quality record write, correction detection and patch, affinity scoring,
minimum record guard, chunk reordering, and all degradation paths (Milvus unavailable, empty
collection, low confidence). Integration tests shall cover the end-to-end turn-recording and
second-query affinity activation scenario.

---

## 4. Configuration Reference

### 4.1 `MilvusConfig` New Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `enable_adaptive_learning` | `bool` | `false` | Master AQL on/off switch |
| `aql_quality_retention_days` | `int` | `30` | TTL for quality records (days) |
| `aql_min_records_for_routing` | `int` | `20` | Min records before affinity routing activates |
| `aql_affinity_confidence_threshold` | `float` | `0.65` | Min confidence to apply affinity route |
| `aql_chunk_reorder_threshold` | `float` | `0.70` | Min confidence to reorder split-phase chunks |
| `aql_affinity_weights` | `dict` | `{sim:0.5,success:0.3,bypass:-0.1,corrected:-0.3}` | Score formula weights |
| `aql_correction_patterns` | `List[str]` | built-in list | Regex patterns for correction detection |

### 4.2 Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AQL_ENABLE` | `false` | Override `enable_adaptive_learning` |
| `AQL_MIN_RECORDS` | `20` | Override minimum record threshold |
| `AQL_AFFINITY_THRESHOLD` | `0.65` | Override affinity confidence threshold |
| `AQL_QUALITY_RETENTION_DAYS` | `30` | Override quality record TTL |

---

## 5. Constraints and Assumptions

- The embedding model (Ollama `nomic-embed-text`, 4096 dimensions) is fixed. AQL reuses the
  existing `EmbeddingService` without modification.
- Correction detection is heuristic only. Ground-truth labelling and human-in-the-loop
  annotation are out of scope.
- A minimum of 20 quality records with overlapping domain tags is required before affinity
  routing produces statistically meaningful results.
- The system is single-user. User identity-based personalisation is out of scope.
- AQL does not modify `DIRECT_QUERY_ROUTES` automatically. Route tuning remains
  operator-driven based on quality report output.

---

## 6. Out of Scope

| Item | Reason |
|---|---|
| Automatic update of `tool_cache_freshness_keywords` | Operator must review and apply changes |
| Automatic update of `DIRECT_QUERY_ROUTES` | Same as above |
| A/B testing framework for routing strategies | Single-user system; no control group |
| User identity-based personalisation | No auth / single-user |
| Cross-session learning beyond Milvus TTL window | TTL window is the learning horizon |
| Active learning / human annotation UI | Out of scope for this implementation |
| New external services or databases | Only existing Milvus instance used |

---

## 7. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-AQL-01 | With `enable_adaptive_learning=false`, no quality records are written and no affinity routing code is entered |
| AC-AQL-02 | A quality record is written to `tool_execution_quality_v1` after each completed chat turn when AQL is enabled |
| AC-AQL-03 | Quality record write failure (Milvus unreachable) does not affect the chat response or subsequent turns |
| AC-AQL-04 | A follow-up message matching a correction pattern causes `user_corrected=true` to be set on the previous quality record |
| AC-AQL-05 | Correction detection does not trigger an additional LLM call |
| AC-AQL-06 | With fewer than 20 quality records, `resolve_tools_from_quality_history` returns `confidence=0.0` and logs a warning |
| AC-AQL-07 | With sufficient quality records, a semantically similar second query activates the affinity route and reduces LLM calls |
| AC-AQL-08 | Affinity route never bypasses the LLM — the LLM receives the narrowed tool list and makes final selections |
| AC-AQL-09 | Records with `user_corrected=true` are excluded from affinity scoring |
| AC-AQL-10 | Chunk reordering moves affinity tools to chunk 1 when confidence ≥ `aql_chunk_reorder_threshold` |
| AC-AQL-11 | `GET /api/admin/memory/quality-report` returns all required fields with correct aggregation |
| AC-AQL-12 | `GET /api/admin/memory/freshness-candidates` returns ranked candidates without modifying any config |
| AC-AQL-13 | Both admin endpoints return 503 when Milvus is unreachable |
| AC-AQL-14 | The Milvus DB snapshot log includes `tool_execution_quality` row count |
| AC-AQL-15 | All new Milvus transactions emit `START / END` log boundary markers |
| AC-AQL-16 | `make test` passes with all existing 867 tests plus new AQL unit and integration tests |
