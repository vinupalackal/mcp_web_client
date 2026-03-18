# MCP Client Requirements for `executionHints`
## Advisory Runtime Metadata for Proc Tools in `tools/list`

**Version:** 1.0  
**Date:** March 17, 2026  
**Status:** Implemented on server / Client adoption required  
**Author:** MCP Server Team  
**Primary Audience:** MCP client engineers, SDK maintainers, product owners  
**Related Files:**
- [mcp_debug_server.c](../mcp_debug_server.c)
- [tests/test_mcp_server.cpp](../tests/test_mcp_server.cpp)
- [docs/ARCHITECTURE.md](ARCHITECTURE.md)

---

## 1. Purpose

This document defines the client-side requirements for the newly added advisory `executionHints` object published on proc diagnostic tools in the `tools/list` response.

The purpose of `executionHints` is to help MCP clients:
- choose better request wait budgets,
- present more accurate UX messaging for long-running diagnostics,
- distinguish one-shot tools from sampled tools,
- avoid premature client-side timeouts for proc diagnostics.

`executionHints` is **advisory metadata** only. It does **not** change the callable contract of any tool and it does **not** replace `inputSchema` validation.

---

## 2. Scope

This requirement applies to MCP clients that consume `tools/list` and later invoke proc diagnostics through `tools/call`.

### 2.1 In Scope
- Parsing `executionHints` from `tools/list`
- Using `executionHints` for client timeout/wait behavior
- Using `executionHints` for progress and messaging decisions
- Backward-compatible handling when hints are absent

### 2.2 Out of Scope
- Changing server-side tool execution behavior
- Replacing tool argument validation
- Inferring guaranteed completion time
- Cancellation protocol changes
- Non-proc tools that do not yet publish `executionHints`

---

## 3. Server Contract

### 3.1 Placement in `tools/list`

For supported proc tools, `executionHints` is returned as a top-level sibling field on each tool entry:

```json
{
  "name": "proc_cpu_spin_diagnose",
  "description": "Detect likely CPU spin threads for a process",
  "inputSchema": { "type": "object", "properties": {} },
  "outputSchema": { "type": "object", "properties": {} },
  "executionHints": {
    "defaultTimeoutMs": 30000,
    "maxTimeoutMs": 120000,
    "estimatedRuntimeMs": 11000,
    "clientWaitMarginMs": 5000,
    "mode": "sampling",
    "sampling": {
      "defaultSampleCount": 6,
      "defaultIntervalMs": 2000
    }
  },
  "metadata": {
    "layer": 1,
    "risk": "low",
    "source": "native",
    "handlerType": "native"
  }
}
```

### 3.2 Availability

`executionHints` is currently published only for the following proc-native tools:
- `proc_memory_leak_detect`
- `proc_memory_growth_watch`
- `proc_fd_leak_detect`
- `proc_fd_growth_watch`
- `proc_memory_map_diagnose`
- `proc_thread_hang_diagnose`
- `proc_futex_wait_diagnose`
- `proc_hung_thread_diagnose`
- `proc_cpu_spin_diagnose`
- `proc_memory_pressure_diagnose`

Clients MUST NOT assume that all tools include `executionHints`.

---

## 4. Field Semantics

### 4.1 `defaultTimeoutMs`
- The default server-side timeout budget for the tool when no overriding tool argument is supplied.
- Client use: baseline wait budget and UX messaging.
- Client MUST treat this as advisory, not guaranteed runtime.

### 4.2 `maxTimeoutMs`
- The maximum server-side timeout cap accepted for the tool.
- Client use: upper bound for UI controls or user-entered timeout values.
- Client SHOULD use this to clamp timeout input widgets where the tool exposes a timeout argument.

### 4.3 `estimatedRuntimeMs`
- Approximate expected runtime under default sampling behavior.
- Client use: spinner/progress copy, wait budget planning, long-running classification.
- Client MUST NOT interpret this as a guaranteed completion SLA.

### 4.4 `clientWaitMarginMs`
- Recommended extra client-side wait slack to account for transport, serialization, and server-side scheduling overhead.
- Client SHOULD add this margin when computing its own request timeout.

