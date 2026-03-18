# MCP Client — Repeated Tool Execution Requirements

**Feature Name:** Repeated Tool Execution (`mcp_repeated_exec`)  
**Version:** 1.0  
**Date:** March 17, 2026  
**Status:** Draft — Pending Implementation  
**Primary Audience:** MCP client engineers, product owners  
**Related Files:**
- [REQUIREMENTS.md](REQUIREMENTS.md)
- [MCP-CLIENT-EXECUTION-HINTS-REQUIREMENTS.md](MCP-CLIENT-EXECUTION-HINTS-REQUIREMENTS.md)
- [EXECUTION_HINTS_IMPLEMENTATION.md](EXECUTION_HINTS_IMPLEMENTATION.md)

---

## 1. Purpose

This document defines the requirements for a **Repeated Tool Execution** capability in the MCP client.

The feature allows users to instruct the client — via natural language chat — to run a specified MCP tool N times at a configurable interval, collect and persist each run's output, and present a synthesised cross-run analysis to the user as the final LLM response.

Primary use cases:
- Longitudinal proc diagnostics (memory leak detection, CPU spin monitoring, FD growth tracking)
- Trend and regression analysis across repeated samples
- Automated multi-point data collection without requiring the user to send N separate chat messages

---

## 2. Scope

### 2.1 In Scope
- A client-side virtual tool `mcp_repeated_exec` registered in the LLM tool catalog
- Mandatory parameter validation with user-facing error messaging
- Sequential repeated execution of any target MCP tool
- Per-run file persistence under a configurable output directory
- Aggregated synthesis prompt sent to the LLM after the final run
- E2E timeout budget computation covering all N runs
- Environment variable configuration for device ID and output directory

### 2.2 Out of Scope
- Parallel / concurrent repeated execution (runs are always sequential)
- Cancellation of an in-progress repeated execution
- UI controls for repeated execution (settings modal, dedicated page)
- Scheduling or cron-style recurring execution (session-lifetime only)
- Server-side changes to any MCP tool
- Changes to `inputSchema` of any target tool

---

## 3. Feature Overview

### 3.1 Virtual Tool Model

`mcp_repeated_exec` is a **client-side synthetic tool**. It is:
- Injected into the LLM's tool catalog alongside real MCP tools
- Never dispatched to an MCP server via JSON-RPC
- Intercepted by the MCP client before MCP dispatch and orchestrated locally

The LLM cannot distinguish it from a real tool. It calls it using the standard tool-call mechanism.

### 3.2 Tool Schema Published to LLM

```json
{
  "type": "function",
  "function": {
    "name": "mcp_repeated_exec",
    "description": "Execute an MCP tool N times at a fixed interval for trend analysis and longitudinal diagnostics. repeat_count and interval_ms are mandatory — the tool will return an error if either is missing. Results are saved to files and all runs are sent to the LLM for final synthesis.",
    "parameters": {
      "type": "object",
      "required": ["target_tool", "repeat_count", "interval_ms"],
      "properties": {
        "target_tool": {
          "type": "string",
          "description": "Namespaced MCP tool ID to repeat (server_alias__tool_name)"
        },
        "tool_arguments": {
          "type": "object",
          "description": "Arguments to pass to the target tool on every run (optional, defaults to {})"
        },
        "repeat_count": {
          "type": "integer",
          "minimum": 1,
          "maximum": 10,
          "description": "Number of times to execute the target tool (1–10)"
        },
        "interval_ms": {
          "type": "integer",
          "minimum": 0,
          "description": "Delay between consecutive runs in milliseconds (0 = back-to-back)"
        }
      }
    }
  }
}
```

---

## 4. Functional Requirements

### 4.1 Parameter Validation

**FR-REP-001**  
The client MUST validate that `repeat_count` is present and an integer in the range [1, 10].

**FR-REP-002**  
The client MUST validate that `interval_ms` is present and a non-negative integer.

**FR-REP-003**  
If either `repeat_count` or `interval_ms` is missing or invalid, the client MUST NOT execute any tool calls. Instead it MUST return a tool result message to the LLM that reads:

