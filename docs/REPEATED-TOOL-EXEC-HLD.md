# High-Level Design Document
## Repeated Tool Execution (`mcp_repeated_exec`)

**Project**: MCP Client Web  
**Feature**: Repeated Tool Execution  
**Version**: 0.7.0-repeated-exec  
**Date**: March 17, 2026  
**Status**: Design Phase  
**Parent HLD**: [HLD.md](HLD.md) (v0.2.0-jsonrpc)  
**Requirements**: [REPEATED-TOOL-EXEC-REQUIREMENTS.md](REPEATED-TOOL-EXEC-REQUIREMENTS.md)  
**Related**: [MCP-CLIENT-EXECUTION-HINTS-REQUIREMENTS.md](MCP-CLIENT-EXECUTION-HINTS-REQUIREMENTS.md)

---

## 1. Executive Summary

This document describes the high-level design for the **Repeated Tool Execution** feature. It enables users to ask the MCP client — via natural language chat — to execute any registered MCP tool N times at a configurable interval, collect per-run output to disk, and deliver an LLM-synthesised cross-run analysis as the final response.

The key design principles are:

- **Virtual tool, not a mode flag**: `mcp_repeated_exec` is injected into the LLM's tool catalog as a first-class callable tool. No new API endpoints, no session flags, no UI controls required.
- **Additive, non-breaking**: All single-run tool execution paths are completely unaffected. The feature is an interceptor layer in the existing tool dispatch loop.
- **Fail-tolerant**: Individual run failures are recorded and included in the synthesis; they do not abort the sequence.
- **File lifecycle managed**: Per-run output files are written immediately after each run and deleted after the aggregated synthesis prompt is sent to the LLM.
- **Timeout-aware**: Reuses existing `executionHints` timeout logic per run; computes and logs a full E2E budget before starting.

---

## 2. Architecture Overview

### 2.1 Updated Component Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          User's Browser                             │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              Frontend (Vanilla JavaScript)  — UNCHANGED     │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │   │
│  │  │   Chat UI   │  │  Settings    │  │   localStorage   │   │   │
│  │  │  (app.js)   │  │(settings.js) │  │   (Configs)      │   │   │
│  │  └─────────────┘  └──────────────┘  └──────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ HTTP REST
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      FastAPI Backend Server                         │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │          POST /api/sessions/{id}/messages  (main.py)          │ │
│  │                                                               │ │
│  │  ┌────────────────────────────────────────────────────────┐  │ │
│  │  │               Multi-Turn Tool Loop                     │  │ │
│  │  │                                                        │  │ │
│  │  │  LLM Response ──► has tool_calls?                      │  │ │
│  │  │                        │                               │  │ │
│  │  │               ┌────────┴────────┐                      │  │ │
│  │  │               │                 │                      │  │ │
│  │  │    mcp_repeated_exec?       real MCP tool?             │  │ │
│  │  │               │                 │                      │  │ │
│  │  │               ▼                 ▼                      │  │ │
│  │  │  ┌──────────────────┐  ┌──────────────────────┐       │  │ │
│  │  │  │ Repeated Exec    │  │ execute_tool()       │       │  │ │
│  │  │  │ Orchestrator NEW │  │ (existing, unchanged)│       │  │ │
│  │  │  └────────┬─────────┘  └──────────────────────┘       │  │ │
│  │  │           │                                            │  │ │
│  │  │           ▼                                            │  │ │
│  │  │  ┌────────────────────────────────────────────────┐   │  │ │
│  │  │  │  execute_repeated() in MCPManager              │   │  │ │
│  │  │  │  1. Validate params                            │   │  │ │
│  │  │  │  2. Log E2E budget advisory                    │   │  │ │
│  │  │  │  3. Loop N times:                              │   │  │ │
│  │  │  │     a. execute_tool() → result                 │   │  │ │
│  │  │  │     b. Write run file to data/runs/            │   │  │ │
│  │  │  │     c. asyncio.sleep(interval_ms)              │   │  │ │
│  │  │  │  4. Build synthesis prompt                     │   │  │ │
│  │  │  │  5. Delete run files                           │   │  │ │
│  │  │  │  6. Return RepeatedExecSummary                 │   │  │ │
│  │  │  └───────────────────────┬────────────────────────┘   │  │ │
│  │  │                          │ synthesis prompt            │  │ │
│  │  │                          ▼                             │  │ │
│  │  │              Inject into messages_for_llm              │  │ │
│  │  │              → LLM final synthesis turn                │  │ │
│  │  └────────────────────────────────────────────────────────┘  │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌────────────────────┐  ┌──────────────────────────────────────┐  │
│  │   MCPManager       │  │  File System                         │  │
│  │   - execute_tool() │  │  data/runs/  ◄── NEW (temp files)    │  │
│  │   - execute_      ◄├──┤  <device>_<tool>_<run>_<ts>.txt      │  │
│  │     repeated() NEW │  │  (written per run, deleted after     │  │
│  └────────────────────┘  │   synthesis prompt is injected)      │  │
│                           └──────────────────────────────────────┘  │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ JSON-RPC 2.0
                                   ▼
                    ┌──────────────────────────┐
                    │       MCP Server         │
                    │  tools/call (N times)    │
                    └──────────────────────────┘
