# Repeated Tool Execution — User Guide

**Feature:** `mcp_repeated_exec`  
**Version:** 0.7.0-repeated-exec  
**Date:** March 18, 2026  

---

## Overview

The **Repeated Tool Execution** feature lets you ask the MCP client — in plain chat — to run any MCP tool multiple times at a fixed interval, and automatically receive a synthesised cross-run analysis as the final answer.

**Typical use cases:**
- Detecting memory leaks or CPU spin growth over time
- Trending diagnostic metrics (file descriptors, network connections, disk I/O)
- Collecting multi-point samples without sending N separate chat messages

No settings, no toggles — everything is driven through natural language.

---

## Quick Start

Type a message like:

> *"Run `debug_server__proc_cpu_spin_diagnose` 5 times, every 10 seconds, and tell me if CPU spin is getting worse."*

The client handles the rest:
1. Runs the tool 5 times, 10 seconds apart
2. Saves each result to a temporary file
3. Sends all results to the LLM for trend analysis
4. Returns a single synthesised response

---

## How to Phrase Your Request

You do not need to know the internal parameter names. Just describe what you want in natural language. The LLM maps your intent to the three required parameters automatically.

| What you say | What the LLM infers |
|---|---|
| *"5 times"* | `repeat_count: 5` |
| *"every 10 seconds"* | `interval_ms: 10000` |
| *"back-to-back"* / *"no delay"* | `interval_ms: 0` |
| *"run `server__tool_name`"* | `target_tool: "server__tool_name"` |

### Example prompts

**Memory leak detection**
> "Run `debug_server__proc_fd_leak_detect` 6 times every 30 seconds and tell me if file descriptors are growing."

**CPU spin trending**
> "Execute `debug_server__proc_cpu_spin_diagnose` 5 times with a 10-second gap between each run. Summarise whether the CPU spin is consistent or getting worse."

**Quick back-to-back sampling**
> "Run `openwrt__network_status` 3 times immediately one after the other and compare the results."

**With tool arguments**
> "Run `debug_server__proc_mem_growth_check` 4 times every 15 seconds with `pid=1234`. Is memory growing?"

---

## Parameters Reference

| Parameter | Required | Range / Type | Description |
|---|---|---|---|
| `target_tool` | ✅ | string | Namespaced tool ID: `server_alias__tool_name`. Visible in the Tools tab of Settings. |
| `repeat_count` | ✅ | integer, 1–10 | Number of times to execute the tool. Max is **10**. |
| `interval_ms` | ✅ | integer ≥ 0 | Delay between runs in milliseconds. Use `0` for back-to-back. |
| `tool_arguments` | ☐ | object | Arguments passed to the target tool on every run. Defaults to `{}`. |

---

## What Happens During Execution

```
Your message
    │
    ▼
LLM recognises repeated-execution intent
    │
    ▼
Client validates: target_tool exists? repeat_count 1–10? interval_ms ≥ 0?
    │
    ▼
Run 1 ──► result saved to data/runs/ ──► wait interval_ms
Run 2 ──► result saved to data/runs/ ──► wait interval_ms
  ...
Run N ──► result saved to data/runs/
    │
    ▼
All run results assembled into synthesis prompt
    │
    ▼
Temporary run files deleted
    │
    ▼
LLM generates cross-run analysis
    │
    ▼
Single response returned to you
```

> **Note:** Runs are always **sequential**. Run N+1 does not start until Run N finishes (success or failure). The interval timer starts after each run completes, not before.

---

## Timing and Long-Running Requests

Before execution starts, the backend logs an **E2E budget** advisory:

```
Repeated exec E2E budget: 5 runs × (35s tool + 10s interval) + LLM(180s) = 405s total.
Ensure upstream proxy/client timeouts exceed this value.
```

The formula is:

$$totalTime = repeat\_count \times (toolTimeout + interval\_ms) + llmSynthesisTimeout$$

**Practical guidance:**

| `repeat_count` | `interval_ms` | Approx. wait (tool ~10s) |
|---|---|---|
| 3 | 5 000 | ~45 s |
| 5 | 10 000 | ~100 s |
| 5 | 30 000 | ~200 s |
| 10 | 60 000 | ~700 s |

The browser tab must stay open for the full duration. The HTTP request will remain open until the synthesis response is returned.

---

## What the Response Looks Like

After all runs complete, the LLM receives a structured summary of every run and writes a natural-language analysis. A typical response looks like:

