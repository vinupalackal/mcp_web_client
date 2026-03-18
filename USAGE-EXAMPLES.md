# MCP Debug Server — Complete Usage Examples

> Complete prompt-to-output examples for **all tools** — 26 native tools and all JSON registry tools.
> Native tools return structured JSON; JSON registry tools return raw text (stdout).
>
> Each entry contains:
> - **User prompt** to the LLM
> - **MCP tool call** the LLM sends
> - **Server response** (JSON or raw text)
> - **LLM narrative** interpretation

---

## Table of Contents

- [Part A — Native Tool Examples](#part-a--native-tool-examples)
- [Part B — JSON Registry Tool Examples](#part-b--json-registry-tool-examples)
  - [B1 — System Information](#b1--system-information)
  - [B2 — Process & Storage](#b2--process--storage)
  - [B3 — Network — Generic Linux](#b3--network--generic-linux)
  - [B4 — Network — OpenWrt Gateway](#b4--network--openwrt-gateway)
  - [B5 — Log Analysis](#b5--log-analysis)
  - [B6 — Service Management](#b6--service-management)
  - [B7 — Containers & Hardware](#b7--containers--hardware)

---

# Part A — Native Tool Examples

---

## A-1 · `server_info`

**User prompt**
> "What version is the MCP server and what capabilities does it support?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "server_info", "arguments": {} } }
```

**Server response**
```json
{
  "summary": "MCP debug server v1.3.0 on stdio transport. Capabilities: tools, resources.",
  "metrics": { "version": "1.3.0", "transport": "stdio", "capabilities": ["tools","resources"] },
  "key_findings": ["Server is running and reachable."],
  "evidence": [],
  "next_suggestions": ["Run get_uptime for device uptime."]
}
```

**LLM response**
> The MCP server is at version **1.3.0**, using **stdio** transport, and exposes `tools` and `resources` capabilities. The connection is healthy.

---

## A-2 · `get_uptime`

**User prompt**
> "How long has this device been running without a reboot?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_uptime", "arguments": {} } }
```

**Server response**
```json
{
  "summary": "Device uptime: 6 days 14 hours 33 minutes.",
  "metrics": { "uptime_seconds": 572380, "uptime_human": "6d 14h 33m", "idle_seconds_total": 2189421 },
  "key_findings": ["No recent reboot detected."],
  "evidence": ["/proc/uptime: 572380.14 2189421.60"],
  "next_suggestions": ["Run get_loadavg to verify CPU is not under stress."]
}
```

**LLM response**
> The device has been up for **6 days, 14 hours, 33 minutes** with no reboot. Idle time across CPUs is 2.18M seconds, indicating the CPUs are largely inactive.

---

## A-3 · `get_loadavg`

**User prompt**
> "Is the CPU under stress right now?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_loadavg", "arguments": {} } }
```

**Server response**
```json
{
  "summary": "Load averages: 0.45 / 0.38 / 0.29 — nominal.",
  "metrics": { "load_1m": 0.45, "load_5m": 0.38, "load_15m": 0.29, "running_tasks": 1, "total_tasks": 176 },
  "key_findings": ["Load is well below CPU count — no CPU pressure."],
  "evidence": ["/proc/loadavg: 0.45 0.38 0.29 1/176 2184"],
  "next_suggestions": []
}
```

**LLM response**
> CPU load is nominal: **0.45 / 0.38 / 0.29** (1m/5m/15m). With only 1 running task out of 176, the system is lightly loaded.

---

## A-4 · `get_meminfo`

**User prompt**
> "How much free memory does the device have?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_meminfo", "arguments": {} } }
```

**Server response**
```json
{
  "summary": "MemAvailable: 287 MB of 512 MB — 56% usable.",
  "metrics": { "MemTotal_kB": 524288, "MemFree_kB": 143360, "MemAvailable_kB": 294912, "Buffers_kB": 8192, "Cached_kB": 98304, "SwapTotal_kB": 0, "SwapFree_kB": 0 },
  "key_findings": ["No swap configured.", "Cached memory (96 MB) is reclaimable."],
  "evidence": ["/proc/meminfo snapshot"],
  "next_suggestions": ["Run proc_memory_pressure_diagnose for detailed pressure analysis."]
}
```

**LLM response**
> The device has **287 MB available** out of 512 MB (56% usable). No swap is configured — if memory is exhausted, the OOM killer activates immediately without any swap buffer.

---

## A-5 · `get_dmesg_tail`

**User prompt**
> "Show me the last 100 kernel log lines to check for errors."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_dmesg_tail", "arguments": { "lines": 100 } } }
```

**Server response**
```json
{
  "summary": "100 kernel ring buffer lines returned. 0 error events found.",
  "metrics": { "lines_returned": 100 },
  "key_findings": ["No OOM events, hardware errors, or panics in last 100 lines."],
  "evidence": ["[571200.001] eth0: renamed from veth3c8f2a1"],
  "next_suggestions": []
}
```

**LLM response**
> The last 100 kernel log lines are clean — no OOM kills, hardware errors, or panics. The only notable event is a veth rename (normal for container networking).

---

## A-6 · `list_top_processes`

**User prompt**
> "Which process is consuming the most memory?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "list_top_processes", "arguments": { "sort": "rss", "limit": 10 } } }
```

**Server response**
```json
{
  "summary": "Top 10 processes by RSS. Highest: rdkbrowserng (PID 2201) at 182 MB.",
  "metrics": { "top_count": 10, "sort": "rss" },
  "key_findings": ["rdkbrowserng holds 182 MB — 36% of total RAM."],
  "evidence": ["PID 2201 rdkbrowserng: RSS=186368 kB VSZ=1048576 kB CPU=2.1%"],
  "next_suggestions": ["Run proc_memory_leak_detect on PID 2201 to check for growth."]
}
```

**LLM response**
> `rdkbrowserng` (PID 2201) is the top memory consumer at **182 MB RSS** (36% of total RAM). It's worth monitoring for growth — consider running a memory leak check on it.

---

## A-7 · `get_network_overview`

**User prompt**
> "What network interfaces are active and what's the default gateway?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_network_overview", "arguments": {} } }
```

**Server response**
```json
{
  "summary": "3 interfaces UP. Default gateway: 192.168.1.1 via eth0.",
  "metrics": { "interfaces_up": 3, "default_gateway": "192.168.1.1" },
  "key_findings": ["eth0: 192.168.1.105/24 UP", "wlan0: 10.0.0.2/24 UP", "lo: 127.0.0.1/8 UP"],
  "evidence": ["ip addr: eth0 UP", "ip route: default via 192.168.1.1 dev eth0"],
  "next_suggestions": []
}
```

**LLM response**
> Three interfaces are active: `eth0` (192.168.1.105/24), `wlan0` (10.0.0.2/24), and `lo`. Default gateway is **192.168.1.1** via eth0.

---

## A-8 · `get_registry_summary`

**User prompt**
> "How many tools are available and from which registries?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_registry_summary", "arguments": {} } }
```

**Server response**
```json
{
  "summary": "4 registries, 91 tools total.",
  "metrics": { "total_registries": 4, "total_tools": 91 },
  "key_findings": ["native: 26 tools (LAYER1)", "tools_registry: 13 tools", "openwrt_tools_config: 23 tools", "mcp_tools_config: 6 tools"],
  "evidence": [],
  "next_suggestions": ["Run list_registries to see all registry configs."]
}
```

**LLM response**
> There are **91 tools** across 4 registries: 26 native (`/proc`-based), 13 from `tools_registry.json`, 23 OpenWrt-specific, and 6 systemd service management tools.

---

## A-9 · `list_registries`

**User prompt**
> "What JSON config files are loaded as tool registries?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "list_registries", "arguments": {} } }
```

**Server response**
```json
{
  "summary": "4 active registries.",
  "metrics": { "count": 4 },
  "key_findings": ["native (built-in, enabled)", "tools_registry.json (JSON, enabled)", "openwrt_tools_config.json (JSON, enabled)", "mcp_tools_config.json (JSON, enabled)"],
  "evidence": [],
  "next_suggestions": ["Run get_registry_info with a registry name for full tool listing."]
}
```

**LLM response**
> Four registries are loaded: the built-in native registry plus three JSON-file registries (`tools_registry.json`, `openwrt_tools_config.json`, `mcp_tools_config.json`).

---

## A-10 · `get_registry_info`

**User prompt**
> "What tools are available in the openwrt_tools_config registry?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_registry_info", "arguments": { "registry_name": "openwrt_tools_config" } } }
```

**Server response**
```json
{
  "summary": "Registry 'openwrt_tools_config': 23 tools.",
  "metrics": { "tool_count": 23 },
  "key_findings": ["get_wan_ip_config", "get_dhcp_leases", "get_firewall_rules", "get_wireless_status", "... (20 more)"],
  "evidence": [],
  "next_suggestions": []
}
```

**LLM response**
> The `openwrt_tools_config` registry contains **23 tools** focused on OpenWrt gateway management — WAN/LAN config, DHCP, DNS, firewall, wireless, and NAT.

---

## A-11 · `listLogFiles`

**User prompt**
> "What log files exist under /var/log?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "listLogFiles", "arguments": { "basePaths": ["/var/log"] } } }
```

**Server response**
```json
{
  "summary": "Found 14 log files under /var/log, sorted newest-first.",
  "metrics": { "file_count": 14 },
  "key_findings": ["/var/log/messages (4.2 MB, 2m ago)", "/var/log/wifi.log (1.1 MB, 5m ago)", "/var/log/crash.log (12 KB, 1h ago)"],
  "evidence": [],
  "next_suggestions": ["Run readLogTail on /var/log/crash.log for crash details."]
}
```

**LLM response**
> Found 14 log files. The most recently updated are `/var/log/messages` (4.2 MB, 2 minutes ago) and `/var/log/wifi.log`. There is also a `crash.log` last written 1 hour ago — worth inspecting.

---

## A-12 · `readLogTail`

**User prompt**
> "Show me the last 50 lines of /var/log/messages filtered for 'error'."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "readLogTail", "arguments": { "file": "/var/log/messages", "limit": 50, "query": "error", "ignoreCase": true } } }
```

**Server response**
```json
{
  "summary": "3 matching lines returned from /var/log/messages (query: 'error').",
  "metrics": { "lines_returned": 3, "lines_scanned": 50 },
  "key_findings": ["Mar 14 09:12:01 kernel: usb 1-1: error -71 while reading from device"],
  "evidence": ["Mar 14 09:12:01 kernel: usb 1-1: error -71", "Mar 14 09:15:44 wpa_supplicant[1842]: error: deauth reason 15"],
  "next_suggestions": []
}
```

**LLM response**
> Found **3 error lines** in the last 50 of `/var/log/messages`. Notable: a USB error `-71` (device disconnect/timeout) at 09:12 and a WiFi deauth reason 15 (4-way handshake timeout) at 09:15.

---

## A-13 · `searchLogs`

**User prompt**
> "Search all logs for 'OOM' or 'out of memory'."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "searchLogs", "arguments": { "query": "out of memory", "limit": 30 } } }
```

**Server response**
```json
{
  "summary": "Found 5 matches for 'out of memory' across 2 files.",
  "metrics": { "total_matches": 5, "files_matched": 2 },
  "key_findings": ["3 matches in /var/log/messages", "2 matches in /var/log/kern.log"],
  "evidence": ["Mar 14 08:44:11 kernel: Out of memory: Kill process 2881 (rdkbrowserng) score 856 or sacrifice child"],
  "next_suggestions": ["Run proc_memory_pressure_diagnose to assess current memory state."]
}
```

**LLM response**
> Found **5 OOM events** across 2 log files. The kernel OOM-killed `rdkbrowserng` (PID 2881) with score 856 at 08:44. This is a recurring memory pressure problem — run `proc_memory_pressure_diagnose` immediately.

---

## A-14 · `readLogRange`

**User prompt**
> "Show me /var/log/messages between 08:40 and 08:50 this morning."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "readLogRange", "arguments": { "file": "/var/log/messages", "timeFrom": "Mar 14 08:40", "timeTo": "Mar 14 08:50" } } }
```

**Server response**
```json
{
  "summary": "34 lines returned from /var/log/messages in time window.",
  "metrics": { "lines_returned": 34 },
  "evidence": ["Mar 14 08:44:11 kernel: Out of memory: Kill process 2881", "Mar 14 08:44:12 kernel: oom_reaper: reaped process 2881"],
  "next_suggestions": []
}
```

**LLM response**
> The 08:40–08:50 window shows **34 log lines** including the OOM kill sequence at 08:44:11–12. The kernel selected and reaped `rdkbrowserng` (PID 2881) within 1 second.

---

## A-15 · `sampleLogMetadata`

**User prompt**
> "What's the time range and size of /var/log/messages?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "sampleLogMetadata", "arguments": { "file": "/var/log/messages" } } }
```

**Server response**
```json
{
  "summary": "File: /var/log/messages — 4.2 MB, ~42000 lines, syslog format.",
  "metrics": { "size_bytes": 4404224, "estimated_lines": 42000, "format": "syslog" },
  "key_findings": ["First timestamp: Mar 7 14:22:03", "Last timestamp: Mar 14 09:31:55"],
  "evidence": [],
  "next_suggestions": []
}
```

**LLM response**
> `/var/log/messages` is **4.2 MB** (~42,000 lines), covering **7 days** from Mar 7 to Mar 14 in standard syslog format.

---

## A-16 · `tr181_get_parameters`

**User prompt**
> "What WiFi channel is Radio 1 on and what's the firmware version?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "tr181_get_parameters", "arguments": { "parameters": ["Device.WiFi.Radio.1.Channel", "Device.DeviceInfo.SoftwareVersion"] } } }
```

**Server response**
```json
{
  "summary": "2 TR-181 parameters retrieved.",
  "metrics": { "parameters_returned": 2, "parameters_failed": 0 },
  "evidence": ["Device.WiFi.Radio.1.Channel = 36", "Device.DeviceInfo.SoftwareVersion = 5.4.1-RDK-V20240110"],
  "next_suggestions": []
}
```

**LLM response**
> Radio 1 is on **channel 36** (5 GHz). Firmware is `5.4.1-RDK-V20240110` (RDK-V build from January 10, 2024).

---

## A-17 · `proc_memory_leak_detect`

**User prompt**
> "Check if wpa_supplicant is leaking memory."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "proc_memory_leak_detect", "arguments": { "process_name": "wpa_supplicant", "interval_seconds": 30, "sample_count": 3 } } }
```

**Server response**
```json
{
  "summary": "MEDIUM confidence memory leak in wpa_supplicant (PID 1842). +1840 kB over 60s.",
  "metrics": { "pid": 1842, "leak_score": "MEDIUM", "rss_delta_total_kB": 1840 },
  "evidence": ["t=0s: VmRSS=18432 kB", "t=30s: 19312 kB (+880)", "t=60s: 20272 kB (+960)"],
  "next_suggestions": ["Run proc_memory_map_diagnose on PID 1842."]
}
```

**LLM response**
> `wpa_supplicant` grew **+1840 kB in 60 seconds** (monotonically) — MEDIUM confidence leak at ~30 KB/min. Recommend mapping its heap with `proc_memory_map_diagnose`.

---

## A-18 · `proc_memory_growth_watch`

**User prompt**
> "Watch PID 2201 memory for 10 seconds with rapid samples."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "proc_memory_growth_watch", "arguments": { "pid": 2201, "sample_count": 5, "sample_interval_ms": 500, "top_regions": 3 } } }
```

**Server response**
```json
{
  "summary": "rdkbrowserng (PID 2201): RSS +12 MB over 2s. Growth rate: 6 MB/s.",
  "metrics": { "rss_start_kB": 186368, "rss_end_kB": 198656, "delta_kB": 12288, "rate_kb_per_sec": 6144 },
  "key_findings": ["[heap] grew +9.8 MB", "anon mapping 0x7f40000 grew +2.4 MB"],
  "next_suggestions": ["Spike rate 6 MB/s is very high — investigate immediately."]
}
```

**LLM response**
> `rdkbrowserng` is growing at **6 MB/second** — extremely aggressive. The heap is the primary growth region (+9.8 MB). This process will exhaust available memory quickly.

---

## A-19 · `proc_fd_leak_detect`

**User prompt**
> "Check if xconf-client has a file descriptor leak."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "proc_fd_leak_detect", "arguments": { "process_name": "xconf-client", "interval_seconds": 20, "sample_count": 3 } } }
```

**Server response**
```json
{
  "summary": "HIGH confidence FD leak in xconf-client (PID 3105). FD count: 42 → 131 (+89).",
  "metrics": { "pid": 3105, "leak_score": "HIGH", "fd_delta_total": 89 },
  "evidence": ["t=0s: 42 FDs", "t=20s: 89 FDs", "t=40s: 131 FDs"],
  "key_findings": ["socket:[AF_INET] to 192.168.1.1:443 opened 34 times, never closed."],
  "next_suggestions": ["Check HTTP connection reuse in xconf-client."]
}
```

**LLM response**
> **HIGH confidence FD leak**: `xconf-client` went from 42 → 131 FDs in 40 seconds. A socket to `192.168.1.1:443` is opened 34 times without being closed — classic HTTP keep-alive connection leak.

---

## A-20 · `proc_fd_growth_watch`

**User prompt**
> "Watch xconf-client FDs rapidly for 30 seconds."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "proc_fd_growth_watch", "arguments": { "process_name": "xconf-client", "sample_count": 6, "sample_interval_ms": 5000 } } }
```