```

### 2.2 Component Delta from v0.6.0

| Component | Change | Description |
|-----------|--------|-------------|
| `backend/models.py` | Extended | New `RepeatedExecRunResult` and `RepeatedExecSummary` models |
| `backend/mcp_manager.py` | Extended | New `execute_repeated()` method; virtual tool constant |
| `backend/main.py` | Extended | Intercept `mcp_repeated_exec` in tool dispatch loop; build synthesis prompt |
| `backend/static/` | **Unchanged** | No frontend changes required |
| `backend/session_manager.py` | **Unchanged** | Existing `add_tool_trace()` used as-is |
| `backend/llm_client.py` | **Unchanged** | LLM communication unaffected |

---

## 3. Detailed Component Design

### 3.1 Virtual Tool Registration

`mcp_repeated_exec` is a client-side synthetic tool. It is appended to the LLM tool catalog by `MCPManager.get_tools_for_llm()` on every call, alongside real MCP tools. It never appears in `self.tools` (the real tool registry).

```
LLM tool catalog (sent on turn 1):
┌──────────────────────────────────────────────────────────┐
│  debug_server__proc_cpu_spin_diagnose   (real MCP tool)  │
│  debug_server__proc_fd_leak_detect      (real MCP tool)  │
│  ...                                                     │
│  mcp_repeated_exec                 ◄── virtual, injected │
└──────────────────────────────────────────────────────────┘
```

The virtual tool schema is defined as a module-level constant `VIRTUAL_REPEATED_EXEC_TOOL` in `mcp_manager.py`. Required parameters are `target_tool`, `repeat_count`, and `interval_ms`.

### 3.2 Dispatch Intercept in `main.py`

Inside the existing tool execution loop, a guard clause routes `mcp_repeated_exec` before the normal MCP dispatch path:

```
for each tool_call in normalized_tool_calls:
    │
    ├── actual_tool_name == "mcp_repeated_exec" ?
    │       │
    │       YES → validate params
    │             if invalid → inject error string as tool result → continue loop
    │             if valid   → call execute_repeated()
    │                          build synthesis prompt
    │                          inject as tool result → continue to LLM synthesis turn
    │
    └── NO  → existing single-run MCP dispatch path (unchanged)
```

This intercept is a single `if actual_tool_name == "mcp_repeated_exec":` branch before the server lookup. The rest of the tool loop is untouched.

### 3.3 `execute_repeated()` — Execution Flow

```
execute_repeated(server, tool_name, arguments, repeat_count, interval_ms, hints)
│
├── 1. Compute & log E2E budget advisory
│       totalBudgetMs = N × (recommendedWaitMs + interval_ms) + llm_timeout_ms
│
├── 2. For run_index in 1..N:
│       │
│       ├── a. Record start_time, timestamp_utc
│       │
│       ├── b. Call execute_tool(server, tool_name, arguments, hints)
│       │       → success: store result
│       │       → failure: store error, continue (do NOT abort)
│       │
│       ├── c. Write run file:
│       │       path = <output_dir>/<device_id>_<tool_name>_<run_index>_<ts>.txt
│       │       content = RepeatedExecRunResult as JSON
│       │       failure → warn + continue
│       │
│       └── d. asyncio.sleep(interval_ms / 1000)  [skip after last run]
│
├── 3. Build synthesis prompt from all RepeatedExecRunResults
│       (truncate if > MCP_MAX_TOOL_OUTPUT_CHARS_TO_LLM)
│
├── 4. Delete all run files written in step 2c
│       failure per file → warn + continue
│
└── 5. Return RepeatedExecSummary
```

### 3.4 File Lifecycle

```
Run 1 starts
    │
    ▼