> "`mcp_repeated_exec` requires both `repeat_count` (integer 1–10) and `interval_ms` (integer ≥ 0). Please ask the user to re-send the request with both values specified."

The LLM will surface this as a natural-language reply to the user (no special UI required).

**FR-REP-004**  
The client MUST validate that the `target_tool` exists in the current tool registry. If not found, return:

> "Target tool `<target_tool>` is not registered. Please refresh tools and try again."

**FR-REP-005**  
`repeat_count` MUST be capped at 10. Any value above 10 MUST be rejected with:

> "`repeat_count` must be between 1 and 10. Value `<N>` is not allowed."

---

### 4.2 Execution Behaviour

**FR-REP-006**  
Runs MUST be executed sequentially. Run N+1 MUST NOT start until Run N has completed (success or failure).

**FR-REP-007**  
The interval between runs MUST be implemented using a non-blocking async sleep (`asyncio.sleep(interval_ms / 1000)`). The FastAPI event loop MUST NOT be blocked during the interval.

**FR-REP-008**  
Each run MUST call the existing `execute_tool()` method on `MCPManager`, reusing the `executionHints` timeout logic already in place.

**FR-REP-009**  
If an individual run fails (exception or MCP error), the client MUST:
- Record the failure with its error message in the run result
- Continue to the next run (do not abort the entire sequence)
- Include the failure in the final synthesis prompt sent to the LLM

**FR-REP-010**  
The interval delay MUST be applied between runs only, not before Run 1 or after Run N.

---

### 4.3 File Persistence

**FR-REP-011**  
Each run MUST be saved to a separate file immediately after that run completes (success or failure), before the next run begins.

**FR-REP-012**  
The output directory MUST be configurable via the `MCP_REPEATED_EXEC_OUTPUT_DIR` environment variable. Default: `data/runs` relative to the project root.

**FR-REP-013**  
The output directory MUST be created automatically if it does not exist.

**FR-REP-014**  
File names MUST follow this exact format:

```
<device_id>_<tool_name>_<run_index>_<timestamp>.txt
```

Where:
- `device_id` = value of `MCP_DEVICE_ID` env var, falling back to `socket.gethostname()`
- `tool_name` = the bare tool name (without server alias prefix), with spaces replaced by underscores
- `run_index` = zero-padded integer matching `repeat_count` width (e.g. `01`, `02` for repeat_count=10)
- `timestamp` = ISO 8601 compact UTC format: `YYYYMMDDTHHmmssZ`

Example for `repeat_count=5`, run 2, on host `myhost`:
```
myhost_proc_cpu_spin_diagnose_02_20260317T143213Z.txt
```

**FR-REP-015**  
Each output file MUST be a UTF-8 encoded JSON object with the following fields:

```json
{
  "device_id": "myhost",
  "target_tool": "debug_server__proc_cpu_spin_diagnose",
  "tool_name": "proc_cpu_spin_diagnose",
  "tool_arguments": {},
  "run_index": 2,
  "repeat_count": 5,
  "interval_ms": 10000,
  "timestamp_utc": "2026-03-17T14:32:13Z",
  "duration_ms": 11432,
  "success": true,
  "result": { ... },
  "error": null
}
```

**FR-REP-016**  
If a file write fails, the client MUST log a warning and continue. A file write failure MUST NOT abort the run sequence or surface an error to the user.

---

### 4.4 LLM Synthesis

**FR-REP-017**  
Once all N run files have been written and the synthesis prompt has been successfully injected into `messages_for_llm`, the client MUST delete all per-run output files produced by that repeated execution sequence.

**FR-REP-017a — Deletion Scope**  
Only the files created by the current execution sequence (identified by matching `device_id`, `tool_name`, and the run timestamp range) MUST be deleted. Files from prior sequences in the same output directory MUST NOT be affected.

**FR-REP-017b — Deletion Failure Handling**  
If a file cannot be deleted (e.g. permission error), the client MUST log a warning including the file path. A deletion failure MUST NOT prevent the synthesis prompt from being sent to the LLM and MUST NOT surface an error to the user.