### 4.5 `mode`
- Enumerated string describing the expected execution pattern.
- Current values:
  - `sampling`: tool collects multiple samples over time
  - `oneShot`: tool executes as a single bounded collection pass
- Client MAY use this to alter UX labels such as “Sampling…” vs “Collecting snapshot…”.

### 4.6 `sampling.defaultSampleCount`
- Default number of samples used by the tool’s default behavior.
- Present for both `sampling` and `oneShot` modes.
- For `oneShot`, current value is `1`.

### 4.7 `sampling.defaultIntervalMs`
- Default delay between samples in milliseconds.
- Present only when the tool has a non-zero default sampling interval.
- Client MUST tolerate the absence of this field.

---

## 5. Client Requirements

### 5.1 Parsing and Compatibility

**CR-EXEC-001**  
Clients MUST parse `executionHints` as an optional object.

**CR-EXEC-002**  
Clients MUST continue functioning correctly when `executionHints` is absent.

**CR-EXEC-003**  
Clients MUST ignore unknown fields inside `executionHints` to preserve forward compatibility.

**CR-EXEC-004**  
Clients MUST NOT reject a tool entry solely because `executionHints` is missing, incomplete, or contains additional fields.

### 5.2 Timeout and Wait Budget Handling

**CR-EXEC-005**  
When `executionHints` is present, clients SHOULD compute a recommended client-side request wait budget using:

$$
recommendedWaitMs = \max(defaultTimeoutMs, estimatedRuntimeMs) + clientWaitMarginMs
$$

**CR-EXEC-006**  
Clients MUST NOT force the actual tool call timeout argument to match `defaultTimeoutMs` unless the client explicitly chooses to set that argument.

**CR-EXEC-007**  
If the client exposes a user-configurable timeout control, it SHOULD clamp or validate the requested value against `maxTimeoutMs` when known.

**CR-EXEC-008**  
Clients SHOULD avoid using a shorter transport/request timeout than `estimatedRuntimeMs + clientWaitMarginMs` for tools with `mode = sampling`.

### 5.3 UI / UX Behavior

**CR-EXEC-009**  
Clients SHOULD use `mode` to distinguish between snapshot-style and sampled diagnostics in user-facing messaging.

**CR-EXEC-010**  
Clients SHOULD present sampled proc diagnostics as potentially long-running when:
- `mode = sampling`, or
- `estimatedRuntimeMs >= 5000`

**CR-EXEC-011**  
Clients MAY show an informational hint such as:
- “This tool samples data for about 11 seconds by default.”
- “Default timeout is 30 seconds; client wait budget should exceed that.”

### 5.4 Invocation Logic

**CR-EXEC-012**  
Clients MUST continue to rely on `inputSchema` for argument correctness.

**CR-EXEC-013**  
Clients MUST treat `executionHints` as non-authoritative advisory metadata and MUST NOT infer support for any argument solely from `executionHints`.

**CR-EXEC-014**  
Clients SHOULD use `inputSchema` and `executionHints` together:
- `inputSchema` for what may be called,
- `executionHints` for how long it may take.

---

## 6. Current Proc Tool Values

The following table reflects the currently implemented server defaults.

| Tool | Mode | Default Timeout (ms) | Max Timeout (ms) | Estimated Runtime (ms) | Wait Margin (ms) | Default Sample Count | Default Interval (ms) |
|------|------|----------------------:|-----------------:|-----------------------:|-----------------:|---------------------:|----------------------:|
| `proc_memory_leak_detect` | `sampling` | 120000 | 600000 | 31000 | 10000 | 2 | 30000 |
| `proc_memory_growth_watch` | `sampling` | 15000 | 120000 | 3000 | 5000 | 3 | 1000 |
| `proc_fd_leak_detect` | `sampling` | 120000 | 600000 | 31000 | 10000 | 2 | 30000 |
| `proc_fd_growth_watch` | `sampling` | 70000 | 180000 | 51000 | 10000 | 6 | 10000 |
| `proc_memory_map_diagnose` | `oneShot` | 30000 | 120000 | 2000 | 5000 | 1 | omitted |
| `proc_thread_hang_diagnose` | `sampling` | 30000 | 120000 | 2000 | 5000 | 2 | 1000 |
| `proc_futex_wait_diagnose` | `sampling` | 30000 | 120000 | 9000 | 5000 | 5 | 2000 |
| `proc_hung_thread_diagnose` | `sampling` | 30000 | 120000 | 11000 | 5000 | 6 | 2000 |
| `proc_cpu_spin_diagnose` | `sampling` | 30000 | 120000 | 11000 | 5000 | 6 | 2000 |
| `proc_memory_pressure_diagnose` | `sampling` | 30000 | 120000 | 6000 | 5000 | 2 | 5000 |

