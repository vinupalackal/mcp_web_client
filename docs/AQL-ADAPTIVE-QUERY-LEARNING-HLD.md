# High-Level Design Document
## Adaptive Query Learning (AQL) for MCP Client Web

**Project**: MCP Client Web  
**Feature**: Adaptive Query Learning — feedback-driven tool routing and cache policy  
**Version**: 0.1.0-aql-hld  
**Date**: April 3, 2026  
**Status**: Design Ready  
**Parent HLD**: `docs/MILVUS_MCP_INTEGRATION_HLD.md`  
**Requirements**: `docs/AQL-ADAPTIVE-QUERY-LEARNING-REQUIREMENTS.md`  
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
- `docs/AQL-P5-AFFINITY-LOOKUP-ENGINE-REQUIREMENTS.md`
- `docs/AQL-P5-AFFINITY-LOOKUP-ENGINE-HLD.md`
- `docs/AQL-P5-AFFINITY-LOOKUP-ENGINE-IMPLEMENTATION-SPEC.md`
- `docs/AQL-P6-ROUTING-INTEGRATION-REQUIREMENTS.md`
- `docs/AQL-P6-ROUTING-INTEGRATION-HLD.md`
- `docs/AQL-P6-ROUTING-INTEGRATION-IMPLEMENTATION-SPEC.md`
- `docs/AQL-P7-SPLIT-PHASE-CHUNK-REORDERING-REQUIREMENTS.md`
- `docs/AQL-P7-SPLIT-PHASE-CHUNK-REORDERING-HLD.md`
- `docs/AQL-P7-SPLIT-PHASE-CHUNK-REORDERING-IMPLEMENTATION-SPEC.md`

**Per-phase execution workflow**:
- Treat each AQL phase as a doc-backed mini-project: requirements → HLD → implementation spec → implementation → test development → focused validation → full test execution.
- Do not treat a phase as complete after docs alone; the expected execution order is phase docs, code implementation, test updates/additions, focused test runs, and then full regression execution.
- For Phase 2 and later, do not start code from only the parent AQL docs when the repo is following a per-phase documentation workflow.

---

## 1. Executive Summary

Every completed chat turn produces rich execution signals: which tools were selected, which succeeded or failed, how many LLM turns were needed, and whether the user accepted the response. Today all of these signals are logged but discarded.

Adaptive Query Learning (AQL) captures those signals in a dedicated Milvus collection and feeds them back into four decision points:

1. **Tool routing** — semantically similar future queries reuse the tool set that worked before, reducing LLM round-trips.
2. **Cache policy** — tools that produce stale results when cached are automatically flagged as freshness-sensitive keyword candidates.
3. **Split-phase ordering** — tool chunks are reordered so historically high-yield tools appear first, collapsing multi-chunk selection into fewer LLM calls.
4. **Quality visibility** — an admin report surfaces routing accuracy, failure rates, and token cost trends.

AQL is **purely additive**. All existing routing paths remain intact. AQL paths activate only when confidence thresholds are met and Milvus is reachable. When neither condition holds the system degrades silently to today's LLM-based routing.

### 1.1 Design Principles

- **Observe before acting**: Phases 1–2 (data collection) are deployed before any routing changes.
- **Soft priors, not hard overrides**: AQL narrows the tool set offered to the LLM; it never bypasses the LLM entirely.
- **Operator-controlled configuration**: AQL never modifies `DIRECT_QUERY_ROUTES` or `tool_cache_freshness_keywords` automatically. Recommendations are surfaced via API; humans apply changes.
- **Graceful degradation**: If Milvus is unreachable or the quality collection is empty, the system falls back to current LLM routing with no error surface to the user.
- **Single infrastructure**: No new services. All AQL persistence reuses the existing Milvus instance alongside `conversation_memory` and `tool_cache`.

---

## 2. Architecture Overview

### 2.1 Where AQL fits in the existing pipeline

