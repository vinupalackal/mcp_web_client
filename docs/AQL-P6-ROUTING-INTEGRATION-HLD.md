# AQL Phase 6 — Routing Integration: High-Level Design

**Feature**: AQL Phase 6 — Routing Integration  
**Version**: 0.1.0  
**Date**: April 4, 2026  
**Status**: Design Ready  
**Parent HLD**: `docs/AQL-ADAPTIVE-QUERY-LEARNING-HLD.md`  
**Requirements**: `docs/AQL-P6-ROUTING-INTEGRATION-REQUIREMENTS.md`  
**Implementation Spec**: `docs/AQL-P6-ROUTING-INTEGRATION-IMPLEMENTATION-SPEC.md`

---

## 1. Executive Summary

Phase 6 inserts the Phase 5 affinity lookup engine into the live `send_message()`
routing path as a guarded soft prior. The key design constraint is conservative
precedence: direct and memory routes continue to win, while affinity only
narrows the tool catalog passed to the LLM.

---

## 2. Routing Placement

Current flow:

```
direct route → memory route → tool catalog prep → LLM tool selection
```

Phase 6 flow:

```
direct route
   ↓ (if none)
memory route
   ↓ (if none)
affinity route
   ↓ (if confident)
allowed_tool_names narrowed
   ↓
tool catalog prep
   ↓
LLM tool selection
```

---

## 3. Component Design

### 3.1 `backend/main.py`

A new local `affinity_route_result` variable is initialized near the current
route-selection logic.

Pseudo-flow:

```python
request_mode_details = _classify_request_mode_details(...)
domain_tags = list(request_mode_details.get("domains", []))

affinity_route_result = AffinityRouteResult()
affinity_route_applied = False

if direct_tool_route is None and _memory_service is not None:
    memory_tool_names = await _memory_service.resolve_tools_from_memory(...)
    if memory_tool_names:
        apply memory route
    elif effective_config.enable_adaptive_learning:
        affinity_route_result = await _memory_service.resolve_tools_from_quality_history(
            query=message.content,
            domain_tags=domain_tags,
        )
        if affinity_route_result.confidence >= effective_config.aql_affinity_confidence_threshold:
            allowed_tool_names = affinity_route_result.tool_names
            include_virtual_repeated = False
            affinity_route_applied = True
```

### 3.2 Routing-mode accounting

The existing runtime helper that builds the quality-record payload uses a local
routing-mode function. Phase 6 extends that helper so it reports `"affinity"`
when the affinity path is applied.

### 3.3 Logging

Two new log outcomes:
- **Applied**: includes confidence, record count, and tool names
- **Skipped**: includes confidence and threshold when lookup ran but did not qualify

---

## 4. Testing Strategy

### 4.1 Unit tests

Add `test_main_runtime.py` tests that verify:
- confident affinity narrows the tool catalog sent to the LLM,
- low-confidence affinity leaves the broader catalog intact,
- direct routes skip affinity lookup,
- memory routes skip affinity lookup.

### 4.2 Integration test

Add one end-to-end chat test that:
- provides a fake memory service with no memory-route match,
- returns a confident affinity recommendation,
- captures the OpenAI request payload,
- asserts only the recommended tool names are sent to the LLM,
- verifies the final response still comes from the LLM synthesis path.

---

## 5. Safety Properties

- No direct-route regression
- No memory-route regression
- No LLM bypass introduced
- Low-confidence affinity fully degrades to the previous routing path

---

## 6. Files Changed

| File | Change |
|---|---|
| `backend/main.py` | Insert affinity route integration into `send_message()` |
| `tests/backend/unit/test_main_runtime.py` | Add Phase 6 routing integration tests |
| `tests/backend/integration/test_chat_api.py` | Add one Phase 6 end-to-end affinity routing scenario |
| `docs/AQL-P6-ROUTING-INTEGRATION-REQUIREMENTS.md` | New |
| `docs/AQL-P6-ROUTING-INTEGRATION-HLD.md` | New |
| `docs/AQL-P6-ROUTING-INTEGRATION-IMPLEMENTATION-SPEC.md` | New |
