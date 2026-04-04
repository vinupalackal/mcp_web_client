"""
MCP Client Web - FastAPI Application
LibreChat-inspired interface for MCP server communication via JSON-RPC 2.0
"""

from __future__ import annotations

import logging
import os
import json
import inspect
import re
import sys
import asyncio
import uuid
import httpx
from pathlib import Path as PathLib
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path, Body, Query, status, Request, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Any, List, Optional, Dict, Callable
from datetime import datetime, timezone


CURRENT_DIR = PathLib(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.models import (
    ServerConfig,
    LLMConfig,
    MilvusConfig,
    EnterpriseTokenRequest,
    EnterpriseTokenResponse,
    EnterpriseTokenStatusResponse,
    ChatMessage,
    ChatResponse,
    SessionConfig,
    SessionResponse,
    MessageListResponse,
    ToolSchema,
    ToolTestPrompt,
    ToolTestOutputRequest,
    ToolTestOutputResponse,
    ToolRefreshResponse,
    ServerHealthRefreshResponse,
    DeleteResponse,
    ErrorResponse,
    HealthResponse,
    RepeatedExecSummary,
    UserProfile,
    UserSettings,
    UserSettingsPatch,
    AdminUserPatch,
    UserListResponse,
    MemoryMaintenanceRequest,
    MemoryMaintenanceResponse,
    MemoryIngestTriggerRequest,
    MemoryIngestTriggerResponse,
    MemoryCollectionRowCount,
    MemoryRowCountsResponse,
    QualityReportResponse,
    FreshnessCandidatesResponse,
)

# SSO imports (v0.4.0-sso-user-settings)
try:
    from backend.database import init_db, upsert_user, get_user_by_id
    from backend.database import UserRow, SessionLocal
except ModuleNotFoundError as exc:
    if exc.name == "sqlalchemy":
        raise RuntimeError(
            "Missing required dependency 'sqlalchemy'. Activate the project's virtual "
            "environment and install dependencies with 'python -m pip install -r requirements.txt'. "
            "If you launch via uvicorn, prefer 'python -m uvicorn backend.main:app --reload'."
        ) from exc
    raise

from backend.user_store import (
    UserScopedLLMConfigStore,
    UserScopedServerStore,
    UserSettingsStore,
)
from backend.auth.jwt_utils import issue_app_token, verify_app_token
from backend.auth.pkce import generate_pkce_pair, generate_state_token

# Conditionally import SSO providers (only if configured)
_sso_providers: Dict[str, object] = {}

def _load_sso_providers() -> None:
    """Load whichever OIDC providers have all required env vars configured."""
    try:
        from backend.auth.azure_ad import AzureADProvider
        if AzureADProvider.is_configured():
            _sso_providers["azure_ad"] = AzureADProvider()
            logger_internal.info("SSO: Azure AD provider loaded")
    except Exception as exc:
        logger_internal.debug(f"Azure AD provider not loaded: {exc}")

    try:
        from backend.auth.google import GoogleProvider
        if GoogleProvider.is_configured():
            _sso_providers["google"] = GoogleProvider()
            logger_internal.info("SSO: Google provider loaded")
    except Exception as exc:
        logger_internal.debug(f"Google provider not loaded: {exc}")


def _sso_enabled() -> bool:
    """Return True when SSO is fully configured (SECRET_KEY + at least one IdP)."""
    return bool(os.getenv("SECRET_KEY")) and bool(_sso_providers)


# Per-user store singletons (used when SSO is active)
_llm_store = UserScopedLLMConfigStore()
_server_store = UserScopedServerStore()
_settings_store = UserSettingsStore()

# In-memory PKCE state store: state_token → {nonce, code_verifier, provider}
# (per-process; cleared on restart — PKCE flows are short-lived)
_pkce_state: Dict[str, dict] = {}

# Admin emails allowlist (comma-separated in env)
def _get_admin_emails() -> list:
    raw = os.getenv("SSO_ADMIN_EMAILS", "")
    return [e.strip().lower() for e in raw.split(",") if e.strip()]

# Load environment variables from .env file
env_path = PathLib(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Configure loggers (dual-logger pattern)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger_internal = logging.getLogger("mcp_client.internal")
logger_external = logging.getLogger("mcp_client.external")

# Import managers
from backend.mcp_manager import mcp_manager
from backend.llm_client import LLMClientFactory
from backend.prompt_injection import (
    build_classification_prompt,
    build_layer2_injection_prompt,
    build_system_prompt,
    classify_issue_from_text,
    parse_issue_classification,
)
from backend.session_manager import SessionManager


DIRECT_QUERY_ROUTES: List[Dict[str, Any]] = [
    {
        "name": "free_memory",
        "patterns": [
            r"\bhow much free memory\b",
            r"\bfree memory\b",
            r"\bmemory free\b",
            r"\bavailable memory\b",
            r"\bmemory available\b",
        ],
        "tool_candidates": [
            ["system_memory_free", "get_memory_info", "system_memory_stats"],
        ],
    },
    {
        "name": "uptime",
        "patterns": [
            r"\buptime\b",
            r"\bhow long .*up\b",
            r"\bhow long.*running\b",    # "how long has this device been running"
            r"\bwithout.*reboot\b",       # "without a reboot"
            r"\bsince.*reboot\b",         # "since last reboot"
            r"\blast\s+reboot\b",         # "last reboot time"
            r"\btime.*running\b",         # "time it's been running"
        ],
        "tool_candidates": [
            ["get_system_uptime", "get_uptime"],
        ],
    },
    {
        "name": "cpu_usage",
        "patterns": [
            r"\bcpu usage\b",
            r"\bcpu load\b",
            r"\bload average\b",
        ],
        "tool_candidates": [
            ["get_cpu_usage"],
            ["system_cpu_stats"],
            ["get_load_average", "system_load_average"],
        ],
    },
    {
        "name": "disk_usage",
        "patterns": [
            r"\bdisk usage\b",
            r"\bfree disk\b",
            r"\bdisk space\b",
        ],
        "tool_candidates": [
            ["get_disk_usage", "system_disk_space", "check_disk_space", "get_disk_stats"],
        ],
    },
    {
        "name": "wan_ip",
        "patterns": [
            r"\bwan ip\b",
            r"\bpublic ip\b",
            r"\bexternal ip\b",
        ],
        "tool_candidates": [
            ["get_wan_ip_config"],
            ["get_wan_connection_status", "wan_status"],
        ],
    },
    {
        "name": "kernel_logs",
        "patterns": [
            r"\bdmesg\b",
            r"\bkernel\s+log[s]?\b",
            r"\bkernel\s+message[s]?\b",
            r"\blast\s+\d+\s+kernel\b",      # "last 100 kernel lines"
            r"\bsyslog\b",
            r"\bklog\b",
            r"\bjournalctl\b",
            r"\bboot\s+log[s]?\b",
        ],
        "tool_candidates": [
            ["get_dmesg", "dmesg_log", "kernel_logs", "get_kernel_logs", "kernel_log"],
            ["get_syslog", "syslog"],
            ["get_service_logs", "system_logs"],
        ],
    },
]

REQUEST_DOMAIN_PATTERNS: Dict[str, tuple[str, ...]] = {
    "memory": (
        r"\bmemory\b",
        r"\bmemfree\b",
        r"\bmemavailable\b",
        r"\brss\b",
        r"\bswap\b",
        r"\boom\b",
    ),
    "cpu": (
        r"\bcpu\b",
        r"\bload\b",
        r"\butili[sz]ation\b",
        r"\bspin\b",
        r"\binterrupts\b",
    ),
    "uptime": (
        r"\buptime\b",
        r"\bboot time\b",
        r"\breboot(?:ed)?\b",
    ),
    "network": (
        r"\bwan\b",
        r"\blan\b",
        r"\bdns\b",
        r"\bping\b",
        r"\broute\b",
        r"\bconnect(?:ion|ivity)?\b",
        r"\bnetwork\b",
        r"\bdhcp\b",
        r"\bip\s+config(?:uration)?\b",  # specific: avoid false-positive on 'ip address X.X.X.X'
        r"\bip\s+route\b",
        r"\bip\s+addr(?:ess)?\s+(?:is|was|change|assign)\b",
    ),
    "disk": (
        r"\bdisk\b",
        r"\bstorage\b",
        r"\bfilesystem\b",
        r"\binode\b",
    ),
    "wifi": (
        r"\bwifi\b",
        r"\bwireless\b",
        r"\bssid\b",
        r"\bradio\b",
        r"\bclient[s]?\b",
    ),
    "logs": (
        r"\blog[s]?\b",
        r"\bdmesg\b",
        r"\bkernel\b",
        r"\berror[s]?\b",
        r"\btrace\b",
    ),
}

# Maps domain names → tool-name substrings that indicate a tool is relevant
# to that domain.  Used by _narrow_tools_by_domain() to reduce the 265-tool
# catalog to a focused set before handing it to the LLM.  This prevents the
# LLM from calling audio/video/HDMI tools when the user asks for kernel logs.
DOMAIN_TOOL_KEYWORDS: Dict[str, List[str]] = {
    "logs":    ["log", "dmesg", "kern", "syslog", "journal", "event", "trace", "audit"],
    "memory":  ["mem", "memory", "heap", "ram", "swap", "oom", "vmstat"],
    "cpu":     ["cpu", "proc", "load", "util", "thread", "scheduler", "irq"],
    "network": ["net", "wan", "lan", "ip", "dns", "route", "dhcp", "firewall",
                "ping", "socket", "arp", "nft", "iptable"],
    "disk":    ["disk", "storage", "fs", "mount", "filesystem", "partition",
                "block", "inode", "df", "du"],
    "wifi":    ["wifi", "wireless", "wlan", "ssid", "radio", "beacon", "station",
                "ap", "wpa"],
    "uptime":  ["uptime", "boot", "reboot", "running", "start"],
}


def _narrow_tools_by_domain(
    tools_for_llm: List[Dict[str, Any]],
    matched_domains: List[str],
) -> List[Dict[str, Any]]:
    """Filter the LLM tool catalog to only tools relevant to the matched domains.

    When a targeted_status query matches e.g. ["logs"], this reduces a
    265-tool catalog to only the handful of tools whose bare names contain
    "log", "dmesg", "kern", etc., preventing the LLM from being presented
    with (and then calling) unrelated audio/video/HDMI tools.

    Falls back to the full catalog if no tools survive the filter (safety net).
    The virtual mcp_repeated_exec tool is always preserved.
    """
    if not matched_domains:
        return tools_for_llm

    target_keywords: List[str] = []
    for domain in matched_domains:
        target_keywords.extend(DOMAIN_TOOL_KEYWORDS.get(domain, []))

    if not target_keywords:
        return tools_for_llm

    narrowed: List[Dict[str, Any]] = []
    virtual_tools: List[Dict[str, Any]] = []

    for tool in tools_for_llm:
        tool_name = tool.get("function", {}).get("name", "").lower()
        if tool_name == "mcp_repeated_exec":
            virtual_tools.append(tool)
            continue
        bare_name = tool_name.split("__", 1)[-1] if "__" in tool_name else tool_name
        if any(kw in bare_name for kw in target_keywords):
            narrowed.append(tool)

    if not narrowed:
        logger_internal.warning(
            "Domain narrowing found 0 matching tools for domains=%s keywords=%s; using full catalog",
            matched_domains, target_keywords,
        )
        return tools_for_llm

    logger_internal.info(
        "Domain narrowing: %s tools → %s tools for domains=%s",
        len(tools_for_llm) - len(virtual_tools),
        len(narrowed),
        matched_domains,
    )
    return narrowed + virtual_tools


def _dedupe_llm_tool_catalog(
    tools_for_llm: List[Dict[str, Any]],
    *,
    context_label: str,
) -> List[Dict[str, Any]]:
    """Remove duplicate tool entries by function name while preserving order."""
    deduped: List[Dict[str, Any]] = []
    seen_names: set[str] = set()

    for tool in tools_for_llm:
        tool_name = tool.get("function", {}).get("name", "")
        if not tool_name:
            deduped.append(tool)
            continue
        if tool_name in seen_names:
            continue
        seen_names.add(tool_name)
        deduped.append(tool)

    removed_count = len(tools_for_llm) - len(deduped)
    if removed_count > 0:
        logger_internal.info(
            "LLM tool catalog deduped for %s: removed %s duplicate tool entr%s",
            context_label,
            removed_count,
            "y" if removed_count == 1 else "ies",
        )

    return deduped


def _dedupe_llm_tool_catalog_and_chunks(
    tools_for_llm: List[Dict[str, Any]],
    tool_chunks: List[List[Dict[str, Any]]],
    *,
    context_label: str,
) -> tuple[List[Dict[str, Any]], List[List[Dict[str, Any]]]]:
    """Deduplicate a tool catalog and all of its chunks with consistent labels."""
    deduped_tools = _dedupe_llm_tool_catalog(
        tools_for_llm,
        context_label=context_label,
    )
    deduped_chunks = [
        _dedupe_llm_tool_catalog(
            chunk,
            context_label=f"{context_label} chunk {idx}",
        )
        for idx, chunk in enumerate(tool_chunks, 1)
    ]
    return deduped_tools, deduped_chunks


def _rechunk_llm_tool_catalog(
    tools_for_llm: List[Dict[str, Any]],
    *,
    effective_limit: int,
    include_virtual_repeated: bool,
) -> List[List[Dict[str, Any]]]:
    """Split a tool catalog into chunks while preserving virtual-tool placement."""
    virtual_slot = 1 if include_virtual_repeated else 0
    effective_chunk_size = max(1, effective_limit - virtual_slot)
    real_tools = [
        tool for tool in tools_for_llm
        if tool.get("function", {}).get("name") != "mcp_repeated_exec"
    ]
    virtual_tools = [
        tool for tool in tools_for_llm
        if tool.get("function", {}).get("name") == "mcp_repeated_exec"
    ]

    if len(real_tools) <= effective_chunk_size:
        return [real_tools + virtual_tools]

    return [
        real_tools[offset: offset + effective_chunk_size] + virtual_tools
        for offset in range(0, len(real_tools), effective_chunk_size)
    ]


FOLLOW_UP_PATTERNS = (
    r"\bwhat about\b",
    r"\bhow about\b",
    r"\bsame device\b",
    r"\bsame issue\b",
    r"\bwhat changed\b",
    r"\bnow\b",
    r"\bagain\b",
    r"\bcompare\b",
    r"\bstill\b",
)

TARGETED_STATUS_PATTERNS = (
    r"\bcheck\b",
    r"\bshow\b",
    r"\bstatus\b",
    r"\busage\b",
    r"\blist\b",
    r"\bmetrics\b",
)

DIAGNOSTIC_REQUEST_KEYWORDS = (
    "diagnose",
    "diagnostic",
    "root cause",
    "investigate",
    "analysis",
    "analyze",
    "problem",
    "issue",
    "failing",
    "failure",
    "crash",
    "coredump",
    "hang",
    "freeze",
    "slow",
    "high load",
    "memory leak",
    "oom",
)

EXPLANATION_REQUEST_PATTERNS = (
    r"\bwhy\b",
    r"\broot cause\b",
    r"\breason\b",
    r"\binvestigate\b",
    r"\bexplain\b",
)

VAGUE_STATUS_PATTERNS = (
    r"\bhealth\b",
    r"\bcheck device\b",
    r"\bcheck system\b",
    r"\bshow system info\b",
    r"\bshow info\b",
)

PRIOR_CONTEXT_REFERENCES = (
    r"\bthat\b",
    r"\bit\b",
    r"\bthose\b",
    r"\bbefore\b",
    r"\bearlier\b",
    r"\bprevious\b",
)

WORKFLOW_ACTION_PATTERNS = (
    r"\bthen\b",
    r"\bsummarize\b",
    r"\bexecute\b",
    r"\brun\b",
    r"\bcall\b",
)

REQUEST_MODES = (
    "direct_fact",
    "targeted_status",
    "full_diagnostic",
    "follow_up",
)

# Initialize managers
session_manager = SessionManager()

# In-memory storage
servers_storage: dict[str, ServerConfig] = {}
llm_config_storage: Optional[LLMConfig] = None
milvus_config_storage: Optional[MilvusConfig] = None
enterprise_token_cache: dict[str, object] = {}
_memory_service: Optional[Any] = None
# Tools now managed by mcp_manager

# Persistent storage directory (credentials live here, not in the browser)
MCP_DATA_DIR = PathLib(os.getenv("MCP_DATA_DIR", "./data"))
USAGE_EXAMPLES_PATH = PROJECT_ROOT / "docs" / "USAGE-EXAMPLES.md"


def _load_tool_test_prompts() -> List[ToolTestPrompt]:
    """Parse documented example user prompts from USAGE-EXAMPLES.md."""
    if not USAGE_EXAMPLES_PATH.exists():
        logger_internal.warning("Usage examples file not found: %s", USAGE_EXAMPLES_PATH)
        return []

    try:
        lines = USAGE_EXAMPLES_PATH.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger_internal.error("Failed to read usage examples file: %s", exc)
        return []

    prompts: List[ToolTestPrompt] = []
    seen_tool_names: set[str] = set()
    current_tool_name: Optional[str] = None
    heading_pattern = re.compile(r"^##+\s+.*`([^`]+)`\s*$")

    line_index = 0
    while line_index < len(lines):
        stripped_line = lines[line_index].strip()
        heading_match = heading_pattern.match(stripped_line)
        if heading_match:
            current_tool_name = heading_match.group(1).strip()
            line_index += 1
            continue

        if stripped_line == "**User prompt**" and current_tool_name:
            prompt_start = line_index + 1
            while prompt_start < len(lines) and not lines[prompt_start].lstrip().startswith(">"):
                if lines[prompt_start].strip() and not lines[prompt_start].lstrip().startswith(">"):
                    break
                prompt_start += 1

            prompt_lines: List[str] = []
            while prompt_start < len(lines):
                prompt_line = lines[prompt_start].lstrip()
                if not prompt_line.startswith(">"):
                    break
                prompt_lines.append(prompt_line[1:].lstrip())
                prompt_start += 1

            prompt_text = "\n".join(prompt_lines).strip()
            if prompt_text and current_tool_name not in seen_tool_names:
                prompts.append(ToolTestPrompt(tool_name=current_tool_name, prompt=prompt_text))
                seen_tool_names.add(current_tool_name)

            current_tool_name = None
            line_index = prompt_start
            continue

        line_index += 1

    return prompts


def _write_tool_test_output(content: str) -> ToolTestOutputResponse:
    """Persist Tool Tester results to data/output.txt."""
    MCP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = MCP_DATA_DIR / "output.txt"
    normalized_content = content.rstrip() + "\n"
    output_path.write_text(normalized_content, encoding="utf-8")
    updated_at = datetime.utcnow()
    try:
        relative_path = output_path.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        relative_path = output_path
    return ToolTestOutputResponse(
        file_path=str(relative_path),
        bytes_written=len(normalized_content.encode("utf-8")),
        updated_at=updated_at,
    )


def _save_llm_config_to_disk(config: LLMConfig) -> None:
    """Persist LLM config (including credentials) to server-side disk."""
    try:
        MCP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        (MCP_DATA_DIR / "llm_config.json").write_text(config.model_dump_json(indent=2))
        logger_internal.info(f"LLM config persisted to disk (provider={config.provider})")
    except Exception as e:
        logger_internal.error(f"Failed to persist LLM config to disk: {e}")


def _load_llm_config_from_disk() -> "LLMConfig | None":
    """Load LLM config from server-side disk on startup."""
    config_file = MCP_DATA_DIR / "llm_config.json"
    if not config_file.exists():
        return None
    try:
        config = LLMConfig.model_validate_json(config_file.read_text())
        logger_internal.info(f"Loaded LLM config from disk (provider={config.provider})")
        return config
    except Exception as e:
        logger_internal.warning(f"Failed to load LLM config from disk: {e}")
        return None


def _save_servers_to_disk() -> None:
    """Persist all MCP server configs (including tokens) to server-side disk."""
    try:
        MCP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        import json as _json
        servers_list = [_json.loads(s.model_dump_json()) for s in servers_storage.values()]
        (MCP_DATA_DIR / "servers.json").write_text(_json.dumps(servers_list, indent=2))
        logger_internal.info(f"Servers persisted to disk ({len(servers_storage)} servers)")
    except Exception as e:
        logger_internal.error(f"Failed to persist servers to disk: {e}")


def _load_servers_from_disk() -> "dict[str, ServerConfig]":
    """Load MCP server configs from server-side disk on startup."""
    servers_file = MCP_DATA_DIR / "servers.json"
    if not servers_file.exists():
        return {}
    try:
        import json as _json
        data = _json.loads(servers_file.read_text())
        loaded = {s["server_id"]: ServerConfig.model_validate(s) for s in data}
        logger_internal.info(f"Loaded {len(loaded)} servers from disk")
        return loaded
    except Exception as e:
        logger_internal.warning(f"Failed to load servers from disk: {e}")
        return {}


def _default_milvus_config_from_env() -> MilvusConfig:
    """Build the effective Milvus config from environment defaults."""
    try:
        return MilvusConfig(
            enabled=_get_bool_env("MEMORY_ENABLED", False),
            milvus_uri=os.getenv("MEMORY_MILVUS_URI", ""),
            collection_prefix=os.getenv("MEMORY_COLLECTION_PREFIX", "mcp_client"),
            repo_id=os.getenv("MEMORY_REPO_ID", ""),
            collection_generation=os.getenv("MEMORY_COLLECTION_GENERATION", "v1"),
            max_results=_get_int_env("MEMORY_MAX_RESULTS", 5),
            retrieval_timeout_s=_get_float_env("MEMORY_RETRIEVAL_TIMEOUT_S", 15.0),
            degraded_mode=_get_bool_env("MEMORY_DEGRADED_MODE", True),
            enable_conversation_memory=_get_bool_env("MEMORY_CONVERSATION_ENABLED", False),
            conversation_retention_days=_get_int_env("MEMORY_CONVERSATION_RETENTION_DAYS", 7),
            enable_tool_cache=_get_bool_env("MEMORY_TOOL_CACHE_ENABLED", False),
            tool_cache_ttl_s=_get_float_env("MEMORY_TOOL_CACHE_TTL_S", 3600.0),
            tool_cache_allowlist=[
                t.strip()
                for t in os.getenv("MEMORY_TOOL_CACHE_ALLOWLIST", "").split(",")
                if t.strip()
            ],
            tool_cache_freshness_keywords=[
                kw.strip().lower()
                for kw in os.getenv("MEMORY_TOOL_CACHE_FRESHNESS_KEYWORDS", "").split(",")
                if kw.strip()
            ],
            enable_adaptive_learning=_get_bool_env("AQL_ENABLE", False),
            aql_quality_retention_days=_get_int_env("AQL_QUALITY_RETENTION_DAYS", 30),
            aql_min_records_for_routing=_get_int_env("AQL_MIN_RECORDS", 20),
            aql_affinity_confidence_threshold=_get_float_env("AQL_AFFINITY_THRESHOLD", 0.65),
            enable_expiry_cleanup=_get_bool_env("MEMORY_EXPIRY_CLEANUP_ENABLED", True),
            expiry_cleanup_interval_s=_get_float_env("MEMORY_EXPIRY_CLEANUP_INTERVAL_S", 300.0),
        )
    except Exception as exc:
        logger_internal.warning("Invalid Milvus env config; falling back to disabled defaults: %s", exc)
        return MilvusConfig()


def _redacted_milvus_uri(uri: str) -> str:
    """Mask credentials in a Milvus URI while leaving host/port visible for diagnostics."""
    if not uri:
        return "<empty>"
    return re.sub(r"://[^/@]+@", "://[REDACTED]@", uri)


def _memory_config_summary(config: MilvusConfig) -> str:
    """Return a compact, operator-friendly summary of active memory settings."""
    return (
        "enabled=%s uri=%s prefix=%s generation=%s timeout_s=%.1f repo_id=%s "
        "conversation=%s tool_cache=%s degraded_mode=%s"
    ) % (
        config.enabled,
        _redacted_milvus_uri(config.milvus_uri),
        config.collection_prefix,
        config.collection_generation,
        config.retrieval_timeout_s,
        config.repo_id or "<none>",
        config.enable_conversation_memory,
        config.enable_tool_cache,
        config.degraded_mode,
    )


def _save_milvus_config_to_disk(config: MilvusConfig) -> None:
    """Persist Milvus config to server-side disk."""
    try:
        MCP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        (MCP_DATA_DIR / "milvus_config.json").write_text(config.model_dump_json(indent=2))
        logger_internal.info("Milvus config persisted to disk")
        logger_internal.info("  %s", _memory_config_summary(config))
    except Exception as exc:
        logger_internal.error("Failed to persist Milvus config to disk: %s", exc)


def _load_milvus_config_from_disk() -> "MilvusConfig | None":
    """Load Milvus config from server-side disk on startup."""
    config_file = MCP_DATA_DIR / "milvus_config.json"
    if not config_file.exists():
        return None
    try:
        config = MilvusConfig.model_validate_json(config_file.read_text())
        logger_internal.info("Loaded Milvus config from disk")
        logger_internal.info("  %s", _memory_config_summary(config))
        return config
    except Exception as exc:
        logger_internal.warning("Failed to load Milvus config from disk: %s", exc)
        return None


def _get_effective_milvus_config() -> MilvusConfig:
    """Return the active Milvus config, preferring persisted state over env defaults."""
    return milvus_config_storage or _default_milvus_config_from_env()


def _milvus_startup_diagnostic(exc: Exception, milvus_uri: str) -> list[str]:
    """Return operator-facing guidance for common Milvus startup failures."""
    reason = str(exc).lower()
    redacted_uri = _redacted_milvus_uri(milvus_uri)

    if "no route to host" in reason or "network is unreachable" in reason:
        return [
            f"  Startup diagnostic: network unreachable / no route to host for {redacted_uri}",
            "  Suggested fix: verify the host/IP is correct, ensure this machine is on the right network/VPN, and confirm port 19530 is exposed/reachable from the app host",
        ]
    if "connection refused" in reason:
        return [
            f"  Startup diagnostic: connection refused for {redacted_uri}",
            "  Suggested fix: verify Milvus is running and listening on port 19530, and confirm Docker/Kubernetes port publishing if applicable",
        ]
    if "timed out" in reason or "timeout" in reason:
        return [
            f"  Startup diagnostic: connection timed out for {redacted_uri}",
            "  Suggested fix: verify routing/firewall rules to the Milvus host and check whether the server is overloaded or slow to accept connections",
        ]
    return []


def _initialize_memory_service(config: Optional[MilvusConfig] = None) -> Optional[Any]:
    """Create or tear down the in-process memory service using the active Milvus config."""
    global milvus_config_storage, _memory_service

    if config is not None:
        milvus_config_storage = config

    effective_config = _get_effective_milvus_config()
    _memory_service = None

    logger_internal.info("Memory subsystem init requested")
    logger_internal.info("  %s", _memory_config_summary(effective_config))

    if not effective_config.enabled:
        logger_internal.info("Memory subsystem disabled")
        logger_internal.info("  Memory-backed retrieval, conversation memory, and tool cache are inactive")
        return None

    if llm_config_storage is None:
        logger_internal.warning(
            "Memory subsystem enabled but no LLM config is loaded; skipping memory initialisation"
        )
        logger_internal.warning("  Startup continues without memory features")
        return None

    try:
        from backend.embedding_service import EmbeddingService
        from backend.memory_persistence import MemoryPersistence
        from backend.memory_service import MemoryService, MemoryServiceConfig
        from backend.milvus_store import MilvusStore

        _memory_service = MemoryService(
            embedding_service=EmbeddingService(
                llm_config_storage,
                enterprise_access_token=_get_cached_enterprise_token(),
            ),
            milvus_store=MilvusStore(
                milvus_uri=effective_config.milvus_uri,
                collection_prefix=effective_config.collection_prefix,
            ),
            memory_persistence=MemoryPersistence(),
            config=MemoryServiceConfig(
                enabled=True,
                repo_id=effective_config.repo_id,
                collection_generation=effective_config.collection_generation,
                max_results=effective_config.max_results,
                retrieval_timeout_s=effective_config.retrieval_timeout_s,
                degraded_mode=effective_config.degraded_mode,
                enable_conversation_memory=effective_config.enable_conversation_memory,
                conversation_retention_days=effective_config.conversation_retention_days,
                enable_tool_cache=effective_config.enable_tool_cache,
                tool_cache_ttl_s=effective_config.tool_cache_ttl_s,
                tool_cache_allowlist=tuple(effective_config.tool_cache_allowlist),
                tool_cache_freshness_keywords=tuple(
                    effective_config.tool_cache_freshness_keywords
                ) or MemoryServiceConfig().tool_cache_freshness_keywords,
                enable_adaptive_learning=effective_config.enable_adaptive_learning,
                aql_quality_retention_days=effective_config.aql_quality_retention_days,
                aql_min_records_for_routing=effective_config.aql_min_records_for_routing,
                aql_affinity_confidence_threshold=effective_config.aql_affinity_confidence_threshold,
                aql_chunk_reorder_threshold=effective_config.aql_chunk_reorder_threshold,
                aql_affinity_weights=dict(effective_config.aql_affinity_weights),
                aql_correction_patterns=tuple(effective_config.aql_correction_patterns),
                enable_expiry_cleanup=effective_config.enable_expiry_cleanup,
                expiry_cleanup_interval_s=effective_config.expiry_cleanup_interval_s,
            ),
        )
        if hasattr(_memory_service, "run_expiry_cleanup_if_due"):
            _memory_service.run_expiry_cleanup_if_due(force=True)
        logger_internal.info("Memory subsystem initialized")
        logger_internal.info(
            "  Milvus reachable at %s; memory features are active",
            _redacted_milvus_uri(effective_config.milvus_uri),
        )
        return _memory_service
    except Exception as exc:
        logger_internal.warning("Memory subsystem initialization failed: %s", exc)
        logger_internal.warning(
            "  Milvus connection failed for %s",
            _redacted_milvus_uri(effective_config.milvus_uri),
        )
        for diagnostic_line in _milvus_startup_diagnostic(exc, effective_config.milvus_uri):
            logger_internal.warning(diagnostic_line)
        logger_internal.warning(
            "  Continuing startup without memory features; chat stays available but retrieval, conversation memory, and tool cache are inactive"
        )
        _memory_service = None
        return None


def _get_enterprise_token_status() -> EnterpriseTokenStatusResponse:
    """Return current enterprise token cache status."""
    if not enterprise_token_cache.get("access_token"):
        return EnterpriseTokenStatusResponse(
            token_cached=False,
            cached_at=None,
            expires_in=None
        )

    return EnterpriseTokenStatusResponse(
        token_cached=True,
        cached_at=enterprise_token_cache.get("cached_at"),
        expires_in=enterprise_token_cache.get("expires_in")
    )


def _get_cached_enterprise_token() -> Optional[str]:
    """Get cached enterprise token if available."""
    access_token = enterprise_token_cache.get("access_token")
    return access_token if isinstance(access_token, str) and access_token else None


def _redacted_token_request_curl(token_request: EnterpriseTokenRequest) -> str:
    """Build a redacted curl equivalent for enterprise token acquisition logs."""
    return (
        "curl --location --request POST "
        f"'{token_request.token_endpoint_url}' \\\n+  --header 'Content-Type: application/json' \\\n+  --header 'X-Client-Id: [REDACTED]' \\\n+  --header 'X-Client-Secret: [REDACTED]' \\\n+  --data ''"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    global llm_config_storage, milvus_config_storage
    logger_internal.info("🚀 MCP Client Web starting up")
    logger_internal.info(f"Environment: MCP_ALLOW_HTTP_INSECURE={os.getenv('MCP_ALLOW_HTTP_INSECURE', 'false')}")
    logger_internal.info(f"Data directory: {MCP_DATA_DIR.resolve()}")

    # Initialise DB schema (creates tables if not present)
    try:
        init_db()
    except Exception as exc:
        logger_internal.error(f"DB init failed: {exc}")

    # Load SSO providers
    _load_sso_providers()
    if _sso_enabled():
        logger_internal.info(
            f"SSO enabled with providers: {list(_sso_providers.keys())}"
        )
    else:
        logger_internal.info("SSO not configured — running in single-user mode")

    # Load persisted credentials and configs from server-side disk
    loaded_config = _load_llm_config_from_disk()
    if loaded_config:
        llm_config_storage = loaded_config
    loaded_servers = _load_servers_from_disk()
    if loaded_servers:
        servers_storage.update(loaded_servers)

    milvus_config_storage = _load_milvus_config_from_disk() or _default_milvus_config_from_env()
    _initialize_memory_service()
    if _memory_service is not None:
        _memory_service._print_milvus_db_snapshot("STARTUP")

    yield
    logger_internal.info("👋 MCP Client Web shutting down")


# Initialize FastAPI app
app = FastAPI(
    title="MCP Client Web API",
    version="0.2.0-jsonrpc",
    description="LibreChat-inspired MCP client with JSON-RPC 2.0 support for distributed tool execution",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# CORS middleware (configure for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth middleware — validates app_token cookie on /api/* routes when SSO is on
# ---------------------------------------------------------------------------

_SSO_SKIP_PREFIXES = (
    "/auth/",
    "/static/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
    "/login",
    "/api/health",
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Attach current_user to request.state when SSO is active."""
    if not _sso_enabled():
        request.state.current_user = None
        return await call_next(request)

    path = request.url.path
    if any(path.startswith(p) for p in _SSO_SKIP_PREFIXES):
        request.state.current_user = None
        return await call_next(request)

    token = request.cookies.get("app_token")
    if not token:
        if path.startswith("/api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )
        return RedirectResponse(url="/login", status_code=302)

    import jwt as _jwt
    try:
        claims = verify_app_token(token)
    except _jwt.ExpiredSignatureError:
        if path.startswith("/api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"detail": "Session expired"},
            )
        return RedirectResponse(url="/login?reason=session_expired", status_code=302)
    except _jwt.InvalidTokenError:
        if path.startswith("/api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )
        return RedirectResponse(url="/login", status_code=302)

    user = get_user_by_id(claims["sub"])
    if user is None or not user.is_active:
        if path.startswith("/api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={"detail": "Account disabled"},
            )
        return RedirectResponse(url="/login", status_code=302)

    request.state.current_user = user
    return await call_next(request)


# ---------------------------------------------------------------------------
# FastAPI dependency helpers
# ---------------------------------------------------------------------------

def _get_current_user(request: Request) -> Optional[UserRow]:
    """Return current_user or None (no-op in single-user mode)."""
    return getattr(request.state, "current_user", None)


def _require_user(request: Request) -> UserRow:
    """Raise 401 if not authenticated (only enforced when SSO is enabled)."""
    user = getattr(request.state, "current_user", None)
    if _sso_enabled() and user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user  # type: ignore[return-value]


def _require_admin(request: Request) -> UserRow:
    """Raise 403 if user is not an admin."""
    user = _require_user(request)
    if user is not None:
        import json as _json
        roles = _json.loads(user.roles) if isinstance(user.roles, str) else (user.roles or [])
        if "admin" not in roles:
            raise HTTPException(status_code=403, detail="Admin role required")
    return user  # type: ignore[return-value]


def _user_id_or_none(request: Request) -> Optional[str]:
    user = getattr(request.state, "current_user", None)
    return user.user_id if user else None


def _make_user_profile(row: UserRow) -> UserProfile:
    import json as _json
    roles = _json.loads(row.roles) if isinstance(row.roles, str) else (row.roles or ["user"])
    return UserProfile(
        user_id=row.user_id,
        email=row.email,
        display_name=row.display_name,
        avatar_url=row.avatar_url,
        roles=roles,
        created_at=row.created_at,
        last_login_at=row.last_login_at,
    )


# Helper: resolve servers — per-user when SSO, global dict otherwise
def _get_user_servers(user_id: Optional[str]) -> List[ServerConfig]:
    if user_id:
        return _server_store.list(user_id)
    return list(servers_storage.values())


def _get_user_llm_config(user_id: Optional[str]) -> Optional[LLMConfig]:
    if user_id:
        return _llm_store.get_full(user_id)
    return llm_config_storage


def _normalize_user_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _matches_any_pattern(text: str, patterns: tuple[str, ...] | List[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _extract_request_domains(message_content: str) -> List[str]:
    normalized_message = _normalize_user_text(message_content)
    matched_domains: List[str] = []

    for domain_name, patterns in REQUEST_DOMAIN_PATTERNS.items():
        if _matches_any_pattern(normalized_message, patterns):
            matched_domains.append(domain_name)

    return matched_domains


def _has_recent_device_context(conversation_summary: Optional[str]) -> bool:
    if not conversation_summary:
        return False
    normalized_summary = _normalize_user_text(conversation_summary)
    return any(marker in normalized_summary for marker in (
        "device",
        "ip",
        "mac",
        "model",
        "firmware",
    ))


def _references_prior_context(message_content: str, conversation_summary: Optional[str]) -> bool:
    if not conversation_summary:
        return False
    normalized_message = _normalize_user_text(message_content)
    return _matches_any_pattern(normalized_message, FOLLOW_UP_PATTERNS) or _matches_any_pattern(
        normalized_message,
        PRIOR_CONTEXT_REFERENCES,
    )


def _count_direct_route_hits(message_content: str) -> int:
    normalized_message = _normalize_user_text(message_content)
    return sum(
        1
        for route in DIRECT_QUERY_ROUTES
        if any(re.search(pattern, normalized_message) for pattern in route["patterns"])
    )


def _compute_request_mode_scores(
    message_content: str,
    *,
    existing_messages: List[ChatMessage],
    direct_tool_route: Optional[Dict[str, Any]],
    conversation_summary: Optional[str],
) -> Dict[str, int]:
    normalized_message = _normalize_user_text(message_content)
    matched_domains = _extract_request_domains(message_content)
    has_history = len(existing_messages) > 0

    scores: Dict[str, int] = {
        "direct_fact": 0,
        "targeted_status": 0,
        "full_diagnostic": 0,
        "follow_up": 0,
    }

    if direct_tool_route is not None:
        scores["direct_fact"] += 6

    if _matches_any_pattern(normalized_message, FOLLOW_UP_PATTERNS):
        scores["follow_up"] += 4

    if _matches_any_pattern(normalized_message, TARGETED_STATUS_PATTERNS):
        scores["targeted_status"] += 3

    if _matches_any_pattern(normalized_message, EXPLANATION_REQUEST_PATTERNS) or _contains_any_keyword(
        normalized_message,
        DIAGNOSTIC_REQUEST_KEYWORDS,
    ):
        scores["full_diagnostic"] += 4

    if len(matched_domains) == 1:
        scores["direct_fact"] += 2
    elif len(matched_domains) >= 2:
        scores["targeted_status"] += 3

    direct_route_hits = _count_direct_route_hits(message_content)
    if direct_route_hits == 1:
        scores["direct_fact"] += 2
    elif direct_route_hits >= 2:
        scores["targeted_status"] += 2

    if _matches_any_pattern(normalized_message, VAGUE_STATUS_PATTERNS):
        scores["targeted_status"] += 2

    if _matches_any_pattern(normalized_message, WORKFLOW_ACTION_PATTERNS):
        scores["targeted_status"] += 3
        scores["direct_fact"] -= 2

    if not _contains_any_keyword(normalized_message, DIAGNOSTIC_REQUEST_KEYWORDS) and not _matches_any_pattern(
        normalized_message,
        EXPLANATION_REQUEST_PATTERNS,
    ):
        scores["direct_fact"] += 2
        scores["targeted_status"] += 1

    if re.match(r"^[a-z0-9_\-? ]{1,20}\?$", normalized_message) and len(matched_domains) <= 1:
        scores["direct_fact"] += 2

    if len(normalized_message.split()) <= 2 and direct_route_hits == 0 and len(matched_domains) == 1:
        scores["targeted_status"] += 3
        scores["direct_fact"] -= 1

    if has_history and _has_recent_device_context(conversation_summary):
        scores["follow_up"] += 2

    if has_history and _references_prior_context(message_content, conversation_summary):
        scores["follow_up"] += 2

    if _matches_any_pattern(normalized_message, EXPLANATION_REQUEST_PATTERNS):
        scores["full_diagnostic"] += 2
        scores["direct_fact"] -= 3

    if has_history and not _matches_any_pattern(normalized_message, FOLLOW_UP_PATTERNS) and len(matched_domains) == 0:
        scores["follow_up"] += 1

    return scores


def _compute_request_mode_confidence(scores: Dict[str, int], top_mode: str) -> float:
    top_score = scores.get(top_mode, 0)
    positive_total = sum(max(score, 0) for score in scores.values())
    if top_score <= 0 or positive_total <= 0:
        return 0.0
    return round(top_score / positive_total, 3)


def _get_bool_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _get_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return default


def _get_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


def _resolve_bool_override(value: Optional[bool], env_name: str, default: bool) -> bool:
    if value is not None:
        return bool(value)
    return _get_bool_env(env_name, default=default)


def _resolve_float_override(value: Optional[float], env_name: str, default: float) -> float:
    if value is not None:
        return float(value)
    return _get_float_env(env_name, default)


def _resolve_int_override(value: Optional[int], env_name: str, default: int) -> int:
    if value is not None:
        return int(value)
    return _get_int_env(env_name, default)


def _format_retrieval_context(blocks: List[Any]) -> str:
    """Render retrieval blocks into a compact system-context section."""
    lines = ["## Retrieved context"]
    for block in blocks:
        source_path = getattr(block, "source_path", "") or "unknown"
        collection = getattr(block, "collection", "memory") or "memory"
        snippet = getattr(block, "snippet", "") or ""
        lines.append(f"### {source_path} ({collection})")
        lines.append(snippet)
    return "\n\n".join(lines)


def _inject_context_section(messages: List[dict], context_section: Optional[str]) -> List[dict]:
    """Append context to a copied provider message list without mutating session history."""
    provider_messages = list(messages)
    if not context_section:
        return provider_messages

    if provider_messages and provider_messages[0].get("role") == "system":
        original_content = provider_messages[0].get("content", "")
        provider_messages[0] = {
            **provider_messages[0],
            "content": f"{original_content}\n\n{context_section}" if original_content else context_section,
        }
    else:
        provider_messages.insert(0, {"role": "system", "content": context_section})
    return provider_messages


def _should_consult_llm_mode_classifier(
    request_mode_details: Dict[str, Any],
    *,
    direct_tool_route: Optional[Dict[str, Any]],
    llm_config: LLMConfig,
) -> bool:
    if not _resolve_bool_override(
        llm_config.tiny_llm_mode_classifier_enabled,
        "MCP_ENABLE_LLM_MODE_CLASSIFIER",
        default=False,
    ):
        return False
    if llm_config.provider == "mock":
        return False
    if direct_tool_route is not None:
        return False

    min_confidence = _resolve_float_override(
        llm_config.tiny_llm_mode_classifier_min_confidence,
        "MCP_LLM_MODE_CLASSIFIER_MIN_CONFIDENCE",
        0.60,
    )
    min_score_gap = _resolve_int_override(
        llm_config.tiny_llm_mode_classifier_min_score_gap,
        "MCP_LLM_MODE_CLASSIFIER_MIN_SCORE_GAP",
        3,
    )

    return (
        request_mode_details.get("confidence", 0.0) < min_confidence
        or request_mode_details.get("score_gap", 0) < min_score_gap
    )


def _should_enable_split_phase_early_stop(
    *,
    request_mode: str,
    request_mode_details: Dict[str, Any],
) -> bool:
    if request_mode != "direct_fact":
        return False

    min_confidence = _get_float_env(
        "MCP_SPLIT_PHASE_DIRECT_FACT_EARLY_STOP_MIN_CONFIDENCE",
        0.75,
    )
    return float(request_mode_details.get("confidence", 0.0) or 0.0) >= min_confidence


def _split_phase_has_real_tool_calls(tool_calls: List[Dict[str, Any]]) -> bool:
    for tool_call in tool_calls:
        tool_name = tool_call.get("function", {}).get("name", "")
        if tool_name and tool_name != "mcp_repeated_exec":
            return True
    return False


def _should_batch_tool_results(num_tool_calls: int) -> bool:
    """Return True when the tool-call count exceeds the batch threshold.

    When True  → all MCP tools are fired concurrently and their results are
                 collected in a single asyncio.gather before the LLM sees any
                 of them (batch path).
    When False → tools are executed sequentially; results are still injected
                 together into the follow-up LLM request, but execution is
                 ordered rather than concurrent.  This avoids unnecessary
                 concurrency overhead for small tool sets.

    Threshold is controlled by ``MCP_TOOL_BATCH_THRESHOLD`` (default 3).
    """
    threshold = _get_int_env("MCP_TOOL_BATCH_THRESHOLD", 3)
    return num_tool_calls > threshold


def _merge_split_phase_tool_calls(chunk_results: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen: set = set()

    for chunk_calls in chunk_results:
        for tool_call in chunk_calls:
            tool_name = tool_call.get("function", {}).get("name", "")
            tool_args = tool_call.get("function", {}).get("arguments", "{}")
            if isinstance(tool_args, dict):
                tool_args = json.dumps(tool_args, sort_keys=True)
            dedup_key = (tool_name, tool_args)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            merged.append(tool_call)

    return merged


def _schedule_execution_quality_record(
    *,
    memory_service: Any,
    payload: Dict[str, Any],
) -> bool:
    """Schedule passive AQL quality recording without blocking the response path."""
    if memory_service is None:
        return False
    record_method = getattr(memory_service, "record_execution_quality", None)
    config = getattr(memory_service, "config", None)
    if not callable(record_method):
        return False
    if not getattr(config, "enable_adaptive_learning", False):
        return False

    task = asyncio.create_task(record_method(**payload))

    def _log_background_result(completed_task: asyncio.Task) -> None:
        try:
            completed_task.result()
        except Exception as error:  # pragma: no cover - defensive only
            logger_internal.warning("AQL quality background task failed: %s", error)

    task.add_done_callback(_log_background_result)
    return True


def _schedule_correction_patch(
    *,
    memory_service: Any,
    session_id: str,
    user_message: str,
    previous_turn_metadata: Optional[Dict[str, Any]],
) -> bool:
    """Schedule retroactive correction labeling for the previous quality record."""
    if memory_service is None:
        return False
    config = getattr(memory_service, "config", None)
    if not getattr(config, "enable_adaptive_learning", False):
        return False

    detector = getattr(memory_service, "is_correction_message", None)
    patch_method = getattr(memory_service, "patch_correction_signal", None)
    if not callable(detector) or not callable(patch_method):
        return False

    if not previous_turn_metadata:
        return False
    query_hash = str(previous_turn_metadata.get("query_hash", "")).strip()
    if not query_hash:
        return False

    try:
        if not detector(user_message):
            return False
    except Exception as error:  # pragma: no cover - defensive only
        logger_internal.warning("AQL correction detection failed: %s", error)
        return False

    task = asyncio.create_task(
        patch_method(session_id=session_id, query_hash=query_hash)
    )

    def _log_background_result(completed_task: asyncio.Task) -> None:
        try:
            completed_task.result()
        except Exception as error:  # pragma: no cover - defensive only
            logger_internal.warning("AQL correction background task failed: %s", error)

    task.add_done_callback(_log_background_result)
    return True


def _remember_last_quality_turn(
    *,
    memory_service: Any,
    session_id: str,
    user_message: str,
    request_id: str,
) -> bool:
    """Persist internal-only metadata needed to patch the immediately prior turn."""
    if memory_service is None:
        return False
    build_hash = getattr(memory_service, "build_quality_query_hash", None)
    if not callable(build_hash):
        return False
    try:
        query_hash = str(build_hash(user_message) or "").strip()
    except Exception as error:  # pragma: no cover - defensive only
        logger_internal.warning("AQL turn metadata generation failed: %s", error)
        return False
    if not query_hash:
        return False
    session_manager.set_last_turn_metadata(
        session_id,
        {
            "query_hash": query_hash,
            "request_id": request_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return True


async def _collect_split_phase_tool_calls(
    *,
    llm_client: Any,
    messages_snapshot: List[Dict[str, Any]],
    tool_chunks: List[List[Dict[str, Any]]],
    split_mode: str,
    request_mode: str,
    request_mode_details: Dict[str, Any],
    extract_tool_calls_from_content: Callable[[str, int], List[Dict[str, Any]]],
    chunk_yield_collector: Optional[Callable[[int, int, int], None]] = None,
) -> List[Dict[str, Any]]:
    ordinals = [
        "FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH",
        "SIXTH", "SEVENTH", "EIGHTH", "NINTH", "TENTH",
    ]
    stop_on_first_real_tool = _should_enable_split_phase_early_stop(
        request_mode=request_mode,
        request_mode_details=request_mode_details,
    )
    if stop_on_first_real_tool:
        logger_internal.info(
            "Split-phase early stop enabled: mode=%s confidence=%.2f min_confidence=%.2f chunks=%s",
            request_mode,
            float(request_mode_details.get("confidence", 0.0) or 0.0),
            _get_float_env("MCP_SPLIT_PHASE_DIRECT_FACT_EARLY_STOP_MIN_CONFIDENCE", 0.75),
            len(tool_chunks),
        )
        logger_external.info(
            "→ SPLIT EARLY-STOP ENABLED: mode=%s confidence=%.2f chunks=%s",
            request_mode,
            float(request_mode_details.get("confidence", 0.0) or 0.0),
            len(tool_chunks),
        )

    async def query_chunk(sp_idx: int, sp_chunk: List[Dict[str, Any]]) -> tuple[int, List[Dict[str, Any]]]:
        ordinal = ordinals[sp_idx - 1] if sp_idx <= len(ordinals) else f"#{sp_idx}"
        logger_external.info(
            "→ %s REQUEST TO LLM WITH SPLIT [%s]: Tools Count: %s",
            ordinal, split_mode.upper(), len(sp_chunk),
        )
        try:
            resp = await llm_client.chat_completion(
                messages=messages_snapshot,
                tools=sp_chunk,
            )
        except Exception as err:
            logger_internal.error(
                "Split-phase chunk %s/%s failed: %s",
                sp_idx, len(tool_chunks), err,
            )
            return sp_idx, []

        msg = resp["choices"][0]["message"]
        finish = resp["choices"][0].get("finish_reason", "")
        calls = msg.get("tool_calls") or []

        if not calls and msg.get("content"):
            calls = extract_tool_calls_from_content(msg.get("content", ""), sp_idx)

        logger_external.info(
            "← %s RESPONSE FROM LLM WITH SPLIT [%s]: %s tool call(s) requested, finish=%s",
            ordinal, split_mode.upper(), len(calls), finish,
        )
        return sp_idx, calls

    chunk_results: List[List[Dict[str, Any]]] = [[] for _ in tool_chunks]

    if split_mode == "sequential":
        logger_internal.info(
            "Split-phase mode=sequential: sending %s chunk(s) one after another",
            len(tool_chunks),
        )
        for seq_idx, seq_chunk in enumerate(tool_chunks, 1):
            chunk_index, chunk_calls = await query_chunk(seq_idx, seq_chunk)
            if chunk_yield_collector is not None:
                chunk_yield_collector(chunk_index, len(seq_chunk), len(chunk_calls))
            chunk_results[chunk_index - 1] = chunk_calls
            if stop_on_first_real_tool and _split_phase_has_real_tool_calls(chunk_calls):
                logger_internal.info(
                    "Split-phase early stop: direct_fact confidence=%.2f satisfied by chunk %s/%s; skipping remaining %s chunk(s)",
                    float(request_mode_details.get("confidence", 0.0) or 0.0),
                    chunk_index,
                    len(tool_chunks),
                    len(tool_chunks) - chunk_index,
                )
                break
    else:
        logger_internal.info(
            "Split-phase mode=concurrent: firing %s chunk(s) in parallel%s",
            len(tool_chunks),
            " with early-stop enabled" if stop_on_first_real_tool else "",
        )
        tasks = [
            asyncio.create_task(query_chunk(i + 1, chunk))
            for i, chunk in enumerate(tool_chunks)
        ]

        try:
            for completed in asyncio.as_completed(tasks):
                chunk_index, chunk_calls = await completed
                if chunk_yield_collector is not None:
                    chunk_yield_collector(chunk_index, len(tool_chunks[chunk_index - 1]), len(chunk_calls))
                chunk_results[chunk_index - 1] = chunk_calls
                if stop_on_first_real_tool and _split_phase_has_real_tool_calls(chunk_calls):
                    pending_tasks = [task for task in tasks if not task.done()]
                    logger_internal.info(
                        "Split-phase early stop: direct_fact confidence=%.2f satisfied by chunk %s/%s with %s tool call(s); cancelling %s pending chunk(s)",
                        float(request_mode_details.get("confidence", 0.0) or 0.0),
                        chunk_index,
                        len(tool_chunks),
                        len(chunk_calls),
                        len(pending_tasks),
                    )
                    for pending_task in pending_tasks:
                        pending_task.cancel()
                    if pending_tasks:
                        await asyncio.gather(*pending_tasks, return_exceptions=True)
                    break
        finally:
            leftover_tasks = [task for task in tasks if not task.done()]
            for leftover_task in leftover_tasks:
                leftover_task.cancel()
            if leftover_tasks:
                await asyncio.gather(*leftover_tasks, return_exceptions=True)

    return _merge_split_phase_tool_calls(chunk_results)


async def _stream_split_phase_tool_calls(
    *,
    llm_client: Any,
    messages_snapshot: List[Dict[str, Any]],
    tool_chunks: List[List[Dict[str, Any]]],
    split_mode: str,
    request_mode: str,
    request_mode_details: Dict[str, Any],
    extract_tool_calls_from_content: Callable[[str, int], List[Dict[str, Any]]],
    chunk_yield_collector: Optional[Callable[[int, int, int], None]] = None,
):
    """Async generator variant of _collect_split_phase_tool_calls.

    Yields (chunk_index, new_tool_calls, skipped_count) as each LLM chunk
    responds, so the caller can start MCP execution immediately instead of
    waiting for all chunks to complete first.  Deduplication is applied
    incrementally across all yielded batches via a shared seen-keys set.
    """
    ordinals = [
        "FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH",
        "SIXTH", "SEVENTH", "EIGHTH", "NINTH", "TENTH",
    ]
    stop_on_first_real_tool = _should_enable_split_phase_early_stop(
        request_mode=request_mode,
        request_mode_details=request_mode_details,
    )
    if stop_on_first_real_tool:
        logger_internal.info(
            "Split-phase pipeline early stop enabled: mode=%s confidence=%.2f chunks=%s",
            request_mode,
            float(request_mode_details.get("confidence", 0.0) or 0.0),
            len(tool_chunks),
        )

    seen_dedup_keys: set = set()

    def _filter_new_calls(
        calls: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], int]:
        """Return only tool calls not yet seen; second element is the skipped count."""
        new_calls: List[Dict[str, Any]] = []
        skipped = 0
        for call in calls:
            name = call.get("function", {}).get("name", "")
            args = call.get("function", {}).get("arguments", "{}")
            if isinstance(args, dict):
                args = json.dumps(args, sort_keys=True)
            key = (name, args)
            if key in seen_dedup_keys:
                skipped += 1
                continue
            seen_dedup_keys.add(key)
            new_calls.append(call)
        return new_calls, skipped

    async def query_chunk(
        sp_idx: int, sp_chunk: List[Dict[str, Any]]
    ) -> tuple[int, List[Dict[str, Any]]]:
        ordinal = ordinals[sp_idx - 1] if sp_idx <= len(ordinals) else f"#{sp_idx}"
        logger_external.info(
            "→ %s REQUEST TO LLM WITH SPLIT [%s]: Tools Count: %s",
            ordinal, split_mode.upper(), len(sp_chunk),
        )
        try:
            resp = await llm_client.chat_completion(
                messages=messages_snapshot,
                tools=sp_chunk,
            )
        except Exception as err:
            logger_internal.error(
                "Split-phase chunk %s/%s failed: %s",
                sp_idx, len(tool_chunks), err,
            )
            return sp_idx, []

        msg = resp["choices"][0]["message"]
        finish = resp["choices"][0].get("finish_reason", "")
        calls = msg.get("tool_calls") or []

        if not calls and msg.get("content"):
            calls = extract_tool_calls_from_content(msg.get("content", ""), sp_idx)

        logger_external.info(
            "← %s RESPONSE FROM LLM WITH SPLIT [%s]: %s tool call(s) requested, finish=%s",
            ordinal, split_mode.upper(), len(calls), finish,
        )
        return sp_idx, calls

    if split_mode == "sequential":
        logger_internal.info(
            "Split-phase pipeline mode=sequential: sending %s chunk(s) one after another",
            len(tool_chunks),
        )
        for seq_idx, seq_chunk in enumerate(tool_chunks, 1):
            chunk_index, chunk_calls = await query_chunk(seq_idx, seq_chunk)
            new_calls, skipped = _filter_new_calls(chunk_calls)
            if chunk_yield_collector is not None:
                chunk_yield_collector(chunk_index, len(seq_chunk), len(new_calls))
            yield chunk_index, new_calls, skipped
            if stop_on_first_real_tool and _split_phase_has_real_tool_calls(new_calls):
                logger_internal.info(
                    "Split-phase pipeline early stop: satisfied by chunk %s/%s; stopping sequential dispatch",
                    chunk_index, len(tool_chunks),
                )
                break
    else:
        logger_internal.info(
            "Split-phase pipeline mode=concurrent: firing %s chunk(s) in parallel",
            len(tool_chunks),
        )
        tasks = [
            asyncio.create_task(query_chunk(i + 1, chunk))
            for i, chunk in enumerate(tool_chunks)
        ]
        try:
            for completed in asyncio.as_completed(tasks):
                chunk_index, chunk_calls = await completed
                new_calls, skipped = _filter_new_calls(chunk_calls)
                if chunk_yield_collector is not None:
                    chunk_yield_collector(chunk_index, len(tool_chunks[chunk_index - 1]), len(new_calls))
                yield chunk_index, new_calls, skipped
                if stop_on_first_real_tool and _split_phase_has_real_tool_calls(new_calls):
                    pending_tasks = [t for t in tasks if not t.done()]
                    logger_internal.info(
                        "Split-phase pipeline early stop: satisfied by chunk %s/%s; cancelling %s pending chunk(s)",
                        chunk_index, len(tool_chunks), len(pending_tasks),
                    )
                    for pt in pending_tasks:
                        pt.cancel()
                    if pending_tasks:
                        await asyncio.gather(*pending_tasks, return_exceptions=True)
                    break
        finally:
            leftover_tasks = [t for t in tasks if not t.done()]
            for lt in leftover_tasks:
                lt.cancel()
            if leftover_tasks:
                await asyncio.gather(*leftover_tasks, return_exceptions=True)


async def _run_pipeline_execution(
    *,
    stream: Any,
    run_mcp_tool: Callable,
    tool_concurrency: int,
    num_chunks: int,
) -> tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Drive the split-phase pipeline.

    Consumes the async generator from _stream_split_phase_tool_calls(), fires
    one asyncio.Task per yielded tool call (bounded by a semaphore), then
    drains all tasks before returning.

    Returns:
        all_parsed  — ordered list of parsed tool-call dicts (same shape as
                      Phase-1 _parsed_tool_calls in the turn loop).
        results_map — tool_id → execution-result dict (same shape as
                      _parallel_results_map in Phase 2).
    """
    import time as _pt

    semaphore = asyncio.Semaphore(tool_concurrency)
    all_parsed: List[Dict[str, Any]] = []
    task_to_pc: Dict[Any, Dict[str, Any]] = {}

    async def _bounded_run(pc: Dict[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            return await run_mcp_tool(pc)

    # Consume the generator — start MCP tasks as each chunk yields new calls.
    async for chunk_index, new_calls, skipped in stream:
        idx_offset = len(all_parsed) + 1
        for i, call in enumerate(new_calls):
            _tc_name = call.get("function", {}).get("name", "")
            _tc_args_raw = call.get("function", {}).get("arguments", "{}")
            try:
                _tc_args = json.loads(_tc_args_raw) if isinstance(_tc_args_raw, str) else _tc_args_raw
            except (json.JSONDecodeError, TypeError):
                _tc_args = {}
            _tc_dedup = json.dumps(
                {"tool": _tc_name, "arguments": _tc_args},
                sort_keys=True,
                default=str,
            )
            pc = {
                "idx": idx_offset + i,
                "tool_id": call.get("id") or f"pipeline_tool_{chunk_index}_{i + 1}",
                "namespaced_tool_name": _tc_name,
                "arguments": _tc_args,
                "dedupe_key": _tc_dedup,
            }
            all_parsed.append(pc)

            if _tc_name == "mcp_repeated_exec":
                # Virtual tool — stays sequential, executed post-drain in Phase 3.
                logger_internal.info("Pipeline: mcp_repeated_exec deferred to post-drain sequential execution")
                continue

            logger_internal.info(
                "Pipeline enqueue [chunk %s/%s]: %s (dedup_skipped=%s)",
                chunk_index, num_chunks, _tc_name, skipped,
            )
            logger_external.info(
                "→ PIPELINE ENQUEUE [chunk %s/%s]: %s (dedup_skipped=%s)",
                chunk_index, num_chunks, _tc_name, skipped,
            )
            task = asyncio.create_task(_bounded_run(pc))
            task_to_pc[task] = pc

    # Drain — wait for all in-flight MCP tasks.
    logger_internal.info("Pipeline drain: %s task(s) in-flight", len(task_to_pc))
    _drain_start = _pt.time()
    raw_results: List[Any] = []
    if task_to_pc:
        raw_results = list(await asyncio.gather(*task_to_pc.keys(), return_exceptions=True))
    _drain_elapsed = _pt.time() - _drain_start

    results_map: Dict[str, Dict[str, Any]] = {}
    succeeded = 0
    failed = 0
    for (task, pc), raw in zip(task_to_pc.items(), raw_results):
        if isinstance(raw, BaseException):
            results_map[pc["tool_id"]] = {
                **pc,
                "result_content": f"Error: {raw}",
                "tool_result": str(raw),
                "success": False,
                "duration_ms": 0,
            }
            failed += 1
        else:
            results_map[pc["tool_id"]] = raw
            if raw.get("success"):
                succeeded += 1
            else:
                failed += 1

    logger_external.info(
        "← PIPELINE DRAIN COMPLETE: %s succeeded, %s failed, elapsed=%.1fs",
        succeeded, failed, _drain_elapsed,
    )

    return all_parsed, results_map


def _build_llm_mode_classifier_prompt(
    *,
    message_content: str,
    conversation_summary: Optional[str],
    direct_tool_route: Optional[Dict[str, Any]],
    heuristic_details: Dict[str, Any],
) -> List[Dict[str, str]]:
    summary_text = conversation_summary or "none"
    route_name = direct_tool_route["route_name"] if direct_tool_route else "none"

    system_prompt = (
        "You are a tiny routing classifier for a device-diagnostics chat system.\n"
        "Pick exactly one mode from: direct_fact, targeted_status, full_diagnostic, follow_up.\n"
        "Return only strict JSON with keys: mode, confidence, reasoning.\n"
        "confidence must be a number between 0 and 1.\n"
        "Mode guide:\n"
        "- direct_fact: single factual lookup or one concrete metric.\n"
        "- targeted_status: focused live status check or concise multi-check command.\n"
        "- full_diagnostic: root cause, explanation, investigation, or broad failure analysis.\n"
        "- follow_up: depends on previous context or asks about prior findings."
    )
    user_prompt = (
        f"Latest user request: {message_content}\n"
        f"Conversation summary: {summary_text}\n"
        f"Direct route candidate: {route_name}\n"
        f"Heuristic mode: {heuristic_details.get('mode')}\n"
        f"Heuristic confidence: {heuristic_details.get('confidence', 0.0)}\n"
        f"Heuristic score gap: {heuristic_details.get('score_gap', 0)}\n"
        f"Heuristic domains: {', '.join(heuristic_details.get('domains', [])) or 'none'}\n"
        f"Heuristic scores: {json.dumps(heuristic_details.get('scores', {}), sort_keys=True)}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _parse_llm_mode_classifier_response(response_content: str) -> Optional[Dict[str, Any]]:
    raw_content = (response_content or "").strip()
    if not raw_content:
        return None

    candidates: List[str] = [raw_content]
    fenced_matches = re.findall(r"```(?:json)?\s*([\s\S]*?)```", raw_content, re.IGNORECASE)
    for fenced_match in fenced_matches:
        cleaned = fenced_match.strip()
        if cleaned:
            candidates.append(cleaned)

    decoder = json.JSONDecoder()
    for index, char in enumerate(raw_content):
        if char not in "{[":
            continue
        try:
            parsed_payload, _ = decoder.raw_decode(raw_content[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed_payload, dict):
            candidates.append(json.dumps(parsed_payload))

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except (TypeError, json.JSONDecodeError):
            continue

        if not isinstance(payload, dict):
            continue

        mode = str(payload.get("mode", "")).strip()
        if mode not in REQUEST_MODES:
            continue

        confidence_raw = payload.get("confidence", 0.0)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0

        confidence = max(0.0, min(1.0, round(confidence, 3)))
        reasoning = str(payload.get("reasoning", "")).strip()
        return {
            "mode": mode,
            "confidence": confidence,
            "reasoning": reasoning,
        }

    return None


async def _classify_request_mode_with_llm(
    *,
    llm_config: LLMConfig,
    enterprise_access_token: Optional[str],
    message_content: str,
    conversation_summary: Optional[str],
    direct_tool_route: Optional[Dict[str, Any]],
    heuristic_details: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    prompt_messages = _build_llm_mode_classifier_prompt(
        message_content=message_content,
        conversation_summary=conversation_summary,
        direct_tool_route=direct_tool_route,
        heuristic_details=heuristic_details,
    )
    classifier_max_tokens = max(
        32,
        _resolve_int_override(
            llm_config.tiny_llm_mode_classifier_max_tokens,
            "MCP_LLM_MODE_CLASSIFIER_MAX_TOKENS",
            96,
        ),
    )
    classifier_config = llm_config.model_copy(
        update={
            "temperature": 0.0,
            "max_tokens": classifier_max_tokens,
        }
    )
    classifier_client = LLMClientFactory.create(
        classifier_config,
        enterprise_access_token=enterprise_access_token,
    )
    llm_response = await classifier_client.chat_completion(
        messages=prompt_messages,
        tools=[],
    )
    classifier_message = llm_response["choices"][0]["message"]
    classifier_content = (classifier_message.get("content") or "").strip()
    parsed_response = _parse_llm_mode_classifier_response(classifier_content)
    if parsed_response is None:
        logger_internal.warning(
            "Tiny LLM mode-classifier returned unparseable content; falling back to heuristics. preview=%s",
            classifier_content[:200] if classifier_content else "<empty>",
        )
        return None

    min_accept_confidence = _resolve_float_override(
        llm_config.tiny_llm_mode_classifier_accept_confidence,
        "MCP_LLM_MODE_CLASSIFIER_ACCEPT_CONFIDENCE",
        0.55,
    )
    if parsed_response["confidence"] < min_accept_confidence:
        logger_internal.info(
            "Tiny LLM mode-classifier confidence %.2f below threshold %.2f; keeping heuristic mode=%s",
            parsed_response["confidence"],
            min_accept_confidence,
            heuristic_details.get("mode"),
        )
        return None

    parsed_response["raw_content"] = classifier_content
    return parsed_response


def _classify_request_mode_details(
    message_content: str,
    *,
    existing_messages: List[ChatMessage],
    direct_tool_route: Optional[Dict[str, Any]],
    conversation_summary: Optional[str] = None,
) -> Dict[str, Any]:
    matched_domains = _extract_request_domains(message_content)
    scores = _compute_request_mode_scores(
        message_content,
        existing_messages=existing_messages,
        direct_tool_route=direct_tool_route,
        conversation_summary=conversation_summary,
    )
    ranked_modes = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_mode, top_score = ranked_modes[0]
    second_score = ranked_modes[1][1] if len(ranked_modes) > 1 else 0
    confidence = _compute_request_mode_confidence(scores, top_mode)

    if confidence < 0.45 or (top_score - second_score) < 2:
        top_mode = "targeted_status"

    return {
        "mode": top_mode,
        "domains": matched_domains,
        "scores": scores,
        "confidence": confidence,
        "score_gap": top_score - second_score,
        "source": "heuristic",
    }


def _find_matching_tool_names(
    candidate_names: List[str],
    available_tool_names: List[str],
) -> List[str]:
    resolved: List[str] = []
    available_set = set(available_tool_names)

    for candidate_name in candidate_names:
        if candidate_name in available_set and candidate_name not in resolved:
            resolved.append(candidate_name)

        for available_tool_name in available_tool_names:
            bare_name = available_tool_name.split("__", 1)[-1]
            if bare_name == candidate_name and available_tool_name not in resolved:
                resolved.append(available_tool_name)

    return resolved


def _select_one_tool_from_candidate_group(
    candidate_names: List[str],
    available_tool_names: List[str],
) -> Optional[str]:
    """Resolve one preferred tool from a prioritized candidate group.

    Each inner ``tool_candidates`` list in ``DIRECT_QUERY_ROUTES`` is treated as
    an OR-group ordered by preference. This keeps direct routing generic: route
    authors can express semantic alternatives such as
    ``["get_system_uptime", "get_uptime"]`` and the selector will expose only
    the first available match instead of sending both overlapping tools.
    """
    matches = _find_matching_tool_names(candidate_names, available_tool_names)
    return matches[0] if matches else None


def _select_direct_tool_route(
    message_content: str,
    available_tool_names: List[str],
) -> Optional[Dict[str, Any]]:
    normalized_message = _normalize_user_text(message_content)
    if not normalized_message:
        return None

    if _contains_any_keyword(normalized_message, DIAGNOSTIC_REQUEST_KEYWORDS):
        return None

    for route in DIRECT_QUERY_ROUTES:
        if not any(re.search(pattern, normalized_message) for pattern in route["patterns"]):
            continue

        allowed_tool_names: List[str] = []
        for candidate_group in route["tool_candidates"]:
            tool_name = _select_one_tool_from_candidate_group(candidate_group, available_tool_names)
            if tool_name and tool_name not in allowed_tool_names:
                allowed_tool_names.append(tool_name)

        if allowed_tool_names:
            return {
                "route_name": route["name"],
                "allowed_tool_names": allowed_tool_names,
                "include_virtual_repeated": False,
                "include_history": False,
            }

    return None


def _extract_tool_result_text(result: Any) -> str:
    """Unwrap an MCP JSON-RPC tool result into clean text suitable for the LLM.

    MCP servers return::

        {"content": [{"type": "text", "text": "..."}, ...], "isError": bool}

    The ``text`` fields themselves often contain another JSON object like::

        {"output": "<shell output>", "exit_code": 0, "executed_command": "..."}

    This function unwraps all of that into a single readable string so the LLM
    does not have to parse nested JSON.
    """
    if not isinstance(result, dict):
        return str(result)

    parts: List[str] = []
    for item in result.get("content") or []:
        if not isinstance(item, dict):
            continue
        raw_text = item.get("text", "")
        if not isinstance(raw_text, str):
            raw_text = json.dumps(raw_text)

        # Try to parse the inner JSON blob (common for shell-wrapper MCP tools)
        try:
            inner = json.loads(raw_text)
        except (json.JSONDecodeError, ValueError):
            parts.append(raw_text.strip())
            continue

        if isinstance(inner, dict):
            # Prefer the "output" field from shell-wrapper tools
            output_val = inner.get("output", "")
            cmd_val = inner.get("executed_command", "")
            if output_val and isinstance(output_val, str) and output_val.strip():
                # Prefix with the command that produced this output so the LLM
                # has context (e.g. "cat /proc/meminfo") without noise.
                if cmd_val and isinstance(cmd_val, str) and cmd_val.strip():
                    parts.append(f"$ {cmd_val.strip()}\n{output_val.strip()}")
                else:
                    parts.append(output_val.strip())
            else:
                # Remove noisy/redundant fields before presenting to the LLM
                clean = {k: v for k, v in inner.items()
                         if k not in ("exit_code", "executed_command")}
                parts.append(json.dumps(clean, indent=2) if clean else raw_text.strip())
        else:
            parts.append(raw_text.strip())

    if result.get("isError"):
        prefix = "[TOOL ERROR] "
    else:
        prefix = ""

    combined = "\n".join(p for p in parts if p)
    return prefix + combined if combined else json.dumps(result)


def _build_synthesis_prompt(
    *,
    current_user_message: str,
    tool_names_executed: List[str],
    tool_executions: Optional[List[Dict[str, Any]]] = None,
    is_direct_fact: bool = False,
) -> str:
    """System prompt for the follow-up LLM turn after tool results are in context.

    When ``is_direct_fact=True`` the prompt suppresses diagnostic commentary
    (health assessment, speculative advice, maintenance recommendations) and
    instructs the model to report only the fact that was asked for.
    """
    tools_str = ", ".join(tool_names_executed) if tool_names_executed else "(none)"

    # Build a compact per-tool status table to orient the LLM
    status_lines: List[str] = []
    if tool_executions:
        for te in tool_executions:
            tool_name = str(te.get("tool", ""))
            status = "✓ success" if te.get("success") else "✗ failed"
            # Brief result preview (first 120 chars of the text, stripped of newlines)
            raw_result = te.get("result", "")
            if isinstance(raw_result, dict):
                preview = _extract_tool_result_text(raw_result)
            else:
                preview = str(raw_result)
            preview = " ".join(preview.split())[:120]
            status_lines.append(f"  • {tool_name} [{status}]: {preview}")
    status_table = "\n".join(status_lines) if status_lines else "  (none)"

    if is_direct_fact:
        return (
            "You are a live device assistant. The following tools have already executed "
            "and their full outputs are in the conversation history above.\n\n"
            f"Tools executed:\n{status_table}\n\n"
            "INSTRUCTIONS:\n"
            "1. Do NOT call any more tools.\n"
            "2. Read the tool output in the conversation above.\n"
            "3. Convert raw numbers into human-readable form "
            "(e.g. seconds → days/hours/minutes, kB → MB/GB).\n"
            "4. State only the fact that was asked for. "
            "Do NOT add health assessments, speculation about causes, "
            "maintenance recommendations, or advice that was not requested.\n"
            "5. If the tool failed, say what could not be determined.\n"
            "6. One sentence or two is enough for a simple factual answer.\n"
            f"\nUser request: {current_user_message}"
        )

    return (
        "You are a live device assistant. The following tools have already executed "
        "and their full outputs are in the conversation history above.\n\n"
        f"Tools executed:\n{status_table}\n\n"
        "INSTRUCTIONS:\n"
        "1. Do NOT call any more tools.\n"
        "2. Read ALL tool outputs in the conversation above — do not rely only on the "
        "summary table (it is truncated).\n"
        "3. Translate raw numbers into human-readable form "
        "(e.g. kB → MB/GB, seconds → days/hours/minutes).\n"
        "4. Provide a concise analytical answer: state the key facts, assess whether "
        "values indicate healthy / degraded / critical conditions, and highlight "
        "anything that needs attention.\n"
        "5. If tools failed, say so and explain what could not be determined.\n"
        "6. Keep the answer focused — one short paragraph or a tight bullet list.\n"
        f"\nUser request: {current_user_message}"
    )


def _build_repeated_exec_triage_instruction(
    *,
    target_tool_name: str,
    repeat_count: int,
) -> str:
    """Instruction block for the final LLM pass after repeated tool execution."""
    return (
        "\nPlease analyse the repeated-run results carefully and respond in triaging output format. "
        f"Explain the observed behaviour across all {repeat_count} runs of `{target_tool_name}`, "
        "not just the final run. Highlight meaningful changes, anomalies, failed runs, and why they matter. "
        "If evidence is weak or mixed, say that explicitly and explain the uncertainty.\n\n"
        "Use this structure exactly:\n"
        "## Diagnostic Summary\n"
        "**Issue Type:** <observed issue type or 'trend analysis'>\n"
        "**Tool / Scope:** <tool analysed and what was checked>\n"
        "**Overall Assessment:** <1-2 sentences summarising the main conclusion>\n\n"
        "### Trend Explanation\n"
        "<2-4 sentences explaining what changed across runs, whether the system looks stable, improving, worsening, or intermittent, and why>\n\n"
        "### Root Cause Assessment\n"
        "<2-4 sentences with the most likely explanation, or say 'Insufficient evidence' and explain what is missing>\n\n"
        "### Evidence\n"
        "- Run pattern: <what stayed consistent across runs>\n"
        "- Key anomalies: <spikes, failures, regressions, or none>\n"
        "- Representative examples: <specific run numbers, timestamps, or values>\n\n"
        "### Impact\n"
        "<1-3 sentences describing severity, user-visible risk, and what is affected>\n\n"
        "### Recommended Actions\n"
        "1. <Immediate action or workaround>\n"
        "2. <Next verification or comparison step>\n"
        "3. <Longer-term fix, monitoring, or follow-up>"
    )


def _build_direct_tool_prompt(
    *,
    available_tool_names: List[str],
    current_user_message: str,
    conversation_summary: Optional[str] = None,
) -> str:
    tool_inventory = ", ".join(available_tool_names) if available_tool_names else "none"
    sections = [
        "You are a live device assistant connected to MCP tools.",
        f"Available tools: {tool_inventory}",
        "Use only the available tools.",
        "This is a direct factual lookup, not a full diagnostic investigation.",
        "Call only the minimum number of tools needed to answer the latest user question.",
        "If more than one independent tool is genuinely needed, call them together as parallel tool calls in your first response.",
        "Do not run broad diagnostic baselines, unrelated checks, or repeated-execution workflows unless the user explicitly asks for investigation or trending.",
        "Answer with the freshest concrete values and only brief supporting context.",
        f"Latest user request: {current_user_message}",
    ]
    if conversation_summary:
        sections.insert(3, "Conversation summary:\n" + conversation_summary)
    return "\n\n".join(sections)


def _build_targeted_tool_prompt(
    *,
    available_tool_names: List[str],
    current_user_message: str,
    request_mode: str,
    conversation_summary: Optional[str] = None,
) -> str:
    tool_inventory = ", ".join(available_tool_names) if available_tool_names else "none"
    sections = [
        "You are a live device assistant connected to MCP tools.",
        f"Request mode: {request_mode}",
        f"Available tools: {tool_inventory}",
        "Use only the available tools.",
        "This request needs a focused status check, not a full root-cause investigation unless the evidence clearly demands escalation.",
        "Select only the smallest relevant set of fresh tools for the latest user request.",
        "When multiple independent checks are needed, call them together as parallel tool calls in your first response.",
        "If the request expands into a broader failure investigation, say that a deeper diagnostic pass is needed before calling unrelated tools.",
        f"Latest user request: {current_user_message}",
    ]
    if conversation_summary:
        sections.insert(3, "Conversation summary:\n" + conversation_summary)
    return "\n\n".join(sections)


def _classify_request_mode(
    message_content: str,
    *,
    existing_messages: List[ChatMessage],
    direct_tool_route: Optional[Dict[str, Any]],
    conversation_summary: Optional[str] = None,
) -> str:
    return _classify_request_mode_details(
        message_content,
        existing_messages=existing_messages,
        direct_tool_route=direct_tool_route,
        conversation_summary=conversation_summary,
    )["mode"]


def _resolve_history_mode(
    session_config: Dict[str, Any],
    *,
    request_mode: str,
    direct_tool_route: Optional[Dict[str, Any]],
) -> str:
    if not session_config.get("include_history", True):
        return "latest"
    if direct_tool_route is not None:
        return "latest"

    history_mode = session_config.get("history_mode", "summary")
    if history_mode not in {"summary", "full", "latest"}:
        history_mode = "summary"

    if request_mode == "direct_fact":
        return "latest"
    if request_mode in {"targeted_status", "follow_up"} and history_mode == "full":
        return "summary"
    return history_mode


# ============================================================================
# Login page route
# ============================================================================

@app.get("/login", include_in_schema=False)
async def login_page():
    """Serve the SSO login page."""
    login_html = PathLib(__file__).parent / "static" / "login.html"
    if login_html.exists():
        return FileResponse(str(login_html))
    return HTMLResponse("<h1>SSO not configured</h1>", status_code=503)


# ============================================================================
# Auth endpoints (OIDC flow)
# ============================================================================

@app.get("/auth/login/{provider}", tags=["Auth"], summary="Initiate OIDC login")
async def auth_login(provider: str) -> RedirectResponse:
    """Build OIDC authorisation URL and redirect the browser to the IdP."""
    p = _sso_providers.get(provider)
    if p is None:
        raise HTTPException(status_code=404, detail=f"SSO provider '{provider}' not configured")

    from backend.auth.pkce import generate_pkce_pair, generate_state_token
    code_verifier, code_challenge = generate_pkce_pair()
    state = generate_state_token()
    nonce = generate_state_token()

    _pkce_state[state] = {
        "nonce": nonce,
        "code_verifier": code_verifier,
        "provider": provider,
    }

    auth_url = p.build_authorisation_url(state=state, nonce=nonce, code_challenge=code_challenge)
    return RedirectResponse(url=auth_url, status_code=302)


@app.get("/auth/callback/{provider}", tags=["Auth"], summary="Handle OIDC redirect callback")
async def auth_callback(
    provider: str,
    request: Request,
    response: Response,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
) -> RedirectResponse:
    """Exchange authorisation code for tokens; issue app session cookie."""
    if error:
        return RedirectResponse(url=f"/login?reason={error}", status_code=302)

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state parameter")

    pkce = _pkce_state.pop(state, None)
    if pkce is None:
        raise HTTPException(status_code=401, detail="Invalid or expired state — possible CSRF")

    if pkce["provider"] != provider:
        raise HTTPException(status_code=401, detail="Provider mismatch")

    p = _sso_providers.get(provider)
    if p is None:
        raise HTTPException(status_code=404, detail=f"SSO provider '{provider}' not configured")

    try:
        token_response = await p.exchange_code(code=code, code_verifier=pkce["code_verifier"])
        id_token = token_response.get("id_token")
        if not id_token:
            raise ValueError("No id_token in token response")
        user_info = await p.validate_id_token(id_token=id_token, nonce=pkce["nonce"])
    except Exception as exc:
        logger_internal.warning(f"OIDC callback failed ({provider}): {exc}")
        return RedirectResponse(url="/login?reason=auth_failed", status_code=302)

    user_row = upsert_user(
        provider=provider,
        provider_sub=user_info.sub,
        email=user_info.email,
        display_name=user_info.display_name,
        avatar_url=user_info.avatar_url,
        admin_emails=_get_admin_emails(),
    )

    import json as _json
    roles = _json.loads(user_row.roles) if isinstance(user_row.roles, str) else (user_row.roles or ["user"])
    ttl = int(os.getenv("SSO_SESSION_TTL_HOURS", "8"))
    app_token = issue_app_token(
        user_id=user_row.user_id,
        email=user_row.email,
        roles=roles,
        ttl_hours=ttl,
    )

    redirect = RedirectResponse(url="/?sso=ok", status_code=302)
    redirect.set_cookie(
        key="app_token",
        value=app_token,
        httponly=True,
        samesite="strict",
        max_age=ttl * 3600,
        path="/",
    )
    logger_internal.info(f"SSO login success: {user_row.email} ({provider})")
    return redirect


@app.post("/auth/logout", tags=["Auth"], summary="Log out and clear session cookie")
async def auth_logout() -> RedirectResponse:
    """Clear the app_token session cookie and redirect to login."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key="app_token", path="/")
    return response


@app.get("/auth/providers", tags=["Auth"], summary="List configured SSO providers", include_in_schema=False)
async def auth_providers():
    """Return the list of configured provider keys for the login page."""
    from fastapi.responses import JSONResponse
    return JSONResponse({"providers": list(_sso_providers.keys())})


# ============================================================================
# User endpoints
# ============================================================================

@app.get(
    "/api/users/me",
    response_model=UserProfile,
    tags=["Users"],
    summary="Get current user profile",
    responses={
        200: {"description": "User profile"},
        401: {"description": "Unauthorized"},
    },
)
async def get_me(request: Request) -> UserProfile:
    """Return the authenticated user's profile."""
    user = _require_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return _make_user_profile(user)


@app.get(
    "/api/users/me/settings",
    response_model=UserSettings,
    tags=["Users"],
    summary="Get current user UI preferences",
    responses={
        200: {"description": "User settings"},
        401: {"description": "Unauthorized"},
    },
)
async def get_my_settings(request: Request) -> UserSettings:
    user = _require_user(request)
    if user is None:
        return UserSettings()
    return _settings_store.get(user.user_id)


@app.patch(
    "/api/users/me/settings",
    response_model=UserSettings,
    tags=["Users"],
    summary="Partial update current user UI preferences",
    responses={
        200: {"description": "Updated settings"},
        401: {"description": "Unauthorized"},
    },
)
async def patch_my_settings(
    request: Request,
    updates: UserSettingsPatch = Body(...),
) -> UserSettings:
    user = _require_user(request)
    if user is None:
        return UserSettings()
    return _settings_store.patch(user.user_id, updates)


# ============================================================================
# Admin endpoints
# ============================================================================

@app.get(
    "/api/admin/users",
    response_model=UserListResponse,
    tags=["Admin"],
    summary="List all users (admin only)",
    responses={
        200: {"description": "Paginated user list"},
        403: {"description": "Admin role required"},
    },
)
async def admin_list_users(
    request: Request,
    limit: int = 50,
    offset: int = 0,
) -> UserListResponse:
    _require_admin(request)
    from sqlalchemy import select, func
    with SessionLocal() as db:
        from backend.database import UserRow as _UserRow
        total_result = db.execute(select(func.count()).select_from(_UserRow))
        total = total_result.scalar_one()
        rows = db.execute(
            select(_UserRow).order_by(_UserRow.created_at.desc()).limit(limit).offset(offset)
        ).scalars().all()
    return UserListResponse(
        users=[_make_user_profile(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/api/admin/users/{user_id}",
    response_model=UserProfile,
    tags=["Admin"],
    summary="Get user profile (admin only)",
    responses={
        200: {"description": "User profile"},
        403: {"description": "Admin role required"},
        404: {"description": "User not found"},
    },
)
async def admin_get_user(
    request: Request,
    user_id: str = Path(..., description="Target user UUID"),
) -> UserProfile:
    _require_admin(request)
    row = get_user_by_id(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _make_user_profile(row)


@app.patch(
    "/api/admin/users/{user_id}",
    response_model=UserProfile,
    tags=["Admin"],
    summary="Enable or disable a user (admin only)",
    responses={
        200: {"description": "Updated user profile"},
        403: {"description": "Admin role required"},
        404: {"description": "User not found"},
    },
)
async def admin_patch_user(
    request: Request,
    user_id: str = Path(..., description="Target user UUID"),
    patch: AdminUserPatch = Body(...),
) -> UserProfile:
    _require_admin(request)
    from sqlalchemy import select
    with SessionLocal() as db:
        from backend.database import UserRow as _UserRow
        row = db.get(_UserRow, user_id)
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        row.is_active = patch.is_active
        db.commit()
        db.refresh(row)
    return _make_user_profile(row)


@app.delete(
    "/api/admin/users/{user_id}/settings",
    response_model=DeleteResponse,
    tags=["Admin"],
    summary="Reset user LLM config and preferences (admin only)",
    responses={
        200: {"description": "Settings reset"},
        403: {"description": "Admin role required"},
        404: {"description": "User not found"},
    },
)
async def admin_reset_user_settings(
    request: Request,
    user_id: str = Path(..., description="Target user UUID"),
) -> DeleteResponse:
    _require_admin(request)
    row = get_user_by_id(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    _llm_store.delete(user_id)
    _settings_store.reset(user_id)
    return DeleteResponse(success=True, message=f"Settings reset for user {user_id}")


@app.post(
    "/api/admin/memory/maintenance",
    response_model=MemoryMaintenanceResponse,
    tags=["Admin"],
    summary="Run memory maintenance (admin only)",
    responses={
        200: {"description": "Manual memory maintenance completed"},
        403: {"description": "Admin role required"},
        503: {"description": "Memory subsystem not available"},
    },
)
async def admin_run_memory_maintenance(
    request: Request,
    payload: MemoryMaintenanceRequest = Body(...),
) -> MemoryMaintenanceResponse:
    """Run a manual expiry-cleanup pass for the optional memory subsystem."""
    _require_admin(request)
    if _memory_service is None or not hasattr(_memory_service, "run_expiry_cleanup_if_due"):
        raise HTTPException(status_code=503, detail="Memory subsystem is not available")

    summary = _memory_service.run_expiry_cleanup_if_due(
        force=payload.force,
        cleanup_expired_conversation_memory=payload.cleanup_expired_conversation_memory,
        cleanup_expired_tool_cache=payload.cleanup_expired_tool_cache,
    )
    return MemoryMaintenanceResponse(
        success=True,
        message="Memory maintenance completed",
        summary=summary,
    )


@app.post(
    "/api/admin/memory/ingest",
    response_model=MemoryIngestTriggerResponse,
    tags=["Admin"],
    summary="Trigger workspace ingestion (admin only)",
    responses={
        200: {"description": "Ingestion job completed"},
        403: {"description": "Admin role required"},
        503: {"description": "Memory subsystem not available"},
    },
)
async def admin_trigger_ingestion(
    request: Request,
    payload: MemoryIngestTriggerRequest = Body(...),
) -> MemoryIngestTriggerResponse:
    """Scan configured code/doc roots and write vector chunks into Milvus.

    ``repo_roots`` and ``doc_roots`` in the request body override the values
    stored in ``MilvusConfig``; if both are omitted the persisted config values
    are used.  The ``repo_id`` field tags every chunk; it falls back to the
    value in ``MilvusConfig`` when left blank.
    """
    _require_admin(request)
    if _memory_service is None:
        raise HTTPException(status_code=503, detail="Memory subsystem is not available")

    from backend.ingestion_service import IngestionService

    effective_config = _get_effective_milvus_config()
    repo_roots = payload.repo_roots or effective_config.repo_roots
    doc_roots = payload.doc_roots or effective_config.doc_roots
    repo_id = payload.repo_id.strip() or effective_config.repo_id or "workspace"

    svc = IngestionService(
        embedding_service=_memory_service.embedding_service,
        milvus_store=_memory_service.milvus_store,
        memory_persistence=_memory_service.memory_persistence,
        repo_roots=repo_roots,
        doc_roots=doc_roots,
        collection_generation=_memory_service.config.collection_generation,
        collection_prefix=effective_config.collection_prefix,
    )

    result = await svc.ingest_workspace_async(repo_id=repo_id)

    return MemoryIngestTriggerResponse(
        success=True,
        job_id=result["job_id"],
        status=result["status"],
        source_count=result.get("source_count", 0),
        chunk_count=result.get("chunk_count", 0),
        deleted_count=result.get("deleted_count", 0),
        error_count=result.get("error_count", 0),
        errors=result.get("errors", []),
    )


@app.get(
    "/api/admin/memory/row-counts",
    response_model=MemoryRowCountsResponse,
    tags=["Admin"],
    summary="Read active Milvus row counts (admin only)",
    responses={
        200: {"description": "Active Milvus row counts returned"},
        403: {"description": "Admin role required"},
        503: {"description": "Memory subsystem not available"},
    },
)
async def admin_memory_row_counts(request: Request) -> MemoryRowCountsResponse:
    """Return the current Milvus row counts for active memory collections."""
    _require_admin(request)
    if _memory_service is None:
        raise HTTPException(status_code=503, detail="Memory subsystem is not available")

    known_keys: list[str] = list(_memory_service.config.collection_keys)
    if (
        _memory_service.config.enable_conversation_memory
        and "conversation_memory" not in known_keys
    ):
        known_keys.append("conversation_memory")
    if _memory_service.config.enable_tool_cache and "tool_cache" not in known_keys:
        known_keys.append("tool_cache")
    if (
        getattr(_memory_service.config, "enable_adaptive_learning", False)
        and "tool_execution_quality" not in known_keys
    ):
        known_keys.append("tool_execution_quality")

    counts = [
        MemoryCollectionRowCount(
            collection_key=key,
            collection_name=_memory_service.milvus_store.build_collection_name(
                key,
                _memory_service.config.collection_generation,
            ),
            row_count=row_count,
            available=row_count >= 0,
        )
        for key in known_keys
        for row_count in [
            _memory_service.milvus_store.get_record_count(
                collection_key=key,
                generation=_memory_service.config.collection_generation,
            )
        ]
    ]

    return MemoryRowCountsResponse(
        success=True,
        generation=_memory_service.config.collection_generation,
        counts=counts,
    )


@app.get(
    "/api/admin/memory/quality-report",
    response_model=QualityReportResponse,
    tags=["Admin"],
    summary="AQL execution quality report (admin only)",
    responses={
        200: {"description": "Quality report returned"},
        403: {"description": "Admin role required"},
        503: {"description": "AQL reporting not available"},
    },
)
async def admin_quality_report(
    request: Request,
    days: int = Query(default=7, ge=1, le=365, description="Lookback window in days"),
    domain: Optional[str] = Query(default=None, description="Optional domain tag filter"),
) -> QualityReportResponse:
    """Return an aggregated AQL quality report for the given time window."""
    _require_admin(request)
    config = _get_effective_milvus_config()
    if _memory_service is None or not getattr(config, "enable_adaptive_learning", False):
        raise HTTPException(
            status_code=503, detail="AQL memory reporting not available"
        )
    logger_external.info(
        "\u2192 GET /api/admin/memory/quality-report (days=%s domain=%s)", days, domain
    )
    report = await _memory_service.get_quality_report(days=days, domain=domain)
    logger_external.info(
        "\u2190 200 OK (total_turns=%s)", report.total_turns
    )
    return report


@app.get(
    "/api/admin/memory/freshness-candidates",
    response_model=FreshnessCandidatesResponse,
    tags=["Admin"],
    summary="AQL freshness keyword candidates (admin only)",
    responses={
        200: {"description": "Freshness candidates returned"},
        403: {"description": "Admin role required"},
        503: {"description": "AQL reporting not available"},
    },
)
async def admin_freshness_candidates(
    request: Request,
) -> FreshnessCandidatesResponse:
    """Return AQL freshness keyword candidates derived from the last 30 days of quality history."""
    _require_admin(request)
    config = _get_effective_milvus_config()
    if _memory_service is None or not getattr(config, "enable_adaptive_learning", False):
        raise HTTPException(
            status_code=503, detail="AQL memory reporting not available"
        )
    logger_external.info("\u2192 GET /api/admin/memory/freshness-candidates")
    report = await _memory_service.get_quality_report(days=30, domain=None)
    current_keywords = list(config.tool_cache_freshness_keywords)
    logger_external.info(
        "\u2190 200 OK (candidates=%s current_keywords=%s)",
        len(report.freshness_keyword_candidates),
        len(current_keywords),
    )
    return FreshnessCandidatesResponse(
        candidates=report.freshness_keyword_candidates,
        current_keywords=current_keywords,
    )


# ============================================================================
# Health Check
# ============================================================================

@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="API health check",
    description="Check if the API is running and responsive"
)
async def health_check() -> HealthResponse:
    """Get API health status and version information"""
    memory_status = {"enabled": False}
    if _memory_service is not None:
        try:
            memory_status = await _memory_service.health_status()
        except Exception as exc:
            logger_internal.warning("Memory health check failed: %s", exc)
            memory_status = {
                "enabled": True,
                "healthy": False,
                "degraded": True,
                "status": "degraded",
                "reason": str(exc),
                "warnings": ["Memory health probe failed"],
                "milvus_reachable": False,
                "embedding_available": None,
                "active_collections": [],
            }

    return HealthResponse(
        status="healthy",
        version="0.2.0-jsonrpc",
        timestamp=datetime.utcnow(),
        memory=memory_status,
    )


# ============================================================================
# MCP Server Management
# ============================================================================

@app.get(
    "/api/servers",
    response_model=List[ServerConfig],
    tags=["MCP Servers"],
    summary="List all MCP servers",
    description="Retrieve all configured MCP servers from backend storage",
    responses={
        200: {"description": "List of configured servers"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    }
)
async def list_servers(request: Request) -> List[ServerConfig]:
    """Get all configured MCP servers"""
    logger_external.info("→ GET /api/servers")
    user_id = _user_id_or_none(request)
    servers = _get_user_servers(user_id)
    logger_external.info(f"← 200 OK (found {len(servers)} servers)")
    return servers


@app.post(
    "/api/servers",
    response_model=ServerConfig,
    status_code=status.HTTP_201_CREATED,
    tags=["MCP Servers"],
    summary="Register new MCP server",
    description="Add a new MCP server configuration for tool discovery and execution",
    responses={
        201: {"description": "Server created successfully"},
        400: {"model": ErrorResponse, "description": "Invalid configuration or duplicate alias"},
        422: {"model": ErrorResponse, "description": "Validation error"}
    }
)
async def create_server(
    request: Request,
    server: ServerConfig = Body(
        ...,
        description="MCP server configuration",
        openapi_examples={
            "local": {
                "summary": "Local MCP server",
                "value": {
                    "alias": "local_tools",
                    "base_url": "http://localhost:3000",
                    "auth_type": "none",
                    "timeout_ms": 15000
                }
            },
            "remote": {
                "summary": "Remote MCP server with auth",
                "value": {
                    "alias": "weather_api",
                    "base_url": "http://192.168.1.100:3000",
                    "auth_type": "bearer",
                    "bearer_token": "secret-token",
                    "timeout_ms": 20000
                }
            }
        }
    )
) -> ServerConfig:
    """
    Register a new MCP server for tool discovery and execution.

    The server will be initialized via JSON-RPC handshake and tools
    will be discovered automatically.
    """
    logger_external.info(f"→ POST /api/servers (alias={server.alias})")
    user_id = _user_id_or_none(request)
    existing_servers = _get_user_servers(user_id)

    # Check for duplicate server_id (for sync from localStorage)
    if server.server_id and any(s.server_id == server.server_id for s in existing_servers):
        logger_internal.info(f"Server already exists: {server.alias} ({server.server_id})")
        logger_external.info(f"← 409 Conflict (already exists)")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Server '{server.server_id}' already exists"
        )

    # Check for duplicate alias
    if any(s.alias == server.alias for s in existing_servers):
        logger_internal.warning(f"Duplicate alias rejected: {server.alias}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Server with alias '{server.alias}' already exists"
        )

    # Validate HTTPS in production
    if not server.base_url.startswith("https://"):
        if os.getenv("MCP_ALLOW_HTTP_INSECURE", "false").lower() != "true":
            logger_internal.warning(f"HTTP URL rejected (production mode): {server.base_url}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="HTTP URLs not allowed in production. Set MCP_ALLOW_HTTP_INSECURE=true for development."
            )

    # Store server
    if user_id:
        _server_store.create(user_id, server)
    else:
        servers_storage[server.server_id] = server
        _save_servers_to_disk()

    logger_internal.info(f"Server registered: {server.alias} ({server.server_id})")
    logger_external.info(f"← 201 Created")
    return server


@app.put(
    "/api/servers/{server_id}",
    response_model=ServerConfig,
    tags=["MCP Servers"],
    summary="Update MCP server configuration",
    responses={
        200: {"description": "Server updated successfully"},
        404: {"model": ErrorResponse, "description": "Server not found"},
        422: {"model": ErrorResponse, "description": "Validation error"}
    }
)
async def update_server(
    request: Request,
    server_id: str = Path(..., description="Server UUID to update"),
    server: ServerConfig = Body(..., description="Updated server configuration")
) -> ServerConfig:
    """Update an existing MCP server configuration"""
    logger_external.info(f"→ PUT /api/servers/{server_id}")
    user_id = _user_id_or_none(request)

    if user_id:
        if not _server_store.owns(user_id, server_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        server.server_id = server_id
        _server_store.update(user_id, server_id, server)
    else:
        if server_id not in servers_storage:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Server {server_id} not found")
        server.server_id = server_id
        servers_storage[server_id] = server
        _save_servers_to_disk()

    logger_internal.info(f"Server updated: {server.alias} ({server_id})")
    logger_external.info(f"← 200 OK")
    return server


@app.delete(
    "/api/servers/{server_id}",
    response_model=DeleteResponse,
    status_code=status.HTTP_200_OK,
    tags=["MCP Servers"],
    summary="Delete MCP server",
    responses={
        200: {"description": "Server deleted successfully"},
        404: {"model": ErrorResponse, "description": "Server not found"}
    }
)
async def delete_server(
    request: Request,
    server_id: str = Path(..., description="Server UUID to delete")
) -> DeleteResponse:
    """Delete an MCP server configuration and its associated tools"""
    logger_external.info(f"→ DELETE /api/servers/{server_id}")
    user_id = _user_id_or_none(request)

    if user_id:
        server = _server_store.get(user_id, server_id)
        if server is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        _server_store.delete(user_id, server_id)
    else:
        if server_id not in servers_storage:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Server {server_id} not found")
        server = servers_storage.pop(server_id)
        _save_servers_to_disk()

    # Remove associated tools from mcp_manager
    tools_to_remove = [
        tool_id for tool_id, tool in mcp_manager.tools.items()
        if tool.server_alias == server.alias
    ]
    for tool_id in tools_to_remove:
        del mcp_manager.tools[tool_id]
    logger_internal.info(f"Removed {len(tools_to_remove)} tools for {server.alias}")

    logger_external.info(f"← 200 OK")
    return DeleteResponse(
        success=True,
        message=f"Server '{server.alias}' deleted successfully"
    )


@app.post(
    "/api/servers/refresh-tools",
    response_model=ToolRefreshResponse,
    tags=["MCP Servers"],
    summary="Refresh tool discovery",
    description="Discover tools from all configured MCP servers via JSON-RPC",
    responses={
        200: {"description": "Tools refreshed successfully"},
        500: {"model": ErrorResponse, "description": "Refresh failed"}
    }
)
async def refresh_tools(request: Request) -> ToolRefreshResponse:
    """Discover tools from all configured MCP servers"""
    logger_external.info("→ POST /api/servers/refresh-tools")
    user_id = _user_id_or_none(request)
    servers = _get_user_servers(user_id)
    
    if not servers:
        logger_internal.warning("No servers configured for tool refresh")
        return ToolRefreshResponse(
            total_tools=0,
            servers_refreshed=0,
            errors=["No MCP servers configured"]
        )
    
    logger_internal.info(f"Tool refresh initiated for {len(servers)} servers")
    
    # Use MCP Manager to discover tools
    total_tools, servers_refreshed, errors = await mcp_manager.discover_all_tools(servers)

    error_aliases = {
        error.split(":", 1)[0].strip()
        for error in errors
        if ":" in error
    }
    checked_at = datetime.utcnow()
    for server in servers:
        server.last_health_check = checked_at
        server.health_status = "unhealthy" if server.alias in error_aliases else "healthy"
    if not _user_id_or_none(request):
        _save_servers_to_disk()
    
    logger_internal.info(
        f"Tool refresh complete: {total_tools} tools from {servers_refreshed}/{len(servers)} servers"
    )
    logger_external.info(f"← 200 OK (discovered {total_tools} tools)")
    
    return ToolRefreshResponse(
        total_tools=total_tools,
        servers_refreshed=servers_refreshed,
        errors=errors
    )


@app.post(
    "/api/servers/refresh-health",
    response_model=ServerHealthRefreshResponse,
    tags=["MCP Servers"],
    summary="Refresh server health status",
    description="Check MCP server reachability via initialize handshake without refreshing tools",
    responses={
        200: {"description": "Server health refreshed successfully"},
        500: {"model": ErrorResponse, "description": "Health refresh failed"}
    }
)
async def refresh_server_health(request: Request) -> ServerHealthRefreshResponse:
    """Refresh health status for all configured MCP servers."""
    logger_external.info("→ POST /api/servers/refresh-health")
    user_id = _user_id_or_none(request)
    servers = _get_user_servers(user_id)

    if not servers:
        logger_internal.warning("No servers configured for health refresh")
        return ServerHealthRefreshResponse(
            servers_checked=0,
            healthy_servers=0,
            unhealthy_servers=0,
            errors=["No MCP servers configured"],
            servers=[]
        )

    checked_count, healthy_servers, errors = await mcp_manager.refresh_server_health(servers)

    error_aliases = {
        error.split(":", 1)[0].strip()
        for error in errors
        if ":" in error
    }
    checked_at = datetime.utcnow()
    for server in servers:
        server.last_health_check = checked_at
        server.health_status = "unhealthy" if server.alias in error_aliases else "healthy"

    if not _user_id_or_none(request):
        _save_servers_to_disk()
    unhealthy_servers = checked_count - healthy_servers

    logger_internal.info(
        f"Server health refresh complete: {healthy_servers}/{checked_count} healthy"
    )
    logger_external.info(f"← 200 OK (checked {checked_count} servers)")

    return ServerHealthRefreshResponse(
        servers_checked=checked_count,
        healthy_servers=healthy_servers,
        unhealthy_servers=unhealthy_servers,
        errors=errors,
        servers=servers
    )


# ============================================================================
# Tool Management
# ============================================================================

@app.get(
    "/api/tools",
    response_model=List[ToolSchema],
    tags=["Tools"],
    summary="List all discovered tools",
    description="Get all tools discovered from MCP servers with namespaced IDs",
    responses={
        200: {"description": "List of discovered tools"}
    }
)
async def list_tools() -> List[ToolSchema]:
    """Get all discovered tools from MCP servers"""
    logger_external.info("→ GET /api/tools")
    tools = mcp_manager.get_all_tools()
    logger_external.info(f"← 200 OK (found {len(tools)} tools)")
    return tools


@app.get(
    "/api/tools/test-prompts",
    response_model=List[ToolTestPrompt],
    tags=["Tools"],
    summary="List documented tool test prompts",
    description="Get example user prompts parsed from USAGE-EXAMPLES.md for MCP tool testing via chat",
    responses={
        200: {"description": "List of documented tool test prompts"}
    }
)
async def list_tool_test_prompts() -> List[ToolTestPrompt]:
    """Return example chat prompts for MCP tool testing."""
    logger_external.info("→ GET /api/tools/test-prompts")
    prompts = _load_tool_test_prompts()
    logger_external.info(f"← 200 OK (found {len(prompts)} prompts)")
    return prompts


@app.post(
    "/api/tools/test-results-output",
    response_model=ToolTestOutputResponse,
    tags=["Tools"],
    summary="Persist Tool Tester output.txt snapshot",
    description="Write the current MCP Tool Tester results panel to data/output.txt on the server",
    responses={
        200: {"description": "Tool Tester output.txt updated"},
        500: {"model": ErrorResponse, "description": "Failed to write output.txt"}
    }
)
async def persist_tool_test_results_output(payload: ToolTestOutputRequest) -> ToolTestOutputResponse:
    """Persist the latest Tool Tester results snapshot to output.txt."""
    logger_external.info("→ POST /api/tools/test-results-output")
    try:
        result = _write_tool_test_output(payload.content)
    except OSError as exc:
        logger_internal.error("Failed to persist Tool Tester output: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to write Tool Tester output.txt"
        ) from exc

    logger_external.info("← 200 OK (%s, %s bytes)", result.file_path, result.bytes_written)
    return result


# ============================================================================
# LLM Configuration
# ============================================================================

@app.get(
    "/api/llm/config",
    response_model=LLMConfig,
    tags=["LLM"],
    summary="Get LLM configuration",
    responses={
        200: {"description": "Current LLM configuration"},
        404: {"model": ErrorResponse, "description": "No configuration set"}
    }
)
async def get_llm_config(request: Request) -> LLMConfig:
    """Get current LLM provider configuration"""
    logger_external.info("→ GET /api/llm/config")
    user_id = _user_id_or_none(request)

    if user_id:
        cfg = _llm_store.get_masked(user_id)
    else:
        cfg = llm_config_storage

    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="LLM configuration not set"
        )

    logger_external.info(f"← 200 OK (provider={cfg.provider})")
    return cfg


@app.post(
    "/api/llm/config",
    response_model=LLMConfig,
    tags=["LLM"],
    summary="Save LLM configuration",
    description="Configure LLM provider (OpenAI, Ollama, Mock, or Enterprise Gateway)",
    responses={
        200: {"description": "Configuration saved successfully"},
        422: {"model": ErrorResponse, "description": "Validation error"}
    }
)
async def save_llm_config(
    request: Request,
    config: LLMConfig = Body(..., description="LLM provider configuration")
) -> LLMConfig:
    """Save LLM provider configuration"""
    global llm_config_storage

    logger_external.info(f"→ POST /api/llm/config (provider={config.provider})")
    logger_internal.info(f"LLM config saved: {config.provider} / {config.model}")

    user_id = _user_id_or_none(request)
    if user_id:
        _llm_store.set(user_id, config)
        logger_external.info(f"← 200 OK")
        return _llm_store.get_masked(user_id) or config

    if config.provider == "enterprise":
        previous_enterprise = llm_config_storage if llm_config_storage and llm_config_storage.provider == "enterprise" else None
        if previous_enterprise and (
            previous_enterprise.client_id != config.client_id
            or previous_enterprise.token_endpoint_url != config.token_endpoint_url
            or previous_enterprise.base_url != config.base_url
        ):
            enterprise_token_cache.clear()
            logger_internal.info("Cleared enterprise token cache due to configuration change")

    llm_config_storage = config
    logger_external.info(f"← 200 OK")
    _save_llm_config_to_disk(config)
    _initialize_memory_service()
    return config


@app.get(
    "/api/milvus/config",
    response_model=MilvusConfig,
    tags=["Memory"],
    summary="Get Milvus configuration",
    responses={
        200: {"description": "Current Milvus configuration"},
    }
)
async def get_milvus_config() -> MilvusConfig:
    """Get the current effective Milvus memory configuration."""
    logger_external.info("→ GET /api/milvus/config")
    config = _get_effective_milvus_config()
    logger_external.info("← 200 OK (enabled=%s)", config.enabled)
    return config


@app.post(
    "/api/milvus/config",
    response_model=MilvusConfig,
    tags=["Memory"],
    summary="Save Milvus configuration",
    description="Configure the optional Milvus-backed memory subsystem",
    responses={
        200: {"description": "Configuration saved successfully"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    }
)
async def save_milvus_config(
    config: MilvusConfig = Body(..., description="Milvus memory configuration")
) -> MilvusConfig:
    """Save the current Milvus memory configuration and apply it immediately."""
    global milvus_config_storage

    logger_external.info("→ POST /api/milvus/config (enabled=%s)", config.enabled)
    milvus_config_storage = config
    _save_milvus_config_to_disk(config)
    _initialize_memory_service(config)
    logger_external.info("← 200 OK")
    return config


@app.post(
    "/api/enterprise/token",
    response_model=EnterpriseTokenResponse,
    tags=["LLM"],
    summary="Acquire enterprise bearer token",
    description="Request an OAuth bearer token for Enterprise Gateway usage and cache it in memory",
    responses={
        200: {"description": "Token acquired successfully"},
        422: {"model": ErrorResponse, "description": "Validation error"},
        502: {"model": ErrorResponse, "description": "Upstream token endpoint failure"}
    }
)
async def acquire_enterprise_token(
    token_request: EnterpriseTokenRequest = Body(..., description="Enterprise token request")
) -> EnterpriseTokenResponse:
    """Acquire and cache enterprise OAuth token."""
    logger_external.info("→ POST /api/enterprise/token")
    logger_external.debug("[enterprise] token request curl equivalent:\n%s", _redacted_token_request_curl(token_request))

    timeout = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)
    headers = {
        "Content-Type": "application/json",
        "X-Client-Id": token_request.client_id,
        "X-Client-Secret": token_request.client_secret,
    }

    try:
        logger_external.info(f"→ POST {token_request.token_endpoint_url}")
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(token_request.token_endpoint_url, content="", headers=headers)
            response.raise_for_status()
            payload = response.json()
        logger_external.info(f"← {response.status_code} OK")

        access_token = payload.get("access_token")
        if not access_token:
            logger_internal.error("Enterprise token endpoint response missing access_token")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Token endpoint response missing access_token"
            )

        cached_at = datetime.utcnow()
        enterprise_token_cache.clear()
        enterprise_token_cache.update({
            "access_token": access_token,
            "cached_at": cached_at,
            "expires_in": payload.get("expires_in")
        })

        logger_external.info("← 200 OK (enterprise token cached)")
        return EnterpriseTokenResponse(
            token_acquired=True,
            expires_in=payload.get("expires_in"),
            cached_at=cached_at,
            error=None
        )
    except HTTPException:
        raise
    except httpx.TimeoutException:
        logger_internal.error("Enterprise token endpoint timeout")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Token endpoint request timed out"
        )
    except httpx.HTTPStatusError as e:
        logger_internal.error(f"Enterprise token endpoint HTTP error: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Token endpoint returned {e.response.status_code}"
        )
    except httpx.HTTPError as e:
        logger_internal.error(f"Enterprise token endpoint error: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to reach token endpoint"
        )


@app.get(
    "/api/enterprise/token/status",
    response_model=EnterpriseTokenStatusResponse,
    tags=["LLM"],
    summary="Get enterprise token cache status",
    responses={
        200: {"description": "Token cache status returned successfully"}
    }
)
async def get_enterprise_token_status() -> EnterpriseTokenStatusResponse:
    """Get enterprise token cache status."""
    logger_external.info("→ GET /api/enterprise/token/status")
    status_response = _get_enterprise_token_status()
    logger_external.info(f"← 200 OK (cached={status_response.token_cached})")
    return status_response


@app.delete(
    "/api/enterprise/token",
    response_model=DeleteResponse,
    tags=["LLM"],
    summary="Clear cached enterprise token",
    responses={
        200: {"description": "Token cache cleared successfully"}
    }
)
async def delete_enterprise_token() -> DeleteResponse:
    """Clear cached enterprise token metadata and token value."""
    logger_external.info("→ DELETE /api/enterprise/token")
    enterprise_token_cache.clear()
    logger_external.info("← 200 OK")
    return DeleteResponse(success=True, message="Enterprise token cache cleared")


# ============================================================================
# Session & Chat Management
# ============================================================================

@app.post(
    "/api/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Chat"],
    summary="Create new chat session",
    description="Initialize a new conversation session with LLM and MCP configuration",
    responses={
        201: {"description": "Session created successfully"},
        400: {"model": ErrorResponse, "description": "Invalid configuration"}
    }
)
async def create_session(
    request: Request,
    config: Optional[SessionConfig] = Body(None, description="Session configuration (optional)")
) -> SessionResponse:
    """Create a new chat session"""
    logger_external.info("→ POST /api/sessions")
    user_id = _user_id_or_none(request)

    session = session_manager.create_session(
        config=config.model_dump() if config else {"include_history": True, "history_mode": "summary", "enabled_servers": []},
        user_id=user_id,
    )
    
    logger_internal.info(f"Session created: {session.session_id}")
    logger_external.info(f"← 201 Created")
    
    return SessionResponse(
        session_id=session.session_id,
        created_at=session.created_at
    )


@app.post(
    "/api/sessions/{session_id}/messages",
    response_model=ChatResponse,
    tags=["Chat"],
    summary="Send chat message",
    description="Send a user message and receive assistant response with tool execution",
    responses={
        200: {"description": "Message processed successfully"},
        404: {"model": ErrorResponse, "description": "Session not found"},
        422: {"model": ErrorResponse, "description": "Validation error"}
    }
)
async def send_message(
    request: Request,
    session_id: str = Path(..., description="Session UUID"),
    message: ChatMessage = Body(..., description="User message")
) -> ChatResponse:
    """Process user message through LLM with tool execution"""
    message_transaction_id = f"chat-{uuid.uuid4()}"
    logger_external.info(f"→ POST /api/sessions/{session_id}/messages")
    logger_internal.info(
        "Chat transaction started: request_id=%s session=%s message=%s",
        message_transaction_id,
        session_id,
        (message.content[:50] if message.content else ""),
    )

    user_id = _user_id_or_none(request)
    retrieval_trace_payload: Optional[Dict[str, Any]] = None

    if _memory_service is not None and hasattr(_memory_service, "run_expiry_cleanup_if_due"):
        _memory_service.run_expiry_cleanup_if_due()

    # Ownership check when SSO is active
    if user_id and _sso_enabled():
        sess = session_manager.get_session(session_id)
        if sess and sess.user_id and sess.user_id != user_id:
            raise HTTPException(status_code=403, detail="Forbidden")

    if not message.content.strip():
        logger_internal.warning("Rejected empty message content")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message content must not be empty"
        )
    
    existing_messages = list(session_manager.get_messages(session_id))
    existing_message_count = len(existing_messages)
    previous_turn_metadata = session_manager.get_last_turn_metadata(session_id)
    _schedule_correction_patch(
        memory_service=_memory_service,
        session_id=session_id,
        user_message=message.content,
        previous_turn_metadata=previous_turn_metadata,
    )

    # Add user message to session
    session_manager.add_message(session_id, message)
    
    # Check LLM config
    active_llm_config = _get_user_llm_config(user_id)
    if not active_llm_config:
        logger_internal.warning("No LLM config found")
        response_message = ChatMessage(
            role="assistant",
            content="Please configure an LLM provider in Settings."
        )
        session_manager.add_message(session_id, response_message)
        return ChatResponse(
            session_id=session_id,
            message=response_message,
            tool_executions=[],
            initial_llm_response=None,
            transaction_id=message_transaction_id,
            retrieval_trace=None,
        )
    
    try:
        # Create LLM client
        enterprise_access_token = None
        if active_llm_config.provider == "enterprise":
            enterprise_access_token = _get_cached_enterprise_token()
            if not enterprise_access_token:
                logger_internal.warning("Enterprise provider selected without cached token")
                response_message = ChatMessage(
                    role="assistant",
                    content="Please fetch an Enterprise Gateway token in Settings before sending messages."
                )
                session_manager.add_message(session_id, response_message)
                return ChatResponse(
                    session_id=session_id,
                    message=response_message,
                    tool_executions=[],
                    initial_llm_response=None,
                    transaction_id=message_transaction_id,
                    retrieval_trace=None,
                )

        llm_client = LLMClientFactory.create(
            active_llm_config,
            enterprise_access_token=enterprise_access_token
        )
        
        all_available_tool_names = list(mcp_manager.tools.keys())
        direct_tool_route = _select_direct_tool_route(message.content, all_available_tool_names)
        allowed_tool_names = direct_tool_route["allowed_tool_names"] if direct_tool_route else None
        include_virtual_repeated = direct_tool_route["include_virtual_repeated"] if direct_tool_route else True
        session = session_manager.get_session(session_id)
        session_config = session.config if session and isinstance(session.config, dict) else {}
        mode_classification_summary = session_manager.build_history_summary(
            session_id,
            upto_index=existing_message_count,
        )
        request_mode_details = _classify_request_mode_details(
            message.content,
            existing_messages=existing_messages,
            direct_tool_route=direct_tool_route,
            conversation_summary=mode_classification_summary,
        )
        affinity_route_applied = False

        if direct_tool_route:
            logger_internal.info(
                "Direct tool route selected: %s → [%s]",
                direct_tool_route["route_name"],
                ", ".join(allowed_tool_names),
            )
        elif _memory_service is not None:
            memory_service_config = getattr(_memory_service, "config", None)
            # Memory-based tool routing: search conversation_memory + tool_cache
            # (never code_memory) for similar past turns and extract which tools
            # were called.  If confident matches exist, use them to narrow the
            # tool catalog without asking the LLM.
            _memory_tool_names = await _memory_service.resolve_tools_from_memory(
                user_message=message.content,
                user_id=user_id or "",
                available_tool_names=all_available_tool_names,
                request_id=message_transaction_id,
            )
            if _memory_tool_names:
                direct_tool_route = {
                    "route_name": "memory_retrieval",
                    "allowed_tool_names": _memory_tool_names,
                    "include_virtual_repeated": False,
                }
                allowed_tool_names = _memory_tool_names
                include_virtual_repeated = False
                logger_internal.info(
                    "Memory tool route selected: [%s]",
                    ", ".join(_memory_tool_names),
                )
            else:
                logger_internal.info(
                    "Memory tool route: no confident match — falling back to LLM tool selection"
                )
                if getattr(memory_service_config, "enable_adaptive_learning", False):
                    affinity_route_result = await _memory_service.resolve_tools_from_quality_history(
                        query=message.content,
                        domain_tags=list(request_mode_details.get("domains", [])),
                    )
                    if (
                        affinity_route_result.tool_names
                        and affinity_route_result.confidence >= getattr(
                            memory_service_config,
                            "aql_affinity_confidence_threshold",
                            0.65,
                        )
                    ):
                        allowed_tool_names = list(affinity_route_result.tool_names)
                        include_virtual_repeated = False
                        affinity_route_applied = True
                        logger_internal.info(
                            "AQL affinity route applied: tools=%s confidence=%.3f records=%s",
                            ", ".join(allowed_tool_names),
                            affinity_route_result.confidence,
                            affinity_route_result.record_count,
                        )
                    else:
                        logger_internal.info(
                            "AQL affinity route skipped: confidence=%.3f threshold=%.3f records=%s",
                            affinity_route_result.confidence,
                            getattr(memory_service_config, "aql_affinity_confidence_threshold", 0.65),
                            affinity_route_result.record_count,
                        )

        def _prepare_initial_tool_catalog(
            *,
            dedupe_context_label: Optional[str] = None,
        ) -> tuple[List[Dict[str, Any]], List[List[Dict[str, Any]]], int, int, bool]:
            tools = mcp_manager.get_tools_for_llm(
                allowed_tool_names=allowed_tool_names,
                include_virtual_repeated=include_virtual_repeated,
            )

            env_limit = int(os.getenv("MCP_MAX_TOOLS_PER_REQUEST", "128"))
            effective_limit = active_llm_config.tools_split_limit or env_limit
            chunks = mcp_manager.get_tools_for_llm_chunks(
                effective_limit,
                allowed_tool_names=allowed_tool_names,
                include_virtual_repeated=include_virtual_repeated,
            )

            if dedupe_context_label is not None:
                tools, chunks = _dedupe_llm_tool_catalog_and_chunks(
                    tools,
                    chunks,
                    context_label=dedupe_context_label,
                )

            split_phase_needed = (
                len(chunks) > 1
                and active_llm_config.tools_split_enabled
            )

            if split_phase_needed:
                logger_internal.info(
                    "Tool catalog: %s tools → %s chunk(s) of ≤%s "
                    "(tools_split_limit=%s, env_limit=%s)",
                    len(tools), len(chunks), effective_limit,
                    active_llm_config.tools_split_limit, env_limit,
                )
            elif len(chunks) > 1 and not active_llm_config.tools_split_enabled:
                logger_internal.warning(
                    "Tool catalog has %s tools across %s chunk(s) but tools_split_enabled=False; "
                    "using full catalog without splitting. Enable 'Split Tools List' in LLM Settings "
                    "to activate split-phase mode.",
                    len(tools), len(chunks),
                )
            elif len(tools) > effective_limit:
                logger_internal.warning(
                    "Tool catalog has %s tools but effective limit=%s; truncating. "
                    "Enable 'Split Tools List' in LLM Settings to activate split-phase mode instead.",
                    len(tools), effective_limit,
                )
                tools = tools[:effective_limit]
                chunks = [tools]

            return tools, chunks, env_limit, effective_limit, split_phase_needed

        tools_for_llm, tool_chunks, _env_limit, _effective_limit, _split_phase_needed = _prepare_initial_tool_catalog(
            dedupe_context_label=(
                f"route {direct_tool_route['route_name']}" if direct_tool_route is not None else None
            )
        )

        logger_internal.info(f"Available tools for LLM: {len(tools_for_llm)} tools")
        if tools_for_llm:
            tool_names = [t["function"]["name"] for t in tools_for_llm]
            logger_internal.info(f"Tool names: {', '.join(tool_names)}")
        else:
            logger_internal.warning("No tools available! LLM will not be able to call any tools.")
        
        if _should_consult_llm_mode_classifier(
            request_mode_details,
            direct_tool_route=direct_tool_route,
            llm_config=active_llm_config,
        ):
            logger_internal.info(
                "Tiny LLM mode-classifier enabled for ambiguous routing: heuristic_mode=%s confidence=%.2f score_gap=%s",
                request_mode_details["mode"],
                request_mode_details["confidence"],
                request_mode_details["score_gap"],
            )
            llm_mode_details = await _classify_request_mode_with_llm(
                llm_config=active_llm_config,
                enterprise_access_token=enterprise_access_token,
                message_content=message.content,
                conversation_summary=mode_classification_summary,
                direct_tool_route=direct_tool_route,
                heuristic_details=request_mode_details,
            )
            if llm_mode_details is not None:
                request_mode_details = {
                    **request_mode_details,
                    "mode": llm_mode_details["mode"],
                    "confidence": llm_mode_details["confidence"],
                    "source": "llm",
                    "llm_reasoning": llm_mode_details.get("reasoning"),
                }
                logger_internal.info(
                    "Tiny LLM mode-classifier selected mode=%s confidence=%.2f reasoning=%s",
                    request_mode_details["mode"],
                    request_mode_details["confidence"],
                    request_mode_details.get("llm_reasoning") or "<none>",
                )

        request_mode = request_mode_details["mode"]
        history_mode = _resolve_history_mode(
            session_config,
            request_mode=request_mode,
            direct_tool_route=direct_tool_route,
        )

        if history_mode == "full":
            history_start_index = 0
        else:
            history_start_index = existing_message_count

        conversation_summary = None
        if history_mode == "summary":
            conversation_summary = mode_classification_summary

        logger_internal.info(
            "Request routing: mode=%s source=%s history_mode=%s direct_route=%s confidence=%.2f domains=%s scores=%s",
            request_mode,
            request_mode_details.get("source", "heuristic"),
            history_mode,
            direct_tool_route["route_name"] if direct_tool_route else "none",
            request_mode_details["confidence"],
            request_mode_details["domains"],
            request_mode_details["scores"],
        )

        # ── Domain-aware tool narrowing ────────────────────────────────────
        # When targeted_status (or direct_fact with no route match) is chosen
        # and the query maps to specific domains, restrict the tool catalog to
        # only domain-relevant tools.  This prevents the LLM from being shown
        # (and thus calling) audio/video/HDMI tools when the user asks for
        # kernel logs, memory tools for disk queries, etc. — particularly
        # critical during split-phase where the LLM only sees a subset per turn.
        if direct_tool_route is None and request_mode in {"targeted_status", "direct_fact"}:
            _matched_domains = request_mode_details.get("domains", [])
            if _matched_domains:
                tools_for_llm = _narrow_tools_by_domain(tools_for_llm, _matched_domains)
                # Recompute tool_names and chunks from the narrowed list
                tool_names = [t["function"]["name"] for t in tools_for_llm]
                tool_chunks = _rechunk_llm_tool_catalog(
                    tools_for_llm,
                    effective_limit=_effective_limit,
                    include_virtual_repeated=include_virtual_repeated,
                )
                tools_for_llm, tool_chunks = _dedupe_llm_tool_catalog_and_chunks(
                    tools_for_llm,
                    tool_chunks,
                    context_label=f"domain narrowing {','.join(_matched_domains)}",
                )
                _split_phase_needed = len(tool_chunks) > 1 and active_llm_config.tools_split_enabled
                logger_internal.info(
                    "Domain-narrowed catalog: %s tools, %s chunk(s), split_needed=%s domains=%s",
                    len(tools_for_llm), len(tool_chunks), _split_phase_needed, _matched_domains,
                )


        # Get conversation history (pass provider for correct message formatting)
        messages_for_llm = session_manager.get_messages_for_llm(
            session_id, 
            provider=llm_config_storage.provider,
            start_index=history_start_index
        )
        
        tool_executions = []
        initial_llm_response = None
        executed_tool_results: dict[str, dict] = {}
        _pre_executed_results_map: Dict[str, Dict[str, Any]] = {}  # set by pipeline path
        issue_classification: Optional[str] = None
        latest_assistant_tool_guidance: Optional[str] = None
        layer2_context_messages: List[dict] = []
        retrieval_context_section: Optional[str] = None
        retrieval_sources: Optional[List[Dict[str, Any]]] = None
        has_real_tools = any(tool_name != "mcp_repeated_exec" for tool_name in tool_names)
        aql_tools_bypassed: set[str] = set()
        aql_chunk_yields: List[Dict[str, int]] = []
        aql_llm_turn_count = 0
        aql_synthesis_tokens = 0

        def _record_chunk_yield(chunk_index: int, offered: int, selected: int) -> None:
            aql_chunk_yields.append(
                {
                    "chunk": max(int(chunk_index), 0),
                    "offered": max(int(offered), 0),
                    "selected": max(int(selected), 0),
                }
            )

        def _current_routing_mode() -> str:
            if affinity_route_applied:
                return "affinity"
            if direct_tool_route is not None:
                if direct_tool_route.get("route_name") == "memory_retrieval":
                    return "memory"
                return "direct"
            return "llm_fallback"

        def _build_execution_quality_payload() -> Dict[str, Any]:
            selected_tools = [
                str(tool_exec.get("tool", ""))
                for tool_exec in tool_executions
                if tool_exec.get("tool")
            ]
            succeeded_tools = [
                str(tool_exec.get("tool", ""))
                for tool_exec in tool_executions
                if tool_exec.get("tool") and tool_exec.get("success")
            ]
            failed_tools = [
                str(tool_exec.get("tool", ""))
                for tool_exec in tool_executions
                if tool_exec.get("tool") and not tool_exec.get("success")
            ]
            cache_hit_tools = [
                str(tool_exec.get("tool", ""))
                for tool_exec in tool_executions
                if tool_exec.get("tool") and tool_exec.get("cache_hit")
            ]
            return {
                "user_message": message.content,
                "session_id": session_id,
                "domain_tags": list(request_mode_details.get("domains", [])),
                "issue_type": issue_classification or request_mode.replace("_", " "),
                "tools_selected": selected_tools,
                "tools_succeeded": succeeded_tools,
                "tools_failed": failed_tools,
                "tools_bypassed": sorted(aql_tools_bypassed),
                "tools_cache_hit": cache_hit_tools,
                "chunk_yields": list(aql_chunk_yields),
                "llm_turn_count": aql_llm_turn_count,
                "synthesis_tokens": aql_synthesis_tokens,
                "routing_mode": _current_routing_mode(),
                "user_corrected": False,
                "follow_up_gap_s": -1,
            }

        def build_runtime_system_message() -> dict:
            tool_result_contents = [str(tool_exec.get("result", "")) for tool_exec in tool_executions]
            assistant_guidance = latest_assistant_tool_guidance
            if not assistant_guidance and issue_classification:
                assistant_guidance = f"Issue classified as: {issue_classification}"

            # After tool execution, switch to a synthesis-focused prompt so the model
            # knows to read the results already in context rather than keep calling tools.
            if tool_executions:
                executed_names = [str(t.get("tool", "")) for t in tool_executions]
                return {
                    "role": "system",
                    "content": _build_synthesis_prompt(
                        current_user_message=message.content,
                        tool_names_executed=executed_names,
                        tool_executions=tool_executions,
                        is_direct_fact=(request_mode == "direct_fact"),
                    ),
                }

            if direct_tool_route is not None:
                return {
                    "role": "system",
                    "content": _build_direct_tool_prompt(
                        available_tool_names=tool_names,
                        current_user_message=message.content,
                        conversation_summary=conversation_summary,
                    ),
                }
            if request_mode in {"targeted_status", "follow_up"}:
                return {
                    "role": "system",
                    "content": _build_targeted_tool_prompt(
                        available_tool_names=tool_names,
                        current_user_message=message.content,
                        request_mode=request_mode,
                        conversation_summary=conversation_summary,
                    ),
                }
            return {
                "role": "system",
                "content": build_system_prompt(
                    available_tool_names=tool_names,
                    current_user_message=message.content,
                    assistant_content=assistant_guidance,
                    tool_result_contents=tool_result_contents,
                    conversation_summary=conversation_summary,
                ),
            }
        
        def rebuild_messages_for_llm() -> List[dict]:
            provider_messages = session_manager.get_messages_for_llm(
                session_id,
                provider=llm_config_storage.provider,
                start_index=history_start_index
            )
            runtime_system_message = build_runtime_system_message()
            if provider_messages and provider_messages[0].get("role") == "system":
                provider_messages[0] = runtime_system_message
            else:
                provider_messages.insert(0, runtime_system_message)
            return _inject_context_section(provider_messages, retrieval_context_section)

        def build_classification_messages() -> List[dict]:
            provider_messages = session_manager.get_messages_for_llm(
                session_id,
                provider=llm_config_storage.provider,
                start_index=history_start_index,
            )
            classification_message = {
                "role": "system",
                "content": build_classification_prompt(
                    available_tool_names=tool_names,
                    current_user_message=message.content,
                ),
            }
            if provider_messages and provider_messages[0].get("role") == "system":
                provider_messages[0] = classification_message
            else:
                provider_messages.insert(0, classification_message)
            return provider_messages

        def extract_tool_calls_from_content(content: str, turn_number: int) -> List[dict]:
            """Recover tool requests when a provider returns JSON in content instead of tool_calls."""
            raw_content = (content or "").strip()
            if not raw_content:
                return []

            available_tool_names = {
                tool["function"]["name"]
                for tool in tools_for_llm
                if tool.get("type") == "function" and tool.get("function", {}).get("name")
            }
            bare_tool_name_map: Dict[str, List[str]] = {}
            for available_tool_name in available_tool_names:
                bare_tool_name = available_tool_name.split("__", 1)[-1]
                bare_tool_name_map.setdefault(bare_tool_name, []).append(available_tool_name)

            def resolve_tool_name(candidate_tool_name: str) -> Optional[str]:
                if not candidate_tool_name:
                    return None
                if candidate_tool_name in available_tool_names:
                    return candidate_tool_name

                bare_matches = bare_tool_name_map.get(candidate_tool_name, [])
                if len(bare_matches) == 1:
                    return bare_matches[0]

                return None

            def build_recovered_tool_calls(parsed_payload: Any) -> List[dict]:
                candidate_calls = parsed_payload if isinstance(parsed_payload, list) else [parsed_payload]
                recovered_tool_calls = []

                for content_index, candidate in enumerate(candidate_calls, 1):
                    if not isinstance(candidate, dict):
                        return []

                    function_payload = candidate.get("function") if isinstance(candidate.get("function"), dict) else {}
                    tool_name = candidate.get("name") or function_payload.get("name")
                    resolved_tool_name = resolve_tool_name(tool_name)
                    if not resolved_tool_name:
                        return []

                    arguments = candidate.get("parameters")
                    if arguments is None:
                        arguments = candidate.get("arguments")
                    if arguments is None:
                        arguments = function_payload.get("arguments")
                    if arguments is None:
                        arguments = {}

                    if isinstance(arguments, str):
                        arguments_str = arguments
                    else:
                        arguments_str = json.dumps(arguments)

                    recovered_tool_calls.append({
                        "id": f"content_tool_call_{turn_number}_{content_index}",
                        "type": "function",
                        "function": {
                            "name": resolved_tool_name,
                            "arguments": arguments_str,
                        },
                    })

                return recovered_tool_calls

            def extract_json_payloads(text: str) -> List[Any]:
                candidates: List[Any] = []
                decoder = json.JSONDecoder()

                try:
                    candidates.append(json.loads(text))
                except (TypeError, json.JSONDecodeError):
                    pass

                for fenced_match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE):
                    fenced_content = fenced_match.group(1).strip()
                    if not fenced_content:
                        continue
                    try:
                        candidates.append(json.loads(fenced_content))
                    except (TypeError, json.JSONDecodeError):
                        continue

                for start_index, char in enumerate(text):
                    if char not in "[{":
                        continue
                    try:
                        parsed_payload, _ = decoder.raw_decode(text[start_index:])
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed_payload, (dict, list)):
                        candidates.append(parsed_payload)

                return candidates

            cleaned_content = raw_content
            if cleaned_content.startswith("**") and cleaned_content.endswith("**"):
                cleaned_content = cleaned_content[2:-2].strip()
            if cleaned_content.startswith("`") and cleaned_content.endswith("`"):
                cleaned_content = cleaned_content.strip("`").strip()
            if cleaned_content.startswith("json"):
                cleaned_content = cleaned_content[4:].strip()

            for parsed_content in extract_json_payloads(cleaned_content):
                recovered_tool_calls = build_recovered_tool_calls(parsed_content)
                if recovered_tool_calls:
                    return recovered_tool_calls

            return []

        if has_real_tools and request_mode in {"full_diagnostic", "targeted_status"} and direct_tool_route is None:
            classification_messages = build_classification_messages()
            logger_external.info(
                "→ LLM Classification Request: %s messages, tools disabled for strict issue classification",
                len(classification_messages),
            )
            logger_internal.info(
                "Classification messages to LLM: %s",
                json.dumps(classification_messages, indent=2),
            )

            classification_response = await llm_client.chat_completion(
                messages=classification_messages,
                tools=[],
            )
            aql_llm_turn_count += 1
            classification_msg = classification_response["choices"][0]["message"]
            classification_content = (classification_msg.get("content") or "").strip()
            latest_assistant_tool_guidance = classification_content or None

            issue_classification = (
                parse_issue_classification(classification_content)
                or classify_issue_from_text(message.content)
            )

            logger_external.info(
                "← LLM Classification Response: classification=%s preview=%s",
                issue_classification or "unclassified",
                classification_content[:200] if classification_content else "<empty>",
            )

            if issue_classification:
                layer2_prompt = build_layer2_injection_prompt(
                    classification=issue_classification,
                    available_tool_names=tool_names,
                )
                logger_internal.info("Strict classification selected issue type: %s", issue_classification)

                if classification_content:
                    layer2_context_messages.append(
                        {
                            "role": "assistant",
                            "content": classification_content,
                        }
                    )
                if layer2_prompt:
                    layer2_context_messages.append(
                        {
                            "role": "user",
                            "content": layer2_prompt,
                        }
                    )
            else:
                logger_internal.warning(
                    "Strict classification pass did not return a recognized issue type; continuing with heuristic-free tool selection"
                )

        # Insert system message at the beginning if not already present
        if messages_for_llm and messages_for_llm[0].get("role") == "system":
            messages_for_llm[0] = build_runtime_system_message()
        else:
            messages_for_llm.insert(0, build_runtime_system_message())

        if layer2_context_messages:
            messages_for_llm.extend(layer2_context_messages)

        if _memory_service is not None:
            retrieval_result = await _memory_service.enrich_for_turn(
                user_message=message.content,
                session_id=session_id,
                request_id=message_transaction_id,
                user_id=user_id or "",
                include_code_memory=False,  # planning phase — skip code/doc memory
            )
            session_manager.add_retrieval_trace(
                session_id,
                request_id=message_transaction_id,
                query_hash=retrieval_result.query_hash,
                collection_keys=list(retrieval_result.collection_keys),
                result_count=len(retrieval_result.blocks),
                degraded=retrieval_result.degraded,
                degraded_reason=retrieval_result.degraded_reason,
                latency_ms=retrieval_result.latency_ms,
                message_preview=(message.content or "")[:120],
            )
            retrieval_trace_payload = {
                "request_id": message_transaction_id,
                "query_hash": retrieval_result.query_hash,
                "collection_keys": list(retrieval_result.collection_keys),
                "result_count": len(retrieval_result.blocks),
                "degraded": retrieval_result.degraded,
                "degraded_reason": retrieval_result.degraded_reason,
                "latency_ms": retrieval_result.latency_ms,
                "message_preview": (message.content or "")[:120],
            }
            if retrieval_result.degraded:
                logger_internal.warning("Retrieval degraded: %s", retrieval_result.degraded_reason)
            elif retrieval_result.blocks:
                retrieval_context_section = _format_retrieval_context(retrieval_result.blocks)
                retrieval_sources = [
                    {
                        "source_path": block.source_path,
                        "collection": block.collection,
                        "score": round(block.score, 4),
                    }
                    for block in retrieval_result.blocks
                ]
                messages_for_llm = _inject_context_section(messages_for_llm, retrieval_context_section)
                logger_internal.debug(
                    "Retrieval context injected: %s block(s) in %.1f ms",
                    len(retrieval_result.blocks),
                    retrieval_result.latency_ms,
                )

        # _run_one_mcp_tool is defined here — before the split-phase block — so
        # the pipeline can invoke it immediately on chunk arrival without waiting
        # for the turn loop to start (FR-SPIPE-002).
        async def _run_one_mcp_tool(pc: Dict[str, Any]) -> Dict[str, Any]:
            """Execute one normal MCP tool call. Pure I/O — no side effects."""
            _name = pc["namespaced_tool_name"]
            _args = pc["arguments"]
            if not _name or "__" not in _name:
                logger_internal.error("Invalid tool name format: %s", _name)
                return {**pc, "result_content": f"Error: Invalid tool name format: {_name}",
                        "tool_result": None, "success": False, "duration_ms": 0}
            _server_alias, _actual_name = _name.split("__", 1)
            _server = next(
                (s for s in servers_storage.values() if s.alias == _server_alias),
                None,
            )
            if not _server:
                logger_internal.error("Server not found: %s", _server_alias)
                return {**pc, "result_content": f"Error: Server '{_server_alias}' not found",
                        "tool_result": None, "success": False, "duration_ms": 0}
            _stored = mcp_manager.tools.get(_name)
            _hints = _stored.execution_hints if _stored else None
            if _hints:
                _est_ms = _hints.estimatedRuntimeMs or 0
                if _hints.mode == "sampling" or _est_ms >= 5000:
                    logger_internal.info(
                        "Long-running diagnostic tool: %s | mode=%s, estimatedRuntime=%.1fs. "
                        "This diagnostic samples data over time — client timeout extended accordingly.",
                        _name, _hints.mode, _est_ms / 1000,
                    )
                else:
                    logger_internal.info(
                        "One-shot diagnostic tool: %s | mode=%s, estimatedRuntime=%.1fs. "
                        "Collecting snapshot.",
                        _name, _hints.mode, _est_ms / 1000,
                    )
            import time as _time_mod
            _start = _time_mod.time()
            # ---- tool cache lookup ---- #
            if _memory_service is not None:
                _cache_result = _memory_service.lookup_tool_cache(
                    tool_name=_name,
                    arguments=_args if isinstance(_args, dict) else {},
                    user_id=user_id or "",
                )
                if getattr(_cache_result, "freshness_bypassed", False):
                    aql_tools_bypassed.add(_name)
                if _cache_result.hit and _cache_result.approved:
                    _dur = int((_time_mod.time() - _start) * 1000)
                    logger_internal.info(
                        "Tool cache HIT: %s (cache_id=%s)", _name, _cache_result.cache_id
                    )
                    return {**pc, "result_content": _cache_result.result_text,
                            "tool_result": {"content": _cache_result.result_text},
                            "success": True, "duration_ms": _dur, "cache_hit": True}
            try:
                _result = await mcp_manager.execute_tool(
                    server=_server,
                    tool_name=_actual_name,
                    arguments=_args,
                    execution_hints=_hints,
                )
                _dur = int((_time_mod.time() - _start) * 1000)
                _max_chars = int(os.getenv("MCP_MAX_TOOL_OUTPUT_CHARS_TO_LLM", "131072"))
                _res_str = _extract_tool_result_text(_result)
                if len(_res_str) > _max_chars:
                    _res_str = _res_str[:_max_chars] + "... [truncated]"
                _success = not bool(_result.get("isError")) if isinstance(_result, dict) else True
                # ---- store in cache if allowlisted and successful ---- #
                if _success and _memory_service is not None:
                    _cache_store_result = _memory_service.record_tool_cache(
                        tool_name=_name,
                        arguments=_args if isinstance(_args, dict) else {},
                        result_text=_res_str,
                        user_id=user_id or "",
                    )
                    if inspect.isawaitable(_cache_store_result):
                        await _cache_store_result
                return {**pc, "result_content": _res_str, "tool_result": _result,
                        "success": _success, "duration_ms": _dur}
            except Exception as _exc:
                _dur = int((_time_mod.time() - _start) * 1000)
                logger_internal.error("Tool execution error: %s", _exc)
                return {**pc, "result_content": f"Error: {_exc}", "tool_result": str(_exc),
                        "success": False, "duration_ms": _dur}

        # ------------------------------------------------------------------ #
        # Split-phase pre-collection                                           #
        # When the tool catalog is larger than tools_split_limit (or           #
        # MCP_MAX_TOOLS_PER_REQUEST), tools are split into chunks and the LLM  #
        # is queried once per chunk against a read-only snapshot of the        #
        # conversation.  All tool_calls returned across every chunk are merged  #
        # (deduplicated by tool name + arguments) and injected into Turn 0     #
        # of the main loop below, bypassing the normal first-turn LLM call.   #
        #                                                                      #
        # Pipeline mode (MCP_SPLIT_PHASE_PIPELINE_ENABLED=true): MCP tools are #
        # started immediately as each chunk responds instead of waiting for    #
        # all chunks first, overlapping LLM wait time with MCP execution time. #
        # ------------------------------------------------------------------ #
        split_phase_tool_calls: Optional[List[Dict[str, Any]]] = None

        # ------------------------------------------------------------------ #
        # Direct-route Turn-0 bypass                                           #
        # When a direct_tool_route resolves to exactly one tool (e.g. the      #
        # heuristic uptime / memory / cpu routes) and no split-phase was       #
        # needed, skip the first LLM call entirely: synthesise a tool_calls    #
        # response directly and inject it in Turn 0, exactly like split-phase  #
        # does.  The LLM is still called for synthesis after the tool returns. #
        # ------------------------------------------------------------------ #
        _direct_route_tool_calls: Optional[List[Dict[str, Any]]] = None
        if (
            direct_tool_route is not None
            and direct_tool_route.get("route_name") != "memory_retrieval"
            and split_phase_tool_calls is None
            and allowed_tool_names
            and len(allowed_tool_names) == 1
        ):
            _only_tool_name = allowed_tool_names[0]
            _only_tool_in_catalog = next(
                (t for t in tools_for_llm if t.get("function", {}).get("name") == _only_tool_name),
                None,
            )
            if _only_tool_in_catalog is not None:
                _direct_route_tool_calls = [{
                    "id": f"direct_route_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": _only_tool_name,
                        "arguments": "{}",
                    },
                }]
                logger_internal.info(
                    "Direct-route Turn-0 bypass: skipping LLM call, injecting tool_call for %s",
                    _only_tool_name,
                )
        if _split_phase_needed and has_real_tools:
            _messages_snapshot = list(messages_for_llm)  # read-only snapshot
            _split_mode = active_llm_config.tools_split_mode  # "sequential" | "concurrent"
            _pipeline_enabled = _get_bool_env("MCP_SPLIT_PHASE_PIPELINE_ENABLED", False)
            if _pipeline_enabled:
                logger_internal.info(
                    "Split-phase pipeline enabled: chunks=%s concurrency=%s mode=%s",
                    len(tool_chunks),
                    int(os.getenv("MCP_MAX_TOOL_CALLS_PER_TURN", "8")),
                    _split_mode,
                )
                _stream = _stream_split_phase_tool_calls(
                    llm_client=llm_client,
                    messages_snapshot=_messages_snapshot,
                    tool_chunks=tool_chunks,
                    split_mode=_split_mode,
                    request_mode=request_mode,
                    request_mode_details=request_mode_details,
                    extract_tool_calls_from_content=extract_tool_calls_from_content,
                    chunk_yield_collector=_record_chunk_yield,
                )
                aql_llm_turn_count += len(tool_chunks)
                _pipeline_parsed, _pipeline_results = await _run_pipeline_execution(
                    stream=_stream,
                    run_mcp_tool=_run_one_mcp_tool,
                    tool_concurrency=int(os.getenv("MCP_MAX_TOOL_CALLS_PER_TURN", "8")),
                    num_chunks=len(tool_chunks),
                )
                # Rebuild the tool_call list in LLM format for Turn 0 injection.
                split_phase_tool_calls = [
                    {
                        "id": pc["tool_id"],
                        "type": "function",
                        "function": {
                            "name": pc["namespaced_tool_name"],
                            "arguments": (
                                json.dumps(pc["arguments"])
                                if isinstance(pc["arguments"], dict)
                                else (pc["arguments"] or "{}")
                            ),
                        },
                    }
                    for pc in _pipeline_parsed
                ]
                # Expose results for Phase 2/3 in Turn 0 so they are not re-executed.
                _pre_executed_results_map = _pipeline_results
            else:
                split_phase_tool_calls = await _collect_split_phase_tool_calls(
                    llm_client=llm_client,
                    messages_snapshot=_messages_snapshot,
                    tool_chunks=tool_chunks,
                    split_mode=_split_mode,
                    request_mode=request_mode,
                    request_mode_details=request_mode_details,
                    extract_tool_calls_from_content=extract_tool_calls_from_content,
                    chunk_yield_collector=_record_chunk_yield,
                )
                aql_llm_turn_count += len(tool_chunks)
            _sp_tool_names = [tc.get("function", {}).get("name", "") for tc in split_phase_tool_calls]
            logger_external.info(
                "MCP CLIENT → MCP SERVER TOOLS LIST: [%s] (%s tool(s) across %s chunk(s))",
                ", ".join(_sp_tool_names) if _sp_tool_names else "<none>",
                len(split_phase_tool_calls),
                len(tool_chunks),
            )

        # Multi-turn loop for tool calling
        max_turns = int(os.getenv("MCP_MAX_TOOL_CALLS_PER_TURN", "8"))
        
        for turn in range(max_turns):
            logger_internal.info(f"Turn {turn + 1}/{max_turns}")
            # Tools are sent only on the first request. Once any tool has executed,
            # subsequent requests omit the catalog so the model focuses on summarising
            # the results. The system prompt instructs the model to call all needed
            # tools in parallel in the first response.
            tools_for_request = tools_for_llm if not tool_executions else []
            
            # Call LLM — or inject split-phase pre-collected tool calls for Turn 0
            if turn == 0 and split_phase_tool_calls is not None:
                if split_phase_tool_calls:
                    # Inject the merged tool calls from all chunks; skip LLM call
                    logger_internal.info(
                        "Split-phase Turn 0: injecting %s pre-collected tool call(s), skipping LLM call",
                        len(split_phase_tool_calls),
                    )
                    llm_response = {
                        "choices": [{
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": split_phase_tool_calls,
                            },
                            "finish_reason": "tool_calls",
                        }],
                        "usage": {},
                    }
                else:
                    # No tools requested from any chunk — go straight to synthesis
                    logger_internal.info(
                        "Split-phase Turn 0: no tool calls collected; requesting direct synthesis"
                    )
                    logger_external.info(
                        "→ LLM Request (split-phase synthesis): %s messages, 0 tools",
                        len(messages_for_llm),
                    )
                    llm_response = await llm_client.chat_completion(
                        messages=messages_for_llm,
                        tools=[],
                    )
                    aql_llm_turn_count += 1
            elif turn == 0 and _direct_route_tool_calls is not None:
                # Direct-route bypass: skip LLM, inject the single known tool call
                logger_internal.info(
                    "Direct-route Turn 0: injecting 1 pre-determined tool call for %s, skipping LLM call",
                    _direct_route_tool_calls[0]["function"]["name"],
                )
                logger_external.info(
                    "MCP CLIENT → MCP SERVER TOOLS LIST: [%s] (direct-route bypass, no LLM call)",
                    _direct_route_tool_calls[0]["function"]["name"],
                )
                llm_response = {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": _direct_route_tool_calls,
                        },
                        "finish_reason": "tool_calls",
                    }],
                    "usage": {},
                }
            else:
                # Normal path: log and call LLM
                logger_external.info(
                    f"→ LLM Request: {len(messages_for_llm)} messages, {len(tools_for_request)} tools sent ({len(tools_for_llm)} available)"
                )
                logger_internal.info(f"Messages to LLM: {json.dumps(messages_for_llm, indent=2)}")
                if tools_for_request:
                    logger_internal.info(f"Tools sent to LLM: {json.dumps(tools_for_request, indent=2)}")
                elif tools_for_llm:
                    logger_internal.info(
                        "Skipping tool catalog for follow-up LLM request because tool results are already in context"
                    )
                llm_response = await llm_client.chat_completion(
                    messages=messages_for_llm,
                    tools=tools_for_request,
                )
                aql_llm_turn_count += 1
            
            # Extract assistant message
            assistant_msg = llm_response["choices"][0]["message"]
            finish_reason = llm_response["choices"][0]["finish_reason"]
            
            # Log response from LLM
            logger_external.info(f"← LLM Response: finish_reason={finish_reason}, has_tool_calls={'tool_calls' in assistant_msg}")
            logger_internal.info(f"LLM Response: {json.dumps(llm_response, indent=2)}")
            logger_internal.info(f"LLM finish_reason: {finish_reason}")
            logger_internal.info(f"LLM message has tool_calls: {'tool_calls' in assistant_msg}")
            
            # Check if LLM wants to call tools
            assistant_tool_calls = assistant_msg.get("tool_calls") or []
            recovered_tool_calls_from_content = []
            if not assistant_tool_calls and assistant_msg.get("content"):
                recovered_tool_calls_from_content = extract_tool_calls_from_content(
                    assistant_msg.get("content", ""),
                    turn + 1,
                )
                if recovered_tool_calls_from_content:
                    assistant_tool_calls = recovered_tool_calls_from_content
                    logger_internal.warning(
                        "Recovered %s tool call(s) from assistant content because provider returned JSON content instead of tool_calls",
                        len(assistant_tool_calls),
                    )
            has_tool_calls = len(assistant_tool_calls) > 0

            if has_tool_calls:
                assistant_content = (assistant_msg.get("content") or "").strip()
                if assistant_content and initial_llm_response is None and not recovered_tool_calls_from_content:
                    initial_llm_response = assistant_content
                if assistant_content:
                    latest_assistant_tool_guidance = assistant_content

                if finish_reason != "tool_calls":
                    logger_internal.info(
                        "LLM returned tool_calls with non-standard finish_reason=%s; continuing with tool execution",
                        finish_reason,
                    )

                num_tool_calls = len(assistant_tool_calls)
                logger_internal.info(f"LLM requested {num_tool_calls} tool call{'s' if num_tool_calls > 1 else ''}")
                
                if num_tool_calls > 1:
                    tool_names = [tc.get("function", {}).get("name", "") for tc in assistant_tool_calls]
                    logger_internal.info(f"Multiple tools will be executed: {', '.join(tool_names)}")
                
                # Store assistant message with tool calls
                from backend.models import ToolCall, FunctionCall
                tool_calls_models = []
                normalized_tool_calls = []
                for tool_call_index, tc in enumerate(assistant_tool_calls, 1):
                    function_payload = tc.get("function", {})
                    tool_call_id = tc.get("id") or f"tool_call_{turn + 1}_{tool_call_index}"

                    # Convert arguments to JSON string if it's a dict (Ollama format)
                    arguments = function_payload.get("arguments", {})
                    if isinstance(arguments, dict):
                        arguments = json.dumps(arguments)
                    elif not isinstance(arguments, str):
                        arguments = json.dumps(arguments or {})

                    normalized_tool_calls.append({
                        "id": tool_call_id,
                        "type": tc.get("type", "function"),
                        "function": {
                            "name": function_payload.get("name", ""),
                            "arguments": arguments,
                        },
                    })
                    
                    tool_calls_models.append(
                        ToolCall(
                            id=tool_call_id,
                            type="function",
                            function=FunctionCall(
                                name=function_payload.get("name", ""),
                                arguments=arguments
                            )
                        )
                    )
                
                assistant_message_obj = ChatMessage(
                    role="assistant",
                    content="" if recovered_tool_calls_from_content else (assistant_msg.get("content") or ""),
                    tool_calls=tool_calls_models
                )
                session_manager.add_message(session_id, assistant_message_obj)

                # --- E2E turn budget advisory ---
                # Compute the worst-case wall-clock budget for this entire turn:
                #   totalTurnBudgetMs = llm_call_1 + sum(tool_budgets) + llm_call_2
                # This is purely advisory: logged so operators can size upstream
                # proxy / nginx / client-side fetch timeouts accordingly.
                llm_timeout_ms = llm_config_storage.llm_timeout_ms
                tool_budget_parts = []
                for tc in normalized_tool_calls:
                    tc_name = tc["function"].get("name", "")
                    stored_tool = mcp_manager.tools.get(tc_name)
                    hints = stored_tool.execution_hints if stored_tool else None
                    if hints:
                        budget_ms = hints.recommended_wait_ms()
                    else:
                        # Fall back to the server-level timeout_ms for this tool's server
                        tc_server_alias = tc_name.split("__", 1)[0] if "__" in tc_name else ""
                        fallback_server = next(
                            (s for s in servers_storage.values() if s.alias == tc_server_alias), None
                        )
                        budget_ms = fallback_server.timeout_ms if fallback_server else int(
                            os.getenv("MCP_REQUEST_TIMEOUT_MS", "20000")
                        )
                    tool_budget_parts.append((tc_name, budget_ms))

                total_tool_budget_ms = sum(b for _, b in tool_budget_parts)
                # Two LLM calls: the one that produced these tool_calls + the follow-up synthesis call
                total_turn_budget_ms = (2 * llm_timeout_ms) + total_tool_budget_ms
                tool_budget_str = ", ".join(
                    f"{name.split('__', 1)[-1]}({b / 1000:.0f}s)" for name, b in tool_budget_parts
                )
                logger_internal.info(
                    "E2E turn budget advisory: "
                    f"2×LLM({llm_timeout_ms / 1000:.0f}s) + tools[{tool_budget_str}] "
                    f"= {total_turn_budget_ms / 1000:.0f}s total. "
                    "Ensure upstream proxy/client timeouts exceed this value."
                )

                # Log the full list of tools about to be dispatched to MCP servers
                _exec_tool_names = [tc["function"].get("name", "") for tc in normalized_tool_calls]
                logger_external.info(
                    "MCP CLIENT → MCP SERVER TOOLS LIST: [%s] (%s tool(s))",
                    ", ".join(_exec_tool_names),
                    len(_exec_tool_names),
                )

                # -----------------------------------------------------------------
                # Phase 1: Pre-parse all tool calls and classify them.
                # -----------------------------------------------------------------
                _parsed_tool_calls: List[Dict[str, Any]] = []
                for _idx, _tc in enumerate(normalized_tool_calls, 1):
                    _tc_id = _tc["id"]
                    _tc_name = _tc["function"].get("name", "")
                    _tc_args_raw = _tc["function"].get("arguments", "{}")
                    try:
                        _tc_args = json.loads(_tc_args_raw) if isinstance(_tc_args_raw, str) else _tc_args_raw
                    except json.JSONDecodeError:
                        _tc_args = {}
                    _tc_dedup = json.dumps(
                        {"tool": _tc_name, "arguments": _tc_args},
                        sort_keys=True,
                        default=str,
                    )
                    _parsed_tool_calls.append({
                        "idx": _idx,
                        "tool_id": _tc_id,
                        "namespaced_tool_name": _tc_name,
                        "arguments": _tc_args,
                        "dedupe_key": _tc_dedup,
                    })

                # -----------------------------------------------------------------
                # Phase 2: Fire all independent (non-deduped, non-virtual) MCP
                # tool calls in parallel.  Results are collected keyed by tool_id
                # and injected in original tool_call order in Phase 3 below.
                # mcp_repeated_exec stays sequential; it is excluded from the batch.
                # Pipeline path: _pre_executed_results_map is pre-populated and
                # _parallel_candidates will be empty; asyncio.gather is skipped.
                # -----------------------------------------------------------------

                # Seed _parallel_results_map from pipeline results for Turn 0
                # so Phase 3 reads already-executed results without re-running them.
                _parallel_results_map: Dict[str, Dict[str, Any]] = (
                    dict(_pre_executed_results_map) if (turn == 0 and _pre_executed_results_map) else {}
                )

                _parallel_candidates = [
                    pc for pc in _parsed_tool_calls
                    if pc["namespaced_tool_name"] != "mcp_repeated_exec"
                    and pc["dedupe_key"] not in executed_tool_results
                    and pc["tool_id"] not in _parallel_results_map  # skip pipeline-pre-executed
                ]
                _use_batch = _should_batch_tool_results(num_tool_calls)
                if len(_parallel_candidates) > 1:
                    if _use_batch:
                        logger_internal.info(
                            "Executing %s tool calls in parallel (batch mode, threshold=%s): %s",
                            len(_parallel_candidates),
                            _get_int_env("MCP_TOOL_BATCH_THRESHOLD", 3),
                            ", ".join(pc["namespaced_tool_name"] for pc in _parallel_candidates),
                        )
                        logger_external.info(
                            "→ PARALLEL TOOL DISPATCH: %s tool(s) fired concurrently",
                            len(_parallel_candidates),
                        )
                    else:
                        logger_internal.info(
                            "Executing %s tool calls sequentially (below batch threshold=%s): %s",
                            len(_parallel_candidates),
                            _get_int_env("MCP_TOOL_BATCH_THRESHOLD", 3),
                            ", ".join(pc["namespaced_tool_name"] for pc in _parallel_candidates),
                        )
                        logger_external.info(
                            "→ SEQUENTIAL TOOL DISPATCH: %s tool(s) run one-at-a-time",
                            len(_parallel_candidates),
                        )

                _raw_parallel: List[Any] = []
                if _parallel_candidates:
                    if _use_batch:
                        # Batch path: fire all in parallel, wait for all results.
                        _raw_parallel = list(await asyncio.gather(
                            *[_run_one_mcp_tool(pc) for pc in _parallel_candidates],
                            return_exceptions=True,
                        ))
                    else:
                        # Sequential path: run one at a time; results are still
                        # injected together in Phase 3 after all tools complete.
                        for _seq_pc in _parallel_candidates:
                            try:
                                _seq_result = await _run_one_mcp_tool(_seq_pc)
                            except Exception as _seq_exc:  # noqa: BLE001
                                _seq_result = _seq_exc
                            _raw_parallel.append(_seq_result)

                for _pc, _raw in zip(_parallel_candidates, _raw_parallel):
                    if isinstance(_raw, BaseException):
                        _parallel_results_map[_pc["tool_id"]] = {
                            **_pc,
                            "result_content": f"Error: {_raw}",
                            "tool_result": str(_raw),
                            "success": False,
                            "duration_ms": 0,
                        }
                    else:
                        _parallel_results_map[_pc["tool_id"]] = _raw

                # -----------------------------------------------------------------
                # Phase 3: Inject results in original tool_call order.
                # Deduped hits use the cached result; mcp_repeated_exec is executed
                # sequentially inline; normal tool results come from the parallel map.
                # -----------------------------------------------------------------
                for pc in _parsed_tool_calls:
                    tool_id = pc["tool_id"]
                    namespaced_tool_name = pc["namespaced_tool_name"]
                    arguments = pc["arguments"]
                    dedupe_key = pc["dedupe_key"]
                    idx = pc["idx"]

                    logger_internal.info("Executing tool %s/%s: %s", idx, num_tool_calls, namespaced_tool_name)

                    if dedupe_key in executed_tool_results:
                        cached_execution = executed_tool_results[dedupe_key]
                        logger_internal.info(
                            "Skipping duplicate tool call in same turn: %s with arguments=%s",
                            namespaced_tool_name,
                            arguments,
                        )
                        result_content = cached_execution["result_content"]
                        tool_result_msg = llm_client.format_tool_result(
                            tool_call_id=tool_id,
                            content=result_content,
                        )
                        messages_for_llm.append(tool_result_msg)
                        tool_msg_obj = ChatMessage(role="tool", content=result_content)
                        if "tool_call_id" in tool_result_msg:
                            tool_msg_obj.tool_call_id = tool_result_msg["tool_call_id"]
                        session_manager.add_message(session_id, tool_msg_obj)
                        continue

                    # ---------------------------------------------------------
                    # mcp_repeated_exec intercept (virtual client-side tool)
                    # Must be checked BEFORE the __-split guard below.
                    # ---------------------------------------------------------
                    if namespaced_tool_name == "mcp_repeated_exec":
                        logger_internal.info("Intercepted mcp_repeated_exec virtual tool call")

                        # --- Parameter validation (FR-REP-001..005) ---
                        target_tool = arguments.get("target_tool", "") if isinstance(arguments, dict) else ""
                        repeat_count_raw = arguments.get("repeat_count") if isinstance(arguments, dict) else None
                        interval_ms_raw = arguments.get("interval_ms") if isinstance(arguments, dict) else None
                        tool_arguments_raw = arguments.get("tool_arguments", {}) if isinstance(arguments, dict) else {}
                        if not isinstance(tool_arguments_raw, dict):
                            tool_arguments_raw = {}

                        validation_error: Optional[str] = None

                        if repeat_count_raw is None or interval_ms_raw is None:
                            validation_error = (
                                "`mcp_repeated_exec` requires both `repeat_count` (integer 1\u201310) "
                                "and `interval_ms` (integer \u2265 0). "
                                "Please ask the user to re-send the request with both values specified."
                            )
                        elif not isinstance(repeat_count_raw, int) or not isinstance(interval_ms_raw, int):
                            validation_error = (
                                "`mcp_repeated_exec` requires both `repeat_count` (integer 1\u201310) "
                                "and `interval_ms` (integer \u2265 0). "
                                "Please ask the user to re-send the request with both values specified."
                            )
                        elif repeat_count_raw < 1 or repeat_count_raw > 10:
                            validation_error = (
                                f"`repeat_count` must be between 1 and 10. "
                                f"Value `{repeat_count_raw}` is not allowed."
                            )
                        elif interval_ms_raw < 0:
                            validation_error = (
                                "`interval_ms` must be a non-negative integer (\u2265 0)."
                            )
                        elif not target_tool or target_tool not in mcp_manager.tools:
                            validation_error = (
                                f"Target tool `{target_tool}` is not registered. "
                                "Please refresh tools and try again."
                            )

                        if validation_error:
                            logger_internal.warning(
                                f"mcp_repeated_exec: validation failed \u2014 {validation_error}"
                            )
                            result_content = validation_error

                            tool_result_msg = llm_client.format_tool_result(
                                tool_call_id=tool_id,
                                content=result_content
                            )
                            messages_for_llm.append(tool_result_msg)
                            tool_msg_obj = ChatMessage(role="tool", content=result_content)
                            if "tool_call_id" in tool_result_msg:
                                tool_msg_obj.tool_call_id = tool_result_msg["tool_call_id"]
                            session_manager.add_message(session_id, tool_msg_obj)
                            continue

                        # --- Resolve server for target tool ---
                        repeat_count: int = repeat_count_raw
                        interval_ms: int = interval_ms_raw
                        target_server_alias = target_tool.split("__", 1)[0]
                        target_tool_name = target_tool.split("__", 1)[1]
                        target_server = next(
                            (s for s in servers_storage.values() if s.alias == target_server_alias),
                            None
                        )
                        if not target_server:
                            validation_error = (
                                f"Server `{target_server_alias}` for tool `{target_tool}` "
                                "is not registered. Please check your server configuration."
                            )
                            logger_internal.warning(f"mcp_repeated_exec: {validation_error}")
                            result_content = validation_error
                            tool_result_msg = llm_client.format_tool_result(
                                tool_call_id=tool_id, content=result_content
                            )
                            messages_for_llm.append(tool_result_msg)
                            tool_msg_obj = ChatMessage(role="tool", content=result_content)
                            if "tool_call_id" in tool_result_msg:
                                tool_msg_obj.tool_call_id = tool_result_msg["tool_call_id"]
                            session_manager.add_message(session_id, tool_msg_obj)
                            continue

                        target_hints = mcp_manager.tools[target_tool].execution_hints

                        # --- Execute repeated runs ---
                        import time as _time
                        rep_start = _time.time()
                        summary: RepeatedExecSummary
                        written_files: list
                        summary, written_files = await mcp_manager.execute_repeated(
                            server=target_server,
                            tool_name=target_tool_name,
                            tool_arguments=tool_arguments_raw,
                            repeat_count=repeat_count,
                            interval_ms=interval_ms,
                            execution_hints=target_hints,
                        )
                        rep_duration_ms = int((_time.time() - rep_start) * 1000)

                        # --- Build synthesis prompt (FR-REP-018/019/020) ---
                        max_chars = int(os.getenv("MCP_MAX_TOOL_OUTPUT_CHARS_TO_LLM", "131072"))  # default 128 KB
                        header = (
                            f"Repeated execution of `{target_tool_name}` complete.\n"
                            f"Runs: {repeat_count} | "
                            f"Interval: {interval_ms / 1000:.1f}s | "
                            f"Successful: {summary.success_count} | "
                            f"Failed: {summary.failure_count}\n"
                            "Intermediate files written and deleted after aggregation.\n\n"
                        )
                        instruction = _build_repeated_exec_triage_instruction(
                            target_tool_name=target_tool_name,
                            repeat_count=repeat_count,
                        )

                        # Budget chars for run blocks (header + instruction are protected)
                        reserved = len(header) + len(instruction)
                        budget_for_runs = max(0, max_chars - reserved)

                        run_blocks = []
                        for run in summary.runs:
                            run_status = "SUCCESS" if run.success else "FAILED"
                            result_str = _extract_tool_result_text(run.result) if run.result else ""
                            err_str = run.error or ""
                            block = (
                                f"--- Run {run.run_index} ({run.timestamp_utc}, "
                                f"{run.duration_ms / 1000:.1f}s, {run_status}) ---\n"
                                + (result_str if run.success else f"Error: {err_str}")
                                + "\n\n"
                            )
                            run_blocks.append(block)

                        # Truncate run blocks proportionally if needed
                        total_run_chars = sum(len(b) for b in run_blocks)
                        if total_run_chars > budget_for_runs and run_blocks:
                            ratio = budget_for_runs / total_run_chars
                            run_blocks = [
                                b[: max(80, int(len(b) * ratio))] + "... [truncated]\n\n"
                                for b in run_blocks
                            ]
                            logger_internal.info(
                                f"Synthesis prompt truncated: "
                                f"{total_run_chars} -> ~{budget_for_runs} chars "
                                f"(limit {max_chars})"
                            )
                        else:
                            logger_internal.info(
                                f"Synthesis prompt: "
                                f"{total_run_chars + reserved} chars (limit {max_chars}), "
                                "no truncation needed"
                            )

                        result_content = header + "".join(run_blocks) + instruction

                        # --- Delete run files (FR-REP-017) ---
                        for fpath in written_files:
                            try:
                                fpath.unlink()
                                logger_internal.info(f"Run file deleted: {fpath}")
                            except Exception as del_exc:
                                logger_internal.warning(
                                    f"Failed to delete run file: {fpath} \u2014 {del_exc}"
                                )

                        # --- Track in tool_executions & session trace (FR-REP-021) ---
                        tool_executions.append({
                            "tool": "mcp_repeated_exec",
                            "arguments": arguments,
                            "result": summary.model_dump(),
                            "result_text": result_content,
                            "success": summary.success_count > 0,
                            "duration_ms": rep_duration_ms,
                            "cache_hit": False,
                        })
                        session_manager.add_tool_trace(
                            session_id=session_id,
                            tool_name="mcp_repeated_exec",
                            arguments=arguments,
                            result=summary.model_dump(),
                            success=summary.success_count > 0,
                        )

                        # --- Inject synthesis as tool result message ---
                        tool_result_msg = llm_client.format_tool_result(
                            tool_call_id=tool_id,
                            content=result_content
                        )
                        logger_internal.info(
                            "mcp_repeated_exec synthesis injected: "
                            f"{len(result_content)} chars, "
                            f"{repeat_count} runs, "
                            f"{summary.success_count} success / {summary.failure_count} failed"
                        )
                        messages_for_llm.append(tool_result_msg)
                        tool_msg_obj = ChatMessage(role="tool", content=result_content)
                        if "tool_call_id" in tool_result_msg:
                            tool_msg_obj.tool_call_id = tool_result_msg["tool_call_id"]
                        session_manager.add_message(session_id, tool_msg_obj)
                        continue
                    # ---------------------------------------------------------
                    # END mcp_repeated_exec intercept
                    # ---------------------------------------------------------

                    # Inject result from parallel execution map (Phase 2 above).
                    _pr = _parallel_results_map.get(tool_id)
                    if _pr is None:
                        # Shouldn't happen, but fall back gracefully.
                        logger_internal.error(
                            "Parallel result missing for tool_id=%s tool=%s; skipping",
                            tool_id, namespaced_tool_name,
                        )
                        continue

                    result_content = _pr["result_content"]
                    tool_result = _pr["tool_result"]
                    tool_success = _pr["success"]
                    duration_ms = _pr["duration_ms"]

                    # Prefix with tool name so Ollama (which strips tool_call_id) still
                    # knows which tool produced this result.
                    labeled_result_content = f"[{namespaced_tool_name}]\n{result_content}"

                    # Track execution & update dedup cache.
                    tool_executions.append({
                        "tool": namespaced_tool_name,
                        "arguments": arguments,
                        "result": tool_result,
                        "result_text": result_content,
                        "success": tool_success,
                        "duration_ms": duration_ms,
                        "cache_hit": bool(_pr.get("cache_hit", False)),
                    })
                    executed_tool_results[dedupe_key] = {
                        "result_content": labeled_result_content,
                        "result": tool_result,
                        "success": tool_success,
                    }

                    if tool_success:
                        logger_internal.info("Tool result accepted as success: %s", namespaced_tool_name)
                    else:
                        logger_internal.warning(
                            "Tool result reported isError=true: %s", namespaced_tool_name,
                        )

                    session_manager.add_tool_trace(
                        session_id=session_id,
                        tool_name=namespaced_tool_name,
                        arguments=arguments,
                        result=tool_result,
                        success=tool_success,
                    )

                    # Format and inject tool result message.
                    tool_result_msg = llm_client.format_tool_result(
                        tool_call_id=tool_id,
                        content=labeled_result_content,
                    )
                    logger_internal.info(
                        "Prepared tool result for LLM: provider=%s tool=%s tool_call_id=%s content_preview=%s",
                        llm_config_storage.provider,
                        namespaced_tool_name,
                        tool_id,
                        labeled_result_content[:400],
                    )

                    # Add to messages
                    messages_for_llm.append(tool_result_msg)

                    # Store in session
                    tool_msg_obj = ChatMessage(
                        role="tool",
                        content=labeled_result_content,
                    )
                    
                    # Store in session
                    tool_msg_obj = ChatMessage(
                        role="tool",
                        content=result_content
                    )
                    if "tool_call_id" in tool_result_msg:
                        tool_msg_obj.tool_call_id = tool_result_msg["tool_call_id"]
                    session_manager.add_message(session_id, tool_msg_obj)

                # Rebuild provider-specific message history before the next LLM turn.
                # This is required for Ollama, which cannot accept raw tool-role
                # messages or assistant tool_calls history in the same format as OpenAI.
                messages_for_llm = rebuild_messages_for_llm()
                tool_result_messages = [
                    msg for msg in messages_for_llm
                    if msg.get("role") == "tool"
                    or (
                        msg.get("role") == "user"
                        and isinstance(msg.get("content"), str)
                        and msg.get("content", "").startswith("Tool result:")
                    )
                ]
                if tool_result_messages:
                    latest_tool_result = tool_result_messages[-1]
                    logger_internal.info(
                        "Follow-up LLM request includes tool result message: role=%s content_preview=%s",
                        latest_tool_result.get("role"),
                        str(latest_tool_result.get("content", ""))[:400],
                    )

                # Synthesis enrichment: inject code_memory / doc_memory context
                # NOW (before the next LLM call) so the synthesis response can
                # actually cite source material.  Running it after finish_reason=stop
                # is too late — the answer is already built.
                if _memory_service is not None and tool_executions:
                    _synth_retrieval = await _memory_service.enrich_for_turn(
                        user_message=message.content,
                        session_id=session_id,
                        request_id=f"{message_transaction_id}-synthesis",
                        user_id=user_id or "",
                        include_code_memory=True,  # synthesis phase — include code/doc memory
                    )
                    if not _synth_retrieval.degraded and _synth_retrieval.blocks:
                        _synth_context = _format_retrieval_context(_synth_retrieval.blocks)
                        messages_for_llm = _inject_context_section(
                            messages_for_llm, _synth_context
                        )
                        logger_internal.info(
                            "Synthesis code-memory context injected: %s block(s) collections=%s",
                            len(_synth_retrieval.blocks),
                            list(_synth_retrieval.collection_keys),
                        )

                # Continue loop to get next LLM response
                continue
            
            # No more tool calls - final response
            else:
                # Only warn when tools were actually sent in this request and the model
                # returned stop without using any.  On synthesis turns tools_for_request
                # is intentionally empty, so this is not a concern there.
                if tools_for_request and not has_tool_calls:
                    logger_internal.warning(
                        "LLM returned final response without tool_calls despite %s tools being sent. finish_reason=%s, response_preview=%s",
                        len(tools_for_request),
                        finish_reason,
                        (assistant_msg.get("content", "")[:200] or "<empty>")
                    )

                logger_internal.info(f"LLM gave final response (no tool calls). Response length: {len(assistant_msg.get('content', ''))}")
                logger_internal.info(f"=== FINAL LLM MESSAGE ===\n{assistant_msg.get('content', '')}\n========================")
                response_usage = llm_response.get("usage") if isinstance(llm_response, dict) else {}
                if isinstance(response_usage, dict):
                    aql_synthesis_tokens = int(
                        response_usage.get("total_tokens")
                        or response_usage.get("completion_tokens")
                        or 0
                    )
                
                if tool_executions:
                    tools_summary = ', '.join([f"{te['tool']} ({'success' if te['success'] else 'failed'})" for te in tool_executions])
                    logger_internal.info(f"Tools executed in this turn ({len(tool_executions)}): {tools_summary}")
                
                final_response = ChatMessage(
                    role="assistant",
                    content=assistant_msg.get("content", "")
                )
                session_manager.add_message(session_id, final_response)
                logger_internal.info(
                    "Chat transaction completed: request_id=%s session=%s tool_executions=%s response_length=%s",
                    message_transaction_id,
                    session_id,
                    len(tool_executions),
                    len(final_response.content or ""),
                )
                logger_external.info("← 200 OK")
                if _memory_service is not None:
                    _tool_names = [te["tool"] for te in tool_executions if "tool" in te]
                    await _memory_service.record_turn(
                        user_message=message.content,
                        assistant_response=final_response.content or "",
                        session_id=session_id,
                        user_id=user_id or "",
                        tool_names=_tool_names,
                        turn_number=existing_message_count,
                    )
                    _remember_last_quality_turn(
                        memory_service=_memory_service,
                        session_id=session_id,
                        user_message=message.content,
                        request_id=message_transaction_id,
                    )
                    _schedule_execution_quality_record(
                        memory_service=_memory_service,
                        payload=_build_execution_quality_payload(),
                    )
                return ChatResponse(
                    session_id=session_id,
                    message=final_response,
                    tool_executions=tool_executions,
                    initial_llm_response=initial_llm_response,
                    transaction_id=message_transaction_id,
                    retrieval_trace=retrieval_trace_payload,
                    context_sources=retrieval_sources,
                )
        logger_internal.warning(f"Max tool call turns ({max_turns}) reached")
        fallback = ChatMessage(
            role="assistant",
            content="I've reached the maximum number of tool calls. Please start a new conversation."
        )
        session_manager.add_message(session_id, fallback)
        logger_internal.info(
            "Chat transaction completed: request_id=%s session=%s tool_executions=%s response_length=%s fallback=%s",
            message_transaction_id,
            session_id,
            len(tool_executions),
            len(fallback.content or ""),
            True,
        )
        logger_external.info("← 200 OK")
        if _memory_service is not None:
            _tool_names = [te["tool"] for te in tool_executions if "tool" in te]
            await _memory_service.record_turn(
                user_message=message.content,
                assistant_response=fallback.content or "",
                session_id=session_id,
                user_id=user_id or "",
                tool_names=_tool_names,
                turn_number=existing_message_count,
            )
            _remember_last_quality_turn(
                memory_service=_memory_service,
                session_id=session_id,
                user_message=message.content,
                request_id=message_transaction_id,
            )
            _schedule_execution_quality_record(
                memory_service=_memory_service,
                payload=_build_execution_quality_payload(),
            )
        return ChatResponse(
            session_id=session_id,
            message=fallback,
            tool_executions=tool_executions,
            initial_llm_response=initial_llm_response,
            transaction_id=message_transaction_id,
            retrieval_trace=retrieval_trace_payload,
            context_sources=retrieval_sources,
        )
        
    except Exception as e:
        logger_internal.error(
            "Chat transaction failed: request_id=%s session=%s reason=%s",
            message_transaction_id,
            session_id,
            e,
        )
        error_response = ChatMessage(
            role="assistant",
            content=f"Sorry, I encountered an error: {str(e)}"
        )
        session_manager.add_message(session_id, error_response)
        logger_external.info("← 200 OK (error)")
        
        return ChatResponse(
            session_id=session_id,
            message=error_response,
            tool_executions=[],
            context_sources=None,
            initial_llm_response=None,
            transaction_id=message_transaction_id,
            retrieval_trace=retrieval_trace_payload,
        )


@app.get(
    "/api/sessions/{session_id}/messages",
    response_model=MessageListResponse,
    tags=["Chat"],
    summary="Get message history",
    description="Retrieve all messages in a session",
    responses={
        200: {"description": "Message history retrieved"},
        404: {"model": ErrorResponse, "description": "Session not found"}
    }
)
async def get_messages(
    session_id: str = Path(..., description="Session UUID")
) -> MessageListResponse:
    """Get conversation history for a session"""
    logger_external.info(f"→ GET /api/sessions/{session_id}/messages")
    
    # TODO: Get messages from SessionManager
    # messages = await session_manager.get_messages(session_id)
    
    logger_external.info(f"← 200 OK")
    
    return MessageListResponse(
        session_id=session_id,
        messages=[]
    )


# ============================================================================
# Static Files & Frontend
# ============================================================================

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
async def serve_frontend():
    """Serve the main frontend HTML"""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(
            index_path,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    else:
        return {"message": "MCP Client Web API - Frontend not yet deployed. Access API docs at /docs"}


@app.get("/tool-tester", include_in_schema=False)
async def serve_tool_tester():
    """Serve the dedicated MCP tool tester page."""
    tool_tester_path = os.path.join(static_dir, "tool-tester.html")
    if os.path.exists(tool_tester_path):
        return FileResponse(
            tool_tester_path,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Tool tester page not found"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