```
User message
     │
     ▼
┌────────────────────────────────────────────────────────────────────────┐
│  Routing Layer (backend/main.py — send_message)                        │
│                                                                        │
│  1. Direct-route match  ──► single-tool bypass (existing)             │
│  2. Memory tool resolve ──► conversation_memory / tool_cache (existing)│
│  3. ► AQL affinity route (NEW) ─────────────────────────┐             │
│  4. LLM split-phase selection (existing, with AQL chunk  │             │
│     reorder NEW)                                         │             │
│                                                          ▼             │
│                                              allowed_tool_names        │
└────────────────────────────────────────────────────────────────────────┘
     │
     ▼
Tool execution  ──► MCP Server
     │
     ▼
Synthesis LLM call
     │
     ▼
HTTP response returned to client
     │
     ▼ (async, post-response)
┌────────────────────────────────────────────────────────────────────────┐
│  AQL Quality Recorder (NEW)                                            │
│  • Embed query                                                         │
│  • Write quality record to tool_execution_quality_v1                  │
│  • Detect correction on next turn → retroactive patch                 │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.2 New Milvus Collection

```
Existing collections:
  mcp_client_conversation_memory_v1
  mcp_client_tool_cache_v1
  mcp_client_code_memory_v1
  mcp_client_doc_memory_v1

New collection (AQL):
  mcp_client_tool_execution_quality_v1
```

---

## 3. Data Model

### 3.1 `tool_execution_quality_v1` Schema

| Field | Type | Description |
|---|---|---|
| `id` | `VARCHAR` PK | `quality-{query_hash}-{timestamp_hex}` |
| `vector` | `FLOAT_VECTOR[4096]` | Embedding of the user message (Ollama nomic-embed-text) |
| `query_hash` | `VARCHAR` | SHA-256 of normalised query text (dedup key) |
| `domain_tags` | `VARCHAR` | JSON array e.g. `["memory","cpu"]` |
| `issue_type` | `VARCHAR` | Classifier result e.g. `"Performance / CPU"` |
| `tools_selected` | `VARCHAR` | JSON array — all tools LLM chose |
| `tools_succeeded` | `VARCHAR` | JSON array — `isError=False` subset |
| `tools_failed` | `VARCHAR` | JSON array — `isError=True` subset |
| `tools_bypassed` | `VARCHAR` | JSON array — freshness-bypassed tools |
| `tools_cache_hit` | `VARCHAR` | JSON array — cache-served tools |
| `chunk_yields` | `VARCHAR` | JSON array `[{chunk, offered, selected}, ...]` |
| `llm_turn_count` | `INT64` | Number of LLM turns used |
| `synthesis_tokens` | `INT64` | Total tokens consumed in synthesis turn |
| `routing_mode` | `VARCHAR` | `direct` / `affinity` / `memory` / `llm_fallback` |
| `user_corrected` | `BOOL` | True if next message matched correction pattern |
| `follow_up_gap_s` | `INT64` | Seconds until next user message (−1 = none) |
| `session_id` | `VARCHAR` | Session the turn belongs to |
| `timestamp` | `INT64` | Unix epoch seconds |
| `expires_at` | `INT64` | TTL-based expiry (aligned with `QUALITY_RETENTION_DAYS`) |

**Index**: IVF_FLAT on `vector`; scalar index on `domain_tags`, `user_corrected`, `timestamp`.

### 3.2 Affinity Score Formula

$$
\text{affinity} = 0.5 \cdot \text{sim} + 0.3 \cdot \text{success\_rate} - 0.1 \cdot \text{bypass\_rate} - 0.3 \cdot \mathbb{1}[\text{user\_corrected}]
$$

Where:
- $\text{sim}$ = cosine similarity between incoming query embedding and candidate record
- $\text{success\_rate}$ = `len(tools_succeeded) / len(tools_selected)`
- $\text{bypass\_rate}$ = `len(tools_bypassed) / len(tools_selected)`
- $\mathbb{1}[\text{user\_corrected}]$ = 1 if the record is marked corrected, 0 otherwise

All weights are configurable via `MilvusConfig.aql_affinity_weights`.

---

## 4. Component Design

### 4.1 `MemoryService` — New Methods

```
MemoryService (backend/memory_service.py)
├── [existing] lookup_tool_cache(...)
├── [existing] record_tool_cache(...)
├── [existing] resolve_tools_from_memory(...)
├── [existing] enrich_for_turn(...)
│
├── [NEW] async record_execution_quality(...)         §4.1.1
├── [NEW] async patch_correction_signal(...)          §4.1.2
├── [NEW] async resolve_tools_from_quality_history(...)  §4.1.3
└── [NEW] async get_quality_report(...)               §4.1.4
```

#### 4.1.1 `record_execution_quality()`

Called **asynchronously after** the HTTP response is sent (fire-and-forget with error logging).

```
Inputs:
  query, session_id, domain_tags, issue_type,
  tools_selected, tools_succeeded, tools_failed,
  tools_bypassed, tools_cache_hit, chunk_yields,
  llm_turn_count, synthesis_tokens, routing_mode

