# Split-Phase Pipelined Tool Execution — Requirements

## Overview

Today the split-phase flow collects **all** LLM chunk responses before executing **any**
MCP tool.  This means the wall-clock time paid for the slowest chunk is dead time —
MCP servers sit idle while waiting.

The pipelined variant starts executing MCP tools as soon as the **first** chunk
responds, overlapping LLM wait time with MCP execution time.

---

## Functional Requirements

### FR-SPIPE-001 — Activation condition
The pipelined execution path MUST activate whenever the split-phase pre-collection
step is triggered (`_split_phase_needed == True` and `has_real_tools == True`).
It applies to both `concurrent` and `sequential` split modes.

When split-phase is not needed (tool catalog fits in one request), the pipeline
MUST NOT activate; the existing single-chunk path is unchanged.

---

### FR-SPIPE-002 — Immediate execution on chunk arrival
When a split-phase LLM chunk returns one or more tool calls, the backend MUST
enqueue and **begin executing** those tool calls against MCP servers immediately,
without waiting for remaining chunks to respond.

This means MCP tool execution for chunk 1 may be in-flight while the LLM is still
generating responses for chunks 2 and 3.

---

### FR-SPIPE-003 — Incremental per-chunk deduplication
Before enqueueing tool calls from any arriving chunk, the system MUST check whether
an identical tool call is already present in the execution queue in any of the
following states: **pending**, **executing**, or **completed**.

Deduplication key is `(namespaced_tool_name, normalized_JSON_arguments)` — the same
key used by the existing `executed_tool_results` dict.

Duplicate tool calls MUST be silently skipped at enqueue time.

---

### FR-SPIPE-004 — Result reuse for skipped duplicates
A tool call that was skipped as a duplicate MUST be resolved using the result of
the matching already-queued execution once that execution completes.

The duplicate MUST appear in the final tool-result messages with its own
`tool_call_id` but the same `content` as the original.

---

### FR-SPIPE-005 — Pipeline drain before synthesis
The final LLM synthesis turn (the turn that receives all tool results) MUST NOT
begin until **all** tool executions that have been enqueued by the pipeline are
in a terminal state (completed or failed).

The pipeline drain replaces the current `asyncio.gather` that fires after all
chunks have been collected.

---

### FR-SPIPE-006 — Chunk failure isolation
A chunk that returns an LLM timeout, HTTP error, or an empty tool-call list
contributes zero entries to the queue and MUST NOT block tool calls enqueued
by other chunks from executing.

---

### FR-SPIPE-007 — `mcp_repeated_exec` exclusion
The `mcp_repeated_exec` virtual tool is stateful and must remain sequential.
It MUST be excluded from parallel pipelined execution, exactly as it is
today, and processed inline after the pipeline drains.

---

### FR-SPIPE-008 — Per-tool tracing preserved
Each tool execution in the pipeline MUST emit the same trace events, the same
`tool_executions` list entries, and the same session-manager `add_message` calls
as the existing non-pipelined path.

---

### FR-SPIPE-009 — Tool cache integration preserved
The safe-tool-cache lookup (`lookup_tool_cache`) and store (`record_tool_cache`)
calls on `_memory_service` MUST be retained for every execution through the
pipeline, including pipelined ones.

---

### FR-SPIPE-010 — Sequential split mode degeneracy
When `tools_split_mode = "sequential"`, the pipeline degenerates naturally:

- Chunk 1 responds → enqueue and execute its tools
- Chunk 2 responds → deduplicate against queue, enqueue remainder, execute
- Continue until all sequential chunks are processed
- Drain (all in-flight tools are already serialized in sequential mode)

This is equivalent to the current sequential path plus incremental dedup.

---

### FR-SPIPE-011 — Turn-0 injection unchanged
After the pipeline drains, Turn 0 of the main loop MUST still be driven by a
synthetic LLM response that injects the **ordered, deduplicated** set of executed
tool results — the same shape as the current `split_phase_tool_calls` injection,
but with results already populated.

The main multi-turn loop structure MUST NOT change.

---

## Non-Functional Requirements

### NFR-SPIPE-001 — Latency improvement
The pipeline MUST reduce observable wall-clock time compared to the current
"wait-all-then-execute" approach whenever at least one chunk responds before the
slowest chunk.

Expected saving: approximately `(slowest_chunk_latency - fastest_chunk_latency)` +
`mcp_tool_execution_time_for_earliest_tools`.

---

### NFR-SPIPE-002 — No additional LLM calls
The pipeline MUST NOT trigger any additional LLM requests beyond the existing
split-phase chunk queries.

---

### NFR-SPIPE-003 — Concurrency bound preserved
All pipelined MCP executions are subject to the existing
`MCP_MAX_TOOL_CALLS_PER_TURN` cap.  If the pipeline would exceed it, excess tool
calls MUST be queued and started only after in-flight executions complete.

---

### NFR-SPIPE-004 — Logging
The pipeline MUST log:
- when a tool call is enqueued from a chunk before all other chunks have responded
  (distinguish from the normal post-collection path)
- when a duplicate tool call is skipped at enqueue time (vs. the current skip at
  execution-phase dedup time)
- the queue depth and in-flight count at each enqueue/drain event

---

### NFR-SPIPE-005 — Backward compatibility toggle
The pipelined path MUST be controlled by a feature flag env var
`MCP_SPLIT_PHASE_PIPELINE_ENABLED` (default `false`) so operators can fall back to
the current collect-all-then-execute behaviour without a code change.

