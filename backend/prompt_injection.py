"""Prompt injection helpers for diagnostic-oriented MCP chat sessions."""

from __future__ import annotations

import os
import re
from typing import Iterable, List, Optional, Sequence


ISSUE_CLASSIFICATIONS: List[tuple[str, Sequence[str]]] = [
    ("Crash / Coredump", ("process died", "segfault", "core dump", "coredump", "sigsegv", "sigabrt", "sigbus", "sigfpe", "crash", "crashed")),
    ("Hang / Freeze", ("unresponsive", "stuck", "frozen", "freeze", "hung", "hang", "watchdog")),
    ("Memory", ("oom", "memory leak", "high rss", "swap", "out of memory", "memory usage")),
    ("Network / Connectivity", ("no internet", "dns fail", "ping loss", "dhcp", "network", "connectivity", "packet loss", "wan", "lan")),
    ("Video / Audio", ("no picture", "black screen", "audio drop", "hdmi", "video", "audio", "display")),
    ("Firmware / OTA", ("update failed", "firmware mismatch", "upgrade", "ota", "rollback", "flashing")),
    ("Performance / CPU", ("slow", "high load", "cpu spin", "performance", "latency", "cpu")),
    ("Service / Process", ("service not running", "zombie process", "failed to start", "process not running", "daemon", "service")),
]

ISSUE_CLASSIFICATION_ALIASES = {
    "crash": "Crash / Coredump",
    "coredump": "Crash / Coredump",
    "crash coredump": "Crash / Coredump",
    "hang": "Hang / Freeze",
    "freeze": "Hang / Freeze",
    "hang freeze": "Hang / Freeze",
    "memory": "Memory",
    "network": "Network / Connectivity",
    "connectivity": "Network / Connectivity",
    "network connectivity": "Network / Connectivity",
    "video": "Video / Audio",
    "audio": "Video / Audio",
    "video audio": "Video / Audio",
    "firmware": "Firmware / OTA",
    "ota": "Firmware / OTA",
    "firmware ota": "Firmware / OTA",
    "performance": "Performance / CPU",
    "cpu": "Performance / CPU",
    "performance cpu": "Performance / CPU",
    "service": "Service / Process",
    "process": "Service / Process",
    "service process": "Service / Process",
}

VIDEO_TOOL_MARKERS = (
    "audio_status",
    "video_status",
    "hdmi_",
    "display_",
    "ott_",
    "rdkshell_",
    "opengl_",
)

BASELINE_TOOL_CANDIDATES = {
    "Broadband": [
        ["device_version"],
        ["device_time_status"],
        ["process_status"],
        ["system_memory_stats"],
        ["system_memory_used"],
        ["system_memory_free"],
        ["device_reboot_reason"],
    ],
    "Video": [
        ["device_details"],
        ["device_time"],
        ["process_status"],
        ["device_top"],
        ["upgrade_firmware_status"],
    ],
}

LAYER2_TOOL_CANDIDATES = {
    "Crash / Coredump": [
        ["process_core_dump"],
        ["process_mini_dump"],
        ["process_zombie_state"],
        ["process_memory_status"],
    ],
    "Network / Connectivity": [
        ["network_dns_check", "wan_dns_check"],
        ["wan_status", "wan_ping_test"],
        ["network_routing_table", "network_ovs_config"],
        ["network_conntrack_check", "network_ddos_check"],
        ["ethernet_link_status", "ethernet_driver_stats"],
        ["network_interface_status", "network_interface_signal"],
        ["lan_mode", "lan_config"],
        ["network_blocked_device"],
    ],
    "Memory": [
        ["system_total_memory"],
        ["system_memory_used"],
        ["system_memory_free"],
        ["system_memory_stats"],
        ["process_memory_status"],
        ["process_status"],
    ],
    "Video / Audio": [
        ["audio_status", "video_status"],
        ["hdmi_info", "hdmi_hdcp_state", "hdmi_hex_dump"],
        ["display_read_edid", "display_get_height", "display_get_width"],
        ["opengl_status"],
        ["rdkshell_get_clients"],
    ],
    "Firmware / OTA": [
        ["upgrade_firmware_status", "upgrade_sw_status"],
        ["firmware_download_status", "webpacdl_status"],
        ["device_boot_file", "device_provision_speed"],
        ["device_reboot_reason"],
    ],
    "Performance / CPU": [
        ["device_top", "system_cpu_stats"],
        ["system_load_average"],
        ["system_interrupts"],
        ["process_status"],
    ],
    "Service / Process": [
        ["system_service_status"],
        ["process_status"],
        ["process_zombie_state"],
        ["process_core_dump"],
    ],
}

