"""Database layer — SQLAlchemy ORM models, engine, session factory, and schema init.

Default database: SQLite (file: ./mcp_client.db)
Override with DB_URL env var for PostgreSQL in production.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger("mcp_client.internal")

_DB_URL = os.getenv("DB_URL", "sqlite:///./mcp_client.db")
_engine = create_engine(
    _DB_URL,
    connect_args={"check_same_thread": False} if "sqlite" in _DB_URL else {},
    echo=False,
)
SessionLocal: sessionmaker = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    user_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider = Column(String(32), nullable=False)
    provider_sub = Column(String(256), nullable=False)
    email = Column(String(256), nullable=False, unique=True)
    display_name = Column(String(256), nullable=False, default="")
    avatar_url = Column(Text, nullable=True)
    roles = Column(Text, nullable=False, default='["user"]')  # JSON list
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    last_login_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("provider", "provider_sub", name="uq_provider_sub"),)


class UserLLMConfigRow(Base):
    __tablename__ = "user_llm_configs"

    user_id = Column(String(36), primary_key=True)   # FK → users.user_id
    config_json = Column(Text, nullable=False)        # AES-256-GCM encrypted JSON
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class UserServerRow(Base):
    __tablename__ = "user_servers"

    server_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), nullable=False)      # FK → users.user_id
    config_json = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("user_id", "server_id", name="uq_user_server"),)


class UserSettingsRow(Base):
    __tablename__ = "user_settings"

    user_id = Column(String(36), primary_key=True)   # FK → users.user_id
    theme = Column(String(16), nullable=False, default="system")
    message_density = Column(String(16), nullable=False, default="comfortable")
    tool_panel_visible = Column(Boolean, nullable=False, default=True)
    sidebar_collapsed = Column(Boolean, nullable=False, default=False)
    default_llm_model = Column(String(128), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class MemoryPayloadRefRow(Base):
    __tablename__ = "memory_payload_refs"

    payload_ref = Column(String(128), primary_key=True)
    payload_kind = Column(String(32), nullable=False)
    storage_backend = Column(String(32), nullable=False, default="sql")
    memory_id = Column(String(128), nullable=True)
    collection_key = Column(String(64), nullable=True)
    repo_id = Column(String(256), nullable=True)
    user_id = Column(String(36), nullable=True)
    relative_path = Column(String(1024), nullable=True)
    source_path = Column(String(1024), nullable=True)
    source_type = Column(String(64), nullable=True)
    section = Column(String(256), nullable=True)
    symbol_name = Column(String(256), nullable=True)
    symbol_kind = Column(String(64), nullable=True)
    language = Column(String(32), nullable=True)
    namespace = Column(String(512), nullable=True)
    signature = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    source_hash = Column(String(128), nullable=True)
    start_line = Column(Integer, nullable=True)
    end_line = Column(Integer, nullable=True)
    payload_text = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class MemoryIngestionJobRow(Base):
    __tablename__ = "memory_ingestion_jobs"

    job_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_type = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    repo_id = Column(String(256), nullable=True)
    requested_by_user_id = Column(String(36), nullable=True)
    scope_json = Column(Text, nullable=False, default="{}")
    collection_key = Column(String(64), nullable=True)
    source_count = Column(Integer, nullable=False, default=0)
    chunk_count = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)
    error_summary = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class MemoryCollectionVersionRow(Base):
    __tablename__ = "memory_collection_versions"

    version_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    collection_key = Column(String(64), nullable=False)
    collection_name = Column(String(128), nullable=False)
    generation = Column(String(64), nullable=False)
    embedding_provider = Column(String(64), nullable=True)
    embedding_model = Column(String(128), nullable=True)
    embedding_dimension = Column(Integer, nullable=True)
    index_version = Column(String(64), nullable=True)
    is_active = Column(Boolean, nullable=False, default=False)
    schema_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    activated_at = Column(DateTime, nullable=True)
    retired_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("collection_name", name="uq_memory_collection_name"),
        UniqueConstraint("collection_key", "generation", name="uq_memory_collection_generation"),
    )


class MemoryRetrievalProvenanceRow(Base):
    __tablename__ = "memory_retrieval_provenance"

    provenance_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id = Column(String(64), nullable=False)
    session_id = Column(String(64), nullable=True)
    user_id = Column(String(36), nullable=True)
    repo_id = Column(String(256), nullable=True)
    retrieval_scope = Column(String(64), nullable=True)
    query_text = Column(Text, nullable=False)
    selected_count = Column(Integer, nullable=False, default=0)
    selected_refs_json = Column(Text, nullable=False, default="[]")
    rationale_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class MemoryConversationTurnRow(Base):
    """Sidecar record for a single conversation turn stored in conversation memory."""

    __tablename__ = "memory_conversation_turns"

    turn_id = Column(
        String(64),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id = Column(String(64), nullable=True)           # owning user (SSO)
    session_id = Column(String(64), nullable=False)
    workspace_scope = Column(String(256), nullable=True)  # optional workspace key
    turn_number = Column(Integer, nullable=False, default=0)
    user_message = Column(Text, nullable=False, default="")
    assistant_summary = Column(Text, nullable=False, default="")
    tool_names_json = Column(Text, nullable=False, default="[]")
    payload_ref = Column(String(256), nullable=True)      # link to MemoryPayloadRefRow
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at = Column(DateTime, nullable=True)


class MemoryToolCacheRow(Base):
    """Sidecar record for a safe, allowlisted tool cache entry."""

    __tablename__ = "memory_tool_cache"

    cache_id = Column(
        String(64),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    tool_name = Column(String(256), nullable=False)
    server_alias = Column(String(128), nullable=False, default="")
    # SHA-256 prefix of deterministically normalised tool arguments JSON
    normalized_params_hash = Column(String(128), nullable=False)
    # SHA-256 prefix of scope key (user_id + workspace_scope) — ensures scope isolation
    scope_hash = Column(String(128), nullable=False)
    payload_ref = Column(String(256), nullable=True)
    result_text = Column(Text, nullable=False, default="")
    source_version = Column(String(128), nullable=True)
    is_cacheable = Column(Boolean, nullable=False, default=False)
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tool_name",
            "normalized_params_hash",
            "scope_hash",
            name="uq_tool_cache_key",
        ),
    )


class ChatSessionRow(Base):
    """Persisted chat session — survives backend restarts."""

    __tablename__ = "chat_sessions"

    session_id = Column(String(64), primary_key=True)
    title = Column(String(256), nullable=False, default="New Conversation")
    user_id = Column(String(64), nullable=True)
    config_json = Column(Text, nullable=False, default="{}")
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class ChatMessageRow(Base):
    """Persisted chat message within a session, ordered by sequence_num."""

    __tablename__ = "chat_messages"

    message_id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), nullable=False, index=True)
    sequence_num = Column(Integer, nullable=False, default=0)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False, default="")
    tool_call_id = Column(String(128), nullable=True)
    tool_calls_json = Column(Text, nullable=True)  # JSON list of ToolCall dicts
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all tables if they do not exist."""
    Base.metadata.create_all(bind=_engine)
    logger.info("Database schema initialised (DB_URL=%s)", _DB_URL.split("?")[0])


