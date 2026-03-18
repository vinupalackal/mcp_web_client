# `executionHints` Client Implementation Summary

**Date:** March 17, 2026  
**Reference Requirements:** [MCP-CLIENT-EXECUTION-HINTS-REQUIREMENTS.md](MCP-CLIENT-EXECUTION-HINTS-REQUIREMENTS.md)  
**Reference Checklist:** [MCP-CLIENT-EXECUTION-HINTS-CHECKLIST.md](MCP-CLIENT-EXECUTION-HINTS-CHECKLIST.md)

---

## Overview

The MCP server now publishes advisory `executionHints` on proc diagnostic tool entries in `tools/list`. This implementation adds full client-side support across three layers: data modelling, MCP transport, and the end-to-end chat turn workflow.

The core rule from the requirements is preserved throughout:
> **Use `inputSchema` to know what to send. Use `executionHints` to decide how long to wait.**

---

## Files Changed

### 1. `backend/models.py`

#### New: `ExecutionHintsSampling`
```python
class ExecutionHintsSampling(BaseModel):
    defaultSampleCount: int
    defaultIntervalMs: Optional[int]   # absent for oneShot tools
    model_config = ConfigDict(extra="ignore")  # forward-compatible
```

#### New: `ExecutionHints`
```python
class ExecutionHints(BaseModel):
    defaultTimeoutMs:    Optional[int]
    maxTimeoutMs:        Optional[int]
    estimatedRuntimeMs:  Optional[int]
    clientWaitMarginMs:  Optional[int]
    mode:                Optional[Literal["sampling", "oneShot"]]
    sampling:            Optional[ExecutionHintsSampling]
    model_config = ConfigDict(extra="ignore")  # forward-compatible
```

Includes `recommended_wait_ms()` helper implementing CR-EXEC-005:

$$recommendedWaitMs = \max(defaultTimeoutMs,\ estimatedRuntimeMs) + clientWaitMarginMs$$

#### Updated: `ToolSchema`
- Added `execution_hints: Optional[ExecutionHints] = None`
- Fully backward-compatible — tools without `executionHints` continue to work unchanged
- OpenAPI example extended with a proc tool showing populated hints

---

### 2. `backend/mcp_manager.py`

#### Updated: `_parse_tools()`
- Reads the raw `executionHints` dict from each tool entry returned by `tools/list`
- Validates it into an `ExecutionHints` model (`model_validate`)
- On parse failure, logs a warning and sets `execution_hints = None` (tolerant-reader, CR-EXEC-003/004)
- Logs `mode`, `estimatedRuntimeMs`, and `recommendedWaitMs` at DEBUG level for each hinted tool

#### New: `_compute_tool_timeout(hints)`
Builds a **per-call** `httpx.Timeout` from hints without mutating the global `self.timeout`:

```
read_s = max(global_default_read_s, recommendedWaitMs / 1000)
```

- Hints can only *extend* patience, never reduce it
- Logs when the timeout is extended and by how much
- Returns `self.timeout` unchanged when hints are absent

#### Updated: `execute_tool()`
- New optional parameter: `execution_hints: Optional[ExecutionHints] = None`
- Uses `_compute_tool_timeout(execution_hints)` for the `httpx.AsyncClient` on this call only
- Logs whether timeout is hints-derived or global default
- Does **not** touch tool argument construction — `inputSchema` contract is unchanged (CR-EXEC-006/013)

---

### 3. `backend/main.py`

#### New: E2E Turn Budget Advisory (before the tool execution loop)

Before executing any tools in a turn, the full worst-case wall-clock budget is computed and logged:

$$totalTurnBudgetMs = 2 \times llmTimeoutMs + \sum_{i=1}^{N} recommendedWaitMs_i$$

Where:
- `2 × llmTimeoutMs` covers the LLM call that produced the tool requests **plus** the follow-up synthesis call
- $recommendedWaitMs_i$ comes from `ExecutionHints.recommended_wait_ms()` for each tool; falls back to `server.timeout_ms` when hints are absent