**Server response**
```json
{
  "summary": "Strong FD leak pattern. +4.5 FDs/sec sustained. Top target: socket:443.",
  "metrics": { "fd_rate_per_second": 4.5, "assessment": "strong_fd_leak_pattern" },
  "evidence": ["t=0s: 42", "t=5s: 65 (+23)", "t=10s: 88 (+23)", "t=15s: 111 (+23)"],
  "next_suggestions": ["Enable HTTP connection reuse in xconf-client HTTP client library."]
}
```

**LLM response**
> Confirmed: `xconf-client` opens a new TLS socket every ~1.1 seconds without closing old ones. At this rate, the process-level FD limit will be hit in under 30 minutes.

---

## A-21 · `proc_memory_map_diagnose`

**User prompt**
> "Show me the memory map breakdown for PID 2201."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "proc_memory_map_diagnose", "arguments": { "pid": 2201, "top_mappings": 5 } } }
```

**Server response**
```json
{
  "summary": "rdkbrowserng: VmRSS=194 MB, VmPeak=310 MB. Top region: [heap] 148 MB anon.",
  "metrics": { "VmRSS_kB": 198656, "VmPeak_kB": 317440, "anon_pct": 76, "file_backed_pct": 24 },
  "key_findings": ["[heap] 148 MB — 76% of RSS is anonymous/heap.", "VmPeak 310 MB suggests past higher usage."],
  "next_suggestions": []
}
```

**LLM response**
> `rdkbrowserng`'s heap is **148 MB** (76% of RSS). The peak was 310 MB, so the process has shed some memory previously. The high anonymous mapping ratio confirms heap fragmentation rather than shared library bloat.

---

## A-22 · `proc_thread_hang_diagnose`

**User prompt**
> "CcspWifiAgent stopped responding — check for hung threads."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "proc_thread_hang_diagnose", "arguments": { "process_name": "CcspWifiAgent", "sample_count": 2, "sample_interval_ms": 1000 } } }
```