LAYER2_NARRATIVE = {
    "Crash / Coredump": "Crash issue identified. Prioritize coredump metadata, process memory, zombie-state checks, and look for assert/abort/heap-corruption signals in returned logs.",
    "Network / Connectivity": "Network issue identified. Prioritize DNS, WAN reachability, routing, interface, and Ethernet health checks in that order.",
    "Memory": "Memory issue identified. Prioritize total/used/free memory, detailed memory stats, process RSS/VmPeak, and confirm whether a process restarted after pressure.",
    "Video / Audio": "Video or audio issue identified. Prioritize playback status, HDMI/EDID state, display geometry, and active app/client state.",
    "Firmware / OTA": "Firmware or OTA issue identified. Prioritize upgrade status, download state, boot/provisioning details, reboot reason, and log lines mentioning verification, flashing, abort, or rollback.",
    "Performance / CPU": "Performance issue identified. Prioritize CPU/top snapshots, load averages, interrupt distribution, and the busiest processes.",
    "Service / Process": "Service or process issue identified. Prioritize service state, process presence, zombie state, crash evidence, and startup failure logs.",
}

LOG_TRIAGE_PATTERNS = (
    "dmesg",
    "kernel",
    "segfault",
    "out of memory",
    "oom",
    "call trace",
    "warning:",
    "bug:",
    "watchdog",
    "hung_task",
    "rip:",
    "lr:",
    "ext4-fs error",
    "fatal",
    "assert",
    "core dumped",
)


def infer_platform_profile(available_tool_names: Sequence[str]) -> str:
    """Infer platform profile from env override or discovered tool names."""
    override = os.getenv("MCP_PLATFORM_PROFILE", "").strip().lower()
    if override in {"broadband", "video"}:
        return "Video" if override == "video" else "Broadband"

    for tool_name in available_tool_names:
        bare_name = _bare_tool_name(tool_name)
        if any(
            bare_name == marker or bare_name.startswith(marker)
            for marker in VIDEO_TOOL_MARKERS
        ):
            return "Video"

    return "Broadband"


def parse_issue_classification(text: Optional[str]) -> Optional[str]:
    """Parse an explicit 'Issue classified as:' line from assistant content."""
    if not text:
        return None

    match = re.search(r"issue\s+classified\s+as\s*:\s*(.+)", text, flags=re.IGNORECASE)
    if not match:
        return None

    candidate = match.group(1).strip()
    candidate = re.split(r"[\n\r]", candidate, maxsplit=1)[0].strip()
    return _normalize_classification(candidate)


def classify_issue_from_text(text: Optional[str]) -> Optional[str]:
    """Infer issue class from user text using the strategy keyword table."""
    if not text:
        return None

    haystack = text.lower()
    for label, keywords in ISSUE_CLASSIFICATIONS:
        if any(keyword in haystack for keyword in keywords):
            return label
    return None


def build_classification_prompt(
    *,
    available_tool_names: Sequence[str],
    current_user_message: Optional[str] = None,
) -> str:
    """Build a classification-only prompt for the strict two-pass workflow."""
    platform_profile = infer_platform_profile(available_tool_names)
    tool_inventory = ", ".join(available_tool_names) if available_tool_names else "none"

    sections = [
        "You are a device diagnostics classifier connected to live MCP tools.",
        f"Platform profile: {platform_profile}",
        f"Available tools: {tool_inventory}",
        "Classify only the latest user request into exactly one supported diagnostic issue type.",
        _build_issue_classification_section(),
        "Respond with exactly one line in this format: `Issue classified as: <type>`.",
        "Do not call tools. Do not answer the user's question. Do not add explanations, bullets, or extra prose.",
    ]

    if current_user_message:
        sections.append(f"Latest user request: {current_user_message}")

    return "\n\n".join(section for section in sections if section)


