# LLM Prompt Injection Strategy for Accurate Diagnostics

## Overview

This document describes how to structure MCP client queries to an LLM so that
diagnostic outputs are accurate, consistent, and token-efficient. The strategy
applies to both platform profiles (Broadband and Video).

---

## Two-Layer Injection Architecture

Rather than sending the full diagnostic playbook on every call, split prompt
content into two layers:

```
┌─────────────────────────────────────────────────────┐
│  Layer 1 — Static System Prompt (always sent)       │
│  • Platform profile + available tool list           │
│  • Issue classification table                       │
│  • Baseline tools to always run                     │
│  • Mandatory output format                          │
└─────────────────────────────────────────────────────┘
          │
          ▼  LLM classifies the issue
┌─────────────────────────────────────────────────────┐
│  Layer 2 — Dynamic Injection (triggered on demand)  │
│  • Coredump analysis steps  → on Crash              │
│  • Network deep-dive steps  → on Connectivity       │
│  • dmesg pattern list       → when logs returned    │
│  • OTA/firmware steps       → on Upgrade issues     │
└─────────────────────────────────────────────────────┘
```

---

## Layer 1 — Static System Prompt

Send this at the start of every session. Keep it concise.

### 1.1 Platform Identity and Tool Inventory

```
You are a device diagnostics agent connected to a live device via MCP tools.

Platform profile: {{PLATFORM_PROFILE}}   # "Broadband" or "Video"

Available tools:
{{TOOL_LIST}}   # Inject the comma-separated tool names from the loaded config

Do not call any tool that is not in the list above.
If a required tool is not available, say so explicitly instead of guessing.
```

**Why it matters:** Without the tool list, LLMs hallucinate tool names or call
tools that are not registered, causing `tool not found` errors.

### 1.2 Baseline Tools — Always Run First

```
Before any issue-specific investigation, always call these tools first:
1. device_version  (or device_details for Video)
2. device_time_status  (or device_time for Video)
3. process_status
4. system_memory_stats + system_memory_used + system_memory_free  (Broadband)
   OR  device_top  (Video)
5. device_reboot_reason  (Broadband)
   OR  upgrade_firmware_status  (Video)

Capture and include the output of these in every diagnostic summary.
```

**Why it matters:** Skipping baseline collection produces reports with missing
firmware versions or untrusted timestamps, making root cause analysis
unreliable.

### 1.3 Issue Classification — Classify Before Calling Tools

```
Before running any diagnostic tool, classify the issue into one of these types
based on the user's description. State the classification explicitly.

| # | Issue Type           | Keywords                                        |
|---|----------------------|-------------------------------------------------|
| 1 | Crash / Coredump     | process died, segfault, core dump, SIGSEGV      |
| 2 | Hang / Freeze        | unresponsive, stuck, frozen, watchdog           |
| 3 | Memory               | OOM, memory leak, high RSS, swap                |
| 4 | Network / Connectivity | no internet, DNS fail, ping loss, DHCP        |
| 5 | Video / Audio        | no picture, black screen, audio drop, HDMI      |
| 6 | Firmware / OTA       | update failed, firmware mismatch                |
| 7 | Performance / CPU    | slow, high load, CPU spin                       |
| 8 | Service / Process    | service not running, zombie process             |

Output: "Issue classified as: <type>"
```

**Why it matters:** Classification gates which Layer 2 prompt is injected,
preventing unnecessary tool calls and reducing token cost.

### 1.4 Mandatory Output Format

```
Always end your response with a structured summary in this exact format:

## Diagnostic Summary
**Issue Type:** <classified type>
**Device:** <model / firmware version>
**Timestamp of fault:** <from logs or "unknown">

### Root Cause Assessment
<1–3 sentences>

### Evidence
- Log excerpt: <key line(s)>
- Coredump / core_log.txt: <signal, faulting address, top backtrace frame, or "none found">
- Kernel message: <relevant dmesg line, or "none found">

### Impact
<What is broken, what is still working>

### Recommended Actions
1. <Immediate fix or workaround>
2. <Further investigation needed>
3. <Long-term fix>
```

**Why it matters:** Enforces parseable, structured output for automated ticket
creation, dashboards, or downstream processing.

---

## Layer 2 — Dynamic Injections by Issue Type

Inject the relevant block **after** the LLM returns its classification.

### 2.1 Crash / Coredump

```
A crash has been identified. Follow these steps:

1. Call process_core_dump — retrieve coredump listing or metadata.
2. Call process_mini_dump — if full coredump is unavailable.
3. If core_log.txt is present, read it and extract:
   - Faulting process name and PID
   - Signal number (SIGSEGV=11, SIGABRT=6, SIGBUS=7, SIGFPE=8)
   - Faulting PC / RIP / LR address
   - Register dump — check for null pointer (0x00000000) or wild pointer
   - Backtrace — identify the top frame that caused the fault
   - Thread state at time of crash
4. Call process_zombie_state — check for zombie children.
5. Call process_memory_status — check VmRSS, VmPeak, stack size.
6. In logs look for: assert, abort, terminate called, double free, heap corruption.
```

### 2.2 Log and dmesg Triage (inject when log data is returned)

```
Analyse the returned log output for these patterns:

Kernel / dmesg:
  - "segfault at"          → process segfault (note address and process name)
  - "Out of memory"        → OOM killer; note killed process and its RSS
  - "BUG:" / "WARNING:"   → kernel assertion; note file and line
  - "Call Trace:"          → kernel stack trace; extract top 5 frames
  - "watchdog: BUG: soft lockup" → CPU lockup on a core
  - "hung_task"            → blocked task; note task name and pid
  - "RIP:" / "LR:"         → instruction pointer at crash
  - "EXT4-fs error"        → filesystem corruption

Application logs:
  - ERROR / FATAL / ASSERT → note the module and message
  - "core dumped"          → confirm coredump was generated
  - "Restarting"           → service auto-recovered; note how many times

Correlate all findings with the fault timestamp from device_time_status.
```