**Server response**
```json
{
  "summary": "2 hung threads in CcspWifiAgent (PID 2044). Both in pipe_wait.",
  "metrics": { "pid": 2044, "hung_threads": 2, "diagnostic_assessment": "thread_hung_on_io" },
  "evidence": ["TID 2051: pipe_wait, 0 ctx-switches x2 samples", "TID 2063: pipe_wait, 0 ctx-switches x2 samples"],
  "next_suggestions": ["Write-end of pipe was closed. Add SIGPIPE handler and reconnect logic."]
}
```

**LLM response**
> Two threads (TID 2051, 2063) are stuck in `pipe_wait` with zero context switches — the pipe write-end was closed. This is the root cause of the unresponsive process. Fix: add pipe health check and reconnection in `CcspWifiAgent`'s IPC layer.

---

## A-23 · `proc_futex_wait_diagnose`

**User prompt**
> "Is there a deadlock in process 3381?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "proc_futex_wait_diagnose", "arguments": { "pid": 3381, "sample_count": 4, "sample_interval_ms": 1000 } } }
```

**Server response**
```json
{
  "summary": "Deadlock-like futex blocking in PID 3381. 2 threads mutually blocked.",
  "metrics": { "diagnostic_assessment": "deadlock_like_futex_blocking", "likely_stuck_futex": 2 },
  "evidence": ["TID 3382: futex_wait_queue_me, stable wchan, 0 ctx-progress", "TID 3383: futex_wait, stable wchan, 0 ctx-progress"],
  "next_suggestions": ["Two threads each holding a lock the other needs — classic AB-BA deadlock."]
}
```

**LLM response**
> **Deadlock confirmed**: TIDs 3382 and 3383 are each waiting on a futex held by the other (AB-BA deadlock pattern). The process will not recover without a restart. Code fix: enforce consistent lock ordering in the application.

---

## A-24 · `proc_hung_thread_diagnose`

**User prompt**
> "Process 4000 seems frozen — which threads are hung?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "proc_hung_thread_diagnose", "arguments": { "pid": 4000, "sample_count": 6, "sample_interval_ms": 2000 } } }
```

**Server response**
```json
{
  "summary": "1 hung thread in PID 4000. TID 4001 in ep_poll with 0 ctx-switches for 12s.",
  "metrics": { "diagnostic_assessment": "threads_possibly_stuck", "possible_hung_threads": 1 },
  "evidence": ["TID 4001: state=S, wchan=ep_poll, vol_ctxt unchanged x6 samples"],
  "next_suggestions": ["Thread is waiting on an epoll fd that never fires — check the fd registration."]
}
```

**LLM response**
> TID 4001 has been stuck in `ep_poll` for **12 seconds** with zero context switches. The epoll-monitored file descriptor is likely closed or never written to — check the event source registration logic.

---

## A-25 · `proc_cpu_spin_diagnose`

**User prompt**
> "One CPU core is pegged at 100% by ccsppsmplugin — which thread?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "proc_cpu_spin_diagnose", "arguments": { "process_name": "ccsppsmplugin", "sample_count": 6, "sample_interval_ms": 1000 } } }
```

**Server response**
```json
{
  "summary": "CPU-spinning confirmed: TID 3388 at 98.7% CPU across 5 intervals.",
  "metrics": { "diagnostic_assessment": "threads_likely_spinning", "spin_candidate_tid": 3388, "spin_cpu_pct": 98.7 },
  "evidence": ["TID 3388: +982/+979/+985/+981/+983 CPU ticks per 1000ms", "state=R, wchan empty"],
  "next_suggestions": ["Tight loop with no yield/sleep — likely missing loop exit condition or infinite retry."]
}
```

**LLM response**
> **TID 3388** is consuming **98.7% of one CPU core** with no blocking operations — a tight infinite loop. Add `sleep()`/`usleep()` or a proper loop exit condition in `ccsppsmplugin`.

---

## A-26 · `proc_memory_pressure_diagnose`

**User prompt**
> "Is the system under memory pressure? Who will get OOM-killed first?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "proc_memory_pressure_diagnose", "arguments": { "sample_count": 2, "sample_interval_ms": 5000, "top_oom_candidates": 5 } } }
```

**Server response**
```json
{
  "summary": "HIGH memory pressure. Free 6.8%, swap 91%, PSI avg10=18.4%. OOM kill imminent.",
  "metrics": { "severity": "HIGH", "free_ratio_pct": 6.8, "swap_usage_ratio_pct": 91.0, "psi_some_avg10": 18.4 },
  "oom_candidates": [
    { "pid": 2881, "name": "rdkbrowserng", "rss_kB": 198400, "oom_score": 856 },
    { "pid": 1842, "name": "wpa_supplicant", "rss_kB": 20272, "oom_score": 210 }
  ],
  "next_suggestions": ["rdkbrowserng will be killed first (score 856). Fix xconf-client socket leak for quick memory recovery."]
}
```

**LLM response**
> ⚠️ **HIGH memory pressure**: only 6.8% free, swap 91% full, PSI stall 18.4%. **`rdkbrowserng` (OOM score 856)** will be killed first. Immediate action: fix `xconf-client` socket leak and investigate `rdkbrowserng` heap growth.

---

---

# Part B — JSON Registry Tool Examples

> JSON registry tools return **raw shell stdout**. Responses are shown as plain text rather than JSON.

---

## B1 — System Information

---

### `get_system_info`

**User prompt**
> "Give me a complete system snapshot — OS, kernel, CPU, and memory."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_system_info", "arguments": {} } }
```

**Raw output**
```
=== System Info ===
Linux rdkdevice 5.15.0-rdk #1 SMP Mon Jan 10 08:22:11 UTC 2024 armv7l GNU/Linux
=== Hostname ===
rdkdevice
=== Uptime ===
 14:35:02 up 6 days, 14:33,  0 users,  load average: 0.45, 0.38, 0.29
=== CPU ===
Architecture: armv7l    CPU(s): 4    Model name: ARMv7 Cortex-A55
=== Memory ===
              total        used        free      shared  buff/cache   available