**FR-REP-018**  
After all N runs complete, the client MUST construct a synthesis prompt and inject it as the tool result message for `mcp_repeated_exec` in `messages_for_llm`. The LLM receives this in the next turn and generates the final analysis.

**FR-REP-019**  
The synthesis prompt MUST include:
- Target tool name and total run count
- Configured interval
- Note that intermediate files have been deleted after aggregation
- Per-run summary: run index, UTC timestamp, duration, success/failure, result or error
- An explicit instruction to the LLM to analyse trends, anomalies, and changes across runs

**FR-REP-020**  
The synthesis prompt MUST be truncated if its total character length exceeds `MCP_MAX_TOOL_OUTPUT_CHARS_TO_LLM` (default 12000). Individual run results within the prompt MUST be truncated proportionally before the instruction text is truncated.

**FR-REP-021**  
The tool execution trace stored in the session MUST record the full `RepeatedExecSummary` (all runs) as a single trace entry with `tool_name = "mcp_repeated_exec"`.

---

### 4.5 Timeout and Budget

**FR-REP-022**  
Before starting execution, the client MUST compute and log an E2E budget for the full repeated run sequence:

$$totalBudgetMs = repeat\_count \times (recommendedWaitMs_{target} + interval\_ms) + llmTimeoutMs$$

Where `recommendedWaitMs_target` uses `executionHints.recommended_wait_ms()` if available, otherwise falls back to `server.timeout_ms`.

**FR-REP-023**  
The E2E budget log line MUST follow the same format as the existing advisory:

```
Repeated exec E2E budget: 5 runs × (35s tool + 10s interval) + LLM(180s) = 405s total.
Ensure upstream proxy/client timeouts exceed this value.
```

**FR-REP-024**  
The per-run MCP call MUST use the `executionHints`-derived `httpx.Timeout` already computed by `_compute_tool_timeout()` — no new timeout logic needed per run.

---

## 5. Non-Functional Requirements

### 5.1 Performance

**NFR-REP-001**  
The async sleep interval MUST NOT block other FastAPI request handling. Uses `asyncio.sleep`.

**NFR-REP-002**  
File I/O for each run MUST be performed synchronously in the async context (output files are small JSON blobs; async file I/O overhead not justified).

### 5.2 Reliability

**NFR-REP-003**  
Individual run failures MUST NOT abort the sequence. The final synthesis MUST include failed runs with their error details.

**NFR-REP-004**  
All N run files MUST be written before the synthesis prompt is sent to the LLM.

### 5.3 Observability

**NFR-REP-005**  
The internal logger MUST emit at minimum the following events:
- Start of repeated execution (target tool, N, interval)
- Each run start (run index, timestamp)
- Each run completion (run index, duration, success/failure)
- Each file write (path)
- Each file deletion (path, success or warning on failure)
- Synthesis prompt length before and after truncation
- E2E budget advisory

### 5.4 Security