**Example log output:**
```
E2E turn budget advisory: 2×LLM(180s) + tools[proc_cpu_spin_diagnose(35s), proc_fd_leak_detect(131s)] = 526s.
Ensure upstream proxy/client timeouts exceed this value.
```

This is **advisory only** — it gives operators visibility to size nginx / load-balancer / client-side fetch timeouts correctly.

#### New: Per-Tool UX Trace (before each `execute_tool` call)

Resolves `execution_hints` from `mcp_manager.tools` by namespaced ID, then emits a trace based on CR-EXEC-009/010:

| Condition | Log message |
|-----------|-------------|
| `mode == "sampling"` or `estimatedRuntimeMs ≥ 5000` | *"Long-running diagnostic tool … This diagnostic samples data over time — client timeout extended accordingly."* |
| `oneShot` (fast) | *"One-shot diagnostic tool … Collecting snapshot."* |

#### Updated: `execute_tool` call site
- Looks up stored `ToolSchema` from `mcp_manager.tools.get(namespaced_tool_name)`
- Passes `execution_hints` to `mcp_manager.execute_tool()`

---

## Timeout Responsibility Boundaries

| Layer | Timeout Mechanism | Source |
|-------|-------------------|--------|
| MCP `execute_tool` HTTP call | `httpx.Timeout(read=recommendedWaitMs/1000)` | `ExecutionHints.recommended_wait_ms()` |
| LLM API calls | `llm_client.timeout` (unchanged) | `llm_config.llm_timeout_ms` |
| FastAPI endpoint | No explicit limit (async awaits) | — |
| **Upstream (nginx / proxy / client)** | Must be ≥ `totalTurnBudgetMs` | **Advisory log** |

---

## Backward & Forward Compatibility

| Scenario | Behaviour |
|----------|-----------|
| Tool entry has no `executionHints` | `execution_hints = None`; global timeout used; no UX trace change |
| Tool entry has unknown extra fields in `executionHints` | Silently ignored (`extra="ignore"`) |
| `oneShot` tool omits `sampling.defaultIntervalMs` | Field is `Optional`, no error |
| Server predates `executionHints` entirely | Full existing behaviour preserved |

---

## Requirements Coverage

| Requirement | Status |
|-------------|--------|
| CR-EXEC-001 Parse `executionHints` as optional object | ✅ |
| CR-EXEC-002 Client works without `executionHints` | ✅ |
| CR-EXEC-003 Unknown fields ignored | ✅ (`extra="ignore"`) |
| CR-EXEC-004 Missing/incomplete hints don't reject tool | ✅ |
| CR-EXEC-005 Compute `recommendedWaitMs` formula | ✅ (`recommended_wait_ms()`) |
| CR-EXEC-006 Don't force tool `timeout_ms` arg from hints | ✅ |
| CR-EXEC-007 Clamp user timeout against `maxTimeoutMs` | ⬜ Not yet (no UI timeout widget in scope) |
| CR-EXEC-008 Transport timeout ≥ `estimatedRuntimeMs + clientWaitMarginMs` for `sampling` | ✅ (`_compute_tool_timeout`) |
| CR-EXEC-009 Use `mode` for UX messaging | ✅ |
| CR-EXEC-010 Present `sampling` / `estimatedRuntimeMs ≥ 5000` as long-running | ✅ |
| CR-EXEC-011 Show informational hint copy | ✅ (trace log) |
| CR-EXEC-012 `inputSchema` remains authoritative for arguments | ✅ (unchanged) |
| CR-EXEC-013 `executionHints` is non-authoritative advisory only | ✅ |
| CR-EXEC-014 Use both `inputSchema` and `executionHints` together | ✅ |

> **Note on CR-EXEC-007:** `maxTimeoutMs` is stored on `ExecutionHints` and available for use. A UI timeout clamping control is out of scope for this iteration as the client has no user-configurable per-tool timeout widget today.

---

## Test Results

All pre-existing tests pass without modification:

```
tests/backend/unit/test_mcp_manager.py   ✅  24 passed
tests/backend/unit/test_models.py        ✅  50 passed
─────────────────────────────────────────────────────
74 passed in 0.18s
```
