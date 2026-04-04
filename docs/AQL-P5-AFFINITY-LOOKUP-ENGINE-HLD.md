# AQL Phase 5 — Affinity Lookup Engine: High-Level Design

**Feature**: AQL Phase 5 — Affinity Lookup Engine  
**Version**: 0.1.0  
**Date**: April 4, 2026  
**Status**: Design Ready  
**Parent HLD**: `docs/AQL-ADAPTIVE-QUERY-LEARNING-HLD.md`  
**Requirements**: `docs/AQL-P5-AFFINITY-LOOKUP-ENGINE-REQUIREMENTS.md`  
**Implementation Spec**: `docs/AQL-P5-AFFINITY-LOOKUP-ENGINE-IMPLEMENTATION-SPEC.md`

---

## 1. Executive Summary

Phase 5 adds the internal lookup engine that turns stored quality-history
records into a confidence-scored recommendation of likely useful tools for a new
query. The phase is intentionally isolated: it computes recommendations but does
not yet influence live routing.

---

## 2. Architecture Placement

```
User query + domain tags
        │
        ▼
MemoryService.resolve_tools_from_quality_history()   (NEW)
        │
        ├─ 1. Normalize query
        ├─ 2. Embed query
        ├─ 3. ANN search tool_execution_quality
        ├─ 4. Filter corrected + non-overlapping domains
        ├─ 5. Score records
        ├─ 6. Aggregate weighted tool votes
        └─ 7. Return AffinityRouteResult
```

The output remains internal to `MemoryService` in this phase.

---

## 3. Data Flow

### 3.1 Lookup Sequence

```
1. query="show cpu usage details"
2. domain_tags=["cpu", "status"]
3. embed → query_vector
4. Milvus search on tool_execution_quality (top N)
5. Flatten hits
6. For each hit:
   - parse domain_tags
   - skip if user_corrected=true
   - skip if no domain overlap
   - normalize similarity from distance
   - compute affinity score
7. If eligible_count < min_records: return empty result
8. Aggregate tools from tools_succeeded / tools_selected
9. Return {tool_names, confidence, record_count}
```

### 3.2 Scoring Model

For each eligible quality record:

$$
\text{affinity} =
(w_{sim} \cdot \text{similarity}) +
(w_{success} \cdot \text{success\_rate}) +
(w_{bypass} \cdot \text{bypass\_rate}) +
(w_{corrected} \cdot \mathbb{1}[\text{user\_corrected}])
$$

Where:
- `similarity` is the normalized ANN match signal in `[0, 1]`
- `success_rate = len(tools_succeeded) / max(len(tools_selected), 1)`
- `bypass_rate = len(tools_bypassed) / max(len(tools_selected), 1)`
- `user_corrected` is normally false because corrected records are filtered out first

---

## 4. Component Design

### 4.1 New dataclass

```python
@dataclass(frozen=True)
class AffinityRouteResult:
    tool_names: list[str] = field(default_factory=list)
    confidence: float = 0.0
    record_count: int = 0
```

### 4.2 New `MemoryService` methods

```python
async def resolve_tools_from_quality_history(self, *, query: str, domain_tags: list[str]) -> AffinityRouteResult

def _score_quality_record(self, record: dict[str, Any], similarity: float) -> float

def _aggregate_affinity_tools(self, records: list[tuple[dict[str, Any], float]]) -> list[str]

def _has_domain_overlap(self, record_domains: list[str], query_domains: list[str]) -> bool
```

### 4.3 Search behavior

- Use `milvus_store.search()` against `tool_execution_quality`
- Query filter includes `user_corrected == false` when possible
- Search output fields include:
  - `domain_tags`
  - `tools_selected`
  - `tools_succeeded`
  - `tools_bypassed`
  - `user_corrected`
- After search, flatten nested hits using the existing `_flatten_hits()` helper

### 4.4 Aggregation behavior

- Eligible records are sorted by affinity score descending
- Each tool receives a weighted vote equal to the record affinity score
- When `tools_succeeded` is populated, use it for votes
- Otherwise fall back to `tools_selected`
- Returned `tool_names` are ordered by total vote descending

### 4.5 Confidence behavior

- Positive affinity scores contribute to final confidence
- `confidence = mean(positive_scores)`
- Clamp final confidence to `[0.0, 1.0]`
- If no positive scores remain, return zero confidence and no tools

---

## 5. Degradation and Safety

| Failure | Behaviour |
|---|---|
| AQL disabled | Empty `AffinityRouteResult` |
| Embedding failure | Log warning, return empty result |
| Milvus search failure | Log warning, return empty result |
| Too few eligible records | Log warning, return empty result with `record_count` set |
| No domain overlap | Record excluded |

No failure path affects current chat routing in this phase.

---

## 6. Files Changed

| File | Change |
|---|---|
| `backend/memory_service.py` | Add `AffinityRouteResult`, affinity lookup method, and helpers |
| `tests/backend/unit/test_memory_service.py` | Add focused affinity lookup tests |
| `docs/AQL-P5-AFFINITY-LOOKUP-ENGINE-REQUIREMENTS.md` | New |
| `docs/AQL-P5-AFFINITY-LOOKUP-ENGINE-HLD.md` | New |
| `docs/AQL-P5-AFFINITY-LOOKUP-ENGINE-IMPLEMENTATION-SPEC.md` | New |
