# Split-Phase Pipelined Tool Execution — High-Level Design

**Companion document:** [SPLIT-PHASE-PIPELINE-REQUIREMENTS.md](SPLIT-PHASE-PIPELINE-REQUIREMENTS.md)

---

## 1. Motivation

When the MCP tool catalog is large (e.g. 128 tools × JSON schemas ≈ 47 KB), it
cannot fit in a single LLM request for local models like `llama3.1`.  The backend
already handles this by splitting the catalog into *N* chunks and querying the LLM
once per chunk (the "split-phase").

**Current behaviour — collect all, then execute:**

```
t=0       LLM(chunk1) fired   LLM(chunk2) fired   LLM(chunk3) fired
t=75s     chunk1 responds     ...                 ...
t=180s    chunk2 TIMEOUT      chunk3 responds     ← all collected
t=180s    MCP tool A starts   MCP tool B starts   (asyncio.gather)
t=183s    results ready
t=183s    Final LLM synthesis begins
```

MCP servers sit idle from `t=0` to `t=180s` while the backend waits for every
LLM chunk regardless of whether earlier chunks already revealed the needed tools.

**Target behaviour — pipeline: execute as responses arrive:**

```
t=0       LLM(chunk1) fired   LLM(chunk2) fired   LLM(chunk3) fired
t=75s     chunk1 responds → MCP tool A starts immediately
t=78s     MCP tool A done     ...                 ...
t=180s    chunk2 TIMEOUT      chunk3 responds → tool A already done (duplicate skip)
t=180s    drain: all tools terminal
t=180s    Final LLM synthesis begins  (saving ≈ 105 s in this example)
```

---

## 2. Scope

| In scope | Out of scope |
|---|---|
| Split-phase path only (`_split_phase_needed == True`) | Single-chunk / no-split path (unchanged) |
| Both `concurrent` and `sequential` split modes | Multi-turn agentic loop (unchanged) |
| Normal MCP tool calls | `mcp_repeated_exec` virtual tool (stays sequential, post-drain) |
| Feature-flagged (`MCP_SPLIT_PHASE_PIPELINE_ENABLED`) | Memory/retrieval subsystem |

---

## 3. Current Architecture

```
send_message()
  │
  ├─ get_tools_for_llm_chunks()       → N chunks of tool schemas
  │
  ├─ _collect_split_phase_tool_calls()   ← BARRIER 1: waits for ALL N LLM responses
  │    ├─ query_chunk(1) ─┐
  │    ├─ query_chunk(2) ─┤ asyncio.as_completed  (concurrent)
  │    └─ query_chunk(N) ─┘
  │    └─ _merge_split_phase_tool_calls()  ← dedup once at the end
  │
  ├─ Turn 0: inject merged tool_calls (skip LLM call)
  │
  └─ Phase 2: asyncio.gather(all MCP tools)  ← BARRIER 2: waits for ALL tools
       └─ Phase 3: inject results in order → LLM synthesis
```

**Key barriers:**

- BARRIER 1 — `await _collect_split_phase_tool_calls(...)` does not yield until
  every chunk has either responded or timed out.
- BARRIER 2 — `await asyncio.gather(...)` does not yield until every MCP tool has
  either responded or failed.

Both barriers are synchronous from the perspective of the caller; no MCP work
starts until both are resolved.

---

## 4. Target Architecture

```
send_message()
  │
  ├─ get_tools_for_llm_chunks()       → N chunks
  │
  ├─ [flag on] _run_pipeline_execution()        ← replaces BARRIER 1 + BARRIER 2
  │    │
  │    ├─ _stream_split_phase_tool_calls()  ← async generator
  │    │    ├─ query_chunk(1) ──► yields (1, [tool_A]) immediately
  │    │    │                         └─ enqueue tool_A → MCP execution starts
  │    │    ├─ query_chunk(2) ──► TIMEOUT  yields (2, [])
  │    │    └─ query_chunk(N) ──► yields (N, [tool_A, tool_B])
  │    │                               └─ tool_A duplicate → skip
  │    │                               └─ enqueue tool_B → MCP execution starts
  │    │
  │    └─ drain: await asyncio.gather(running tasks)
  │         all tools terminal → return ordered results
  │
  ├─ Turn 0: inject pre-executed tool_calls (same shape as today)
  │
  └─ Phase 3: inject results in order → LLM synthesis  (unchanged)
```

---

## 5. Component Design

### 5.1 `_stream_split_phase_tool_calls()` — async generator

Replaces `_collect_split_phase_tool_calls()` when the pipeline flag is on.

**Signature:**