def build_layer2_injection_prompt(
    *,
    classification: str,
    available_tool_names: Sequence[str],
) -> Optional[str]:
    """Build the dynamic Layer 2 injection that follows a classification pass."""
    normalized = _normalize_classification(classification)
    if not normalized:
        return None

    sections = [f"Issue classified as: {normalized}."]
    narrative = LAYER2_NARRATIVE.get(normalized)
    if narrative:
        sections.append(narrative)

    issue_steps = _render_issue_steps(normalized, available_tool_names)
    if issue_steps:
        sections.append(issue_steps)

    sections.append(
        "Use only the available tool catalog. If a recommended tool is unavailable, say so explicitly instead of guessing."
    )
    sections.append(
        "Proceed with the next diagnostic turn using this issue branch and collect the most relevant fresh tool data first."
    )

    return "\n\n".join(sections)


def build_system_prompt(
    *,
    available_tool_names: Sequence[str],
    current_user_message: Optional[str] = None,
    assistant_content: Optional[str] = None,
    tool_result_contents: Optional[Iterable[str]] = None,
    conversation_summary: Optional[str] = None,
) -> str:
    """Build the static Layer 1 prompt plus opportunistic Layer 2 guidance."""
    platform_profile = infer_platform_profile(available_tool_names)
    tool_inventory = ", ".join(available_tool_names) if available_tool_names else "none"
    baseline_tools = _collect_baseline_tools(platform_profile, available_tool_names)
    classification = parse_issue_classification(assistant_content) or classify_issue_from_text(current_user_message)
    dynamic_sections = _build_dynamic_sections(
        classification=classification,
        available_tool_names=available_tool_names,
        tool_result_contents=list(tool_result_contents or []),
    )

    sections = [
        "You are a device diagnostics agent connected to live MCP tools.",
        f"Platform profile: {platform_profile}",
        f"Available tools: {tool_inventory}",
        "Do not call any tool that is not in the available tool list above.",
        "If a required tool is unavailable, say so explicitly instead of guessing.",
        "For every new user question, fetch fresh real-time data instead of relying on earlier tool results from this session.",
        "If the request needs data from more than one independent tool, call all relevant tools together as parallel tool calls in your first tool-calling response.",
        "Do not serialize independent checks across multiple turns when they can be requested together.",
        _build_issue_classification_section(),
    ]

    if conversation_summary:
        sections.append("Conversation summary:\n" + conversation_summary)

    if baseline_tools:
        sections.append(
            "Before issue-specific investigation, collect these baseline tools when available: "
            + ", ".join(baseline_tools)
            + ". Include their outputs in the final diagnostic summary."
        )

    sections.append(_build_summary_format_section())

    if dynamic_sections:
        sections.append("Dynamic diagnostic guidance:\n" + "\n\n".join(dynamic_sections))

    sections.append(
        "When you receive tool results, explain what you found, provide context, highlight anomalies, and reference concrete values instead of repeating raw JSON."
    )
    sections.append(
        "When a tool fails, explain the failure, likely causes, and the next best diagnostic action."
    )

    return "\n\n".join(section for section in sections if section)