Mem:          512Mi       209Mi       140Mi       1.2Mi       162Mi       302Mi
```

**LLM response**
> Running **Linux 5.15.0-rdk** on a 4-core **ARMv7 Cortex-A55** (`rdkdevice`), up 6 days 14 hours. Memory: 302 MB available of 512 MB. Load is light (0.45/0.38/0.29).

---

### `get_system_uptime`

**User prompt**
> "What does /proc/uptime show?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_system_uptime", "arguments": {} } }
```

**Raw output**
```
572380.14 2189421.60
 14:35:02 up 6 days, 14:33,  0 users,  load average: 0.45, 0.38, 0.29
```

**LLM response**
> The system has been up **572,380 seconds** (~6.6 days). Idle time across CPUs totals 2,189,421 seconds, meaning CPUs are idle ~76% of the time.

---

### `get_cpu_info`

**User prompt**
> "What CPUs does this device have?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_cpu_info", "arguments": { "format": "summary" } } }
```

**Raw output**
```
processor       : 0
model name      : ARMv7 Processor rev 4 (v7l)
BogoMIPS        : 48.00
Features        : half thumb fastmult vfp edsp thumbee neon vfpv3 tls vfpv4 idiva idivt
CPU implementer : 0x41
CPU architecture: 7
CPU variant     : 0x0
CPU part        : 0xd03
CPU revision    : 4
... (3 more cores)
```

**LLM response**
> This is a quad-core **ARMv7 Cortex-A55** (implementer 0x41, part 0xd03) with NEON SIMD, VFPv4 float, and hardware divide support.

---

### `get_cpu_usage`

**User prompt**
> "Show me current CPU usage and which processes are consuming it."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_cpu_usage", "arguments": {} } }
```

**Raw output**
```
top - 14:35:02 up 6 days, load average: 2.81, 1.94, 1.21
Tasks:  186 total,   2 running, 184 sleeping
%Cpu(s): 68.2 us,  8.1 sy,  0.0 ni, 22.1 id,  1.6 wa
PID   USER  PR  NI  VIRT    RES    SHR  S  %CPU %MEM  COMMAND
3388  root  20   0  148m   12m   2.1m  R  97.3  2.4  ccsppsmplugin
2201  root  20   0 1024m  194m   8.2m  S   2.1 38.0  rdkbrowserng
```

**LLM response**
> **68.2% user CPU** in use. `ccsppsmplugin` (TID 3388) is consuming **97.3% of one core** — a clear CPU spin. `rdkbrowserng` uses 2.1% CPU but 38% RAM. Run `proc_cpu_spin_diagnose` on ccsppsmplugin.

---

### `get_memory_info`

**User prompt**
> "Show me full /proc/meminfo."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_memory_info", "arguments": { "units": "MB" } } }
```

**Raw output**
```
MemTotal:         524288 kB
MemFree:          143360 kB
MemAvailable:     294912 kB
Buffers:            8192 kB
Cached:            98304 kB
SwapCached:            0 kB
SwapTotal:             0 kB
SwapFree:              0 kB
Dirty:               512 kB
AnonPages:         376832 kB
Mapped:             61440 kB
Slab:               28672 kB
SReclaimable:       18432 kB
SUnreclaim:         10240 kB
CommitLimit:       524288 kB
Committed_AS:      471040 kB
```

**LLM response**
> RAM: 512 MB total, 287 MB available. No swap. Committed_AS (460 MB) is already close to CommitLimit (512 MB) — the system is close to overcommit limit. `SUnreclaim` (10 MB) slab is locked in kernel and non-reclaimable.

---

### `get_memory_usage`

**User prompt**
> "Which processes use the most RAM right now?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_memory_usage", "arguments": {} } }
```

**Raw output**
```
=== Memory Usage ===
              total        used        free      available
Mem:          512Mi       209Mi       140Mi           287Mi
=== Top Memory Processes ===
USER     PID  %CPU %MEM    VSZ   RSS COMMAND
root    2201   2.1 38.0 1048576 198400 rdkbrowserng
root    1842   0.1  3.9  32768  20272 wpa_supplicant
root    3105   0.3  2.8  16384  14336 xconf-client
```

**LLM response**
> `rdkbrowserng` dominates at **38% RAM (194 MB)**. `wpa_supplicant` (20 MB) and `xconf-client` (14 MB) are secondary. Combined they hold 228 MB — 44% of total.

---

### `get_load_average`

**User prompt**
> "What is the system load average?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_load_average", "arguments": {} } }
```

**Raw output**
```
2.81 1.94 1.21 3/186 4892
 14:35:02 up 6 days, 14:33, load average: 2.81, 1.94, 1.21
```

**LLM response**
> Load: **2.81 / 1.94 / 1.21**. With 4 CPUs, load 2.81 means ~70% CPU utilization — elevated but not saturated. 3 tasks currently runnable out of 186 total.

---

### `get_gateway_system_info`

**User prompt**
> "What OpenWrt firmware version is installed on the gateway?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_gateway_system_info", "arguments": {} } }
```

**Raw output**
```
DISTRIB_ID="OpenWrt"
DISTRIB_RELEASE="23.05.2"
DISTRIB_REVISION="r23630-842932a"
DISTRIB_TARGET="ipq807x/generic"
DISTRIB_ARCH="aarch64_cortex-a53"
MemTotal:  524288 kB   MemFree: 294912 kB
 up 12 days, 4:17
```

**LLM response**
> Running **OpenWrt 23.05.2** (r23630) on IPQ807x (Qualcomm AArch64 Cortex-A53). Uptime 12 days, memory 294 MB free of 512 MB.

---

## B2 — Process & Storage

---

### `get_process_info`

**User prompt**
> "Show me the status of PID 1842."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_process_info", "arguments": { "pid": 1842 } } }
```

**Raw output**
```
Name:   wpa_supplicant
State:  S (sleeping)
Tgid:   1842
Pid:    1842
PPid:   1
VmPeak:  33792 kB
VmSize:  32768 kB
VmRSS:   20272 kB
VmSwap:      0 kB
Threads: 3
voluntary_ctxt_switches:    14821
nonvoluntary_ctxt_switches:   203
wpa_supplicant -c /etc/wpa_supplicant.conf -i wlan0
```

**LLM response**
> PID 1842 (`wpa_supplicant`) is sleeping with **20 MB RSS**, 3 threads, and 14,821 voluntary context switches (normal I/O-waiting behavior). Running with config `/etc/wpa_supplicant.conf` on `wlan0`.

---

### `list_processes`

**User prompt**
> "List the top 20 running processes."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "list_processes", "arguments": { "limit": 20 } } }
```

**Raw output**
```
USER     PID  %CPU %MEM    VSZ    RSS TTY  STAT START   TIME COMMAND
root       1   0.0  0.1   4096   1024 ?    Ss   Mar07   0:02 /sbin/init
root    1842   0.1  3.9  32768  20272 ?    Ssl  Mar07   4:12 wpa_supplicant
root    2201   2.1 38.0 1048576 198400 ?   Ssl  Mar07  22:14 rdkbrowserng
root    3105   0.3  2.8  16384  14336 ?    Ss   Mar10   0:44 xconf-client
root    3381   97.3 2.4 151552  12288 ?    R    Mar12  18:24 ccsppsmplugin
...
```

**LLM response**
> Notable processes: `ccsppsmplugin` running at **97.3% CPU** (CPU spin), `rdkbrowserng` at **38% RAM**. Immediate action items: diagnose `ccsppsmplugin` CPU spin and `rdkbrowserng` memory growth.

---

### `list_zombie_processes`

**User prompt**
> "Are there any zombie processes?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "list_zombie_processes", "arguments": {} } }
```

**Raw output**
```
root    4891  0.0  0.0      0     0 ?   Z    14:22   0:00 [crashed_helper] <defunct>
```

**LLM response**
> **1 zombie process** found: `crashed_helper` (PID 4891). Its parent has not called `wait()` to collect the exit status. Check parent process (use `ps -o ppid= -p 4891`) and ensure it handles child exits.

---

### `get_disk_usage`

**User prompt**
> "How full are the disks?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_disk_usage", "arguments": {} } }
```

**Raw output**
```
Filesystem      Size  Used Avail Use% Mounted on
/dev/mmcblk0p1  2.0G  1.7G  148M  92% /
/dev/mmcblk0p2  512M  301M  211M  59% /data
tmpfs            64M  8.2M   56M  13% /tmp
```

**LLM response**
> ⚠️ **Root filesystem at 92% capacity** (148 MB remaining of 2 GB). This is critical — logs or core dumps could fill it entirely. Run `find_large_files` to identify space consumers.

---

### `check_disk_space`

