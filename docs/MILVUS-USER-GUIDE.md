# Milvus User Guide

## Purpose

This guide explains how to use the repository's Milvus-backed memory features effectively:

- retrieval-enriched answers from indexed code and docs,
- same-user conversation memory,
- safe allowlisted tool-result caching,
- prompt patterns that improve retrieval quality.

This is a user-facing guide for operating and prompting the feature set after it has been implemented.
You can enter or adjust the Milvus runtime configuration from Settings → Milvus Config in the web UI instead of editing the memory environment variables by hand.

---

## 1. What Milvus Does in This App

When memory features are enabled, the backend can use Milvus to improve responses in three ways:

### 1.1 Retrieval Enrichment
The app can search indexed code and documentation and inject the most relevant snippets into the LLM context before it answers.

Use this when you want help with:
- locating where something is implemented,
- understanding how a symbol or config is used,
- finding the right file or doc section,
- answering repo-specific questions that generic model knowledge would miss.

### 1.2 Conversation Memory
The app can store summarized memories of previous turns for the same authenticated user.

Use this when you want the assistant to remember:
- your earlier preferences in the same workspace,
- prior debugging context,
- earlier decisions or constraints,
- previously discussed files or symbols.

Important behavior:
- conversation memory is same-user scoped,
- it can also be workspace-scoped,
- cross-user recall is blocked,
- anonymous sessions do not persist conversation memory.

### 1.3 Safe Tool Cache
For explicitly allowlisted tools only, successful tool results can be cached and reused when:
- the same tool is called,
- with the same normalized arguments,
- in the same user/workspace scope,
- before the TTL expires.

Important behavior:
- non-allowlisted tools are never cached,
- similarity alone never authorizes reuse,
- side-effecting tools should not be allowlisted.

---

## 2. When to Use Milvus Features

Milvus is most useful when your question depends on repository-specific context.

### Good fits
- "Where is the session ownership check implemented?"
- "How does tool cache scoping work in this repo?"
- "Which file adds retrieval traces?"
- "What changed between Phase 2 and Phase 3?"
- "Show the config/env vars for memory cleanup."

### Poor fits
- generic Python syntax questions,
- broad brainstorming with no repo context,
- requests that do not depend on workspace code or docs,
- questions where exact file names or symptoms are omitted.

---

## 3. How to Enable Milvus Features

Use the backend environment variables described in the README.

### Minimal retrieval setup

```bash
MEMORY_ENABLED=true
MEMORY_MILVUS_URI=http://localhost:19530
MEMORY_REPO_ID=my-project
```

### Add conversation memory

```bash
MEMORY_CONVERSATION_ENABLED=true
MEMORY_CONVERSATION_RETENTION_DAYS=7
```

### Add safe tool cache

```bash
MEMORY_TOOL_CACHE_ENABLED=true
MEMORY_TOOL_CACHE_TTL_S=3600
MEMORY_TOOL_CACHE_ALLOWLIST=get_weather,get_build_status
```

### Enable cleanup hardening

```bash
MEMORY_EXPIRY_CLEANUP_ENABLED=true
MEMORY_EXPIRY_CLEANUP_INTERVAL_S=300
```

After changing env vars, restart the backend.

---

## 4. How to Know It Is Working

### Retrieval
You should see one or both of these:
- assistant answers become more repo-specific,
- the UI shows a collapsible sources section below the assistant message.

### Conversation memory
You should notice that the assistant remembers earlier repo-specific context from previous authenticated turns without you restating everything.

### Tool cache
You may see repeated approved tool calls respond faster because a cached result is returned instead of re-running the tool.

### Health endpoint
Check:

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

Look for:
- `memory.enabled`,
- `memory.healthy` / `memory.degraded`,
- `memory.expiry_cleanup`.

---

## 5. Prompting Guide

Milvus works best when your prompt contains concrete retrieval anchors.

### 5.1 Best prompt ingredients
Include as many of these as you can:
- file path,
- function name,
- class name,
- endpoint path,
- environment variable,
- error string,
- log message,
- user-visible behavior,
- milestone/phase name.

### 5.2 Strong prompt patterns

#### Ask for a specific implementation detail
- "Where is `record_turn()` implemented and when is it called?"
- "Find where `MEMORY_TOOL_CACHE_ALLOWLIST` is read and explain how it affects execution."

#### Ask with file or symbol anchors
- "In the memory subsystem, where is conversation expiry cleanup triggered?"
- "Explain how `run_expiry_cleanup_if_due()` works in the backend."

#### Ask with an error or symptom
- "I see stale conversation memory after TTL expiry. Which code path handles cleanup?"
- "Why would the memory subsystem report degraded while the app still returns 200 on `/health`?"

#### Ask for comparison
- "What changed between Phase 2 conversation memory and Phase 4 cleanup hardening?"
- "Compare retrieval enrichment and tool-cache reuse in this repo."

### 5.3 Weak prompt patterns
These often retrieve poorly because they are underspecified:
- "fix memory"
- "where is the bug"
- "explain this project"
- "something is wrong with cache"
- "how does it work"

### 5.4 Rewrite weak prompts into strong ones

Weak:
- "memory is broken"

Better:
- "Conversation memory seems to return stale context after retention expiry. Show where expiry filtering and cleanup happen."

Weak:
- "tool caching problem"

