"""Persistence adapter for Milvus sidecar metadata and audit records."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import (
    MemoryCollectionVersionRow,
    MemoryConversationTurnRow,
    MemoryIngestionJobRow,
    MemoryPayloadRefRow,
    MemoryRetrievalProvenanceRow,
    MemoryToolCacheRow,
    SessionLocal,
)


class MemoryPersistence:
    """Focused adapter around the Milvus sidecar SQLAlchemy tables."""

    def __init__(self, session_factory: Optional[Callable[[], Session]] = None):
        self._session_factory = session_factory or SessionLocal

    def upsert_payload_ref(self, *, payload_ref: str, payload_kind: str, payload_text: str, **fields: Any) -> MemoryPayloadRefRow:
        if not payload_ref:
            raise ValueError("payload_ref is required")
        if not payload_kind:
            raise ValueError("payload_kind is required")
        if payload_text is None:
            raise ValueError("payload_text is required")

        now = datetime.now(timezone.utc)
        with self._session_factory() as db:
            row = db.get(MemoryPayloadRefRow, payload_ref)
            if row is None:
                row = MemoryPayloadRefRow(
                    payload_ref=payload_ref,
                    payload_kind=payload_kind,
                    payload_text=payload_text,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
            else:
                row.payload_kind = payload_kind
                row.payload_text = payload_text
                row.updated_at = now

            for field_name, value in fields.items():
                if field_name == "metadata_json":
                    value = self._json_text(value)
                if hasattr(row, field_name):
                    setattr(row, field_name, value)
                else:
                    raise ValueError(f"Unknown payload ref field: {field_name}")

            if getattr(row, "metadata_json", None) is None:
                row.metadata_json = "{}"

            db.commit()
            db.refresh(row)
            return self._detach(db, row)

    def get_payload_ref(self, payload_ref: str) -> Optional[MemoryPayloadRefRow]:
        with self._session_factory() as db:
            row = db.get(MemoryPayloadRefRow, payload_ref)
            return self._detach(db, row) if row is not None else None

    def list_payload_refs(
        self,
        *,
        collection_key: Optional[str] = None,
        repo_id: Optional[str] = None,
        source_path: Optional[str] = None,
        payload_kind: Optional[str] = None,
    ) -> list[MemoryPayloadRefRow]:
        with self._session_factory() as db:
            stmt = select(MemoryPayloadRefRow).order_by(MemoryPayloadRefRow.created_at.asc())
            if collection_key is not None:
                stmt = stmt.where(MemoryPayloadRefRow.collection_key == collection_key)
            if repo_id is not None:
                stmt = stmt.where(MemoryPayloadRefRow.repo_id == repo_id)
            if source_path is not None:
                stmt = stmt.where(MemoryPayloadRefRow.source_path == source_path)
            if payload_kind is not None:
                stmt = stmt.where(MemoryPayloadRefRow.payload_kind == payload_kind)
            rows = list(db.execute(stmt).scalars().all())
            return self._detach_all(db, rows)

    def delete_payload_refs(self, payload_refs: list[str]) -> int:
        if not payload_refs:
            return 0
        with self._session_factory() as db:
            rows = list(
                db.execute(
                    select(MemoryPayloadRefRow).where(MemoryPayloadRefRow.payload_ref.in_(payload_refs))
                ).scalars().all()
            )
            deleted = len(rows)
            for row in rows:
                db.delete(row)
            db.commit()
            return deleted

    def create_ingestion_job(self, *, job_type: str, scope_json: Any = None, **fields: Any) -> MemoryIngestionJobRow:
        if not job_type:
            raise ValueError("job_type is required")

        now = datetime.now(timezone.utc)
        row = MemoryIngestionJobRow(
            job_type=job_type,
            scope_json=self._json_text(scope_json if scope_json is not None else {}),
            created_at=now,
            updated_at=now,
        )

        for field_name, value in fields.items():
            if field_name == "scope_json":
                value = self._json_text(value)
            if hasattr(row, field_name):
                setattr(row, field_name, value)
            else:
                raise ValueError(f"Unknown ingestion job field: {field_name}")

        with self._session_factory() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._detach(db, row)

    def update_ingestion_job(self, job_id: str, **fields: Any) -> MemoryIngestionJobRow:
        now = datetime.now(timezone.utc)
        with self._session_factory() as db:
            row = db.get(MemoryIngestionJobRow, job_id)
            if row is None:
                raise ValueError(f"Unknown ingestion job: {job_id}")

            for field_name, value in fields.items():
                if field_name == "scope_json":
                    value = self._json_text(value)
                if hasattr(row, field_name):
                    setattr(row, field_name, value)
                else:
                    raise ValueError(f"Unknown ingestion job field: {field_name}")

            row.updated_at = now
            db.commit()
            db.refresh(row)
            return self._detach(db, row)

    def get_ingestion_job(self, job_id: str) -> Optional[MemoryIngestionJobRow]:
        with self._session_factory() as db:
            row = db.get(MemoryIngestionJobRow, job_id)
            return self._detach(db, row) if row is not None else None

    def create_collection_version(
        self,
        *,
        collection_key: str,
        collection_name: str,
        generation: str,
        schema_json: Any = None,
        **fields: Any,
    ) -> MemoryCollectionVersionRow:
        if not collection_key:
            raise ValueError("collection_key is required")
        if not collection_name:
            raise ValueError("collection_name is required")
        if not generation:
            raise ValueError("generation is required")

        now = datetime.now(timezone.utc)
        row = MemoryCollectionVersionRow(
            collection_key=collection_key,
            collection_name=collection_name,
            generation=generation,
            schema_json=self._json_text(schema_json if schema_json is not None else {}),
            created_at=now,
        )

        for field_name, value in fields.items():
            if field_name == "schema_json":
                value = self._json_text(value)
            if hasattr(row, field_name):
                setattr(row, field_name, value)
            else:
                raise ValueError(f"Unknown collection version field: {field_name}")

        with self._session_factory() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._detach(db, row)

    def list_collection_versions(self, collection_key: Optional[str] = None) -> list[MemoryCollectionVersionRow]:
        with self._session_factory() as db:
            stmt = select(MemoryCollectionVersionRow).order_by(MemoryCollectionVersionRow.created_at.asc())
            if collection_key is not None:
                stmt = stmt.where(MemoryCollectionVersionRow.collection_key == collection_key)
            rows = list(db.execute(stmt).scalars().all())
            return self._detach_all(db, rows)

    def activate_collection_version(self, *, collection_key: str, version_id: str) -> MemoryCollectionVersionRow:
        now = datetime.now(timezone.utc)
        with self._session_factory() as db:
            rows = list(
                db.execute(
                    select(MemoryCollectionVersionRow).where(
                        MemoryCollectionVersionRow.collection_key == collection_key
                    )
                ).scalars().all()
            )
            if not rows:
                raise ValueError(f"Unknown collection key: {collection_key}")

            target = next((row for row in rows if row.version_id == version_id), None)
            if target is None:
                raise ValueError(
                    f"Collection version {version_id} not found for collection_key {collection_key}"
                )

            for row in rows:
                if row.version_id == version_id:
                    row.is_active = True
                    row.activated_at = row.activated_at or now
                    row.retired_at = None
                else:
                    if row.is_active:
                        row.retired_at = now
                    row.is_active = False

            db.commit()
            db.refresh(target)
            return self._detach(db, target)

    def record_retrieval_provenance(
        self,
        *,
        request_id: str,
        query_text: str,
        selected_refs_json: Any = None,
        rationale_json: Any = None,
        **fields: Any,
    ) -> MemoryRetrievalProvenanceRow:
        if not request_id:
            raise ValueError("request_id is required")
        if not query_text:
            raise ValueError("query_text is required")

        row = MemoryRetrievalProvenanceRow(
            request_id=request_id,
            query_text=query_text,
            selected_refs_json=self._json_text(selected_refs_json if selected_refs_json is not None else []),
            rationale_json=self._json_text(rationale_json if rationale_json is not None else {}),
        )

        for field_name, value in fields.items():
            if field_name in {"selected_refs_json", "rationale_json"}:
                value = self._json_text(value)
            if hasattr(row, field_name):
                setattr(row, field_name, value)
            else:
                raise ValueError(f"Unknown retrieval provenance field: {field_name}")

        with self._session_factory() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._detach(db, row)

    def list_retrieval_provenance(
        self,
        *,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> list[MemoryRetrievalProvenanceRow]:
        with self._session_factory() as db:
            stmt = select(MemoryRetrievalProvenanceRow).order_by(
                MemoryRetrievalProvenanceRow.created_at.asc()
            )
            if request_id is not None:
                stmt = stmt.where(MemoryRetrievalProvenanceRow.request_id == request_id)
            if session_id is not None:
                stmt = stmt.where(MemoryRetrievalProvenanceRow.session_id == session_id)
            rows = list(db.execute(stmt).scalars().all())
            return self._detach_all(db, rows)

    # ---------------------------------------------------------------------- #
    # Conversation turn persistence (Phase 2)                                 #
    # ---------------------------------------------------------------------- #

    def record_conversation_turn(
        self,
        *,
        session_id: str,
        user_message: str,
        assistant_summary: str,
        **fields: Any,
    ) -> MemoryConversationTurnRow:
        """Insert a new conversation turn sidecar record.

        Required keyword args:
            session_id       — owning session UUID
            user_message     — verbatim user text for this turn
            assistant_summary — condensed assistant response text

        Optional keyword args (passed via **fields):
            turn_id, user_id, workspace_scope, turn_number,
            tool_names_json, payload_ref, created_at, expires_at
        """
        if not session_id:
            raise ValueError("session_id is required")
        if user_message is None:
            raise ValueError("user_message is required")
        if assistant_summary is None:
            raise ValueError("assistant_summary is required")

        now = datetime.now(timezone.utc)
        row = MemoryConversationTurnRow(
            session_id=session_id,
            user_message=user_message,
            assistant_summary=assistant_summary,
            created_at=now,
        )

        for field_name, value in fields.items():
            if field_name == "tool_names_json":
                value = self._json_text(value)
            if hasattr(row, field_name):
                setattr(row, field_name, value)
            else:
                raise ValueError(f"Unknown conversation turn field: {field_name}")

        if getattr(row, "tool_names_json", None) is None:
            row.tool_names_json = "[]"

        with self._session_factory() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._detach(db, row)

    def get_conversation_turns(
        self,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        workspace_scope: Optional[str] = None,
        not_expired_as_of: Optional[datetime] = None,
        limit: int = 20,
    ) -> list[MemoryConversationTurnRow]:
        """Return conversation turns, optionally filtered by user/session/scope.

        Passing ``not_expired_as_of`` filters out rows whose ``expires_at`` is
        set and is before the given datetime (i.e. expired turns are excluded).
        """
        with self._session_factory() as db:
            stmt = (
                select(MemoryConversationTurnRow)
                .order_by(MemoryConversationTurnRow.created_at.asc())
            )
            if user_id is not None:
                stmt = stmt.where(MemoryConversationTurnRow.user_id == user_id)
            if session_id is not None:
                stmt = stmt.where(MemoryConversationTurnRow.session_id == session_id)
            if workspace_scope is not None:
                stmt = stmt.where(MemoryConversationTurnRow.workspace_scope == workspace_scope)
            if not_expired_as_of is not None:
                stmt = stmt.where(
                    (MemoryConversationTurnRow.expires_at.is_(None))
                    | (MemoryConversationTurnRow.expires_at > not_expired_as_of)
                )
            if limit > 0:
                stmt = stmt.limit(limit)
            rows = list(db.execute(stmt).scalars().all())
            return self._detach_all(db, rows)

    def expire_conversation_turns(
        self,
        *,
        user_id: Optional[str] = None,
        workspace_scope: Optional[str] = None,
        older_than: Optional[datetime] = None,
        expired_as_of: Optional[datetime] = None,
    ) -> int:
        """Delete expired or overly-old conversation turns; return count deleted.

        Any combination of ``user_id``, ``workspace_scope``, ``older_than``, and
        ``expired_as_of`` may be supplied. At least one must be provided or
        ``ValueError`` is raised to avoid accidental full-table wipes.
        """
        if (
            user_id is None
            and workspace_scope is None
            and older_than is None
            and expired_as_of is None
        ):
            raise ValueError(
                "At least one of user_id, workspace_scope, older_than, or expired_as_of is required"
            )
        with self._session_factory() as db:
            stmt = select(MemoryConversationTurnRow)
            if user_id is not None:
                stmt = stmt.where(MemoryConversationTurnRow.user_id == user_id)
            if workspace_scope is not None:
                stmt = stmt.where(MemoryConversationTurnRow.workspace_scope == workspace_scope)
            if older_than is not None:
                stmt = stmt.where(MemoryConversationTurnRow.created_at < older_than)
            if expired_as_of is not None:
                stmt = stmt.where(
                    MemoryConversationTurnRow.expires_at.is_not(None)
                )
                stmt = stmt.where(MemoryConversationTurnRow.expires_at < expired_as_of)
            rows = list(db.execute(stmt).scalars().all())
            count = len(rows)
            for row in rows:
                db.delete(row)
            db.commit()
            return count

    # ---------------------------------------------------------------------- #
    # Tool cache persistence (Phase 3)                                        #
    # ---------------------------------------------------------------------- #

    def record_tool_cache_entry(
        self,
        *,
        tool_name: str,
        normalized_params_hash: str,
        scope_hash: str,
        result_text: str,
        **fields: Any,
    ) -> MemoryToolCacheRow:
        """Upsert a tool cache entry by (tool_name, normalized_params_hash, scope_hash).

        If a matching row already exists, it is updated in-place (result + expiry).
        """
        if not tool_name:
            raise ValueError("tool_name is required")
        if not normalized_params_hash:
            raise ValueError("normalized_params_hash is required")
        if not scope_hash:
            raise ValueError("scope_hash is required")

        now = datetime.now(timezone.utc)
        with self._session_factory() as db:
            stmt = (
                select(MemoryToolCacheRow)
                .where(MemoryToolCacheRow.tool_name == tool_name)
                .where(MemoryToolCacheRow.normalized_params_hash == normalized_params_hash)
                .where(MemoryToolCacheRow.scope_hash == scope_hash)
            )
            row = db.execute(stmt).scalars().first()
            if row is None:
                row = MemoryToolCacheRow(
                    tool_name=tool_name,
                    normalized_params_hash=normalized_params_hash,
                    scope_hash=scope_hash,
                    result_text=result_text,
                    created_at=now,
                )
                db.add(row)
            else:
                row.result_text = result_text
                row.created_at = now

            for field_name, value in fields.items():
                if hasattr(row, field_name):
                    setattr(row, field_name, value)
                else:
                    raise ValueError(f"Unknown tool cache field: {field_name}")

            db.commit()
            db.refresh(row)
            return self._detach(db, row)

    def get_tool_cache_entry(
        self,
        *,
        tool_name: str,
        normalized_params_hash: str,
        scope_hash: str,
        not_expired_as_of: Optional[datetime] = None,
    ) -> Optional[MemoryToolCacheRow]:
        """Return a matching cache entry, or ``None`` if not found or expired."""
        with self._session_factory() as db:
            stmt = (
                select(MemoryToolCacheRow)
                .where(MemoryToolCacheRow.tool_name == tool_name)
                .where(MemoryToolCacheRow.normalized_params_hash == normalized_params_hash)
                .where(MemoryToolCacheRow.scope_hash == scope_hash)
            )
            if not_expired_as_of is not None:
                stmt = stmt.where(
                    (MemoryToolCacheRow.expires_at.is_(None))
                    | (MemoryToolCacheRow.expires_at > not_expired_as_of)
                )
            row = db.execute(stmt).scalars().first()
            return self._detach(db, row) if row is not None else None

    def expire_tool_cache_entries(
        self,
        *,
        tool_name: Optional[str] = None,
        scope_hash: Optional[str] = None,
        older_than: Optional[datetime] = None,
        expired_as_of: Optional[datetime] = None,
    ) -> int:
        """Delete tool cache entries matching the given filters; return count deleted.

        At least one filter must be supplied.
        """
        if (
            tool_name is None
            and scope_hash is None
            and older_than is None
            and expired_as_of is None
        ):
            raise ValueError(
                "At least one of tool_name, scope_hash, older_than, or expired_as_of is required"
            )
        with self._session_factory() as db:
            stmt = select(MemoryToolCacheRow)
            if tool_name is not None:
                stmt = stmt.where(MemoryToolCacheRow.tool_name == tool_name)
            if scope_hash is not None:
                stmt = stmt.where(MemoryToolCacheRow.scope_hash == scope_hash)
            if older_than is not None:
                stmt = stmt.where(MemoryToolCacheRow.created_at < older_than)
            if expired_as_of is not None:
                stmt = stmt.where(MemoryToolCacheRow.expires_at.is_not(None))
                stmt = stmt.where(MemoryToolCacheRow.expires_at < expired_as_of)
            rows = list(db.execute(stmt).scalars().all())
            count = len(rows)
            for row in rows:
                db.delete(row)
            db.commit()
            return count

    def _json_text(self, value: Any) -> str:
        if value is None:
            return "{}"
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value)
        except (TypeError, ValueError) as error:
            raise ValueError("Value is not JSON-serializable") from error

    def _detach(self, db: Session, row: Any) -> Any:
        db.expunge(row)
        return row

    def _detach_all(self, db: Session, rows: list[Any]) -> list[Any]:
        for row in rows:
            db.expunge(row)
        return rows
