"""
Token audit for MCP client tool schemas.
Run: python3 scripts/token_audit.py
"""
import json
import tiktoken

enc = tiktoken.get_encoding("cl100k_base")


def tok(obj) -> int:
    return len(enc.encode(json.dumps(obj, separators=(",", ":"))))


def tok_str(s: str) -> int:
    return len(enc.encode(s))


# ── 1. Virtual tool ─────────────────────────────────────────────────────────
# Load VIRTUAL_REPEATED_EXEC_TOOL directly from the module so the audit always
# reflects the current definition without manual sync.
import sys
sys.path.insert(0, ".")
from backend.mcp_manager import VIRTUAL_REPEATED_EXEC_TOOL as virtual

print("=== VIRTUAL mcp_repeated_exec ===")
print(f"  TOTAL: {tok(virtual)} tokens")
print(f"  description: {tok_str(virtual['function']['description'])} tokens")
for k, v in virtual["function"]["parameters"]["properties"].items():
    print(f"  param.{k}: {tok(v)} tokens")


def audit_file(path: str) -> int:
    with open(path) as f:
        data = json.load(f)
    tools = data.get("tools", [])
    print(f"\n=== {path} ({len(tools)} tools) ===")
    total = 0
    rows = []
    for t in tools:
        llm = {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["inputSchema"],
            },
        }
        n = tok(llm)
        total += n
        d_tok = tok_str(t["description"])
        p_tok = tok(t["inputSchema"])
        rows.append((n, t["name"], d_tok, p_tok))
    rows.sort(reverse=True)
    for n, name, d, p in rows:
        print(f"  {n:4d} tok  {name:<40s}  desc={d} params={p}")
    print(f"  SUBTOTAL: {total} tokens")
    return total


t_virtual = tok(virtual)
t_reg = audit_file("tools_registry.json")
t_mcp = audit_file("mcp_tools_config.json")
t_owrt = audit_file("openwrt_tools_config.json")

grand = t_virtual + t_reg + t_mcp + t_owrt
print(f"\n{'='*60}")
print(f"  virtual:             {t_virtual:5d}")
print(f"  tools_registry:      {t_reg:5d}")
print(f"  mcp_tools_config:    {t_mcp:5d}")
print(f"  openwrt_tools:       {t_owrt:5d}")
print(f"  GRAND TOTAL:         {grand:5d}")