def _build_dynamic_sections(
    *,
    classification: Optional[str],
    available_tool_names: Sequence[str],
    tool_result_contents: Sequence[str],
) -> List[str]:
    sections: List[str] = []

    if classification:
        sections.append(f"Issue classified as: {classification}")
        narrative = LAYER2_NARRATIVE.get(classification)
        if narrative:
            sections.append(narrative)

        issue_steps = _render_issue_steps(classification, available_tool_names)
        if issue_steps:
            sections.append(issue_steps)

    if _should_inject_log_triage(tool_result_contents):
        sections.append(
            "Log and dmesg triage: analyse returned logs for segfaults, OOM kills, BUG/WARNING lines, Call Trace frames, watchdog or hung-task events, RIP/LR pointers, filesystem errors, and application ERROR/FATAL/ASSERT markers. Correlate findings with the device fault timestamp when available."
        )

    return sections


def _build_issue_classification_section() -> str:
    entries = []
    for label, keywords in ISSUE_CLASSIFICATIONS:
        entries.append(f"- {label}: {', '.join(keywords[:4])}")

    return (
        "Before running issue-specific diagnostics, classify the issue and state it explicitly as `Issue classified as: <type>`. "
        "Use one of these types:\n" + "\n".join(entries)
    )


def _build_summary_format_section() -> str:
    return (
        "Always end with this structure:\n"
        "## Diagnostic Summary\n"
        "**Issue Type:** <classified type>\n"
        "**Device:** <model / firmware version>\n"
        "**Timestamp of fault:** <from logs or unknown>\n\n"
        "### Root Cause Assessment\n"
        "<1-3 sentences>\n\n"
        "### Evidence\n"
        "- Log excerpt: <key line(s) or none found>\n"
        "- Coredump / core_log.txt: <signal, address, top frame, or none found>\n"
        "- Kernel message: <relevant dmesg line, or none found>\n\n"
        "### Impact\n"
        "<what is broken and what still works>\n\n"
        "### Recommended Actions\n"
        "1. <Immediate fix or workaround>\n"
        "2. <Further investigation needed>\n"
        "3. <Long-term fix>"
    )


def _collect_baseline_tools(platform_profile: str, available_tool_names: Sequence[str]) -> List[str]:
    resolved: List[str] = []
    for candidates in BASELINE_TOOL_CANDIDATES.get(platform_profile, []):
        match = _find_tool_match(candidates, available_tool_names)
        if match:
            resolved.append(match)
    return resolved


def _render_issue_steps(classification: str, available_tool_names: Sequence[str]) -> Optional[str]:
    candidate_groups = LAYER2_TOOL_CANDIDATES.get(classification, [])
    if not candidate_groups:
        return None

    rendered_steps: List[str] = []
    for index, candidates in enumerate(candidate_groups, start=1):
        resolved = _find_all_tool_matches(candidates, available_tool_names)
        if resolved:
            rendered_steps.append(f"{index}. " + " + ".join(resolved))

    if not rendered_steps:
        return None

    return "Prioritize these available tools in order:\n" + "\n".join(rendered_steps)


def _find_tool_match(candidates: Sequence[str], available_tool_names: Sequence[str]) -> Optional[str]:
    for candidate in candidates:
        for available in available_tool_names:
            if _bare_tool_name(available) == candidate:
                return available
    return None


def _find_all_tool_matches(candidates: Sequence[str], available_tool_names: Sequence[str]) -> List[str]:
    matches: List[str] = []
    for candidate in candidates:
        for available in available_tool_names:
            if _bare_tool_name(available) == candidate:
                matches.append(available)
    return matches


def _should_inject_log_triage(tool_result_contents: Sequence[str]) -> bool:
    for content in tool_result_contents:
        lowered = (content or "").lower()
        if any(pattern in lowered for pattern in LOG_TRIAGE_PATTERNS):
            return True
    return False


def _normalize_classification(value: str) -> Optional[str]:
    compact = re.sub(r"[^a-z]+", " ", value.lower()).strip()
    if compact in ISSUE_CLASSIFICATION_ALIASES:
        return ISSUE_CLASSIFICATION_ALIASES[compact]

    for label, _ in ISSUE_CLASSIFICATIONS:
        if compact == re.sub(r"[^a-z]+", " ", label.lower()).strip():
            return label
    return None


def _bare_tool_name(tool_name: str) -> str:
    return tool_name.split("__", 1)[-1]