data/runs/myhost_proc_cpu_spin_diagnose_01_20260317T143201Z.txt  ← written
    │
asyncio.sleep(interval_ms)
    │
Run 2 starts
    │
    ▼
data/runs/myhost_proc_cpu_spin_diagnose_02_20260317T143213Z.txt  ← written
    │
...
    │
Run N completes
    │
    ▼
Synthesis prompt built from all run results in memory
    │
    ▼
All N files deleted
    │
    ▼
synthesis prompt → messages_for_llm → LLM synthesis turn
```

Files exist only for the duration of the run sequence — from the moment each run completes until the synthesis prompt is injected. They serve as a durable write-ahead buffer: if the process crashes between runs, partial results are on disk and recoverable manually.

### 3.5 Synthesis Prompt Structure

The synthesis prompt is injected as the tool result for `mcp_repeated_exec` in `messages_for_llm`. The LLM receives it in the follow-up turn and generates the final analysis.

```
Repeated execution of `proc_cpu_spin_diagnose` complete.
Runs: 5 | Interval: 10s | Successful: 4 | Failed: 1
Intermediate files written and deleted after aggregation.

--- Run 1 (2026-03-17T14:32:01Z, 11.4s, SUCCESS) ---
{"spinning_threads": [...], "pid": 1234, ...}

--- Run 2 (2026-03-17T14:32:23Z, 11.1s, SUCCESS) ---
{"spinning_threads": [...], ...}

--- Run 3 (2026-03-17T14:32:45Z, 0.1s, FAILED) ---
Error: Timeout executing proc_cpu_spin_diagnose

--- Run 4 (2026-03-17T14:33:07Z, 11.8s, SUCCESS) ---
...

--- Run 5 (2026-03-17T14:33:30Z, 11.2s, SUCCESS) ---
...

Please analyse trends, anomalies, and changes across these 5 runs.
Identify any patterns in CPU spin behaviour, note the failed run, and
provide a diagnostic conclusion.
```

If total length exceeds `MCP_MAX_TOOL_OUTPUT_CHARS_TO_LLM`, individual run result blocks are truncated proportionally. The header, run metadata lines, and instruction paragraph are never truncated.

### 3.6 Parameter Validation & Error Path

Validation occurs **before** any execution. If invalid, the error string is returned as the `mcp_repeated_exec` tool result and the LLM surfaces it naturally to the user:

| Condition | Returned Tool Result (verbatim) |
|-----------|--------------------------------|
| `repeat_count` missing | `` `mcp_repeated_exec` requires both `repeat_count` (integer 1–10) and `interval_ms` (integer ≥ 0). Please ask the user to re-send with both values. `` |
| `interval_ms` missing | (same as above) |
| `repeat_count` > 10 | `` `repeat_count` must be between 1 and 10. Value `<N>` is not allowed. `` |
| `target_tool` not in registry | `` Target tool `<target_tool>` is not registered. Please refresh tools and try again. `` |

No exception is raised — the error becomes a normal tool result message in the conversation.

---

## 4. Data Models

### 4.1 `RepeatedExecRunResult`

Represents a single run within a repeated execution sequence. Written to disk as JSON after each run.

```python
class RepeatedExecRunResult(BaseModel):
    run_index:     int                      # 1-based
    timestamp_utc: str                      # "2026-03-17T14:32:01Z"
    duration_ms:   int
    success:       bool
    result:        Optional[Dict[str, Any]] # None on failure
    error:         Optional[str]            # None on success
    file_path:     Optional[str]            # None if file write failed
```

### 4.2 `RepeatedExecSummary`

Aggregates all runs. Stored as the session trace entry for `mcp_repeated_exec`.

```python
class RepeatedExecSummary(BaseModel):
    device_id:        str
    target_tool:      str                        # namespaced
    tool_name:        str                        # bare name
    tool_arguments:   Dict[str, Any]
    repeat_count:     int
    interval_ms:      int
    output_dir:       str
    runs:             List[RepeatedExecRunResult]
    total_duration_ms: int
    success_count:    int
    failure_count:    int