# ---------------------------------------------------------------------------
# Sync helper functions used by user_store
# ---------------------------------------------------------------------------

def get_db() -> Session:
    """Return a new SQLAlchemy session. Caller must close it."""
    return SessionLocal()


def get_user_by_id(user_id: str) -> Optional[UserRow]:
    with SessionLocal() as db:
        return db.get(UserRow, user_id)


def get_user_by_email(email: str) -> Optional[UserRow]:
    with SessionLocal() as db:
        result = db.execute(select(UserRow).where(UserRow.email == email))
        return result.scalar_one_or_none()


def get_user_by_provider(provider: str, provider_sub: str) -> Optional[UserRow]:
    with SessionLocal() as db:
        result = db.execute(
            select(UserRow).where(
                UserRow.provider == provider,
                UserRow.provider_sub == provider_sub,
            )
        )
        return result.scalar_one_or_none()


def upsert_user(
    provider: str,
    provider_sub: str,
    email: str,
    display_name: str,
    avatar_url: Optional[str],
    admin_emails: list,
) -> UserRow:
    """Insert or update a user row on login. Returns the (possibly new) UserRow."""
    now = datetime.now(timezone.utc)
    roles = ["user"]
    if email.lower() in [e.lower() for e in admin_emails]:
        roles = ["user", "admin"]

    with SessionLocal() as db:
        existing = db.execute(
            select(UserRow).where(
                UserRow.provider == provider,
                UserRow.provider_sub == provider_sub,
            )
        ).scalar_one_or_none()

        if existing is not None:
            existing.last_login_at = now
            existing.display_name = display_name
            if avatar_url:
                existing.avatar_url = avatar_url
            existing.roles = json.dumps(roles)
            db.commit()
            db.refresh(existing)
            return existing

        # First login — create new record
        new_user = UserRow(
            user_id=str(uuid.uuid4()),
            provider=provider,
            provider_sub=provider_sub,
            email=email,
            display_name=display_name,
            avatar_url=avatar_url,
            roles=json.dumps(roles),
            is_active=True,
            created_at=now,
            last_login_at=now,
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        # Create default settings row
        settings = UserSettingsRow(user_id=new_user.user_id, updated_at=now)
        db.add(settings)
        db.commit()

        logger.info(f"New user created: {email} ({provider})")
        return new_user
