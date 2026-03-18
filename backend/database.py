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
