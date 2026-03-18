# MCP Client Integration Checklist for `executionHints`

**Purpose:** Quick implementation checklist for MCP clients adopting advisory proc-tool `executionHints` from `tools/list`.  
**Reference:** [MCP-CLIENT-EXECUTION-HINTS-REQUIREMENTS.md](MCP-CLIENT-EXECUTION-HINTS-REQUIREMENTS.md)

---

## 1. Parsing

- [ ] Parse `executionHints` as an optional top-level field on each tool entry from `tools/list`.
- [ ] Keep client behavior unchanged when `executionHints` is absent.
- [ ] Ignore unknown future fields inside `executionHints`.
- [ ] Do not treat `executionHints` as part of `inputSchema`.

---

## 2. Timeout Handling

- [ ] Read `defaultTimeoutMs` when present.
- [ ] Read `maxTimeoutMs` when present.
- [ ] Read `estimatedRuntimeMs` when present.
- [ ] Read `clientWaitMarginMs` when present.
- [ ] Compute a recommended client wait budget using:

$$
recommendedWaitMs = \max(defaultTimeoutMs, estimatedRuntimeMs) + clientWaitMarginMs
$$

- [ ] Ensure client transport/request timeout is not shorter than the recommended wait budget for proc tools.
- [ ] If the UI allows user timeout input, clamp or validate against `maxTimeoutMs` when available.
- [ ] Do not automatically override the tool’s `timeout_ms` argument unless the client intentionally sets it.

---

## 3. UX Behavior

- [ ] Use `mode` to distinguish `sampling` vs `oneShot` tools.
- [ ] Show longer-running messaging for `sampling` tools.
- [ ] Use `sampling.defaultSampleCount` and `sampling.defaultIntervalMs` for informational copy only.
- [ ] Tolerate missing `sampling.defaultIntervalMs` for one-shot tools.
- [ ] Avoid presenting `estimatedRuntimeMs` as a guaranteed completion time.

Suggested copy examples:
- [ ] “This diagnostic samples data over time.”
- [ ] “Expected runtime is about 11 seconds under default settings.”
- [ ] “Client timeout budget increased for sampled proc tool.”

---

## 4. Invocation Logic

- [ ] Continue using `inputSchema` as the only authoritative contract for allowed arguments.
- [ ] Use `executionHints` only for wait-budget and UX decisions.
- [ ] Do not infer support for a timeout argument solely because `executionHints` contains timeout values.
- [ ] Continue to support older servers that publish no `executionHints`.

---

## 5. Proc Tools Currently Publishing `executionHints`

- [ ] `proc_memory_leak_detect`
- [ ] `proc_memory_growth_watch`
- [ ] `proc_fd_leak_detect`
- [ ] `proc_fd_growth_watch`
- [ ] `proc_memory_map_diagnose`
- [ ] `proc_thread_hang_diagnose`
- [ ] `proc_futex_wait_diagnose`
- [ ] `proc_hung_thread_diagnose`
- [ ] `proc_cpu_spin_diagnose`
- [ ] `proc_memory_pressure_diagnose`

---

## 6. Minimum Acceptance Checks

- [ ] Client works with tool entries that include `executionHints`.
- [ ] Client works with tool entries that do not include `executionHints`.
- [ ] Sampled proc tools are not cut off by premature client-side timeouts.
- [ ] One-shot proc tools still work when `sampling.defaultIntervalMs` is absent.
- [ ] Unknown future `executionHints` fields do not break parsing.

---

## 7. Recommended Rollout Order

- [ ] Add parsing support first.
- [ ] Add timeout-budget logic second.
- [ ] Add UX/progress messaging third.
- [ ] Validate against at least one `sampling` tool and one `oneShot` tool.

Recommended smoke-test tools:
- [ ] `proc_cpu_spin_diagnose` (`sampling`)
- [ ] `proc_memory_map_diagnose` (`oneShot`)

---

## 8. One-Line Rule

- [ ] Use `inputSchema` to know what to send.
- [ ] Use `executionHints` to decide how long to wait.