> *"Across 5 runs of `proc_cpu_spin_diagnose` at 10-second intervals, CPU spin was consistently detected in thread `worker-3` (PID 4821). Run 3 timed out, so only 4 data points are available. The spin count increased from 14 → 18 → [timeout] → 21 → 24 across the successful runs, indicating a growing CPU spin condition. Recommended action: inspect `worker-3` for unbounded loops or lock contention."*

If you want a raw data dump instead of analysis, say so explicitly:
> "Don't summarise — just show me the raw output from each run."

---

## Handling Failures

Individual run failures do **not** abort the sequence. The client records the failure and moves on to the next run. The LLM receives both successes and failures and incorporates them into the analysis.

| Scenario | What happens |
|---|---|
| One run times out | Recorded as `FAILED`; next run starts after the interval |
| All runs fail | Synthesis sent with all failures; LLM reports the failure pattern |
| Target tool not registered | Error returned immediately; no runs executed — refresh Tools and try again |
| `repeat_count` missing | LLM asks you to re-send with both required values |
| `interval_ms` missing | LLM asks you to re-send with both required values |
| `repeat_count` > 10 | Rejected immediately with a clear error message |

---

## Finding Your Tool Name

The `target_tool` must be the **namespaced** tool ID in `server_alias__tool_name` format.

To find it:
1. Open **Settings** (⚙️ gear icon in the top right)
2. Click the **Tools** tab
3. Each listed tool shows its full namespaced ID

Alternatively, ask the LLM:
> "What tools are available on the debug server?"

The LLM can look up and use the correct namespaced ID on your behalf.

---

## Configuration (Admins)

| Environment Variable | Default | Purpose |
|---|---|---|
| `MCP_DEVICE_ID` | hostname | Prefix for temporary run file names |
| `MCP_REPEATED_EXEC_OUTPUT_DIR` | `data/runs` | Directory where per-run files are temporarily stored |
| `MCP_MAX_TOOL_OUTPUT_CHARS_TO_LLM` | `12000` | Max characters in the synthesis prompt sent to the LLM |
| `MCP_REQUEST_TIMEOUT_MS` | `20000` | Per-run MCP call timeout fallback (when no execution hints) |

Temporary run files are **always deleted** after the synthesis prompt is sent to the LLM. They are never exposed to the browser or user.

---

## Limitations

| Limitation | Detail |
|---|---|
| Maximum repeat count | 10 runs per request |
| Sequential only | Runs cannot execute in parallel |
| No real-time progress | The chat UI shows a spinner; individual run results are not streamed |
| No cancellation | An in-progress sequence cannot be cancelled once started |
| Session lifetime only | No scheduling or cron-style recurrence |
| No file download | Temporary run files are not accessible via the UI |

---

## Troubleshooting

**"Target tool is not registered"**  
→ Open Settings → Tools → click **Refresh Tools**. Then retry your request.

**The response takes a very long time**  
→ Expected for large `repeat_count` × `interval_ms` combinations. See the [Timing section](#timing-and-long-running-requests) above. Do not close the browser tab.

**"repeat_count must be between 1 and 10"**  
→ Reduce your requested run count to 10 or fewer.

**LLM keeps asking for `repeat_count` or `interval_ms`**  
→ Be explicit in your prompt, e.g.: *"…5 times, 10 seconds apart"*. Both values must be specified.

**Only partial results in the synthesis**  
→ One or more runs may have timed out or failed. The LLM will note this in the response. Check backend logs for `Run X/Y failed` warnings.

---

## Complete Worked Example

**User prompt:**
> "Monitor file descriptor growth on PID 8810. Run `debug_server__proc_fd_leak_detect` 5 times, one minute apart. Tell me if there's a leak."

**What the client does:**

| Run | Time | Duration | Status |
|---|---|---|---|
| 1 | 14:00:00Z | 2.1 s | ✅ Success |
| 2 | 14:01:02Z | 2.3 s | ✅ Success |
| 3 | 14:02:04Z | 2.0 s | ✅ Success |
| 4 | 14:03:06Z | 2.2 s | ✅ Success |
| 5 | 14:04:08Z | 2.1 s | ✅ Success |

**LLM synthesis response:**
> *"PID 8810 shows a clear file descriptor leak. Open FDs grew from 142 → 157 → 174 → 191 → 208 across the five 60-second intervals — an increase of approximately 16–17 FDs per minute. At this rate, the process will exhaust the default limit of 1024 FDs in roughly 50 minutes. Recommend inspecting file/socket open calls in the process for missing close() or shutdown() calls."*