Steps:
  1. Embed query text via EmbeddingService
  2. Build quality record dict
  3. Milvus upsert → tool_execution_quality_v1
  4. Log: MILVUS UPSERT TOOL_EXECUTION_QUALITY START / END
```

#### 4.1.2 `patch_correction_signal(session_id, previous_query_hash)`

Called at the start of a new message if correction patterns match.

```
Steps:
  1. Milvus search: filter = session_id AND query_hash = previous_query_hash
  2. If record found: upsert with user_corrected = True
  3. Log: Quality record patched: user_corrected=True for query_hash=...
```

#### 4.1.3 `resolve_tools_from_quality_history(query, domain_tags)`

Returns `AffinityRouteResult(tool_names, confidence, record_count)`.

```
Steps:
  1. Embed query
  2. Milvus ANN search on tool_execution_quality_v1
     filter: domain_tags overlap AND user_corrected == False
     limit: 10
  3. Guard: if record_count < MIN_QUALITY_RECORDS (20), return confidence=0.0
  4. For each candidate: compute affinity score (§3.2)
  5. Aggregate tool_names by weighted vote across top-N candidates
  6. Return top tools above AFFINITY_TOOL_SCORE_THRESHOLD
     with confidence = mean(top affinity scores)
```

#### 4.1.4 `get_quality_report(days, domain)`

```
Steps:
  1. Milvus search with timestamp filter (last N days), optional domain filter
  2. Aggregate: total turns, avg tools/turn, top succeeded, top failed,
     correction rate, avg synthesis tokens, routing mode distribution
  3. Compute freshness keyword candidates (§4.2)
  4. Return QualityReport dataclass
```

### 4.2 Freshness Keyword Candidate Logic

A tool is flagged as a freshness keyword candidate when **any** of the following hold across the filtered quality records:

| Signal | Threshold |
|---|---|
| Appears in `tools_bypassed` | > 60% of turns where it was selected |
| Appears in `tools_failed` | > 30% of turns AND `tools_cache_hit` contains the tool | 
| `tools_cache_hit` for this tool correlates with `user_corrected=True` | Pearson r > 0.4 |

Candidates are returned ranked by signal strength. The operator adds them to `milvus_config.json → tool_cache_freshness_keywords`.

### 4.3 Split-Phase Chunk Reordering

When quality history produces an `AffinityRouteResult` with confidence above `AQL_CHUNK_REORDER_THRESHOLD`:

```
1. Extract tool_names from affinity result
2. In the domain-narrowed tool list, move affinity tools to position [0..N]
3. Log: AQL chunk reorder: moved N tools to front of chunk 1
4. Proceed with existing split-phase logic (chunk size unchanged)
```

This does **not** change the LLM call — it only changes the order within the tool list sent to chunk 1, maximising the chance chunk 1 yields all needed tools.

### 4.4 Routing Integration (send_message)

The AQL path is inserted between existing step 2 (memory tool resolve) and step 4 (LLM split-phase):

```python
# After memory tool resolve, before split-phase
if (
    _memory_service is not None
    and milvus_config.enable_adaptive_learning
    and direct_tool_route is None
    and memory_route_confidence < MEMORY_ROUTE_CONFIDENCE_THRESHOLD
):
    affinity = await _memory_service.resolve_tools_from_quality_history(
        query=message.content,
        domain_tags=domain_tags,
    )
    if affinity.confidence >= AQL_AFFINITY_CONFIDENCE_THRESHOLD:
        allowed_tool_names = affinity.tool_names
        routing_mode = "affinity"
        logger_internal.info(
            "AQL affinity route: %d tools (confidence=%.2f, records=%d)",
            len(allowed_tool_names), affinity.confidence, affinity.record_count,
        )
