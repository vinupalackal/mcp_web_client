"""
MCP Manager - JSON-RPC 2.0 Client for MCP Servers
Handles server initialization, tool discovery, and tool execution
"""

import asyncio
import json
import logging
import os
import re
import socket
import time
import httpx
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from backend.models import (
    ServerConfig,
    ToolSchema,
    ExecutionHints,
    RepeatedExecRunResult,
    RepeatedExecSummary,
)

# ---------------------------------------------------------------------------
# Virtual tool: mcp_repeated_exec
# Injected into the LLM tool catalog on every get_tools_for_llm() call.
# Intercepted by main.py BEFORE MCP dispatch; never sent to a real server.
# ---------------------------------------------------------------------------
VIRTUAL_REPEATED_EXEC_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "mcp_repeated_exec",
        "description": (
            "Execute an MCP tool N times at a fixed interval for trend analysis and "
            "longitudinal diagnostics. repeat_count and interval_ms are mandatory — "
            "the tool will return an error if either is missing. "
            "Results are saved to files and all runs are sent to the LLM for final synthesis."
        ),
        "parameters": {
            "type": "object",
            "required": ["target_tool", "repeat_count", "interval_ms"],
            "properties": {
                "target_tool": {
                    "type": "string",
                    "description": "Namespaced MCP tool ID to repeat (server_alias__tool_name)",
                },
                "tool_arguments": {
                    "type": "object",
                    "description": "Arguments to pass to the target tool on every run (optional, defaults to {})",
                },
                "repeat_count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "description": "Number of times to execute the target tool (1\u201310)",
                },
                "interval_ms": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Delay between consecutive runs in milliseconds (0 = back-to-back)",
                },
            },
        },
    },
}

logger_internal = logging.getLogger("mcp_client.internal")
logger_external = logging.getLogger("mcp_client.external")