**User prompt**
> "How much space is left in /data?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "check_disk_space", "arguments": { "path": "/data" } } }
```

**Raw output**
```
/dev/mmcblk0p2   512M  301M  211M  59% /data
```

**LLM response**
> `/data` has **211 MB free** (59% used). No immediate concern, but worth monitoring alongside the root filesystem which is nearly full.

---

### `find_large_files`

**User prompt**
> "The root filesystem is 92% full. Find the biggest files."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "find_large_files", "arguments": { "path": "/" } } }
```

**Raw output**
```
-rw-r--r-- 1 root root 1.1G Mar 14 02:11 /var/log/core_rdkbrowserng.2881
-rw-r--r-- 1 root root 312M Mar 13 22:44 /tmp/update_bundle.bin
-rw-r--r-- 1 root root 142M Mar 12 09:30 /var/log/messages
```

**LLM response**
> Found the culprits: a **1.1 GB core dump** from `rdkbrowserng` (PID 2881) and a **312 MB update bundle** in `/tmp`. Removing these would free 1.4 GB and drop disk usage below 30%. The `messages` log (142 MB) should also be rotated.

---

### `check_inode_usage`

**User prompt**
> "Could inode exhaustion be causing file creation failures?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "check_inode_usage", "arguments": {} } }
```

**Raw output**
```
Filesystem       Inodes  IUsed  IFree IUse% Mounted on
/dev/mmcblk0p1   131072 130891    181   99% /
/dev/mmcblk0p2    65536   4821  60715    7% /data
```

**LLM response**
> 🚨 **Root filesystem inodes at 99%** (only 181 free). Even if disk blocks are available, no new files can be created. This explains any "no space left" errors. Investigate `/` for directories with excessive small files (e.g. `/tmp`, `/var/run`).

---

### `get_disk_stats`

**User prompt**
> "Show me disk I/O statistics for mmcblk0."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_disk_stats", "arguments": { "device": "mmcblk0" } } }
```

**Raw output**
```
 179       0 mmcblk0 14821 0 421842 82140 28432 0 1847296 641220 0 92440 723560
 179       1 mmcblk0p1 8821 0 210921 41022 ...
```

**LLM response**
> `mmcblk0` shows 14,821 reads and 28,432 writes since boot. Read time: 82 seconds, write time: 641 seconds — indicating the device has been write-heavy (expected for logging).

---

### `get_filesystem_mounts`

**User prompt**
> "What filesystems are currently mounted?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_filesystem_mounts", "arguments": {} } }
```

**Raw output**
```
rootfs / rootfs rw 0 0
/dev/mmcblk0p1 / ext4 rw,relatime 0 0
/dev/mmcblk0p2 /data ext4 rw,relatime 0 0
tmpfs /tmp tmpfs rw,nosuid,nodev,size=65536k 0 0
proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0
sysfs /sys sysfs rw,nosuid,nodev,noexec,relatime 0 0
```

**LLM response**
> Root on ext4 (mmcblk0p1), `/data` on ext4 (mmcblk0p2), tmpfs limited to 64 MB. All mounts are read-write. Standard Linux embedded layout.

---

### `get_interrupts`

**User prompt**
> "Show interrupt statistics to check for interrupt storms."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_interrupts", "arguments": {} } }
```

**Raw output**
```
           CPU0      CPU1      CPU2      CPU3
 16:      18421     19102     17843     18211  GIC  eth0
 17:     512390    498211    501842    495108  GIC  wlan0
 18:          0         0         0         0  GIC  usb0
```

**LLM response**
> WiFi (`wlan0`, IRQ 17) is generating ~2M interrupts across all CPUs — very high, consistent with active traffic or a driver issue. Ethernet is normal at ~73K total. USB has zero interrupts (device disconnected or unused).

---

### `get_hardware_info`

**User prompt**
> "What PCI and USB devices are present?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_hardware_info", "arguments": {} } }
```

**Raw output**
```
=== PCI Devices ===
00:00.0 Host bridge: Qualcomm IPQ8074 PCIe Host
01:00.0 Network controller: Qualcomm QCA9984 802.11ac Wave 2
=== USB Devices ===
Bus 001 Device 002: ID 0bda:8153 Realtek Semiconductor RTL8153 Gigabit Ethernet
```

**LLM response**
> Two PCIe devices: IPQ8074 SoC host bridge and a **QCA9984 802.11ac Wave 2** WiFi radio. USB: a **Realtek RTL8153** Gigabit Ethernet adapter (USB NIC) on Bus 1.

---

### `get_kernel_parameters`

**User prompt**
> "Show me the current vm.* kernel tunables."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_kernel_parameters", "arguments": {} } }
```

**Raw output**
```
vm.swappiness = 60
vm.overcommit_memory = 0
vm.overcommit_ratio = 50
vm.dirty_ratio = 20
vm.dirty_background_ratio = 10
vm.min_free_kbytes = 65536
net.core.rmem_max = 212992
net.core.wmem_max = 212992
...
```

**LLM response**
> Default vm tunables: swappiness 60 (moderate swap tendency), overcommit mode 0 (heuristic), dirty_ratio 20% (will write-back when 20% of RAM is dirty). `min_free_kbytes=65536` reserves 64 MB as a low-watermark buffer.

---

### `list_loaded_modules`

**User prompt**
> "What kernel modules are loaded?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "list_loaded_modules", "arguments": {} } }
```

**Raw output**
```
Module                  Size  Used by
ath11k_pci             81920  0
ath11k                245760  1 ath11k_pci
mac80211              933888  1 ath11k
cfg80211              974848  2 ath11k,mac80211
r8152                  81920  0
```

**LLM response**
> Loaded: **ath11k** (Qualcomm 802.11ax WiFi driver) and **r8152** (RTL8153 USB Ethernet). The WiFi stack is `cfg80211 → mac80211 → ath11k → ath11k_pci`. All modules have expected dependencies.

---

## B3 — Network — Generic Linux

---

### `get_network_stats`

**User prompt**
> "How many bytes has eth0 transmitted and received?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_network_stats", "arguments": { "interface": "eth0" } } }
```

**Raw output**
```
Inter-|   Receive                              |  Transmit
 face |bytes    packets errs drop fifo frame   |bytes    packets errs drop fifo colls
  eth0: 1284741248 9421084    0    0    0     0   842917888 6214821    0    0    0     0
```

**LLM response**
> `eth0` has received **1.28 GB** (9.4M packets) and transmitted **842 MB** (6.2M packets) since boot — zero errors on either direction. Healthy interface.

---

### `get_network_interfaces`

**User prompt**
> "List all network interfaces and their IP addresses."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_network_interfaces", "arguments": {} } }
```

**Raw output**
```
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536
    link/loopback 00:00:00:00:00:00
    inet 127.0.0.1/8
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    link/ether aa:bb:cc:dd:ee:ff
    inet 192.168.1.105/24
3: wlan0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    link/ether 11:22:33:44:55:66
    inet 10.0.0.2/24
```

**LLM response**
> Three active interfaces: `lo` (loopback), `eth0` (192.168.1.105/24, MAC aa:bb:cc:dd:ee:ff), and `wlan0` (10.0.0.2/24). All are UP with LOWER_UP (physical link present).

---

### `get_network_connections`

**User prompt**
> "What network connections are currently open?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_network_connections", "arguments": {} } }
```

**Raw output**
```
Netid State  Recv-Q Send-Q  Local Address:Port    Peer Address:Port
tcp   LISTEN      0      0  0.0.0.0:22             0.0.0.0:*
tcp   LISTEN      0      0  127.0.0.1:9000         0.0.0.0:*
tcp   ESTAB       0      0  192.168.1.105:52814    93.184.216.34:443
udp   UNCONN      0      0  0.0.0.0:68             0.0.0.0:*
```

**LLM response**
> Listening: SSH (port 22) and a local service on 9000. One established HTTPS connection to `93.184.216.34:443` (example.com). UDP port 68 is the DHCP client.

---

### `test_connectivity`

**User prompt**
> "Can the device reach 8.8.8.8?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "test_connectivity", "arguments": { "host": "8.8.8.8" } } }
```

**Raw output**
```
PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=118 time=12.4 ms
64 bytes from 8.8.8.8: icmp_seq=2 ttl=118 time=11.8 ms
64 bytes from 8.8.8.8: icmp_seq=3 ttl=118 time=12.1 ms
64 bytes from 8.8.8.8: icmp_seq=4 ttl=118 time=12.3 ms
--- 8.8.8.8 ping statistics ---
4 packets transmitted, 4 received, 0% packet loss, avg 12.1 ms
```

**LLM response**
> Internet connectivity is **healthy**: 0% packet loss, average RTT **12.1 ms** to Google DNS (8.8.8.8). The WAN link is up and routing correctly.

---

### `get_routing_table`

**User prompt**
> "What is the routing table?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_routing_table", "arguments": {} } }
```