```

### 4.5 Correction Detection (send_message)

At the start of message processing, before any routing:

```python
CORRECTION_PATTERNS = [
    r"\b(wrong|incorrect|no[,.]|actually|that'?s not|not right|not what I)\b"
]

if _memory_service is not None and milvus_config.enable_adaptive_learning:
    prev = session_manager.get_last_turn_meta(session_id)  # query_hash
    if prev and _is_correction(message.content, CORRECTION_PATTERNS):
        asyncio.create_task(
            _memory_service.patch_correction_signal(session_id, prev.query_hash)
        )
```

Correction detection is regex-only — no extra LLM call.

---

## 5. New API Endpoints

### 5.1 `GET /api/admin/memory/quality-report`

```
Query params:
  days   int   default=7    time window
  domain str   optional     filter by domain tag

Response: QualityReportResponse
{
  "total_turns": 66,
  "avg_tools_per_turn": 3.4,
  "avg_llm_turns": 1.8,
  "avg_synthesis_tokens": 4200,
  "correction_rate": 0.04,
  "top_succeeded_tools": [{"tool": "get_memory_info", "count": 42}, ...],
  "top_failed_tools":    [{"tool": "device_processor_speed", "count": 12}, ...],
  "freshness_keyword_candidates": ["loadavg", "cpu_stats"],
  "routing_distribution": {
    "direct":       0.31,
    "affinity":     0.12,
    "memory":       0.05,
    "llm_fallback": 0.52
  }
}
```

### 5.2 `GET /api/admin/memory/freshness-candidates`

```
Response: FreshnessCandidatesResponse
{
  "candidates": [
    {"pattern": "loadavg",   "signal": "bypass_rate",    "score": 0.82},
    {"pattern": "cpu_stats", "signal": "cache_stale",    "score": 0.61}
  ],
  "current_keywords": ["uptime", "heartbeat", "health", ...]
}
```

Both endpoints return `503 Service Unavailable` with a descriptive message when Milvus is unreachable, matching the pattern of existing admin endpoints.

---

## 6. Configuration

### 6.1 New `MilvusConfig` Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `enable_adaptive_learning` | `bool` | `false` | Master AQL on/off switch |
| `aql_quality_retention_days` | `int` | `30` | TTL for quality records |
| `aql_min_records_for_routing` | `int` | `20` | Min records before affinity routing activates |
| `aql_affinity_confidence_threshold` | `float` | `0.65` | Min confidence to apply affinity route |
| `aql_chunk_reorder_threshold` | `float` | `0.70` | Min confidence to reorder split-phase chunks |
| `aql_affinity_weights` | `dict` | `{sim:0.5, success:0.3, bypass:-0.1, corrected:-0.3}` | Score weights |
| `aql_correction_patterns` | `List[str]` | built-in list | Regex patterns for correction detection |

### 6.2 Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AQL_ENABLE` | `false` | Override `enable_adaptive_learning` |
| `AQL_MIN_RECORDS` | `20` | Override minimum record threshold |
| `AQL_AFFINITY_THRESHOLD` | `0.65` | Override affinity confidence threshold |
| `AQL_QUALITY_RETENTION_DAYS` | `30` | Override quality record TTL |

---

## 7. Milvus Transaction Logging

All new Milvus operations follow the existing dual-logger `START / END` boundary pattern:

```
******* MCP CLIENT to MILVUS UPSERT TOOL_EXECUTION_QUALITY TRANSACTION ****** START
  Milvus upsert start: collection=mcp_client_tool_execution_quality_v1 ...
******* MILVUS to MCP CLIENT UPSERT TOOL_EXECUTION_QUALITY TRANSACTION ****** END

******* MCP CLIENT to MILVUS SEARCH TOOL_EXECUTION_QUALITY TRANSACTION ****** START
  Milvus search start: collection=mcp_client_tool_execution_quality_v1 vectors=1 limit=10 ...
******* MILVUS to MCP CLIENT SEARCH TOOL_EXECUTION_QUALITY TRANSACTION ****** END
```

