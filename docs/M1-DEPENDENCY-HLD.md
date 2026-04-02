# High-Level Design: M1 — Milvus and Parsing Dependencies

**Issue**: [#1 M1: Add Milvus and parsing dependencies](https://github.com/vinupalackal/mcp_web_client/issues/1)  
**Milestone**: M1 - Foundations  
**Phase**: 1A  
**Date**: March 30, 2026  
**Status**: Design Ready  
**Parent HLD**: MILVUS_MCP_INTEGRATION_HLD.md  
**Requirements**: ../Milvus_MCP_Integration_Requirements.md (v2.0)  
**Implementation Plan**: MILVUS_MCP_IMPLEMENTATION_PLAN.md — section 4.13, Phase 1A

---

## 1. Purpose

This document defines the high-level design for the dependency installation step of the Milvus integration. It covers:

- the packages to be added,
- their roles in the broader Milvus integration stack,
- how they connect to the rest of the M1–M2 module chain,
- known risks and mitigations,
- and the import boundary design required to keep the app startable when memory is disabled.

This is a focused, low-risk design: the only deliverable is an updated `requirements.txt`. No application code is changed in this issue.

---

## 2. Package Selection

### 2.1 Selected Packages and Versions

| Package | Pinned Version | Role |
|---|---|---|
| `pymilvus` | `2.5.18` | Milvus Python client — collection management, search, upsert, delete |
| `tree-sitter` | `0.25.2` | Core parser framework and Python bindings |
| `tree-sitter-c` | `0.24.1` | C language grammar for tree-sitter |
| `tree-sitter-cpp` | `0.23.4` | C++ language grammar for tree-sitter |

#### Version Rationale

| Package | Latest | Pinned | Reason |
|---|---|---|---|
| `pymilvus` | 2.6.11 | 2.5.18 | 2.5.x is the stable LTS line; 2.6.x is the feature release. Using 2.5.18 avoids picking up unreleased 2.6.x behavioral changes before any integration test coverage exists. Upgrade to 2.6.x after integration tests pass. |
| `tree-sitter` | 0.25.2 | 0.25.2 | Implementation validation confirmed this core supports the language capsule version exposed by the selected grammar wheels. |
| `tree-sitter-c` | 0.24.1 | 0.24.1 | Latest stable C grammar; validated to load and parse correctly with `tree-sitter==0.25.2`. |
| `tree-sitter-cpp` | 0.23.4 | 0.23.4 | Latest researched C++ grammar; validated to load and parse correctly with `tree-sitter==0.25.2`. |

> **Note for implementer:** Confirm versions at the time of development. Use exact pins (`==`) in the final merged `requirements.txt`, not ranges.

---

## 3. Package Responsibilities in the Integration Stack

Each package is a dependency for specific later modules. This table shows the full traceability from package → module → capability.

```
pymilvus
    └──► backend/milvus_store.py (M2)
             └──► collection lifecycle, vector search, upsert, delete
             └──► backend/memory_service.py (M1C)
             └──► backend/ingestion_service.py (M2)

tree-sitter (core)
    └──► backend/ingestion_service.py (M2)
             └──► Parser object construction
             └──► AST traversal and node extraction
             └──► Symbol boundary detection for chunking

tree-sitter-c
    └──► backend/ingestion_service.py (M2)
             └──► Language.build_library() or Language() constructor
             └──► C source file parsing (.c, .h)

tree-sitter-cpp
    └──► backend/ingestion_service.py (M2)
             └──► Language.build_library() or Language() constructor
             └──► C++ source file parsing (.cpp, .hpp, .cc, .cxx)
```

### 3.1 `pymilvus`

The `pymilvus` package is the official Zilliz/Milvus Python client. It exposes two API surfaces:

- **ORM API** (`pymilvus.Collection`, `FieldSchema`, `CollectionSchema`) — schema-based collection management  
- **MilvusClient API** (`pymilvus.MilvusClient`) — simplified CRUD interface

The Milvus store module (`backend/milvus_store.py`, M2) will use the **MilvusClient API** for Phase 1 because it has a narrower interface suitable for the collection types needed.

Internal transport: `pymilvus` uses **gRPC** for Milvus Standalone/Cluster and an internal HTTP option for Milvus Lite. This HLD targets Milvus Standalone.

### 3.2 `tree-sitter`

`tree-sitter` is a parser generator framework providing incremental, AST-aware parsing. The Python bindings expose:

- `Language` — wraps a compiled grammar
- `Parser` — parses source text into a concrete syntax tree
- `Node` — a node in the syntax tree with `.type`, `.start_point`, `.end_point`, `.children`

The ingestion service (`backend/ingestion_service.py`, M2) uses these to extract:

- function definitions,
- class definitions,
- struct and enum declarations,
- namespace scopes (C++),
- and method bodies.

### 3.3 `tree-sitter-c` and `tree-sitter-cpp`

These grammar packages are **pre-built language bindings** for the tree-sitter core. They expose a compiled grammar object that is loaded into a `Language` instance:

```python
import tree_sitter_c as ts_c
import tree_sitter_cpp as ts_cpp
from tree_sitter import Language, Parser

C_LANGUAGE = Language(ts_c.language())
CPP_LANGUAGE = Language(ts_cpp.language())
```

The `ts_c.language()` and `ts_cpp.language()` calls return a capsule object containing the compiled grammar, compatible with the pinned tree-sitter core ABI.

---

## 4. Import Boundary Design

This is the most important design decision in this issue. The packages must be installed but **must not be imported at module load time** in any file that is unconditionally loaded when the application starts.

### 4.1 Requirement

`ALN-03`: Milvus integration must be optional and controlled by configuration.  
`ALN-04`: If Milvus is disabled or unavailable, the application must continue operating.

This means:

- `backend/main.py` must start and serve traffic even when `MCP_MEMORY_ENABLED=false`
- `pymilvus` and `tree-sitter` must **not** appear in top-level imports in `backend/main.py`, `backend/llm_client.py`, `backend/session_manager.py`, or `backend/mcp_manager.py`

### 4.2 Allowed Import Locations

| Module | Top-level import allowed? | Notes |
|---|---|---|
| `backend/milvus_store.py` | ✅ Yes | This module is only instantiated when memory is enabled |
| `backend/ingestion_service.py` | ✅ Yes | Only activated by explicit ingestion job trigger |
| `backend/embedding_service.py` | ✅ Yes | Only called from memory/ingestion services |
| `backend/memory_service.py` | ✅ Yes | Only instantiated after `MCP_MEMORY_ENABLED` check |
| `backend/main.py` | ❌ No | Top-level; must be clean for disabled mode |
| `backend/llm_client.py` | ❌ No | Always loaded; no Milvus dependency |
| `backend/session_manager.py` | ❌ No | Always loaded; must be Milvus-free |

### 4.3 Conditional Instantiation Pattern

In `backend/main.py`, memory services are created inside an `if` block guarded by `MCP_MEMORY_ENABLED`:

```python
# backend/main.py (Phase 1C)
_memory_service: Optional["MemoryService"] = None

@app.on_event("startup")
async def startup():
    if os.getenv("MCP_MEMORY_ENABLED", "false").lower() == "true":
        from backend.memory_service import MemoryService  # lazy import
        _memory_service = MemoryService(...)
```

This pattern ensures:
- no import-time failure if `pymilvus` is missing in stripped environments
- no Milvus connection attempt when memory is disabled
- clean test isolation for the existing 503-test suite

---

## 5. Dependency Compatibility Analysis

### 5.1 Existing Stack

```
Python 3.11.x (current environment)
fastapi==0.115.0
uvicorn[standard]==0.30.6
pydantic==2.8.2
httpx==0.27.0
python-dotenv==1.0.1
PyJWT==2.9.0
cryptography==42.0.8
sqlalchemy==2.0.36
alembic==1.13.3
```

### 5.2 `pymilvus` Transitive Dependencies

Key transitive dependencies introduced by `pymilvus==2.5.18`:

| Transitive Dep | Purpose | Conflict Risk |
|---|---|---|
| `grpcio` | gRPC transport | Low — uvicorn uses asyncio, not gRPC; both can coexist |
| `grpcio-tools` | gRPC code generation tooling | Low — development-time only, no runtime conflict |
| `protobuf` | gRPC message serialization | Low — no existing protobuf usage in this repo |
| `milvus-lite` | Optional embedded Milvus | Low — optional sub-package, not used in Standalone mode |
| `ujson` | JSON serialization | Low — does not conflict with pydantic/fastapi JSON handling |

#### gRPC + asyncio Coexistence

`uvicorn[standard]` uses `asyncio` for the server event loop. `grpcio` uses either a dedicated background thread or an async stub pattern. They do not conflict at the event loop level as long as:

- `pymilvus` is not called before the event loop starts,
- and `MilvusClient` connections are established in the `startup` lifecycle hook, not at module import time.

The lazy import pattern in section 4.3 ensures this.

### 5.3 `tree-sitter` Transitive Dependencies

`tree-sitter==0.25.2` has minimal transitive dependencies (C extension only, no major Python deps).  
`tree-sitter-c` and `tree-sitter-cpp` are similarly minimal — pre-built C shared libraries wrapped in Python.

**No conflict risk** with the existing stack for tree-sitter packages.

### 5.4 Compatibility Matrix

| Package pair | Compatible? | Notes |
|---|---|---|
| `pymilvus==2.5.18` + `fastapi==0.115.0` | ✅ | No shared dependency surface |
| `pymilvus==2.5.18` + `httpx==0.27.0` | ✅ | gRPC uses different transport from httpx |
| `pymilvus==2.5.18` + `pydantic==2.8.2` | ✅ | pymilvus does not require pydantic v1 in 2.5.x |
| `pymilvus==2.5.18` + `sqlalchemy==2.0.36` | ✅ | No shared ORM usage |
| `tree-sitter==0.25.2` + `tree-sitter-c==0.24.1` | ✅ | Install and parse smoke test passed |
| `tree-sitter==0.25.2` + `tree-sitter-cpp==0.23.4` | ✅ | Install and parse smoke test passed |
| `tree-sitter==0.23.2` + `tree-sitter-c==0.23.6` | ❌ | Runtime ABI mismatch: language version 15 not supported by core |

---

## 6. `requirements.txt` Change Design

### 6.1 Before

```
# MCP Client Web - Python Dependencies

# Core FastAPI stack
fastapi==0.115.0
uvicorn[standard]==0.30.6
pydantic==2.8.2

# HTTP client for async requests
httpx==0.27.0

# Environment configuration
python-dotenv==1.0.0

# SSO / Auth (v0.4.0-sso-user-settings)
PyJWT==2.9.0
cryptography==42.0.8
sqlalchemy==2.0.36
alembic==1.13.3
```

### 6.2 After

```
# MCP Client Web - Python Dependencies

# Core FastAPI stack
fastapi==0.115.0
uvicorn[standard]==0.30.6
pydantic==2.8.2

# HTTP client for async requests
httpx==0.27.0

# Environment configuration
python-dotenv==1.0.1

# SSO / Auth (v0.4.0-sso-user-settings)
PyJWT==2.9.0
cryptography==42.0.8
sqlalchemy==2.0.36
alembic==1.13.3

# Milvus vector store — M1 Foundations (optional, guarded by MCP_MEMORY_ENABLED)
pymilvus==2.5.18

# Tree-sitter code parsing — M1 Foundations (used by ingestion_service.py)
# Grammar packages must match the tree-sitter core ABI version
tree-sitter==0.25.2
tree-sitter-c==0.24.1
tree-sitter-cpp==0.23.4
```

### 6.3 Design Rules for `requirements.txt`

- All new packages are added with **exact pins** (`==`).
- A comment block clearly names the milestone and optional/conditional status.
- The grammar packages include an inline warning about ABI matching.
- Existing pins remain unchanged except where a direct transitive constraint requires a minimal compatible patch update.

### 6.4 Resolved Constraint

During implementation validation, `pymilvus==2.5.18` required `python-dotenv>=1.0.1,<2.0.0`.
The repository previously pinned `python-dotenv==1.0.0`, which made the environment unsatisfiable.

The selected fix is:

- raise `python-dotenv` from `1.0.0` to `1.0.1`
- keep all other existing application pins unchanged
- preserve the Milvus package selection and import isolation design
- use the validated tree-sitter core and grammar combination observed to pass parser smoke tests on macOS arm64 / Python 3.11

This is a narrow compatibility adjustment, not a functional design change.

---

## 7. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| gRPC event loop conflict with uvicorn | Low | High | Use lazy import + startup lifecycle hook; validate in integration test |
| tree-sitter ABI mismatch (grammar vs core) | Medium | Medium | Pin the exact validated combination: `tree-sitter==0.25.2`, `tree-sitter-c==0.24.1`, `tree-sitter-cpp==0.23.4`; validate with parse smoke tests |
| `pymilvus` requires `pydantic<2` on some releases | Low | High | Verified: `pymilvus==2.5.x` supports pydantic v2; confirm during install |
| `pymilvus` minimum `python-dotenv` exceeds repo pin | High | Medium | Raise `python-dotenv` to `1.0.1` and validate full backend startup/tests |
| New packages break existing 503 test suite | Low | High | All new imports are guarded; existing code paths unchanged; run full test suite before merging |
| macOS arm64 binary incompatibility | Low | Medium | tree-sitter and pymilvus both publish arm64 wheels; validate on the development machine |
| Version drift between grammar and core on future update | Medium | Medium | Pin all four packages together; update as a coordinated group, not individually |

---

## 8. Validation Design

### 8.1 Install Validation

```bash
# Step 1 — fresh environment
python3 -m venv /tmp/m1_dep_validation
source /tmp/m1_dep_validation/bin/activate
pip install -r requirements.txt

# Step 2 — import checks
python3 -c "from pymilvus import MilvusClient; print('pymilvus OK')"
python3 -c "import tree_sitter; print('tree-sitter OK')"
python3 -c "import tree_sitter_c; print('tree-sitter-c OK')"
python3 -c "import tree_sitter_cpp; print('tree-sitter-cpp OK')"

# Step 3 — grammar load check
python3 - <<'EOF'
import tree_sitter_c as ts_c
import tree_sitter_cpp as ts_cpp
from tree_sitter import Language, Parser
C_LANGUAGE = Language(ts_c.language())
CPP_LANGUAGE = Language(ts_cpp.language())
parser = Parser(C_LANGUAGE)
tree = parser.parse(b"int main() { return 0; }")
print(f"C parse OK — root node type: {tree.root_node.type}")
CPP_PARSER = Parser(CPP_LANGUAGE)
tree2 = CPP_PARSER.parse(b"class Foo { int x; };")
print(f"C++ parse OK — root node type: {tree2.root_node.type}")
EOF
```

### 8.2 Regression Test

```bash
# Existing tests must remain green
source venv/bin/activate
python3 -m pytest tests/backend/ -v --tb=short
```

Expected: `503 passed`.

### 8.3 Startup Isolation Test

```bash
# Confirm app starts with memory disabled (default)
MCP_MEMORY_ENABLED=false uvicorn backend.main:app --port 8099 &
sleep 2
curl -s http://localhost:8099/health | python3 -m json.tool
kill %1
```

Expected: health endpoint returns `200 OK` and memory is reported as `disabled` or absent.

---

## 9. Downstream Impact

This issue is the unblocking prerequisite for all M1 and M2 implementation issues.

```
#1 Add Milvus and parsing dependencies (this issue)
    │
    ├──► #2 Add memory sidecar schema in backend/database.py
    │       (no pymilvus needed, but logically co-phase)
    │
    ├──► #3 Add memory config and diagnostics models
    │       (no pymilvus needed, but logically co-phase)
    │
    ├──► #4 Add provider-agnostic embedding support
    │       (no pymilvus needed for embedding service itself)
    │
    ├──► #5 Add memory persistence adapter
    │       (no pymilvus needed, uses SQLAlchemy)
    │
    └──► #6 Implement Milvus store abstraction  (M2)
             └──► #7 Implement ingestion pipeline  (M2)
                      └──► #8 Ingestion and store tests  (M2)
```

Issues #2 through #5 do not require `pymilvus` to be present at runtime — they depend on the schema, model, and persistence layers. Only **#6 and beyond** directly call the Milvus client.

However, pinning the dependencies now ensures:
- all contributors work with a reproducible environment,
- CI environments can pre-install packages,
- and there are no surprises when #6 tries to import `pymilvus` for the first time.

---

## 10. Acceptance Design Summary

| Check | Method | Pass Criterion |
|---|---|---|
| Packages install cleanly | `pip install -r requirements.txt` in fresh venv | No errors, no conflicts |
| All four packages importable | Python import check | `OK` printed for all four |
| Grammar ABI correct | tree-sitter grammar load + parse snippet | C and C++ parse succeeds |
| No test regression | `pytest tests/backend/` | 503 passed, 0 failed |
| App starts with memory disabled | `MCP_MEMORY_ENABLED=false uvicorn ...` | `200 OK` on `/health` |
| macOS arm64 validated | Developer machine install | All install + import checks pass |

---

## 11. References

| Document | Location |
|---|---|
| Parent HLD | `docs/MILVUS_MCP_INTEGRATION_HLD.md` |
| Requirements | `Milvus_MCP_Integration_Requirements.md` (v2.0) |
| Implementation Plan | `docs/MILVUS_MCP_IMPLEMENTATION_PLAN.md` section 4.13 |
| GitHub Issue | https://github.com/vinupalackal/mcp_web_client/issues/1 |
| pymilvus changelog | https://github.com/milvus-io/pymilvus/releases |
| tree-sitter Python bindings | https://github.com/tree-sitter/py-tree-sitter |
| tree-sitter-c grammar | https://github.com/tree-sitter/tree-sitter-c |
| tree-sitter-cpp grammar | https://github.com/tree-sitter/tree-sitter-cpp |