**Raw output**
```
default via 192.168.1.1 dev eth0 proto dhcp src 192.168.1.105 metric 100
192.168.1.0/24 dev eth0 proto kernel scope link src 192.168.1.105
10.0.0.0/24 dev wlan0 proto kernel scope link src 10.0.0.2
```

**LLM response**
> Default route: **via 192.168.1.1** on eth0 (DHCP assigned). Direct routes for 192.168.1.0/24 (eth0) and 10.0.0.0/24 (wlan0). Routing is standard for a dual-interface device.

---

### `check_open_ports`

**User prompt**
> "What ports are listening and which processes own them?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "check_open_ports", "arguments": {} } }
```

**Raw output**
```
Netid  State   Local Address:Port  Process
tcp    LISTEN  0.0.0.0:22          users:(("sshd",pid=892,fd=3))
tcp    LISTEN  127.0.0.1:9000      users:(("mcp_server",pid=1021,fd=4))
udp    UNCONN  0.0.0.0:68          users:(("udhcpc",pid=1044,fd=5))
```

**LLM response**
> SSH (`sshd`, port 22) and the MCP server (port 9000, localhost only) are listening. `udhcpc` (DHCP client) holds UDP port 68. No unexpected open ports.

---

## B4 — Network — OpenWrt Gateway

---

### `get_wan_ip_config`

**User prompt**
> "What IP address is the WAN interface using?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_wan_ip_config", "arguments": { "interface": "wan" } } }
```

**Raw output**
```
network.wan=interface
network.wan.ifname='eth1'
network.wan.proto='dhcp'
network.wan.metric='10'
2: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    inet 203.0.113.55/24 brd 203.0.113.255 scope global eth1
```

**LLM response**
> WAN is on `eth1` using **DHCP**, assigned **203.0.113.55/24**. The interface is UP with physical link active.

---

### `get_lan_ip_config`

**User prompt**
> "What is the gateway's LAN IP and subnet?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_lan_ip_config", "arguments": {} } }
```

**Raw output**
```
network.lan=interface
network.lan.ifname='eth0'
network.lan.proto='static'
network.lan.ipaddr='192.168.1.1'
network.lan.netmask='255.255.255.0'
```

**LLM response**
> LAN is statically configured: **192.168.1.1/24** on `eth0` (br-lan bridge). This is the router's gateway IP for all LAN clients.

---

### `get_dhcp_leases`

**User prompt**
> "Which devices are connected to the network via DHCP?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_dhcp_leases", "arguments": {} } }
```

**Raw output**
```
1742000000 aa:bb:cc:11:22:33 192.168.1.101 laptop-alice 01:aa:bb:cc:11:22:33
1742003600 dd:ee:ff:44:55:66 192.168.1.102 android-bob  01:dd:ee:ff:44:55:66
1742007200 11:22:33:77:88:99 192.168.1.103 *            01:11:22:33:77:88:99
```

**LLM response**
> **3 DHCP clients**: `laptop-alice` (192.168.1.101), `android-bob` (192.168.1.102), and an unnamed device at 192.168.1.103 (MAC 11:22:33:77:88:99 — consider identifying this unknown device).

---

### `get_dns_config`

**User prompt**
> "What DNS servers is the gateway using?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_dns_config", "arguments": {} } }
```

**Raw output**
```
dhcp.dnsmasq[0]=dnsmasq
dhcp.dnsmasq[0].domainneeded='1'
dhcp.dnsmasq[0].boguspriv='1'
dhcp.dnsmasq[0].server='8.8.8.8'
dhcp.dnsmasq[0].server='8.8.4.4'
# /etc/resolv.conf
nameserver 127.0.0.1
```

**LLM response**
> dnsmasq is configured with **Google DNS (8.8.8.8 and 8.8.4.4)** as upstream. Clients resolve through 127.0.0.1 (dnsmasq). `domainneeded` and `boguspriv` are enabled for security (prevents leaking private reverse lookups).

---

### `get_ntp_status`

**User prompt**
> "Is the clock synced?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_ntp_status", "arguments": {} } }
```

**Raw output**
```
system.ntp=timeserver
system.ntp.server='0.openwrt.pool.ntp.org'
system.ntp.server='1.openwrt.pool.ntp.org'
     remote           refid      st t when poll reach   delay   offset  jitter
*0.openwrt.pool  195.13.8.189    2 u   42   64  377   14.231   -0.842   0.612
```

**LLM response**
> Clock is **synced** to `0.openwrt.pool.ntp.org` (stratum 2). Offset **-0.842 ms**, jitter 0.612 ms — excellent time accuracy. `reach=377` (full octet) means 8/8 recent polls succeeded.

---

### `get_wireless_status`

**User prompt**
> "Show me the WiFi status — channel, clients, signal strength."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_wireless_status", "arguments": {} } }
```

**Raw output**
```
wlan0     ESSID: "HomeNetwork_5G"
          Access Point: AA:BB:CC:DD:EE:FF
          Mode: Master   Channel: 36 (5.180 GHz)   Tx-Power: 23 dBm
          Signal: -42 dBm  Noise: -95 dBm  SNR: 53 dB
          Clients: 4
wlan1     ESSID: "HomeNetwork_2G"
          Channel: 6 (2.437 GHz)
          Clients: 2
```

**LLM response**
> 5 GHz radio (wlan0): channel 36, **SNR 53 dB** (excellent), 4 clients. 2.4 GHz radio (wlan1): channel 6, 2 clients. Both radios are healthy with good signal margins.

---

### `get_firewall_rules`

**User prompt**
> "Show me the active firewall rules."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_firewall_rules", "arguments": {} } }
```

**Raw output**
```
Chain INPUT (policy DROP 0 packets)
 pkts bytes target  prot opt in   out  source       destination
12821  1.2M ACCEPT  all  --  lo   any  anywhere     anywhere
  441   44K ACCEPT  all  --  any  any  anywhere     anywhere  ctstate RELATED,ESTABLISHED
    0     0 DROP    all  --  eth1 any  anywhere     anywhere  ctstate INVALID

Chain FORWARD (policy DROP)
 pkts bytes target  prot opt in   out  source       destination
 8421  841K ACCEPT  all  --  eth0 eth1 192.168.1.0/24 anywhere
```

**LLM response**
> Firewall is correctly configured: INPUT drops by default, loopback and established connections accepted. FORWARD allows LAN→WAN (192.168.1.0/24 → eth1). Invalid packets are dropped on WAN input.

---

### `get_wan_connection_status`

**User prompt**
> "Is the WAN connection up?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_wan_connection_status", "arguments": {} } }
```

**Raw output**
```json
{
  "up": true,
  "proto": "dhcp",
  "ipaddr": "203.0.113.55",
  "netmask": "255.255.255.0",
  "gwaddr": "203.0.113.1",
  "uptime": 572100
}
```

**LLM response**
> WAN is **UP** (DHCP), IP 203.0.113.55, gateway 203.0.113.1. Connection uptime: 572,100 seconds (~6.6 days) — very stable, no recent reconnects.

---

### `get_connected_clients`

**User prompt**
> "Show all devices currently connected to the gateway."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_connected_clients", "arguments": {} } }
```

**Raw output**
```
1742000000 aa:bb:cc:11:22:33 192.168.1.101 laptop-alice
1742003600 dd:ee:ff:44:55:66 192.168.1.102 android-bob
192.168.1.103 dev eth0 lladdr 11:22:33:77:88:99 REACHABLE
192.168.1.104 dev wlan0 lladdr 98:76:54:32:10:fe REACHABLE
```

**LLM response**
> **4 connected clients**: `laptop-alice` and `android-bob` via DHCP, plus two additional devices (192.168.1.103 on eth0, 192.168.1.104 on wlan0) detected via ARP neighbor cache.

---

### `get_nat_sessions`