```python
async def _stream_split_phase_tool_calls(
    *,
    llm_client: Any,
    messages_snapshot: List[Dict[str, Any]],
    tool_chunks: List[List[Dict[str, Any]]],
    split_mode: str,                    # "sequential" | "concurrent"
    request_mode: str,
    request_mode_details: Dict[str, Any],
    extract_tool_calls_from_content: Callable,
) -> AsyncGenerator[tuple[int, List[Dict[str, Any]], int], None]:
    # yields: (chunk_index, new_tool_calls, skipped_duplicate_count)
```

**Behaviour:**

- Maintains a `seen_dedup_keys: set[tuple[str, str]]` across all yields.
- For each arriving chunk (concurrent: `asyncio.as_completed`; sequential: inline
  `await`), filters out already-seen keys before yielding.
- Yields `(chunk_index, new_calls, skipped_count)` immediately after filtering.
- Does **not** wait for other chunks before yielding.
- Early-stop logic (direct_fact, high confidence) is preserved: cancels remaining
  tasks on the first real tool call, as today.

---

### 5.2 `_run_pipeline_execution()` — async driver

Consumes the generator, fires MCP tasks, drains all results.

**Signature:**

```python
async def _run_pipeline_execution(
    *,
    stream: AsyncGenerator,             # from _stream_split_phase_tool_calls()
    run_one_mcp_tool: Callable,         # _run_one_mcp_tool closure (already exists)
    tool_concurrency: int,              # MCP_MAX_TOOL_CALLS_PER_TURN
    num_chunks: int,
) -> tuple[
    List[Dict[str, Any]],              # ordered _parsed_tool_calls
    Dict[str, Dict[str, Any]],         # parallel_results_map (tool_id → result)
]:
```

**Behaviour:**

1. Create `asyncio.Semaphore(tool_concurrency)` to cap concurrent MCP calls.
2. Iterate the generator:
   - For each `new_calls` batch: create one `asyncio.Task` per call, guarded by the
     semaphore.  Store `task → parsed_call` in a `pending_tasks` dict.
3. After the generator is exhausted (all LLM chunks resolved or timed out), call
   `await asyncio.gather(*pending_tasks, return_exceptions=True)` — the drain.
4. Build and return `_parsed_tool_calls` (ordered) and `parallel_results_map`.

---

### 5.3 `send_message()` — modified split-phase block

```
BEFORE:
    split_phase_tool_calls = await _collect_split_phase_tool_calls(...)

AFTER (flag on):
    stream = _stream_split_phase_tool_calls(...)
    _parsed_tool_calls, _parallel_results_map = await _run_pipeline_execution(
        stream=stream,
        run_one_mcp_tool=_run_one_mcp_tool,
        tool_concurrency=int(os.getenv("MCP_MAX_TOOL_CALLS_PER_TURN", "8")),
        num_chunks=len(tool_chunks),
    )
    split_phase_tool_calls = [
        {"id": pc["tool_id"], "type": "function",
         "function": {"name": pc["namespaced_tool_name"],
                      "arguments": json.dumps(pc["arguments"])}}
        for pc in _parsed_tool_calls
    ]
    # Turn-0 injection unchanged; Phase 2 asyncio.gather skipped (already done)
```

Phase 3 (result ordering and injection into `messages_for_llm`) is **not changed**
because it reads from `_parallel_results_map` and `executed_tool_results` — the
same data structures, just populated earlier.

---

## 6. Deduplication Design

Deduplication happens at **three** points, each serving a different purpose:

| Point | Location | Key | Purpose |
|---|---|---|---|
| A — enqueue-time | `_stream_split_phase_tool_calls` `seen` set | `(name, args_json)` | Prevent two async MCP tasks for the same tool call from different chunks |
| B — task-time | `_run_pipeline_execution` checks `pending_tasks` | `tool_id` | Prevent race if same chunk emits the same call twice |
| C — execution-time | Phase 3 `executed_tool_results` dict | `dedupe_key` json blob | Prevent duplicate injection across multi-turn loop turns (unchanged) |

Point A is the **new** check introduced by this design.
Points B and C are preserved from the current implementation.

---

## 7. Concurrency Model

```
                          asyncio event loop (single thread)
                          ─────────────────────────────────
LLM chunk tasks           [task C1]  [task C2]  [task C3]
                               ↓          ↓          ↓
                            yield      yield      yield
                               ↓
generator consumer        for each yield:
                            create MCP task ──► semaphore.acquire()

MCP tool tasks                [task T_A]             [task T_B]
                                  ↓                      ↓
                               result                  result

drain                       asyncio.gather(T_A, T_B, ...)
                                  ↓
                           Phase 3 ordering
                                  ↓
                           LLM synthesis
```