```

### 4.3 File Schema (each `.txt` file)

```json
{
  "device_id":       "myhost",
  "target_tool":     "debug_server__proc_cpu_spin_diagnose",
  "tool_name":       "proc_cpu_spin_diagnose",
  "tool_arguments":  {},
  "run_index":       2,
  "repeat_count":    5,
  "interval_ms":     10000,
  "timestamp_utc":   "2026-03-17T14:32:13Z",
  "duration_ms":     11432,
  "success":         true,
  "result":          { "...": "..." },
  "error":           null
}
```

---

## 5. Timeout and Budget Design

### 5.1 Per-Run Timeout

Each call to `execute_tool()` uses the existing `_compute_tool_timeout(hints)` logic:

$$readTimeout = \max(globalDefault,\ recommendedWaitMs / 1000)$$

No new timeout mechanism is needed — the same `httpx.Timeout` computed from `executionHints` applies to every repeated run.

### 5.2 E2E Budget Advisory (logged before run 1)

$$totalBudgetMs = N \times (recommendedWaitMs_{target} + interval\_ms) + llmTimeoutMs$$

Where `llmTimeoutMs` covers the LLM synthesis call at the end (the triggering LLM call has already completed before `execute_repeated` is entered).

Example for 5 runs of `proc_cpu_spin_diagnose` (35s budget/run) at 10s interval, LLM 180s:

$$5 \times (35000 + 10000) + 180000 = 225000 + 180000 = 405000\ ms\ (405s)$$

Log line:
```
Repeated exec E2E budget: 5 runs × (35s tool + 10s interval) + LLM(180s) = 405s total.
Ensure upstream proxy/client timeouts exceed this value.
```

---

## 6. Sequence Diagram

```
User            Browser          FastAPI (main.py)       MCPManager          MCP Server       LLM
 │                │                     │                     │                   │             │
 │ "Run cpu_spin  │                     │                     │                   │             │
 │  5× every 10s" │                     │                     │                   │             │
 │────────────────►                     │                     │                   │             │
 │                │ POST /messages      │                     │                   │             │
 │                │────────────────────►│                     │                   │             │
 │                │                     │ chat_completion()   │                   │             │
 │                │                     │─────────────────────────────────────────────────────►│
 │                │                     │◄─────────────────────────────────────────────────────│
 │                │                     │ tool_call:          │                   │             │
 │                │                     │ mcp_repeated_exec(  │                   │             │
 │                │                     │   target=cpu_spin,  │                   │             │
 │                │                     │   repeat_count=5,   │                   │             │
 │                │                     │   interval_ms=10000)│                   │             │
 │                │                     │                     │                   │             │
 │                │                     │ validate params     │                   │             │
 │                │                     │ log E2E budget      │                   │             │
 │                │                     │ execute_repeated()  │                   │             │
 │                │                     │────────────────────►│                   │             │
 │                │                     │                     │ execute_tool() ×1 │             │
 │                │                     │                     │──────────────────►│             │
 │                │                     │                     │◄──────────────────│             │
 │                │                     │                     │ write run file 1  │             │
 │                │                     │                     │ sleep 10s         │             │
 │                │                     │                     │ execute_tool() ×2 │             │
 │                │                     │                     │──────────────────►│             │
 │                │                     │                     │◄──────────────────│             │
 │                │                     │                     │ write run file 2  │             │
 │                │                     │                     │ ... (×3, ×4, ×5)  │             │
 │                │                     │                     │ build synthesis   │             │
 │                │                     │                     │ delete run files  │             │
 │                │                     │◄────────────────────│ RepeatedExecSummary             │
 │                │                     │                     │                   │             │
 │                │                     │ inject synthesis    │                   │             │
 │                │                     │ prompt as tool      │                   │             │
 │                │                     │ result in messages  │                   │             │
 │                │                     │                     │                   │             │
 │                │                     │ chat_completion()   │                   │             │
 │                │                     │ (synthesis turn)    │                   │             │
 │                │                     │─────────────────────────────────────────────────────►│
 │                │                     │◄─────────────────────────────────────────────────────│
 │                │                     │ final analysis text │                   │             │
 │                │◄────────────────────│                     │                   │             │
 │◄───────────────│ 200 OK              │                     │                   │             │
 │ "Across 5 runs │                     │                     │                   │             │
 │  Run 3 timed   │                     │                     │                   │             │
 │  out, runs 1,2,│                     │                     │                   │             │
 │  4,5 show..."  │                     │                     │                   │             │