**NFR-REP-006**  
Output files MUST be written only within the configured `MCP_REPEATED_EXEC_OUTPUT_DIR`. Path traversal via `device_id` or `tool_name` MUST be prevented by sanitising those values (strip `/`, `\`, `..`).

**NFR-REP-007**  
`MCP_DEVICE_ID` and `MCP_REPEATED_EXEC_OUTPUT_DIR` MUST NOT be logged at INFO level to avoid unintentional environment disclosure.

---

## 6. Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_DEVICE_ID` | `socket.gethostname()` | Device identifier prefix for output file names |
| `MCP_REPEATED_EXEC_OUTPUT_DIR` | `data/runs` | Directory for per-run output files (relative to project root) |

Existing variables that apply:

| Variable | Applies To |
|----------|------------|
| `MCP_MAX_TOOL_OUTPUT_CHARS_TO_LLM` | Synthesis prompt truncation (FR-REP-019) |
| `MCP_REQUEST_TIMEOUT_MS` | Fallback per-run MCP call timeout |
| `MCP_MAX_TOOL_CALLS_PER_TURN` | `mcp_repeated_exec` counts as **one** tool call against this limit |

---

## 7. Data Models

### 7.1 `RepeatedExecRunResult`
```python
class RepeatedExecRunResult(BaseModel):
    run_index:    int
    timestamp_utc: str          # ISO 8601 compact UTC
    duration_ms:  int
    success:      bool
    result:       Optional[Dict[str, Any]]
    error:        Optional[str]
    file_path:    Optional[str] # None if file write failed
```

### 7.2 `RepeatedExecSummary`
```python
class RepeatedExecSummary(BaseModel):
    device_id:      str
    target_tool:    str          # namespaced
    tool_name:      str          # bare name
    tool_arguments: Dict[str, Any]
    repeat_count:   int
    interval_ms:    int
    output_dir:     str
    runs:           List[RepeatedExecRunResult]
    total_duration_ms: int
    success_count:  int
    failure_count:  int
```

---

## 8. API / Code Contract

### 8.1 No new REST endpoints
`mcp_repeated_exec` is handled entirely within the existing `POST /api/chat` request lifecycle. No new HTTP endpoints are required.

### 8.2 New method: `MCPManager.execute_repeated()`
```python
async def execute_repeated(
    self,
    server: ServerConfig,
    tool_name: str,            # bare, not namespaced
    tool_arguments: Dict[str, Any],
    repeat_count: int,         # validated: 1–10
    interval_ms: int,          # validated: ≥ 0
    execution_hints: Optional[ExecutionHints] = None
) -> RepeatedExecSummary:
    ...
```

### 8.3 Intercept point in `main.py`
```python
# Inside the tool execution loop, before MCP dispatch:
if actual_tool_name == "mcp_repeated_exec":
    # route to execute_repeated()
    # build synthesis prompt as tool result
    # inject into messages_for_llm
```

---

## 9. Acceptance Criteria

A client implementation is compliant when all of the following hold:

| # | Criterion |
|---|-----------|
| AC-01 | LLM can call `mcp_repeated_exec` via normal tool-call mechanism |
| AC-02 | Missing `repeat_count` → user-facing error message returned; no execution |
| AC-03 | Missing `interval_ms` → user-facing error message returned; no execution |
| AC-04 | `repeat_count` > 10 → rejected with clear error |
| AC-05 | Unknown `target_tool` → rejected with clear error |
| AC-06 | N runs execute sequentially with correct interval between them |
| AC-07 | Each run produces a correctly named file in the output directory |
| AC-08 | File contains valid JSON conforming to FR-REP-015 |
| AC-09 | A failed run does not abort the sequence |
| AC-10 | LLM receives synthesis prompt with all run data after run N |
| AC-11 | Synthesis prompt is truncated if > `MCP_MAX_TOOL_OUTPUT_CHARS_TO_LLM` |
| AC-12 | E2E budget advisory is logged before run 1 starts |
| AC-13 | Session trace records `RepeatedExecSummary` as a single trace entry |
| AC-14 | Single-run tool execution path is completely unaffected |
| AC-15 | All N per-run files are deleted after the synthesis prompt is injected into `messages_for_llm` |
| AC-16 | A file deletion failure logs a warning but does not prevent the LLM synthesis turn |

---

## 10. Non-Requirements

The client is **not** required to:
- Display run progress in the chat UI in real time
- Support cancellation of an in-progress sequence
- Run tools in parallel
- Allow `repeat_count` > 10
- Retain intermediate run files after the synthesis prompt is sent (files are deleted per FR-REP-017)
- Expose file download links in the UI

---

## 11. Open Questions

| # | Question | Owner | Resolution |
|---|----------|-------|------------|
| OQ-01 | Should `interval_ms = 0` be allowed (back-to-back runs with no delay)? | Product | Allowed per FR-REP-002 (minimum = 0) |
| OQ-02 | Should the synthesis prompt include the full raw JSON result per run, or a summarised form? | Product | Full result, truncated proportionally if needed (FR-REP-019) |
| OQ-03 | Should `mcp_repeated_exec` appear in the Tools sidebar in the UI? | Product | TBD — no UI changes in v1 scope |
| OQ-04 | Should run output files be accessible via a new REST endpoint? | Engineering | Out of scope for v1 |