---

## 7. Derivation Rules

The server currently derives the values as follows.

### 7.1 `estimatedRuntimeMs`
For sampled tools:

$$
estimatedRuntimeMs = \min(defaultTimeoutMs, ((defaultSampleCount - 1) \times defaultIntervalMs) + 1000)
$$

For one-shot tools:

$$
estimatedRuntimeMs = 2000
$$

### 7.2 `clientWaitMarginMs`
- `10000` when `defaultTimeoutMs >= 70000`
- otherwise `5000`

Clients SHOULD treat these formulas as descriptive of the current server implementation, not as a contract they must reimplement exactly.

---

## 8. Backward and Forward Compatibility

### 8.1 Backward Compatibility
- Older servers may omit `executionHints` entirely.
- Clients MUST fall back to existing timeout and UX behavior when hints are absent.

### 8.2 Forward Compatibility
- Additional fields may be added to `executionHints` later.
- Additional tool families beyond proc tools may begin publishing `executionHints`.
- Clients MUST preserve tolerant-reader behavior.

---

## 9. Recommended Client Algorithm

```text
1. Call tools/list
2. For each tool:
   - parse inputSchema as usual
   - if executionHints exists:
       - store it as advisory runtime metadata
3. Before tools/call:
   - if executionHints exists:
       - compute recommendedWaitMs
       - set client transport/request timeout >= recommendedWaitMs
       - choose UX copy based on mode
   - else:
       - use client default behavior
4. If user supplies timeout_ms:
   - validate/clamp against maxTimeoutMs when present
5. Execute tool normally
```

---

## 10. Acceptance Criteria for MCP Clients

A client implementation is considered compliant when all of the following are true:

- It successfully parses tool entries with or without `executionHints`.
- It does not break on unknown future `executionHints` fields.
- It uses `executionHints` only as advisory runtime metadata.
- It does not conflate `executionHints` with `inputSchema` validation.
- It can present a longer wait budget for sampled proc tools.
- It correctly handles one-shot tools where `sampling.defaultIntervalMs` is absent.

---

## 11. Example Client Interpretation

For `proc_cpu_spin_diagnose`:
- `defaultTimeoutMs = 30000`
- `estimatedRuntimeMs = 11000`
- `clientWaitMarginMs = 5000`

Recommended client-side wait budget:

$$
\max(30000, 11000) + 5000 = 35000
$$

Recommended UX behavior:
- label as sampled diagnostic,
- warn that collection may take about 11 seconds by default,
- avoid any transport timeout below 35 seconds.

---

## 12. Non-Requirements

The client is **not** required to:
- display all hint fields in the UI,
- expose all timeout controls to end users,
- calculate progress percentage from sampling values,
- guarantee completion within `estimatedRuntimeMs`,
- block invocation when hints are missing.

---

## 13. Implementation Notes

- `executionHints` is intentionally separate from `metadata`.
- `metadata` describes the tool registry entry.
- `executionHints` describes advisory runtime expectations.
- `inputSchema` remains the authoritative source for supported tool arguments.

---

## 14. Summary

Client teams should treat `executionHints` as a new optional runtime-advisory contract on proc tool entries returned by `tools/list`.

The key implementation rule is simple:
- **Use `inputSchema` to know what you may send.**
- **Use `executionHints` to decide how long you should wait.**