```

---

## 7. Error Handling Strategy

| Error Scenario | Handling | User Impact |
|----------------|----------|-------------|
| `repeat_count` or `interval_ms` missing | Return error string as tool result | LLM asks user to re-send with required values |
| `target_tool` not in registry | Return error string as tool result | LLM asks user to refresh tools |
| Individual run timeout | Record error in `RepeatedExecRunResult`, continue | Failed run included in synthesis; LLM notes it |
| Individual run MCP error | Record error, continue | Same as timeout |
| File write failure | Log warning, set `file_path=None`, continue | No user impact; synthesis uses in-memory data |
| File delete failure | Log warning per file, continue | No user impact |
| Synthesis prompt truncation | Truncate run result blocks proportionally | LLM receives all run metadata; results may be abbreviated |
| All N runs fail | All recorded as failures; synthesis sent | LLM synthesises failure pattern and reports to user |

---

## 8. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| Path traversal via `device_id` or `tool_name` | Strip `/`, `\`, `..` before composing file name |
| Output directory escape | All writes confined to `MCP_REPEATED_EXEC_OUTPUT_DIR`; no user-controlled path segments |
| Credential exposure in run files | Run files contain only tool results and arguments; no tokens or API keys |
| `MCP_DEVICE_ID` disclosure | Not logged at INFO level |

---

## 9. Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_DEVICE_ID` | `socket.gethostname()` | Device ID prefix for output file names |
| `MCP_REPEATED_EXEC_OUTPUT_DIR` | `data/runs` | Output directory (relative to project root) |
| `MCP_MAX_TOOL_OUTPUT_CHARS_TO_LLM` | `12000` | Synthesis prompt character limit |
| `MCP_REQUEST_TIMEOUT_MS` | `20000` | Fallback per-run MCP timeout when hints absent |

---

## 10. Observability

### 10.1 Log Events (internal logger)

| Event | Level | Example |
|-------|-------|---------|
| Repeated exec start | INFO | `Repeated exec: proc_cpu_spin_diagnose ×5 interval=10s` |
| E2E budget advisory | INFO | `Repeated exec E2E budget: 5 runs × (35s + 10s) + LLM(180s) = 405s total` |
| Param validation failure | WARNING | `mcp_repeated_exec: missing interval_ms — returning error to LLM` |
| Run start | INFO | `Run 1/5: proc_cpu_spin_diagnose started at 2026-03-17T14:32:01Z` |
| Run complete | INFO | `Run 1/5 complete: 11432ms, success=True` |
| Run failure | WARNING | `Run 3/5 failed: Timeout executing proc_cpu_spin_diagnose` |
| File written | INFO | `Run file written: data/runs/myhost_proc_cpu_spin_diagnose_01_...txt` |
| File write failure | WARNING | `Failed to write run file: <path> — <reason>` |
| Synthesis prompt size | INFO | `Synthesis prompt: 8432 chars (limit 12000), no truncation needed` |
| File deleted | INFO | `Run file deleted: data/runs/myhost_proc_cpu_spin_diagnose_01_...txt` |
| File delete failure | WARNING | `Failed to delete run file: <path> — <reason>` |
| Repeated exec complete | INFO | `Repeated exec complete: 5 runs, 4 success, 1 failed, total=225s` |

### 10.2 Session Trace

A single trace entry is added to the session via `session_manager.add_tool_trace()`:
- `tool_name`: `"mcp_repeated_exec"`
- `arguments`: `{ target_tool, repeat_count, interval_ms, tool_arguments }`
- `result`: full `RepeatedExecSummary` dict
- `success`: `True` if at least one run succeeded, `False` if all failed

---

## 11. Acceptance Criteria Summary

| # | Criterion |
|---|-----------|
| AC-01 | LLM can call `mcp_repeated_exec` via normal tool-call mechanism |
| AC-02 | Missing `repeat_count` → user-facing error; no execution |
| AC-03 | Missing `interval_ms` → user-facing error; no execution |
| AC-04 | `repeat_count` > 10 → rejected with clear error |
| AC-05 | Unknown `target_tool` → rejected with clear error |
| AC-06 | N runs execute sequentially with correct interval between them |
| AC-07 | Each run produces a correctly named file in the output directory |
| AC-08 | File contains valid JSON conforming to the per-run schema |
| AC-09 | A failed run does not abort the sequence |
| AC-10 | LLM receives synthesis prompt with all run data after run N |
| AC-11 | Synthesis prompt truncated if > `MCP_MAX_TOOL_OUTPUT_CHARS_TO_LLM` |
| AC-12 | E2E budget advisory logged before run 1 |
| AC-13 | Session trace records `RepeatedExecSummary` as a single entry |
| AC-14 | Single-run tool execution path completely unaffected |
| AC-15 | All N per-run files deleted after synthesis prompt injected |
| AC-16 | File deletion failure logs a warning; LLM synthesis turn unaffected |