**User prompt**
> "Show me the active NAT sessions through the gateway."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_nat_sessions", "arguments": { "limit": 10 } } }
```

**Raw output**
```
ipv4     2 tcp 6 431999 ESTABLISHED src=192.168.1.101 dst=142.250.80.46 sport=52814 dport=443 src=142.250.80.46 dst=203.0.113.55 sport=443 dport=52814 [ASSURED]
ipv4     2 tcp 6 299 TIME_WAIT src=192.168.1.102 dst=52.94.236.248 sport=55144 dport=443
ipv4     2 udp 17 25 src=192.168.1.101 dst=8.8.8.8 sport=44182 dport=53
```

**LLM response**
> 3 active NAT sessions: `laptop-alice` has an established HTTPS connection to Google (142.250.80.46), `android-bob` has a closing HTTPS session to AWS (52.94.236.248), and `laptop-alice` made a DNS query to 8.8.8.8.

---

### `get_port_forwarding_rules`

**User prompt**
> "What port forwarding rules are configured?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_port_forwarding_rules", "arguments": {} } }
```

**Raw output**
```
firewall.@redirect[0]=redirect
firewall.@redirect[0].name='Web Server'
firewall.@redirect[0].src='wan'
firewall.@redirect[0].src_dport='80'
firewall.@redirect[0].dest_ip='192.168.1.200'
firewall.@redirect[0].dest_port='8080'
```

**LLM response**
> One port forwarding rule: **WAN port 80 → 192.168.1.200:8080** (HTTP to internal web server). No other DNAT rules configured.

---

### `get_bandwidth_usage`

**User prompt**
> "How much traffic has passed through the WAN interface?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_bandwidth_usage", "arguments": {} } }
```

**Raw output**
```
Inter-|         Receive          |         Transmit
 face | bytes    packets  errors | bytes    packets  errors
 eth1: 8421741248 62819084      0  5284741120 38214821       0
```

**LLM response**
> WAN (`eth1`) has received **8.4 GB** (62.8M packets) and transmitted **5.3 GB** (38.2M packets) since last boot — zero errors. Download-heavy traffic pattern (typical for a home gateway).

---

### `get_static_dhcp_reservations`

**User prompt**
> "Are there any static IP reservations configured?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_static_dhcp_reservations", "arguments": {} } }
```

**Raw output**
```
dhcp.@host[0].name='printer'
dhcp.@host[0].mac='11:22:33:AA:BB:CC'
dhcp.@host[0].ip='192.168.1.200'
dhcp.@host[1].name='nas'
dhcp.@host[1].mac='DD:EE:FF:11:22:33'
dhcp.@host[1].ip='192.168.1.201'
```

**LLM response**
> **2 static reservations**: `printer` (MAC 11:22:33:AA:BB:CC → 192.168.1.200) and `nas` (MAC DD:EE:FF:11:22:33 → 192.168.1.201). These match the port-forwarding target (192.168.1.200 for the web server).

---

### `get_qos_config`

**User prompt**
> "Is QoS configured on the gateway?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_qos_config", "arguments": {} } }
```

**Raw output**
```
qdisc htb 1: root refcnt 9 r2q 10 default 0x30 direct_packets_stat 44
 Sent 5284741120 bytes 38214821 pkt
 class htb 1:10 root leaf 10: prio 1
  rate 100Mbit ceil 100Mbit
 class htb 1:20 prio 2 rate 50Mbit ceil 80Mbit
 class htb 1:30 prio 3 rate 10Mbit ceil 100Mbit
```

**LLM response**
> QoS is active using **HTB (Hierarchical Token Bucket)** with 3 classes: high-priority (100 Mbps), mid-priority (50–80 Mbps), and best-effort (10–100 Mbps). Traffic shaping is functioning.

---

### `get_ipv6_config`

**User prompt**
> "What IPv6 addresses are configured?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_ipv6_config", "arguments": {} } }
```

**Raw output**
```
2: eth1: inet6 2001:db8:1234:5678::1/64 scope global dynamic
    valid_lft 86400sec preferred_lft 14400sec
3: eth0: inet6 fd12:3456:789a:1::1/64 scope global
6: wlan0: inet6 fd12:3456:789a:1::2/64 scope global
```

**LLM response**
> WAN has a **public IPv6 /64 prefix** (2001:db8.../64) with 24-hour validity. LAN interfaces use a ULA prefix (fd12.../64). IPv6 is fully operational with prefix delegation.

---

### `get_upnp_status`

**User prompt**
> "Is UPnP configured? Are there any dynamic port mappings?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_upnp_status", "arguments": {} } }
```

**Raw output**
```
upnpd.config=upnpd
upnpd.config.enabled='1'
upnpd.config.internal_iface='br-lan'
upnpd.config.external_iface='eth1'
upnpd.config.port='5000'
```

**LLM response**
> UPnP is **enabled**, listening on LAN (br-lan) and forwarding to WAN (eth1). UPnP port 5000 is the control point. Note: UPnP allows applications to open ports dynamically without firewall rules — consider disabling if not needed for security.

---

## B5 — Log Analysis

---

### `discover_log_files`

**User prompt**
> "What log files exist on this system?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "discover_log_files", "arguments": { "depth": 3 } } }
```

**Raw output**
```
=== Log files in /var/log ===
-rw-r--r-- 1 root root 1.1G Mar 14 02:11 /var/log/core_rdkbrowserng.2881
-rw-r--r-- 1 root root 142M Mar 14 09:31 /var/log/messages
-rw-r--r-- 1 root root 1.1M Mar 14 09:28 /var/log/wifi.log
-rw-r--r-- 1 root root  12K Mar 14 08:45 /var/log/crash.log
-rw-r--r-- 1 root root 4.2K Mar 14 07:12 /var/log/ccsp.log
```

**LLM response**
> Found 5 log files. A **1.1 GB core dump** is consuming most of the disk space. `messages` (142 MB) is the main syslog. `crash.log` was updated at 08:45 — read it to correlate with the OOM event found earlier.

---

### `search_log_issues`

**User prompt**
> "Search /var/log/wifi.log for errors since 09:00 this morning."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "search_log_issues", "arguments": { "log_file": "/var/log/wifi.log", "since": "Mar 14 09:" } } }
```

**Raw output**
```
=== /var/log/wifi.log ===
--- From: Mar 14 09: ---
Mar 14 09:05:11 wpa_supplicant[1842]: error: 4-way handshake failed (reason 15)
Mar 14 09:12:04 wpa_supplicant[1842]: CTRL-EVENT-DISCONNECTED bssid=AA:BB:CC:DD:EE:FF reason=15
Mar 14 09:12:06 wpa_supplicant[1842]: Trying to associate with AA:BB:CC:DD:EE:FF (SSID='HomeNet_5G')
Mar 14 09:12:09 wpa_supplicant[1842]: CTRL-EVENT-CONNECTED
```

**LLM response**
> `wpa_supplicant` had a **4-way handshake failure** at 09:05 (reason 15 = "4-way handshake timeout"), causing a disconnect at 09:12. It successfully reconnected at 09:12:09 — a transient WiFi auth failure, not a persistent issue.

---

### `search_all_logs_for_issues`

**User prompt**
> "Scan all logs for critical errors in the last 200 lines of each."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "search_all_logs_for_issues", "arguments": { "lines": 200, "pattern": "critical|panic|assert|abort|oom" } } }
```

**Raw output**
```
=== /var/log/messages ===
Mar 14 08:44:11 kernel: Out of memory: Kill process 2881 (rdkbrowserng) score 856
Mar 14 08:44:12 kernel: oom_reaper: reaped process 2881, anon-rss:0kB

=== /var/log/crash.log ===
Mar 14 08:44:11 CRITICAL rdkbrowserng[2881] received SIGKILL (OOM)
Mar 14 08:44:12 CRITICAL crash handler invoked, generating core dump
```

**LLM response**
> **2 critical events** across 2 files, all from 08:44: `rdkbrowserng` (PID 2881) was OOM-killed by the kernel, and the crash handler generated a core dump. The 1.1 GB core dump in `/var/log` is from this event.

---

### `get_recent_logs`

**User prompt**
> "Show me the last 50 system log lines."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_recent_logs", "arguments": { "lines": "50" } } }
```

**Raw output**
```
Mar 14 14:30:01 systemd[1]: Started Session 42 of user root.
Mar 14 14:30:15 kernel: [572380.441] eth0: renamed from veth3c8f2a1
Mar 14 14:31:02 wpa_supplicant[1842]: WPA: Group rekeying completed
Mar 14 14:33:55 sshd[4891]: Accepted publickey for root from 192.168.1.10
...
```

**LLM response**
> Recent logs are clean: session management, network rename events, WiFi group rekey, and an SSH login from 192.168.1.10. No errors in the last 50 lines.

---

### `search_error_logs`

**User prompt**
> "Are there any error-priority log entries?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "search_error_logs", "arguments": {} } }
```

**Raw output**
```
Mar 14 08:44:11 kernel: Out of memory: Kill process 2881
Mar 14 09:05:11 wpa_supplicant[1842]: error: 4-way handshake failed
Mar 14 09:12:01 kernel: usb 1-1: error -71 while reading from device
```

