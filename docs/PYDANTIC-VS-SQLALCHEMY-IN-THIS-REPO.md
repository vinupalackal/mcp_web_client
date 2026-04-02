# Pydantic vs SQLAlchemy in This Repo

**Application:** MCP Client Web  
**Date:** March 30, 2026

---

## Purpose

This document explains the difference between **Pydantic models** and **SQLAlchemy models** in this repository, using concrete examples from the codebase.

Short version:

- **Pydantic** defines what API data should look like.
- **SQLAlchemy** defines how data is stored in the database.

They are related, but they are **not the same thing** and should not be used interchangeably.

---

## One-Line Mental Model

| Layer | Main Question | Library Used In This Repo |
|---|---|---|
| API / schema layer | “What should this data look like?” | Pydantic |
| Persistence / database layer | “Where and how is this data stored?” | SQLAlchemy |

---

## What a Pydantic Model Means

A **Pydantic model** is a Python class used for:

- request validation,
- response serialization,
- structured typing,
- and OpenAPI / Swagger schema generation.

In this repo, Pydantic models live mainly in [backend/models.py](backend/models.py).

### Example from this repo

In [backend/models.py](backend/models.py), `UserProfile` defines the shape of user data returned by APIs:

- `user_id`
- `email`
- `display_name`
- `avatar_url`
- `roles`
- `created_at`
- `last_login_at`

That model answers:

> “If the API returns a user profile, what fields must it contain, and what types are they?”

Another example is `HealthResponse` in [backend/models.py](backend/models.py), which defines the structure of a health-check response:

- `status`
- `version`
- `timestamp`

So Pydantic is about **data contract and validation**.

---

## What a SQLAlchemy Model Means

A **SQLAlchemy model** is a Python class that maps to a **database table**.

It is used for:

- table definitions,
- columns and constraints,
- inserts and updates,
- and database queries.

In this repo, SQLAlchemy models live in [backend/database.py](backend/database.py).

### Example from this repo

In [backend/database.py](backend/database.py), `UserRow` maps to the `users` table and defines columns such as:

- `user_id`
- `provider`
- `provider_sub`
- `email`
- `display_name`
- `avatar_url`
- `roles`
- `is_active`
- `created_at`
- `last_login_at`

That model answers:

> “How is a user stored in the database?”

Another example is `UserSettingsRow` in [backend/database.py](backend/database.py), which maps UI settings to the `user_settings` table.

So SQLAlchemy is about **storage and persistence**.

---

## Same Feature, Two Different Layers

A useful way to understand the difference is to look at the **same kind of concept** in both layers.

### Example: User settings

**API/schema model**:
- `UserSettings` in [backend/models.py](backend/models.py)
- used to validate and serialize settings data exchanged via API

**Database model**:
- `UserSettingsRow` in [backend/database.py](backend/database.py)
- used to persist settings in the database

Both refer to user settings, but they do different jobs:

| Model | File | Role |
|---|---|---|
| `UserSettings` | [backend/models.py](backend/models.py) | API contract |
| `UserSettingsRow` | [backend/database.py](backend/database.py) | Database storage |

### Example: User identity

| Model | File | Role |
|---|---|---|
| `UserProfile` | [backend/models.py](backend/models.py) | Response model returned by API |
| `UserRow` | [backend/database.py](backend/database.py) | ORM row stored in `users` table |

---

## Why Both Exist

Most real applications need both layers:

- one layer to **store** the data,
- another layer to **validate and expose** the data.

In this repo:

- SQLAlchemy stores data in SQLite / DB tables.
- Pydantic defines request/response shapes for FastAPI.

That separation is useful because:

- database columns are not always the same as API fields,
- some DB fields should never be exposed directly,
- some API payloads combine data from multiple tables,
- and some API models are diagnostic summaries that are not stored directly at all.

---

## Where Issue #2 and Issue #3 Fit

### Issue #2 — SQLAlchemy side

Issue `#2` added sidecar tables in [backend/database.py](backend/database.py), such as:

- `MemoryPayloadRefRow`
- `MemoryIngestionJobRow`
- `MemoryCollectionVersionRow`
- `MemoryRetrievalProvenanceRow`

These are **SQLAlchemy models** because they define **how memory-related metadata is stored**.

### Issue #3 — Pydantic side

Issue `#3` added models in [backend/models.py](backend/models.py), such as:

- `MemoryFeatureFlags`
- `MemoryConfigSummary`
- `MemoryStatus`
- `MemoryCollectionStatus`
- `MemoryIngestionJobStatus`
- `MemoryDiagnosticsResponse`

These are **Pydantic models** because they define **how memory-related config and diagnostics are represented in API-friendly form**.

---

## When to Use Which in This Repo

### Use Pydantic when:

- defining a request body,
- defining a response body,
- validating structured input/output,
- generating OpenAPI docs,
- modeling diagnostics returned by API endpoints.

Typical location:
- [backend/models.py](backend/models.py)

### Use SQLAlchemy when:

- defining a DB table,
- adding columns or constraints,
- storing persistent state,
- querying or updating records.

Typical location:
- [backend/database.py](backend/database.py)

---

## Simple Rule of Thumb

If the question is:

- **“What should the API accept or return?”** → use **Pydantic**
- **“What should the database store?”** → use **SQLAlchemy**

---

## Final Summary

| Topic | Pydantic | SQLAlchemy |
|---|---|---|
| Purpose | Validation and API schema | Database mapping and persistence |
| Main file in this repo | [backend/models.py](backend/models.py) | [backend/database.py](backend/database.py) |
| Used by | FastAPI / OpenAPI | ORM / DB engine |
| Example | `UserProfile`, `HealthResponse`, `MemoryStatus` | `UserRow`, `UserSettingsRow`, `MemoryPayloadRefRow` |
| Best question | “What should this data look like?” | “How is this data stored?” |

They work together, but they are different layers of the application.