All tasks are `asyncio.Task` objects on the same event loop.
No threads are introduced.
The semaphore ensures at most `MCP_MAX_TOOL_CALLS_PER_TURN` MCP connections are
open simultaneously across all in-flight pipeline stages.

---

## 8. Sequential Mode Behaviour

When `tools_split_mode = "sequential"`, the generator sends chunks one at a time
and awaits each before proceeding.  The pipeline degenerates to:

```
chunk 1 sent → awaited → yield [tool_A] → MCP task T_A created
chunk 2 sent → awaited → yield []       → nothing (timeout or dupe)
chunk 3 sent → awaited → yield [tool_B] → MCP task T_B created
drain: await T_A, T_B
```

MCP tools from earlier chunks still start before later chunks are sent.
This is a net improvement over the current sequential path which waits for all
three LLM responses before any MCP call.

---

## 9. Feature Flag

| Env var | Default | Effect |
|---|---|---|
| `MCP_SPLIT_PHASE_PIPELINE_ENABLED` | `false` | `false` → existing `_collect_split_phase_tool_calls` path unchanged; `true` → `_stream_split_phase_tool_calls` + `_run_pipeline_execution` |

The flag is read once per `send_message()` invocation.
The non-pipeline path is byte-for-byte identical to today's code.

---

## 10. Logging

| Event | Logger | Message pattern |
|---|---|---|
| Pipeline activated | `internal` | `Split-phase pipeline enabled: chunks=%s concurrency=%s` |
| Tool enqueued from chunk | `external` | `→ PIPELINE ENQUEUE [chunk %s/%s]: %s (dedup_skipped=%s)` |
| Tool task started | `internal` | `Pipeline MCP task started: %s` |
| Duplicate skipped at enqueue | `internal` | `Pipeline dedup skip: %s already queued` |
| Drain begins | `internal` | `Pipeline drain: %s task(s) in-flight` |
| Drain complete | `external` | `← PIPELINE DRAIN COMPLETE: %s succeeded, %s failed, elapsed=%.1fs` |

Existing logs from `_run_one_mcp_tool`, `session_manager.add_tool_trace`, and
Phase 3 injection are **unchanged**.

---

## 11. Error Handling

| Failure mode | Handling |
|---|---|
| LLM chunk timeout | Generator yields `(idx, [], 0)`; pipeline continues with other chunks |
| LLM chunk HTTP error | Same as timeout; logged at ERROR level |
| MCP tool timeout / HTTP error | `_run_one_mcp_tool` returns `success=False, result_content="Error: ..."` — same as today |
| All chunks time out | Pipeline drains an empty task set; Turn-0 falls through to direct synthesis (existing behaviour) |
| Semaphore deadlock | Not possible: semaphore is released in `finally` inside the task wrapper |

---

## 12. Sequence Diagram — Concurrent Mode, 3 Chunks

```
send_message        generator           LLM service         MCP server
     │                  │                    │                   │
     │─── start ────────►│                   │                   │
     │                  │──── chunk1 ────────►│                   │
     │                  │──── chunk2 ────────►│                   │
     │                  │──── chunk3 ────────►│                   │
     │                  │                    │                   │
     │                  │◄── response(c1) ───│  (t+75s)          │
     │                  │── yield([tool_A]) ─►│                   │
     │◄─ yield ─────────│                    │                   │
     │─ create task T_A ─────────────────────────────────────────►│
     │                  │                    │                   │
     │                  │◄── TIMEOUT(c2) ───│  (t+180s)         │
     │                  │── yield([]) ───────►│                   │
     │◄─ yield ─────────│                    │                   │
     │                  │◄── response(c3) ───│  (t+180s)         │
     │                  │── yield([tool_A, tool_B]) ─►           │
     │◄─ yield ─────────│  tool_A dedup skip │                   │
     │─ create task T_B ─────────────────────────────────────────►│
     │                  │                    │                   │
     │◄────────────── T_A result ────────────────────────────────│
     │◄────────────── T_B result ────────────────────────────────│
     │── drain complete │                    │                   │
     │── Phase 3 inject │                    │                   │
     │── LLM synthesis ─────────────────────►│                   │
     │◄─────────────── final response ───────│                   │
```

---

## 13. Files Changed

| File | Change |
|---|---|
| `backend/main.py` | Add `_stream_split_phase_tool_calls()` and `_run_pipeline_execution()`; modify split-phase block in `send_message()` behind flag |
| `tests/backend/unit/test_main_runtime.py` | Unit tests for generator dedup, drain ordering, timeout isolation |
| `tests/backend/integration/test_chat_api.py` | Integration test: verify pipeline produces same final answer as non-pipeline path |

No model changes, no new dependencies, no database changes.