**LLM response**
> **3 error entries**: OOM kill (08:44), WiFi handshake failure (09:05), and a USB read error (09:12 — device timeout or disconnect). Two are transient; the OOM kill requires root cause analysis.

---

### `get_kernel_logs`

**User prompt**
> "Show the full dmesg output with timestamps."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_kernel_logs", "arguments": {} } }
```

**Raw output**
```
[Mar14 00:00] Linux version 5.15.0-rdk (gcc version 11.3.0) #1 SMP
[Mar14 08:44] Out of memory: Kill process 2881 (rdkbrowserng) score 856
[Mar14 09:12] usb 1-1: USB disconnect, device number 2
[Mar14 09:12] usb 1-1: new high-speed USB device number 3 using xhci_hcd
...
```

**LLM response**
> Kernel log confirms OOM kill at 08:44 and a USB device reconnect at 09:12 (disconnect + reconnect in quick succession — likely a flaky cable or device power cycle).

---

### `get_system_logs`

**User prompt**
> "Get the last 30 lines from the system log."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_system_logs", "arguments": { "lines": 30 } } }
```

**Raw output**
```
Mar 14 14:28:01 cron[442]: (root) CMD (/usr/sbin/logrotate /etc/logrotate.conf)
Mar 14 14:28:01 logrotate: warning: /var/log/messages: log size exceeds maxsize
Mar 14 14:30:01 systemd[1]: Started Session 42 of user root.
...
```

**LLM response**
> Log rotation is warning that `/var/log/messages` exceeds `maxsize` — this explains the 142 MB log file. Force a rotation with `logrotate -f /etc/logrotate.conf` to free space.

---

## B6 — Service Management

---

### `list_systemd_services`

**User prompt**
> "List all active systemd services."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "list_systemd_services", "arguments": { "state": "active" } } }
```

**Raw output**
```
UNIT                     LOAD   ACTIVE  SUB     DESCRIPTION
mcp-server.service       loaded active  running MCP Debug Server
sshd.service             loaded active  running OpenSSH Server Daemon
wpa_supplicant.service   loaded active  running WPA supplicant
networking.service       loaded active  running LSB: Raise network interfaces
```

**LLM response**
> **4 active services**: MCP server, SSH, wpa_supplicant, and networking. All are in `running` substate (healthy). No degraded or failed services in the active list.

---

### `list_failed_services`

**User prompt**
> "Are any systemd services in a failed state?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "list_failed_services", "arguments": {} } }
```

**Raw output**
```
UNIT                      LOAD   ACTIVE FAILED DESCRIPTION
rdkbrowserng.service      loaded failed failed RDK Browser NG
xconf-client.service      loaded failed failed XConf Client Service

LOAD   = Reflects whether the unit definition was properly loaded.
ACTIVE = The high-level unit activation state.
FAILED = The failure state.
2 units listed.
```

**LLM response**
> **2 failed services**: `rdkbrowserng` (OOM-killed at 08:44) and `xconf-client` (likely exited due to hitting the FD limit from the socket leak). Both require restart after fixing the underlying issues.

---

### `get_service_status`

**User prompt**
> "What is the current status of wpa_supplicant?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_service_status", "arguments": { "service_name": "wpa_supplicant" } } }
```

**Raw output**
```
● wpa_supplicant.service - WPA supplicant
     Loaded: loaded (/lib/systemd/system/wpa_supplicant.service)
     Active: active (running) since Mon 2026-03-07 14:00:22 UTC; 6 days ago
    Main PID: 1842 (wpa_supplicant)
      Status: "connected to HomeNet_5G"
     CGroup: /system.slice/wpa_supplicant.service
             └─1842 /sbin/wpa_supplicant -u -s -O /run/wpa_supplicant
Memory: 19.8M
```

**LLM response**
> `wpa_supplicant` is **active and running** (PID 1842) since Mar 7 — 6 days uptime. Currently connected to `HomeNet_5G`. Memory: 19.8 MB. The earlier handshake failure was transient; service is healthy now.

---

### `get_service_logs`

**User prompt**
> "Show me the last 30 journal entries for wpa_supplicant."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_service_logs", "arguments": { "service_name": "wpa_supplicant", "lines": 30 } } }
```

**Raw output**
```
Mar 14 09:05:11 wpa_supplicant[1842]: WPA: 4-way handshake failed (reason 15)
Mar 14 09:12:04 wpa_supplicant[1842]: CTRL-EVENT-DISCONNECTED reason=15
Mar 14 09:12:06 wpa_supplicant[1842]: Trying to associate with HomeNet_5G
Mar 14 09:12:09 wpa_supplicant[1842]: CTRL-EVENT-CONNECTED
Mar 14 14:31:02 wpa_supplicant[1842]: WPA: Group rekeying completed with HomeNet_5G
```

**LLM response**
> `wpa_supplicant` had a **single disconnect/reconnect cycle** at 09:12 following a handshake timeout (reason 15). It recovered automatically and has been stable since. The 14:31 group rekey is normal periodic WPA2 behavior.

---

### `get_systemd_units`

**User prompt**
> "Show me all systemd timers."

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_systemd_units", "arguments": { "unit_type": "timer" } } }
```

**Raw output**
```
UNIT                     LOAD   ACTIVE  SUB       DESCRIPTION
logrotate.timer          loaded active  waiting   Daily rotation of log files
apt-daily.timer          loaded active  waiting   Daily apt activities
systemd-tmpfiles-clean.timer loaded active waiting Cleanup of Temporary Directories

3 timers listed.
```

**LLM response**
> **3 timers** active: daily log rotation (explains the logrotate warning), daily apt package updates, and tmpfiles cleanup. All are in `waiting` (scheduled, not currently running).

---

### `get_unit_dependencies`

**User prompt**
> "What does rdkbrowserng.service depend on?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_unit_dependencies", "arguments": { "unit_name": "rdkbrowserng.service" } } }
```

**Raw output**
```
rdkbrowserng.service
● ├─networking.service
● ├─wpa_supplicant.service
● ├─dbus.service
● └─sysinit.target
  ├─systemd-journald.service
  └─local-fs.target
```

**LLM response**
> `rdkbrowserng` depends on **networking**, **wpa_supplicant**, and **dbus**. Since `wpa_supplicant` is running and networking is up, `rdkbrowserng` can be safely restarted now that the OOM root cause is addressed.

---

## B7 — Containers & Hardware

---

### `list_docker_containers`

**User prompt**
> "What Docker containers are running?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "list_docker_containers", "arguments": {} } }
```

**Raw output**
```
CONTAINER ID  IMAGE           COMMAND             CREATED      STATUS          PORTS             NAMES
a1b2c3d4e5f6  nginx:latest    "/docker-entrypoin" 2 days ago   Up 2 days       0.0.0.0:80->80/tcp web-server
b2c3d4e5f6a1  redis:7         "docker-entrypoint" 3 days ago   Up 3 days       127.0.0.1:6379->6379/tcp cache
f1e2d3c4b5a6  myapp:v1.2      "/app/start.sh"     1 hour ago   Exited (137) 45 minutes ago      app-worker
```

**LLM response**
> **3 containers**: `web-server` (nginx, UP 2 days, port 80), `cache` (Redis, UP 3 days), and `app-worker` which **exited with code 137** (killed by signal — likely OOM or SIGKILL). Investigate app-worker logs.

---

### `get_container_logs`

**User prompt**
> "What were the last log lines from the crashed app-worker container?"

**Tool call**
```json
{ "method": "tools/call", "params": { "name": "get_container_logs", "arguments": { "container_id": "app-worker", "lines": "50" } } }
```

**Raw output**
```
2026-03-14T13:44:01Z INFO  Starting job processor v1.2.0
2026-03-14T13:44:03Z INFO  Connected to Redis cache
2026-03-14T13:44:15Z INFO  Processing job batch #4821 (500 items)
2026-03-14T13:47:28Z ERROR Fatal: failed to allocate buffer for job result
2026-03-14T13:47:28Z ERROR Backtrace: malloc returned NULL at job_processor.c:482
2026-03-14T13:47:28Z FATAL Process aborting due to allocation failure
```

**LLM response**
> `app-worker` crashed at 13:47 due to a **malloc failure** (NULL return) at `job_processor.c:482` while processing job batch #4821. The container was OOM-killed (exit code 137). Fix: add memory limit guards in `job_processor.c` or increase the container's memory limit.

---

*End of USAGE-EXAMPLES.md — covers all 26 native tools and all JSON registry tools.*
