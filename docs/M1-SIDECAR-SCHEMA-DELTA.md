# M1 Sidecar Schema Delta

**Feature:** M1 - Memory Sidecar Schema in `backend/database.py`  
**Application:** MCP Client Web  
**Date:** March 30, 2026  
**Related Issue:** `#2`  
**Related Requirements:** `Milvus_MCP_Integration_Requirements.md` — DATA-01, DATA-02, DATA-03, DATA-04, DATA-05, FR-RET-07, ALN-06

---

## Purpose

This document summarizes the **database table delta** introduced by M1 issue `#2`.

It focuses only on the schema-level change in `backend/database.py`:
- what tables existed before,
- what tables were added,
- and what those new tables are responsible for.

This is additive schema work only. It does not introduce UI changes or runtime memory-path behavior by itself.

---

## Before / After Table Inventory

### Before This Issue

`backend/database.py` contained only the existing user/settings tables:

| Table | Purpose |
|---|---|
| `users` | SSO-backed user identity and role state |
| `user_llm_configs` | Per-user stored LLM configuration |
| `user_servers` | Per-user MCP server configuration storage |
| `user_settings` | Per-user UI and default settings |

### After This Issue

The existing tables remain unchanged, and the following **additive sidecar tables** are introduced:

| Table | Purpose |
|---|---|
| `memory_payload_refs` | Durable sidecar storage for raw code/doc payloads and payload reference resolution |
| `memory_ingestion_jobs` | Ingestion job status, counts, timing, and error summaries |
| `memory_collection_versions` | Versioned collection metadata, embedding/index versions, and activation state |
| `memory_retrieval_provenance` | Retrieval provenance including selected refs and rationale summaries |

### Net Change Summary

| Category | Before | After |
|---|---|---|
| Existing auth/settings tables | 4 tables | 4 tables unchanged |
| Memory sidecar tables | 0 tables | 4 new additive tables |
| Runtime wiring | none | none in this issue |
| UI-visible behavior | unchanged | unchanged |

---

## Before / After Schema View

| Area | Before | After |
|---|---|---|
| Payload storage | No sidecar payload table | `memory_payload_refs` stores raw payloads plus reference metadata |
| Ingestion tracking | No durable job table | `memory_ingestion_jobs` tracks status, counts, timing, and errors |
| Collection versioning | No SQL metadata for active/inactive collection generations | `memory_collection_versions` tracks collection generation, embedding/index metadata, and activation state |
| Retrieval audit | No retrieval provenance rows | `memory_retrieval_provenance` stores selected refs and retrieval rationale |

---

## Requirement Alignment

| Requirement | Alignment |
|---|---|
| DATA-01 | Sidecar payload storage supports keeping full raw payloads outside Milvus when needed |
| DATA-02 | `payload_ref` identifiers can resolve to durable backing records |
| DATA-03 | Ingestion jobs and retrieval provenance use the existing SQLAlchemy-backed DB layer |
| DATA-04 | Collection generation and embedding/index version metadata are stored explicitly |
| DATA-05 | Multiple collection generations can coexist while one is active |
| FR-RET-07 | Retrieval provenance has a durable table for selected refs and rationale |
| ALN-06 | Existing SQLAlchemy DB layer is reused instead of introducing a second persistence stack |

---

## Notes

- Existing user/auth/settings behavior remains unchanged.
- This issue does not add conversation-memory payload tables yet.
- This issue does not add tool-cache provenance or cache-policy tables yet.
- UI changes will only appear in later issues after runtime wiring and frontend indicators are added.