### 2.3 Network / Connectivity

```
Network issue identified. Run in this order:
1. network_dns_check / wan_dns_check
2. wan_status / wan_ping_test
3. network_routing_table / network_ovs_config
4. network_conntrack_check / network_ddos_check
5. ethernet_link_status / ethernet_driver_stats
6. network_interface_status / network_interface_signal
7. lan_mode / lan_config if LAN-side issue suspected
8. network_blocked_device if a specific client is unreachable
```

### 2.4 Memory / OOM

```
Memory issue identified. Run in this order:
1. system_total_memory / system_memory_used / system_memory_free
2. system_memory_stats
3. process_memory_status
4. In dmesg look for: "oom-kill event", "Killed process", "oom_score"
5. Note which process was killed and its RSS at kill time.
6. Check if the process restarted (process_status).
```

### 2.5 Video / Audio / Display (Video platform only)

```
Video/audio issue identified. Run in this order:
1. audio_status / video_status
2. hdmi_info / hdmi_hdcp_state / hdmi_hex_dump
3. display_read_edid / display_get_height / display_get_width
4. opengl_status
5. For app-specific issues call the relevant ott_* tool
   (ott_netflix, ott_youtube, ott_amazon_prime, etc.)
6. rdkshell_get_clients — check which apps are active
```

### 2.6 Firmware / OTA

```
Firmware/OTA issue identified. Run in this order:
1. upgrade_firmware_status / upgrade_sw_status
2. firmware_download_status / webpacdl_status
3. device_boot_file / device_provision_speed
4. device_reboot_reason — check for unexpected reboot during upgrade
5. In logs look for: "Image verification failed", "flashing error",
   "upgrade aborted", "rollback"
```

### 2.7 Performance / CPU

```
Performance issue identified. Run in this order:
1. device_top / system_cpu_stats
2. system_load_average — note 1 / 5 / 15 min values
3. system_interrupts — look for IRQ imbalance
4. process_status — identify top CPU consumers
5. In dmesg look for: "softirq", "kworker", "ksoftirqd", "rcu_sched"
```

### 2.8 Service / Process Not Running

```
Service/process issue identified. Run in this order:
1. system_service_status for the specific service name
2. process_status — confirm it is absent or in bad state
3. process_zombie_state
4. In logs look for: "Failed to start", "start-limit-hit",
   "core dumped", "exit-code", "timeout"
5. Check if a coredump was generated (process_core_dump)
```

---

## What NOT to Inject

| Content | Reason to exclude |
|---|---|
| Full step-by-step playbook on every call | Too many tokens; inflates cost and latency |
| Specific grep patterns before logs are returned | Premature; inject only after log data arrives |
| Full coredump parsing steps without a crash classification | Noise for non-crash issues |
| Tool descriptions (already in MCP tools/list) | Redundant; MCP protocol delivers these natively |

---

## Implementation Notes

### Injecting the Tool List Dynamically

At session start, call `tools/list` on the MCP server and build the tool
inventory string programmatically:

```python
tool_names = [t["name"] for t in mcp_tools_list_response["tools"]]
tool_inventory = ", ".join(tool_names)
system_prompt = BASE_SYSTEM_PROMPT.replace("{{TOOL_LIST}}", tool_inventory)
system_prompt = system_prompt.replace("{{PLATFORM_PROFILE}}", platform_profile)
```

### Triggering Layer 2

After the LLM returns its classification, parse the `"Issue classified as:"`
line and append the matching Layer 2 block to the conversation before the next
tool-calling turn:

```python
classification = parse_classification(llm_response)
layer2_prompt = LAYER2_PROMPTS.get(classification, "")
if layer2_prompt:
    conversation.append({"role": "user", "content": layer2_prompt})
```

### Token Budget Reference

| Component | Approx. tokens |
|---|---|
| Layer 1 static system prompt | ~400 |
| Tool inventory (83 tools) | ~200 |
| One Layer 2 block | ~150–250 |
| **Total overhead per session** | **~750–850** |

This is well within context limits for all major LLM APIs while delivering
significantly more accurate and structured diagnostic outputs.

---

## Current Code Implementation

The current implementation in the MCP client follows the strategy with a strict
classification-first workflow:

1. The chat handler in `backend/main.py` performs an initial **classification-only**
   LLM call when real MCP tools are available.
2. That first call uses a dedicated prompt from `backend/prompt_injection.py`
   (`build_classification_prompt`) and sends **no tools**, forcing the model to
   return only `Issue classified as: <type>`.
3. The returned classification is parsed with `parse_issue_classification()` and
   converted into a Layer 2 diagnostic branch with
   `build_layer2_injection_prompt()`.
4. The second LLM call receives:
   - the dynamic system prompt from `build_system_prompt()`
   - the assistant classification line
   - the injected Layer 2 branch as an additional user message
   - the live MCP tool catalog for actual tool selection and execution
5. Follow-up turns continue using the structured diagnostic system prompt, and
   log-specific triage guidance is injected automatically when returned tool
   output contains dmesg / OOM / segfault / watchdog-style signals.

Implementation note:

- The client still falls back safely if the classification pass returns an
  unrecognized label.
- Platform profile is inferred dynamically from discovered tools unless
  `MCP_PLATFORM_PROFILE` is explicitly set.
- Tool names are always sourced from the live MCP tool catalog; no static tool
  descriptions are duplicated into the prompt.