class MCPManager:
    """Manages MCP server connections and tool operations via JSON-RPC 2.0"""
    
    def __init__(self):
        self.initialized_servers: Dict[str, bool] = {}
        self.tools: Dict[str, ToolSchema] = {}  # namespaced_id -> ToolSchema
        self.timeout = httpx.Timeout(
            connect=5.0,
            read=float(os.getenv("MCP_REQUEST_TIMEOUT_MS", "20000")) / 1000,
            write=5.0,
            pool=5.0
        )
    
    async def initialize_server(self, server: ServerConfig) -> Dict[str, Any]:
        """
        Initialize MCP server with JSON-RPC handshake.
        
        Sends initialize method with protocol version and client info.
        """
        logger_internal.info(f"Initializing MCP server: {server.alias}")
        
        rpc_url = f"{server.base_url.rstrip('/')}/mcp"
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {
                    "name": "mcp-client-web",
                    "version": "1.0"
                },
                "capabilities": {}
            }
        }
        
        headers = self._build_headers(server)
        
        try:
            logger_external.info(f"→ POST {rpc_url} (initialize)")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    rpc_url,
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                result = response.json()
            
            logger_external.info(f"← {response.status_code} (initialize success)")
            
            # Check for JSON-RPC error
            if "error" in result:
                raise Exception(f"JSON-RPC error: {result['error']}")
            
            self.initialized_servers[server.server_id] = True
            logger_internal.info(f"Server initialized: {server.alias}")
            
            return result.get("result", {})
            
        except httpx.TimeoutException as e:
            logger_internal.error(f"Timeout initializing {server.alias}: {e}")
            raise Exception(f"Timeout connecting to {server.alias}")
        except httpx.HTTPError as e:
            logger_internal.error(f"HTTP error initializing {server.alias}: {e}")
            raise Exception(f"HTTP error: {str(e)}")
        except Exception as e:
            logger_internal.error(f"Failed to initialize {server.alias}: {e}")
            raise
    
    async def discover_tools(self, server: ServerConfig) -> List[ToolSchema]:
        """
        Discover tools from MCP server via tools/list method.
        
        Returns list of tools with namespaced IDs (server_alias__tool_name).
        """
        logger_internal.info(f"Discovering tools from: {server.alias}")
        
        # Ensure server is initialized
        if server.server_id not in self.initialized_servers:
            await self.initialize_server(server)
        
        rpc_url = f"{server.base_url.rstrip('/')}/mcp"
        
        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        }
        
        headers = self._build_headers(server)
        
        try:
            logger_external.info(f"→ POST {rpc_url} (tools/list)")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    rpc_url,
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                result = response.json()
            
            logger_external.info(f"← {response.status_code} (tools/list success)")
            
            # Check for JSON-RPC error
            if "error" in result:
                raise Exception(f"JSON-RPC error: {result['error']}")
            
            # Parse tools from result
            tools_data = result.get("result", {}).get("tools", [])
            tools = self._parse_tools(server.alias, tools_data)
            
            # Store tools
            for tool in tools:
                self.tools[tool.namespaced_id] = tool
            
            logger_internal.info(f"Discovered {len(tools)} tools from {server.alias}")
            
            return tools
            
        except httpx.TimeoutException as e:
            logger_internal.error(f"Timeout discovering tools from {server.alias}: {e}")
            raise Exception(f"Timeout: {server.alias}")
        except httpx.HTTPError as e:
            logger_internal.error(f"HTTP error discovering tools from {server.alias}: {e}")
            raise Exception(f"HTTP error: {str(e)}")
        except Exception as e:
            logger_internal.error(f"Failed to discover tools from {server.alias}: {e}")
            raise
    
    async def discover_all_tools(self, servers: List[ServerConfig]) -> tuple[int, int, List[str]]:
        """
        Discover tools from all configured servers.
        
        Returns: (total_tools, servers_refreshed, errors)
        """
        logger_internal.info(f"Discovering tools from {len(servers)} servers")
        
        total_tools = 0
        servers_refreshed = 0
        errors = []
        
        # Clear existing tools and initialization state
        self.tools.clear()
        self.initialized_servers.clear()
        
        for server in servers:
            try:
                tools = await self.discover_tools(server)
                total_tools += len(tools)
                servers_refreshed += 1
            except Exception as e:
                error_msg = f"{server.alias}: {str(e)}"
                errors.append(error_msg)
                logger_internal.error(f"Error refreshing {server.alias}: {e}")
        
        logger_internal.info(
            f"Tool discovery complete: {total_tools} tools from "
            f"{servers_refreshed}/{len(servers)} servers"
        )
        
        return total_tools, servers_refreshed, errors

    async def check_server_health(self, server: ServerConfig) -> tuple[bool, Optional[str]]:
        """Check whether a server is reachable via MCP initialize handshake."""
        try:
            await self.initialize_server(server)
            return True, None
        except Exception as e:
            self.initialized_servers.pop(server.server_id, None)
            return False, str(e)

    async def refresh_server_health(self, servers: List[ServerConfig]) -> tuple[int, int, List[str]]:
        """Refresh health metadata for all configured servers."""
        healthy_servers = 0
        errors: List[str] = []

        for server in servers:
            is_healthy, error = await self.check_server_health(server)
            if is_healthy:
                healthy_servers += 1
            else:
                errors.append(f"{server.alias}: {error}")

        return len(servers), healthy_servers, errors
    
    async def execute_tool(
        self,
        server: ServerConfig,
        tool_name: str,
        arguments: Dict[str, Any],
        execution_hints: Optional[ExecutionHints] = None
    ) -> Dict[str, Any]:
        """
        Execute a tool on MCP server via tools/call method.

        Args:
            server: Server configuration
            tool_name: Original tool name (not namespaced)
            arguments: Tool arguments
            execution_hints: Advisory runtime metadata from executionHints in tools/list.
                Used to compute a per-call read timeout (CR-EXEC-005/008).
                Does NOT affect the tool argument contract (CR-EXEC-006/013).

        Returns:
            Tool execution result
        """
        logger_internal.info(f"Executing tool: {server.alias}__{tool_name}")
        logger_internal.info(f"Tool arguments: {arguments}")
        
        # Ensure server is initialized
        if server.server_id not in self.initialized_servers:
            await self.initialize_server(server)
        
        rpc_url = f"{server.base_url.rstrip('/')}/mcp"
        
        payload = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        
        headers = self._build_headers(server)
        
        call_timeout = self._compute_tool_timeout(execution_hints)

        try:
            logger_external.info(f"→ MCP Server Request: POST {rpc_url} (tools/call: {tool_name})")
            logger_internal.info(f"JSON-RPC Payload to MCP Server: {payload}")
            logger_internal.info(f"Request headers: {headers}")
            logger_internal.info(
                f"MCP call timeout: read={call_timeout.read:.1f}s "
                f"({'hints-derived' if execution_hints else 'global default'})"
            )

            async with httpx.AsyncClient(timeout=call_timeout) as client:
                response = await client.post(
                    rpc_url,
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                result = response.json()
            
            logger_external.info(f"← MCP Server Response: {response.status_code} (tool execution complete)")
            logger_internal.info(f"JSON-RPC Response from MCP Server: {result}")
            
            # Check for JSON-RPC error
            if "error" in result:
                error_info = result["error"]
                error_msg = error_info.get('message', 'Unknown error')
                error_code = error_info.get('code', 'N/A')
                error_data = error_info.get('data', {})
                
                logger_internal.error(f"MCP server error for {tool_name}:")
                logger_internal.error(f"  Code: {error_code}")
                logger_internal.error(f"  Message: {error_msg}")
                logger_internal.error(f"  Data: {error_data}")
                
                raise Exception(
                    f"Tool execution error: {error_msg}"
                )
            
            execution_result = result.get("result", {})
            logger_internal.info(f"Tool executed successfully: {tool_name}")
            
            return execution_result
            
        except httpx.TimeoutException as e:
            logger_internal.error(f"Timeout executing tool {tool_name}: {e}")
            raise Exception(f"Timeout executing {tool_name}")
        except httpx.HTTPError as e:
            logger_internal.error(f"HTTP error executing tool {tool_name}: {e}")
            raise Exception(f"HTTP error: {str(e)}")
        except Exception as e:
            logger_internal.error(f"Failed to execute tool {tool_name}: {e}")
            raise
    
    async def execute_repeated(
        self,
        server: ServerConfig,
        tool_name: str,
        tool_arguments: Dict[str, Any],
        repeat_count: int,
        interval_ms: int,
        execution_hints: Optional[ExecutionHints] = None,
    ) -> RepeatedExecSummary:
        """Execute a tool N times sequentially with a configurable interval.

        Writes one JSON file per run immediately after each run completes.
        Deletes all run files after the caller has built the synthesis prompt.
        Returns a RepeatedExecSummary with all run results.

        Args:
            server:           Server to execute the tool on.
            tool_name:        Bare tool name (no server alias prefix).
            tool_arguments:   Arguments forwarded to the tool on every run.
            repeat_count:     Number of runs (caller must validate 1-10).
            interval_ms:      Sleep between runs in ms (0 = back-to-back).
            execution_hints:  Advisory hints reused for per-call timeout.
        """
        device_id = self._safe_name(
            os.getenv("MCP_DEVICE_ID", socket.gethostname())
        )
        safe_tool_name = self._safe_name(tool_name)
        pad = len(str(repeat_count))  # zero-padding width

        # Resolve output directory (never logged per NFR-REP-007)
        output_dir_raw = os.getenv("MCP_REPEATED_EXEC_OUTPUT_DIR", "data/runs")
        output_dir = Path(output_dir_raw)
        output_dir.mkdir(parents=True, exist_ok=True)

        namespaced = f"{server.alias}__{tool_name}"
        logger_internal.info(
            f"Repeated exec starting: {namespaced} ×{repeat_count}, interval={interval_ms}ms"
        )

        # --- E2E budget advisory (FR-REP-022/023) ---
        if execution_hints:
            tool_budget_ms = execution_hints.recommended_wait_ms()
        else:
            tool_budget_ms = server.timeout_ms
        # llm_timeout pulled from env; used here for logging only
        llm_timeout_ms = int(os.getenv("MCP_LLM_TIMEOUT_MS", "180000"))
        total_budget_ms = repeat_count * (tool_budget_ms + interval_ms) + llm_timeout_ms
        logger_internal.info(
            f"Repeated exec E2E budget: {repeat_count} runs × "
            f"({tool_budget_ms / 1000:.0f}s tool + {interval_ms / 1000:.0f}s interval) "
            f"+ LLM({llm_timeout_ms / 1000:.0f}s) = {total_budget_ms / 1000:.0f}s total. "
            "Ensure upstream proxy/client timeouts exceed this value."
        )

        seq_start = time.time()
        runs: List[RepeatedExecRunResult] = []
        written_files: List[Path] = []

        for run_idx in range(1, repeat_count + 1):
            ts_dt = datetime.now(timezone.utc)
            timestamp_utc = ts_dt.strftime("%Y%m%dT%H%M%SZ")
            timestamp_iso = ts_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            logger_internal.info(
                f"Run {run_idx}/{repeat_count}: {namespaced} started at {timestamp_iso}"
            )

            run_start = time.time()
            result_payload: Optional[Dict[str, Any]] = None
            error_msg: Optional[str] = None
            run_success = False

            try:
                result_payload = await self.execute_tool(
                    server=server,
                    tool_name=tool_name,
                    arguments=tool_arguments,
                    execution_hints=execution_hints,
                )
                run_success = True
            except Exception as exc:
                error_msg = str(exc)
                logger_internal.warning(
                    f"Run {run_idx}/{repeat_count} failed: {error_msg}"
                )

            duration_ms = int((time.time() - run_start) * 1000)
            logger_internal.info(
                f"Run {run_idx}/{repeat_count} complete: {duration_ms}ms, success={run_success}"
            )

            # --- Write run file (FR-REP-011..016) ---
            run_index_str = str(run_idx).zfill(pad)
            file_name = f"{device_id}_{safe_tool_name}_{run_index_str}_{timestamp_utc}.txt"
            file_path = output_dir / file_name
            file_path_str: Optional[str] = None

            file_payload = {
                "device_id": device_id,
                "target_tool": namespaced,
                "tool_name": tool_name,
                "tool_arguments": tool_arguments,
                "run_index": run_idx,
                "repeat_count": repeat_count,
                "interval_ms": interval_ms,
                "timestamp_utc": timestamp_iso,
                "duration_ms": duration_ms,
                "success": run_success,
                "result": result_payload,
                "error": error_msg,
            }
            try:
                file_path.write_text(
                    json.dumps(file_payload, indent=2, default=str),
                    encoding="utf-8",
                )
                file_path_str = str(file_path)
                written_files.append(file_path)
                logger_internal.info(f"Run file written: {file_path}")
            except Exception as write_exc:
                logger_internal.warning(
                    f"Failed to write run file: {file_path} — {write_exc}"
                )

            runs.append(
                RepeatedExecRunResult(
                    run_index=run_idx,
                    timestamp_utc=timestamp_iso,
                    duration_ms=duration_ms,
                    success=run_success,
                    result=result_payload,
                    error=error_msg,
                    file_path=file_path_str,
                )
            )

            # Interval sleep between runs — not after the last run (FR-REP-010)
            if run_idx < repeat_count and interval_ms > 0:
                await asyncio.sleep(interval_ms / 1000.0)

        total_duration_ms = int((time.time() - seq_start) * 1000)
        success_count = sum(1 for r in runs if r.success)
        failure_count = repeat_count - success_count

        logger_internal.info(
            f"Repeated exec complete: {repeat_count} runs, "
            f"{success_count} success, {failure_count} failed, "
            f"total={total_duration_ms / 1000:.1f}s"
        )

        summary = RepeatedExecSummary(
            device_id=device_id,
            target_tool=namespaced,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            repeat_count=repeat_count,
            interval_ms=interval_ms,
            output_dir=str(output_dir),
            runs=runs,
            total_duration_ms=total_duration_ms,
            success_count=success_count,
            failure_count=failure_count,
        )

        return summary, written_files

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_name(value: str) -> str:
        """Sanitise a string for use in a file name (NFR-REP-006).

        Strips path-traversal characters, replaces spaces and remaining
        non-alphanumeric chars with underscores, and collapses runs.
        """
        # Remove any path-separator or traversal sequences
        value = re.sub(r'[\\/]+', '_', value)
        value = re.sub(r'\.\.\.?', '_', value)
        # Replace spaces
        value = value.replace(' ', '_')
        # Strip any remaining unsafe chars
        value = re.sub(r'[^A-Za-z0-9_\-]', '_', value)
        # Collapse repeated underscores
        value = re.sub(r'_+', '_', value).strip('_')
        return value or "unknown"

    def get_all_tools(self) -> List[ToolSchema]:
        """Get all discovered tools"""
        return list(self.tools.values())
    
    def get_tools_for_llm(self) -> List[Dict[str, Any]]:
        """
        Get tools in OpenAI function calling format for LLM.

        Appends the client-side virtual tool `mcp_repeated_exec` so the LLM
        can request repeated execution of any registered tool.
        """
        tools = []

        for tool in self.tools.values():
            tools.append({
                "type": "function",
                "function": {
                    "name": tool.namespaced_id,
                    "description": tool.description,
                    "parameters": tool.parameters
                }
            })

        # Always inject the virtual repeated-exec tool (intercepted in main.py)
        tools.append(VIRTUAL_REPEATED_EXEC_TOOL)

        return tools

    def get_tools_for_llm_chunks(self, chunk_size: int) -> List[List[Dict[str, Any]]]:
        """Return tools in OpenAI function calling format split into chunks.

        Each chunk contains at most ``chunk_size`` tools, with the virtual
        ``mcp_repeated_exec`` tool always appended so the LLM can call it
        regardless of which chunk it receives.

        When all real tools fit within a single chunk the result is a
        single-element list identical to ``get_tools_for_llm()``.

        Args:
            chunk_size: Maximum tools per chunk (includes the virtual tool slot).
        """
        real_tools = [
            {
                "type": "function",
                "function": {
                    "name": tool.namespaced_id,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self.tools.values()
        ]

        # Reserve one slot per chunk for VIRTUAL_REPEATED_EXEC_TOOL
        effective_chunk_size = max(1, chunk_size - 1)

        if len(real_tools) <= effective_chunk_size:
            # Everything fits — identical to get_tools_for_llm()
            return [real_tools + [VIRTUAL_REPEATED_EXEC_TOOL]]

        # Split real tools into chunks; append virtual tool to each chunk
        chunks: List[List[Dict[str, Any]]] = []
        for offset in range(0, len(real_tools), effective_chunk_size):
            chunk = real_tools[offset: offset + effective_chunk_size]
            chunks.append(chunk + [VIRTUAL_REPEATED_EXEC_TOOL])

        logger_internal.info(
            "Tool split: %s real tools → %s chunk(s) of ≤%s (chunk_size=%s)",
            len(real_tools), len(chunks), effective_chunk_size, chunk_size,
        )
        return chunks
    
    def _build_headers(self, server: ServerConfig) -> Dict[str, str]:
        """Build HTTP headers with authentication"""
        headers = {
            "Content-Type": "application/json"
        }
        
        if server.auth_type == "bearer" and server.bearer_token:
            headers["Authorization"] = f"Bearer {server.bearer_token}"
        elif server.auth_type == "api_key" and server.api_key:
            headers["X-API-Key"] = server.api_key
        
        return headers
    
    def _parse_tools(self, server_alias: str, tools_data: List[Dict]) -> List[ToolSchema]:
        """
        Parse JSON-RPC tools response into ToolSchema objects.

        Adds namespace prefix to tool names: server_alias__tool_name.
        Parses optional executionHints into ExecutionHints model (CR-EXEC-001..004).
        """
        tools = []

        for tool_data in tools_data:
            tool_name = tool_data.get("name", "")
            namespaced_id = f"{server_alias}__{tool_name}"

            # Parse executionHints — optional, tolerate absence and unknown fields
            execution_hints: Optional[ExecutionHints] = None
            raw_hints = tool_data.get("executionHints")
            if raw_hints and isinstance(raw_hints, dict):
                try:
                    execution_hints = ExecutionHints.model_validate(raw_hints)
                    logger_internal.debug(
                        f"Parsed executionHints for {namespaced_id}: "
                        f"mode={execution_hints.mode}, "
                        f"estimatedRuntimeMs={execution_hints.estimatedRuntimeMs}, "
                        f"recommendedWaitMs={execution_hints.recommended_wait_ms()}"
                    )
                except Exception as e:
                    logger_internal.warning(
                        f"Failed to parse executionHints for {namespaced_id}, ignoring: {e}"
                    )

            tool = ToolSchema(
                namespaced_id=namespaced_id,
                server_alias=server_alias,
                name=tool_name,
                description=tool_data.get("description", ""),
                parameters=tool_data.get("inputSchema", {}),
                execution_hints=execution_hints
            )

            tools.append(tool)

        return tools

    def _compute_tool_timeout(self, execution_hints: Optional[ExecutionHints]) -> httpx.Timeout:
        """Build a per-call httpx.Timeout driven by executionHints.

        When executionHints is present the read timeout is set to the
        recommended client-side wait budget (CR-EXEC-005/008):

            recommendedWaitMs = max(defaultTimeoutMs, estimatedRuntimeMs) + clientWaitMarginMs

        The computed read timeout is always at least as large as the global
        default so short hints never *reduce* patience.
        The global self.timeout is never mutated.
        """
        if execution_hints is None:
            return self.timeout

        recommended_s = execution_hints.recommended_wait_ms() / 1000.0
        # Never be less patient than the global default
        read_s = max(self.timeout.read, recommended_s)

        if read_s > self.timeout.read:
            logger_internal.info(
                f"Per-call read timeout extended to {read_s:.1f}s "
                f"(global default {self.timeout.read:.1f}s) "
                f"based on executionHints (mode={execution_hints.mode}, "
                f"recommendedWaitMs={execution_hints.recommended_wait_ms()})"
            )

        return httpx.Timeout(
            connect=self.timeout.connect,
            read=read_s,
            write=self.timeout.write,
            pool=self.timeout.pool
        )


# Global instance
mcp_manager = MCPManager()
