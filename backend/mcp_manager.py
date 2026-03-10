"""
MCP Manager - JSON-RPC 2.0 Client for MCP Servers
Handles server initialization, tool discovery, and tool execution
"""

import logging
import os
import httpx
from typing import Dict, List, Optional, Any
from backend.models import ServerConfig, ToolSchema

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
    
    async def execute_tool(
        self,
        server: ServerConfig,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a tool on MCP server via tools/call method.
        
        Args:
            server: Server configuration
            tool_name: Original tool name (not namespaced)
            arguments: Tool arguments
        
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
        
        try:
            logger_external.info(f"→ MCP Server Request: POST {rpc_url} (tools/call: {tool_name})")
            logger_internal.info(f"JSON-RPC Payload to MCP Server: {payload}")
            logger_internal.info(f"Request headers: {headers}")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
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
    
    def get_all_tools(self) -> List[ToolSchema]:
        """Get all discovered tools"""
        return list(self.tools.values())
    
    def get_tools_for_llm(self) -> List[Dict[str, Any]]:
        """
        Get tools in OpenAI function calling format for LLM.
        
        Returns list of tool definitions suitable for LLM providers.
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
        
        return tools
    
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
        
        Adds namespace prefix to tool names: server_alias__tool_name
        """
        tools = []
        
        for tool_data in tools_data:
            tool_name = tool_data.get("name", "")
            namespaced_id = f"{server_alias}__{tool_name}"
            
            tool = ToolSchema(
                namespaced_id=namespaced_id,
                server_alias=server_alias,
                name=tool_name,
                description=tool_data.get("description", ""),
                parameters=tool_data.get("inputSchema", {})
            )
            
            tools.append(tool)
        
        return tools


# Global instance
mcp_manager = MCPManager()