---

## Gap Analysis — Current Implementation vs. These Requirements

The table below maps each requirement to the closest existing code and identifies
what must change.

| Req | Closest existing code | Gap / change needed |
|-----|-----------------------|---------------------|
| FR-SPIPE-001 | `if _split_phase_needed and has_real_tools:` block in `send_message` | No code change needed; activation condition is already correct. The pipeline replaces what happens *inside* this block. |
| FR-SPIPE-002 | `split_phase_tool_calls = await _collect_split_phase_tool_calls(...)` — **blocks until all chunks complete** before any tool runs | `_collect_split_phase_tool_calls` must be replaced with a streaming version that yields `(chunk_index, tool_calls)` tuples as each chunk resolves; the caller starts MCP execution immediately on each yield. |
| FR-SPIPE-003 | `_merge_split_phase_tool_calls(chunk_results)` — called **once** on the full list after all chunks | Per-chunk dedup must be applied at each yield boundary using a `seen_dedup_keys: set` maintained across yields. |
| FR-SPIPE-004 | `if dedupe_key in executed_tool_results:` check in Phase 3, reusing `cached_execution["result_content"]` — **works at execution time, not at collection time** | Duplicate detection must be moved earlier (enqueue time). The result-reuse logic itself can remain as-is in Phase 3 because deduped tool calls will have matching `dedupe_key` entries by the time Phase 3 runs. |
| FR-SPIPE-005 | `await asyncio.gather(*[_run_one_mcp_tool(pc) for pc in _parallel_candidates], ...)` runs **after all chunks collected** | The `asyncio.gather` must be replaced with an async execution queue that accumulates tasks as chunks arrive and is awaited (`drained`) before the synthesis turn. |
| FR-SPIPE-006 | `except Exception as err: ... return sp_idx, []` already isolates chunk failures | No change needed; existing error handling is already correct. |
| FR-SPIPE-007 | `mcp_repeated_exec` excluded from `_parallel_candidates` via `if pc["namespaced_tool_name"] != "mcp_repeated_exec"` | No change needed; exclusion already works and remains post-pipeline. |
| FR-SPIPE-008 | `tool_executions.append(...)`, `session_manager.add_message(...)` inside Phase 3 | These must be called from inside `_run_one_mcp_tool` or its wrapper when invoked through the pipeline, not only from Phase 3. Access to `tool_executions` and `session_manager` must be safe for concurrent asyncio calls (already safe since asyncio is single-threaded). |
| FR-SPIPE-009 | `lookup_tool_cache` / `record_tool_cache` inside `_run_one_mcp_tool` | No change needed; `_run_one_mcp_tool` already contains the cache calls and will be reused by the pipeline. |
| FR-SPIPE-010 | Sequential path: `for seq_idx, seq_chunk in enumerate(tool_chunks, 1): chunk_index, chunk_calls = await query_chunk(...)` — no intermediate execution | The sequential path must execute tools after each chunk instead of buffering all chunks first. Incremental dedup set passed across loop iterations satisfies this naturally. |
| FR-SPIPE-011 | `split_phase_tool_calls` injected as synthetic `tool_calls` in Turn 0 | Shape is unchanged, but the list is now populated from the pipeline's deduped call set rather than `_merge_split_phase_tool_calls`. Tool results are already in `messages_for_llm` via Phase 3; the injection only needs the ordered `tool_calls` list. |
| NFR-SPIPE-001 | Not measured today | New log timestamps at enqueue and drain enable operator verification. |
| NFR-SPIPE-002 | Satisfied today | No change; pipeline adds no LLM calls. |
| NFR-SPIPE-003 | `MCP_MAX_TOOL_CALLS_PER_TURN` checked via `max_turns`, not a semaphore | A semaphore (`asyncio.Semaphore(MCP_MAX_TOOL_CALLS_PER_TURN)`) must gate tasks entering the pipeline's `asyncio.gather`. |
| NFR-SPIPE-004 | Logs exist for post-collection execution but not for mid-collection enqueue | New log lines needed at enqueue time and at drain-complete time. |
| NFR-SPIPE-005 | No feature flag today | `MCP_SPLIT_PHASE_PIPELINE_ENABLED` env var must be checked; default `false` falls back to `_collect_split_phase_tool_calls` as today. |

---

## Summary of Code Changes Required

1. **`_collect_split_phase_tool_calls()` → `_stream_split_phase_tool_calls()` (async generator)**
   Convert the function to yield `(chunk_index, new_tool_calls, skipped_count)` as each
   chunk completes.  Dedup set is maintained across yields.  Caller fires
   `_run_one_mcp_tool` immediately for `new_tool_calls`.

2. **New helper: `_run_pipeline_execution()`**
   Accepts the async generator, fires `_run_one_mcp_tool` per yielded tool call
   (bounded by semaphore), collects results in `executed_tool_results`,
   and returns the fully-populated ordered `_parsed_tool_calls` list when done.

3. **`send_message()` — replace the split-phase block**
   When `MCP_SPLIT_PHASE_PIPELINE_ENABLED=true`, call `_run_pipeline_execution()`
   instead of `_collect_split_phase_tool_calls()` + the Phase 2 `asyncio.gather`.
   The Turn-0 injection and Phase 3 ordering loop stay unchanged.

4. **`_merge_split_phase_tool_calls()` — keep as-is**
   Used only on the non-pipeline path (feature flag off).  No change.