Better:
- "Why did `get_weather` not hit the safe tool cache? Show the allowlist check, scope hash behavior, and TTL conditions."

Weak:
- "where is auth"

Better:
- "Where does the admin role guard the manual memory maintenance endpoint?"

---

## 6. Prompting for Better Retrieval

### 6.1 Mention exact strings when possible
If you know the literal identifier, include it:
- `MEMORY_EXPIRY_CLEANUP_INTERVAL_S`
- `/api/admin/memory/maintenance`
- `run_expiry_cleanup_if_due`
- `conversation_memory`

This helps retrieval find the right code path faster.

### 6.2 Mention the layer you care about
Say whether you want:
- API behavior,
- backend implementation,
- database/persistence behavior,
- Milvus/vector-store behavior,
- tests,
- docs.

Example:
- "At the persistence layer, how are expired tool-cache entries deleted?"

### 6.3 Mention the desired output shape
Examples:
- "Summarize in plain English"
- "List the relevant files"
- "Show the request flow"
- "Explain before/after behavior"
- "Give me the exact env vars"

### 6.4 Keep related terms together
Better:
- "conversation memory retention expiry cleanup"

Worse:
- "memory thing cleanup old stuff maybe conversation"

---

## 7. Example Prompts by Use Case

### 7.1 Code discovery
- "Which files implement Milvus conversation memory in this repo?"
- "Where is retrieval context injected into the chat message flow?"
- "Find the code path for admin-only memory maintenance."

### 7.2 Debugging
- "Why might expired tool-cache entries still exist after startup? Show the cleanup trigger path."
- "How does the app fail open when Milvus is unavailable?"
- "Which tests verify that cross-user conversation memory recall is blocked?"

### 7.3 Operational usage
- "What env vars control conversation retention, tool-cache TTL, and cleanup interval?"
- "How do I manually trigger memory cleanup?"
- "What should I look at in `/health` if cleanup is not running?"

### 7.4 Prompting with workspace context
- "In this workspace, what changed in Phase 4 hardening for Milvus?"
- "Using the current codebase, explain the difference between retrieval memory and tool cache."

---

## 8. How Conversation Memory Behaves

Conversation memory is not a full transcript replay system. It stores summarized turn memory for later recall.

Best practices:
- restate key constraints once clearly,
- keep terminology consistent across turns,
- mention the same workspace/module names you used earlier,
- for critical tasks, restate exact identifiers instead of relying only on memory.

Example:
- Good follow-up: "Continue with the expiry cleanup work in the memory subsystem; keep the admin endpoint under `/api/admin/memory/maintenance`."
- Weak follow-up: "continue that thing from before"

---

## 9. How Safe Tool Cache Behaves

The safe tool cache is intentionally conservative.

A cache hit requires all of the following:
- tool is explicitly allowlisted,
- arguments normalize to the same hash,
- user/workspace scope hash matches,
- cached entry is still within TTL,
- entry is marked cacheable.

This means you should not expect a cache hit when:
- a different user asks the same question,
- the arguments differ in meaning,
- the TTL has expired,
- the tool is not approved for caching.

Useful prompts:
- "Why was there no cache hit for this tool call?"
- "Show the exact conditions for tool-cache reuse in this codebase."

---

## 10. Troubleshooting

### Retrieval is not helping
Check:
- memory is enabled,
- Milvus is reachable,
- ingestion has actually run,
- prompt contains concrete repo anchors,
- the file/doc you expect is inside indexed roots.

### Conversation memory does not seem to remember
Check:
- you are authenticated (not anonymous),
- conversation memory is enabled,
- retention has not expired,
- you are asking within the same logical scope,
- the earlier turn contained clear, reusable context.

### Tool cache is not hitting
Check:
- tool cache is enabled,
- tool name is on the allowlist,
- TTL has not expired,
- arguments normalize to the same structure,
- user/workspace scope is unchanged.

### Cleanup is not running
Check:
- `MEMORY_EXPIRY_CLEANUP_ENABLED=true`,
- `MEMORY_EXPIRY_CLEANUP_INTERVAL_S` is not too large,
- `/health` shows `memory.expiry_cleanup`,
- the admin maintenance endpoint succeeds when triggered manually.

---

## 11. Recommended Prompting Checklist

Before asking a repo-specific question, try to include:

- what you want to know,
- the subsystem (`retrieval`, `conversation memory`, `tool cache`, `cleanup`),
- at least one exact identifier,
- a symptom or desired outcome,
- whether you want explanation, file list, comparison, or fix.

Template:

> In the `<subsystem>` flow, explain how `<identifier>` works, where it is implemented, and what changed in `<phase/milestone>`.

Example:

> In the memory cleanup flow, explain how `run_expiry_cleanup_if_due` works, where it is called, and how the admin maintenance endpoint differs from automatic cleanup.

---

## 12. Related Docs

- [README.md](../README.md)
- [docs/MILVUS_MCP_IMPLEMENTATION_PLAN.md](MILVUS_MCP_IMPLEMENTATION_PLAN.md)
- [docs/MILVUS_MCP_INTEGRATION_HLD.md](MILVUS_MCP_INTEGRATION_HLD.md)
- [docs/USAGE-EXAMPLES.md](USAGE-EXAMPLES.md)

If you are enabling the feature for the first time, start with the README.
If you are trying to use the feature effectively in day-to-day work, use this guide.
