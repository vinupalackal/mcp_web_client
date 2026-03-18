# Tool Call Flow Verification

## Flow Summary: LLM → MCP Server

### 1️⃣ **User Sends Message**
**File**: [backend/main.py](backend/main.py#L456-L462)
```python
async def send_message(session_id, message):
    # Add user message to session
    session_manager.add_message(session_id, message)
```

### 2️⃣ **Get Available Tools**
**File**: [backend/main.py](backend/main.py#L480-L487)
```python
# Get available tools from MCP Manager
tools_for_llm = mcp_manager.get_tools_for_llm()
logger_internal.info(f"Available tools for LLM: {len(tools_for_llm)} tools")
```

**Tool Format Sent to LLM**:
```json
{
  "type": "function",
  "function": {
    "name": "server_alias__tool_name",
    "description": "...",
    "parameters": {...}
  }
}
```

### 3️⃣ **LLM Chat Completion Call**
**File**: [backend/main.py](backend/main.py#L506-L509)
```python
llm_response = await llm_client.chat_completion(
    messages=messages_for_llm,
    tools=tools_for_llm  # ✅ Tools are provided to LLM
)
```

### 4️⃣ **LLM Chooses Tools**
**File**: [backend/main.py](backend/main.py#L511-L522)
```python
assistant_msg = llm_response["choices"][0]["message"]
finish_reason = llm_response["choices"][0]["finish_reason"]

if finish_reason == "tool_calls" and "tool_calls" in assistant_msg:
    logger_internal.info(f"LLM requested {len(assistant_msg['tool_calls'])} tool calls")
    # Process tool calls...
```

**LLM Response Format**:
```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "tool_calls": [
        {
          "id": "call_123",
          "type": "function",
          "function": {
            "name": "weather_api__get_weather",
            "arguments": "{\"city\": \"London\"}"
          }
        }
      ]
    },
    "finish_reason": "tool_calls"
  }]
}
```

### 5️⃣ **Parse Tool Calls**
**File**: [backend/main.py](backend/main.py#L555-L572)
```python
for tool_call in assistant_msg["tool_calls"]:
    tool_id = tool_call["id"]
    namespaced_tool_name = tool_call["function"]["name"]  # e.g., "server_alias__tool_name"
    arguments_str = tool_call["function"]["arguments"]
    
    # Parse namespaced tool name
    server_alias, actual_tool_name = namespaced_tool_name.split("__", 1)
    
    # Find server by alias
    for s in servers_storage.values():
        if s.alias == server_alias:
            server = s
            break
```

### 6️⃣ **Execute Tool on MCP Server** ✅
**File**: [backend/main.py](backend/main.py#L589-L593)
```python
tool_result = await mcp_manager.execute_tool(
    server=server,
    tool_name=actual_tool_name,  # ✅ Actual tool name (without namespace)
    arguments=arguments
)
```

### 7️⃣ **MCP Manager Executes Tool**
**File**: [backend/mcp_manager.py](backend/mcp_manager.py#L201-L237)
```python
async def execute_tool(self, server, tool_name, arguments):
    logger_internal.info(f"Executing tool: {server.alias}__{tool_name}")
    logger_internal.info(f"Tool arguments: {arguments}")
    
    # ✅ Ensure server is initialized
    if server.server_id not in self.initialized_servers:
        await self.initialize_server(server)
    
    rpc_url = f"{server.base_url.rstrip('/')}/mcp"
    
    # ✅ JSON-RPC 2.0 payload
    payload = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }
    
    # ✅ POST to MCP server
    logger_external.info(f"→ POST {rpc_url} (tools/call: {tool_name})")
    
    async with httpx.AsyncClient(timeout=self.timeout) as client:
        response = await client.post(rpc_url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
    
    logger_external.info(f"← {response.status_code} (tool execution complete)")
    
    return result.get("result", {})
```

### 8️⃣ **Send Result Back to LLM**
**File**: [backend/main.py](backend/main.py#L651-L657)
```python
# Format tool result message
tool_result_msg = llm_client.format_tool_result(
    tool_call_id=tool_id,
    content=result_content
)

messages_for_llm.append(tool_result_msg)
```

### 9️⃣ **LLM Processes Result** (Next Turn)
The loop continues, sending tool results back to LLM for final response.

---

## ✅ Verification Checklist

- [x] Tools are discovered from MCP servers via `tools/list`
- [x] Tools are formatted for LLM with namespaced IDs
- [x] LLM receives tools in `chat_completion()` call
- [x] LLM can choose tools (finish_reason: "tool_calls")
- [x] Tool calls are parsed (namespace split)
- [x] Server is found by alias
- [x] **Tool execution goes to MCP server via JSON-RPC 2.0**
- [x] Server is initialized before tool call (if needed)
- [x] Tool results are sent back to LLM
- [x] Multi-turn loop supports multiple tool calls

---

## 🔍 How to Verify Flow is Working

### Check Logs for Tool Execution
Look for these log patterns when a tool is called:

```
# Internal logs
INFO - mcp_client.internal - Executing tool: server_alias__tool_name
INFO - mcp_client.internal - Tool arguments: {...}

# External logs (API calls)
INFO - mcp_client.external - → POST http://server-url/mcp (tools/call: tool_name)
INFO - mcp_client.external - ← 200 (tool execution complete)

# Success
INFO - mcp_client.internal - Tool executed successfully: tool_name
```

### If Tool Call Fails
```
ERROR - mcp_client.internal - MCP server error for tool_name:
ERROR - mcp_client.internal -   Code: -32002
ERROR - mcp_client.internal -   Message: NOT_INITIALIZED
ERROR - mcp_client.internal -   Data: {...}
```

This indicates the server wasn't initialized. The fix ensures `discover_all_tools()` clears initialization state.

---

## 🐛 Debugging Tips

1. **Enable verbose logging** - Check both `logger_internal` and `logger_external`
2. **Verify tools are available** - Check `/api/tools` endpoint
3. **Check LLM receives tools** - Look for "Available tools for LLM: X tools"
4. **Monitor tool call parsing** - Look for "LLM requested X tool calls"
5. **Watch MCP server calls** - Look for "→ POST .../mcp (tools/call: ...)"
6. **Verify initialization** - Check "Server initialized: alias" log

---

## 🎯 Expected Behavior

**When LLM chooses a tool**:
1. Log shows: `"LLM requested 1 tool calls"`
2. Tool is parsed: `server_alias__tool_name` → `server_alias` + `tool_name`
3. Server is found in storage by alias
4. MCP server is initialized if needed
5. **HTTP POST sent to MCP server**: `POST http://server-url/mcp`
6. JSON-RPC payload includes `method: "tools/call"` and tool parameters
7. Server responds with result
8. Result sent back to LLM for next turn

**The flow is complete and correct!** ✅