The post-response Milvus snapshot block includes the new collection:

```
┌─── MILVUS DATABASE SNAPSHOT ─── AFTER QUERY  request_id=...
│  code_memory                               0 rows
│  doc_memory                                0 rows
│  conversation_memory                      12 rows
│  tool_cache                                3 rows
│  tool_execution_quality                   66 rows     ← NEW
└────────────────────────────────────────────────────────────────
```

---

## 8. Degradation and Safety

| Failure | Behaviour |
|---|---|
| Milvus unreachable | Skip quality write (logged); routing falls back to LLM |
| Embedding service error | Skip quality write (logged); routing falls back to LLM |
| Quality collection empty | `record_count < MIN_QUALITY_RECORDS` guard → confidence=0.0 → LLM fallback |
| Affinity confidence below threshold | Skip affinity route → LLM fallback |
| Correction patch fails | Logged as warning; does not affect current turn |
| `enable_adaptive_learning=false` | All AQL code paths are gated and skipped entirely |

All failure paths produce internal log lines only — no error is returned to the user.

---

## 9. Implementation Phases

| Phase | Scope | Risk | Prerequisite |
|---|---|---|---|
| **P1 — Collection + Schema** | Add `tool_execution_quality_v1` collection init to `MilvusStore`; add `MilvusConfig` fields | None | — |
| **P2 — Quality Recorder** | `record_execution_quality()` + async post-response write in `send_message` | Low | P1 |
| **P3 — Correction Detection** | `patch_correction_signal()` + pre-routing check in `send_message` | Low | P2 |
| **P4 — Quality Reporting APIs** | `get_quality_report()` + `GET /api/admin/memory/quality-report` + `GET /api/admin/memory/freshness-candidates` | None | P2 |
| **P5 — Affinity Lookup Engine** | `resolve_tools_from_quality_history()` in isolation | Low | P2, P3 |
| **P6 — Routing Integration** | Apply affinity results as a guarded soft prior in live requests | Medium | P5 |
| **P7 — Chunk Reordering** | Reorder split-phase tool list using affinity result | Low | P6 |

P1–P5 are pure data collection and read-only tooling — zero routing risk.  
P6–P7 introduce new routing paths, gated behind `enable_adaptive_learning` and confidence thresholds.

---

## 10. Test Strategy

| Layer | Coverage |
|---|---|
| Unit — `test_memory_service.py` | `record_execution_quality` write; `patch_correction_signal` upsert; `resolve_tools_from_quality_history` scoring; degradation when Milvus unavailable; `record_count < MIN` guard |
| Unit — `test_main_runtime.py` | Correction detection regex; affinity route activation/skip; quality write triggered post-response; chunk reorder applied when threshold met |
| Integration — `test_chat_api.py` | End-to-end: quality record written after turn; affinity route used on second similar query; correction patch applied when follow-up matches pattern |
| Admin API | `GET /api/admin/memory/quality-report` returns correct structure; `GET /api/admin/memory/freshness-candidates` returns ranked list |

---

## 11. File Change Summary

| File | Change |
|---|---|
| `backend/memory_service.py` | Add `record_execution_quality`, `patch_correction_signal`, `resolve_tools_from_quality_history`, `get_quality_report`; new `AffinityRouteResult`, `QualityRecord`, `QualityReport` dataclasses |
| `backend/milvus_store.py` | Add `tool_execution_quality` collection init; update `get_record_count` to include new collection |
| `backend/models.py` | Add AQL fields to `MilvusConfig`; add `QualityReportResponse`, `FreshnessCandidatesResponse` Pydantic models |
| `backend/main.py` | Wire AQL correction detection and affinity routing in `send_message`; add async quality write post-response; add two new admin endpoints; update `_print_milvus_db_snapshot` |
| `tests/backend/unit/test_memory_service.py` | New AQL unit tests |
| `tests/backend/unit/test_main_runtime.py` | New routing integration tests |
| `tests/backend/integration/test_chat_api.py` | New end-to-end AQL scenario tests |

No existing API contracts, request/response shapes, or routing behaviours are modified.
