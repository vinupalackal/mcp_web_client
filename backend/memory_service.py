"""Retrieval orchestration service for optional memory-augmented chat turns."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

logger_internal = logging.getLogger("mcp_client.internal")


@dataclass(frozen=True)
class MemoryServiceConfig:
    """Runtime configuration for retrieval orchestration."""

    enabled: bool = False
    repo_id: str = ""
    collection_generation: str = "v1"
    max_results: int = 5
    retrieval_timeout_s: float = 5.0
    degraded_mode: bool = True
    collection_keys: tuple[str, ...] = ("code_memory", "doc_memory")
    # Phase 2: conversation memory
    enable_conversation_memory: bool = False
    conversation_retention_days: int = 7
    # Phase 3: safe tool cache
    enable_tool_cache: bool = False
    tool_cache_ttl_s: float = 3600.0
    # Explicit allowlist of tool names eligible for caching.
    # Empty tuple = no tools cached (feature disabled regardless of enable_tool_cache).
    tool_cache_allowlist: tuple[str, ...] = ()
    # Phase 4: operations hardening / expiry maintenance
    enable_expiry_cleanup: bool = True
    expiry_cleanup_interval_s: float = 300.0


@dataclass(frozen=True)
class RetrievalBlock:
    """Normalized retrieval block returned to chat orchestration."""

    payload_ref: str
    collection: str
    score: float
    snippet: str
    source_path: str


@dataclass(frozen=True)
class RetrievalResult:
    """Outcome of a retrieval-enrichment attempt."""

    blocks: list[RetrievalBlock] = field(default_factory=list)
    degraded: bool = False
    degraded_reason: str = ""
    latency_ms: float = 0.0
    query_hash: str = ""
    collection_keys: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ToolCacheResult:
    """Outcome of a safe tool-cache lookup."""

    hit: bool = False
    result_text: str = ""
    cache_id: str = ""
    # True only when the tool is on the explicit allowlist AND a valid entry was found.
    approved: bool = False


class MemoryService:
    """Coordinate embedding, vector search, and provenance recording for retrieval."""

    def __init__(
        self,
        *,
        embedding_service: Any,
        milvus_store: Any,
        memory_persistence: Any,
        config: Optional[MemoryServiceConfig] = None,
    ):
        self.embedding_service = embedding_service
        self.milvus_store = milvus_store
        self.memory_persistence = memory_persistence
        self.config = config or MemoryServiceConfig()
        self._last_expiry_cleanup_at: Optional[datetime] = None
        self._last_expiry_cleanup_summary: dict[str, Any] = {
            "ran": False,
            "conversation_deleted": 0,
            "tool_cache_deleted": 0,
            "conversation_vector_deleted": None,
            "tool_cache_vector_deleted": None,
            "reason": None,
        }

    async def enrich_for_turn(
        self,
        *,
        user_message: str,
        session_id: str,
        repo_id: Optional[str] = None,
        request_id: Optional[str] = None,
        user_id: str = "",
        workspace_scope: str = "",
        include_code_memory: bool = True,
    ) -> RetrievalResult:
        """Return normalized retrieval blocks for a single chat turn.

        Set ``include_code_memory=False`` for planning/tool-routing calls so
        that ``code_memory`` and ``doc_memory`` collections are skipped.  Those
        collections are only useful during synthesis, when the LLM needs source
        context to explain tool results.  Skipping them during planning keeps
        the context window clean for tool-selection reasoning.

        This method never raises for dependency failures; instead it returns a
        degraded result with an empty block list.
        """
        if not self.config.enabled:
            return RetrievalResult(collection_keys=self.config.collection_keys)

        started = time.perf_counter()
        query_text = self._build_query(user_message)
        query_hash = self._query_hash(query_text)
        effective_repo_id = repo_id if repo_id is not None else self.config.repo_id
        effective_request_id = request_id or self._request_id()
        collections_to_search = tuple(self._collections_to_search(user_id, include_code_memory=include_code_memory))

        # --- Short-circuit: nothing to search ---
        # If the resolved collection list is empty (e.g. anonymous user with
        # include_code_memory=False, so conversation_memory is excluded and
        # code/doc collections are skipped) there is zero chance of returning
        # any blocks.  Skip the Ollama embedding call (~300-400 ms) entirely.
        if not collections_to_search:
            logger_internal.info(
                "Memory retrieval skipped (no collections to search): request_id=%s session=%s user=%s include_code_memory=%s",
                request_id or "<no-request-id>",
                session_id,
                user_id or "<anonymous>",
                include_code_memory,
            )
            return RetrievalResult(
                blocks=[],
                degraded=False,
                degraded_reason="",
                latency_ms=0.0,
                query_hash="",
                collection_keys=collections_to_search,
            )

        logger_internal.info(
            "Memory retrieval transaction started: request_id=%s session=%s user=%s collections=%s query_hash=%s message=%s",
            effective_request_id,
            session_id,
            user_id or "<anonymous>",
            ",".join(collections_to_search),
            query_hash,
            self._preview_text(query_text),
        )

        try:
            blocks = await asyncio.wait_for(
                self._retrieve_blocks(
                    query_text=query_text,
                    repo_id=effective_repo_id,
                    user_id=user_id,
                    workspace_scope=workspace_scope,
                    include_code_memory=include_code_memory,
                ),
                timeout=max(self.config.retrieval_timeout_s, 0.001),
            )
            latency_ms = (time.perf_counter() - started) * 1000.0
            self._record_provenance(
                request_id=effective_request_id,
                session_id=session_id,
                repo_id=effective_repo_id,
                query_text=query_text,
                query_hash=query_hash,
                blocks=blocks,
                latency_ms=latency_ms,
            )
            logger_internal.info(
                "Memory retrieval transaction completed: request_id=%s session=%s result_count=%s latency_ms=%.1f degraded=%s",
                effective_request_id,
                session_id,
                len(blocks),
                latency_ms,
                False,
            )
            return RetrievalResult(
                blocks=blocks,
                degraded=False,
                degraded_reason="",
                latency_ms=latency_ms,
                query_hash=query_hash,
                collection_keys=collections_to_search,
            )
        except asyncio.TimeoutError:
            latency_ms = (time.perf_counter() - started) * 1000.0
            reason = (
                f"Retrieval timeout after {max(self.config.retrieval_timeout_s, 0.001):.3f}s"
            )
            logger_internal.warning(
                "Memory retrieval transaction degraded: request_id=%s session=%s query_hash=%s latency_ms=%.1f reason=%s",
                effective_request_id,
                session_id,
                query_hash,
                latency_ms,
                reason,
            )
            return RetrievalResult(
                degraded=True,
                degraded_reason=reason,
                latency_ms=latency_ms,
                query_hash=query_hash,
                collection_keys=collections_to_search,
            )
        except Exception as error:
            latency_ms = (time.perf_counter() - started) * 1000.0
            reason = str(error)
            logger_internal.warning(
                "Memory retrieval transaction degraded: request_id=%s session=%s query_hash=%s latency_ms=%.1f reason=%s",
                effective_request_id,
                session_id,
                query_hash,
                latency_ms,
                reason,
            )
            return RetrievalResult(
                degraded=True,
                degraded_reason=reason,
                latency_ms=latency_ms,
                query_hash=query_hash,
                collection_keys=collections_to_search,
            )

    async def record_turn(
        self,
        *,
        user_message: str,
        assistant_response: str,
        session_id: str,
        user_id: str = "",
        workspace_scope: str = "",
        tool_names: Optional[list] = None,
        turn_number: int = 0,
    ) -> None:
        """Embed and store a completed conversation turn in the conversation memory
        collection and the sidecar persistence layer.

        This method fails silently — recording errors are logged but never raised
        so the chat response path is not disrupted.
        """
        if not self.config.enabled or not self.config.enable_conversation_memory:
            return

        # For anonymous (single-user, no SSO) deployments user_id is empty.
        # Use the stable synthetic scope "__anonymous__" so that conversation
        # turns are stored and later retrieved under a consistent identity
        # rather than being silently discarded.
        effective_user_id = user_id or "__anonymous__"

        turn_id = self._request_id().replace("retrieval-", "turn-")

        try:
            combined_text = f"{user_message} {assistant_response[:512]}"
            embedding_result = await self.embedding_service.embed_texts([combined_text])
            vector = embedding_result.vectors[0]

            import time as _time
            now_ts = int(_time.time())
            expires_ts = now_ts + self.config.conversation_retention_days * 86400

            logger_internal.info(
                "Conversation memory transaction started: turn_id=%s session=%s user=%s turn_number=%s tool_count=%s message=%s",
                turn_id,
                session_id,
                effective_user_id,
                turn_number,
                len(tool_names or []),
                self._preview_text(user_message),
            )

            record = {
                "id": turn_id,
                "embedding": vector,
                "user_id": effective_user_id,
                "session_id": session_id,
                "workspace_scope": workspace_scope or "",
                "turn_number": turn_number,
                "user_message": user_message[:4096],
                "assistant_summary": assistant_response[:4096],
                "tool_names": ",".join(tool_names or [])[:1024],
                "payload_ref": turn_id,
                "created_at": now_ts,
                "expires_at": expires_ts,
            }

            self.milvus_store.upsert(
                collection_key="conversation_memory",
                generation=self.config.collection_generation,
                records=[record],
            )

            from datetime import datetime, timezone, timedelta
            self.memory_persistence.record_conversation_turn(
                session_id=session_id,
                user_message=user_message[:4096],
                assistant_summary=assistant_response[:4096],
                turn_id=turn_id,
                user_id=effective_user_id,
                workspace_scope=workspace_scope or None,
                turn_number=turn_number,
                tool_names_json=tool_names or [],
                payload_ref=turn_id,
                expires_at=datetime.now(timezone.utc) + timedelta(
                    days=self.config.conversation_retention_days
                ),
            )

            # Console summary — printed to server stdout after every query.
            try:
                from datetime import datetime, timezone as _tz
                total_rows = self.milvus_store.get_record_count(
                    collection_key="conversation_memory",
                    generation=self.config.collection_generation,
                )
                count_str = str(total_rows) if total_rows >= 0 else "unknown"
                tools_display = ", ".join(tool_names or []) or "(none)"
                expires_dt = datetime.fromtimestamp(expires_ts, tz=_tz.utc).strftime(
                    "%Y-%m-%d %H:%M UTC"
                )
                msg_preview = self._preview_text(user_message, max_length=80)
                logger_external.info(
                    "\n"
                    "┌─── MILVUS MEMORY STORE ─── NEW RECORD ADDED ──────────────────────────\n"
                    "│  turn_id    : %s\n"
                    "│  session    : %s\n"
                    "│  user       : %s\n"
                    "│  turn #     : %s\n"
                    "│  message    : %s\n"
                    "│  tools      : %s\n"
                    "│  expires    : %s\n"
                    "│  total rows : %s  (conversation_memory)\n"
                    "└───────────────────────────────────────────────────────────────────────",
                    turn_id,
                    session_id,
                    effective_user_id,
                    turn_number,
                    msg_preview,
                    tools_display,
                    expires_dt,
                    count_str,
                )
            except Exception:
                pass  # never disrupt the response path

            logger_internal.info(
                "Conversation memory transaction completed: turn_id=%s session=%s user=%s expires_at=%s",
                turn_id,
                session_id,
                effective_user_id,
                expires_ts,
            )
        except Exception as error:
            logger_internal.warning(
                "Conversation memory transaction failed: turn_id=%s session=%s user=%s reason=%s",
                turn_id,
                session_id,
                effective_user_id,
                error,
            )

    # ------------------------------------------------------------------ #
    # Phase 3: Safe tool cache                                             #
    # ------------------------------------------------------------------ #

    def lookup_tool_cache(
        self,
        *,
        tool_name: str,
        arguments: dict,
        user_id: str = "",
        workspace_scope: str = "",
    ) -> "ToolCacheResult":
        """Return a cache hit only when the tool is explicitly allowlisted AND a
        valid (non-expired) entry exists for the exact (tool_name, params, scope)
        triple.

        Similarity alone is never used here — the lookup is purely by deterministic
        hash, so the cache cannot be triggered by a near-miss embedding.

        Returns a ``ToolCacheResult`` with ``hit=False`` and ``approved=False``
        in all other cases, including errors.
        """
        if not self.config.enable_tool_cache:
            return ToolCacheResult()
        if not self.config.tool_cache_allowlist:
            return ToolCacheResult()
        if tool_name not in self.config.tool_cache_allowlist:
            # Explicit policy: only allowlisted tools may be cached.
            logger_internal.debug(
                "Tool cache: %s not in allowlist — skipping lookup", tool_name
            )
            return ToolCacheResult()

        try:
            params_hash = self._build_params_hash(tool_name, arguments)
            scope_hash = self._build_cache_scope_hash(user_id, workspace_scope)
            from datetime import datetime, timezone as _tz
            row = self.memory_persistence.get_tool_cache_entry(
                tool_name=tool_name,
                normalized_params_hash=params_hash,
                scope_hash=scope_hash,
                not_expired_as_of=datetime.now(_tz.utc),
            )
            if row is not None and row.is_cacheable:
                logger_internal.debug(
                    "Tool cache HIT: tool=%s cache_id=%s", tool_name, row.cache_id
                )
                return ToolCacheResult(
                    hit=True,
                    result_text=row.result_text,
                    cache_id=row.cache_id,
                    approved=True,
                )
        except Exception as error:
            logger_internal.warning("Tool cache lookup failed: %s", error)
        return ToolCacheResult()

    def record_tool_cache(
        self,
        *,
        tool_name: str,
        arguments: dict,
        result_text: str,
        user_id: str = "",
        workspace_scope: str = "",
        source_version: str = "",
    ) -> None:
        """Store a tool result in the cache when the tool is on the allowlist.

        Fails silently — caching errors must never interrupt the response path.
        """
        if not self.config.enable_tool_cache:
            return
        if not self.config.tool_cache_allowlist:
            return
        if tool_name not in self.config.tool_cache_allowlist:
            return

        try:
            params_hash = self._build_params_hash(tool_name, arguments)
            scope_hash = self._build_cache_scope_hash(user_id, workspace_scope)
            import time as _t
            from datetime import datetime, timezone as _tz, timedelta as _td
            expires_at = datetime.now(_tz.utc) + _td(seconds=max(self.config.tool_cache_ttl_s, 1.0))

            self.memory_persistence.record_tool_cache_entry(
                tool_name=tool_name,
                normalized_params_hash=params_hash,
                scope_hash=scope_hash,
                result_text=result_text,
                is_cacheable=True,
                source_version=source_version or "",
                expires_at=expires_at,
            )
            logger_internal.debug(
                "Tool cache stored: tool=%s params_hash=%.8s scope_hash=%.8s",
                tool_name,
                params_hash,
                scope_hash,
            )
        except Exception as error:
            logger_internal.warning("Failed to store tool cache entry: %s", error)

    async def resolve_tools_from_memory(
        self,
        *,
        user_message: str,
        user_id: str = "",
        available_tool_names: list[str],
        request_id: str = "",
        similarity_threshold: float = 0.30,
    ) -> list[str]:
        """Return tool names recalled from similar past turns that are still available.

        Searches ``conversation_memory`` and ``tool_cache`` only — never
        ``code_memory`` or ``doc_memory``, which hold code/document content
        irrelevant to tool routing.

        Returns an empty list when:
        - Memory is disabled or ``user_id`` is empty (conversation memory is
          user-scoped; anonymous sessions cannot benefit from prior turns).
        - No past turns are found above the similarity threshold.
        - None of the recalled tool names appear in ``available_tool_names``.

        The caller should treat a non-empty return as a routing hint and only
        fall back to LLM-based tool selection when this list is empty.
        """
        if not self.config.enabled:
            return []
        if not self.config.enable_conversation_memory and not self.config.enable_tool_cache:
            return []

        effective_user_id = user_id or "__anonymous__"
        effective_request_id = request_id or self._request_id()
        available_set = set(available_tool_names)

        try:
            return await asyncio.wait_for(
                self._resolve_tools_inner(
                    user_message=user_message,
                    user_id=effective_user_id,
                    available_set=available_set,
                    similarity_threshold=similarity_threshold,
                    effective_request_id=effective_request_id,
                ),
                timeout=max(self.config.retrieval_timeout_s, 0.001),
            )
        except asyncio.TimeoutError:
            logger_internal.warning(
                "resolve_tools_from_memory timed out after %.1fs request_id=%s",
                self.config.retrieval_timeout_s,
                effective_request_id,
            )
            return []
        except Exception as error:
            logger_internal.warning(
                "resolve_tools_from_memory failed request_id=%s error=%s",
                effective_request_id,
                error,
            )
            return []

    async def _resolve_tools_inner(
        self,
        *,
        user_message: str,
        user_id: str,
        available_set: set[str],
        similarity_threshold: float,
        effective_request_id: str,
    ) -> list[str]:
        try:
            embedding_result = await self.embedding_service.embed_texts([user_message])
            query_vector = embedding_result.vectors[0]
        except Exception as error:
            logger_internal.warning(
                "resolve_tools_from_memory: embedding failed request_id=%s error=%s",
                effective_request_id,
                error,
            )
            return []

        tool_names_found: list[str] = []

        # --- conversation_memory: extract tool_names from similar past turns ---
        if self.config.enable_conversation_memory:
            try:
                filter_expr = self._build_conversation_filter_expression(
                    user_id=user_id,
                    workspace_scope="",
                )
                raw_hits = self.milvus_store.search(
                    collection_key="conversation_memory",
                    generation=self.config.collection_generation,
                    query_vectors=[query_vector],
                    limit=5,
                    filter_expression=filter_expr,
                    output_fields=["payload_ref", "tool_names", "user_message", "turn_number"],
                )
                for hit in self._flatten_hits(raw_hits):
                    if self._score_for_hit(hit) > similarity_threshold:
                        continue  # too dissimilar
                    entity = hit.get("entity") if isinstance(hit, dict) else None
                    raw_tool_names = self._field(hit, entity, "tool_names") or ""
                    for name in (t.strip() for t in raw_tool_names.split(",") if t.strip()):
                        if name in available_set and name not in tool_names_found:
                            tool_names_found.append(name)
            except Exception as error:
                logger_internal.warning(
                    "resolve_tools_from_memory: conversation_memory search failed request_id=%s error=%s",
                    effective_request_id,
                    error,
                )

        # --- tool_cache: extract tool_name from semantically similar cached calls ---
        if self.config.enable_tool_cache:
            try:
                raw_hits = self.milvus_store.search(
                    collection_key="tool_cache",
                    generation=self.config.collection_generation,
                    query_vectors=[query_vector],
                    limit=5,
                    filter_expression="",
                    output_fields=["payload_ref", "tool_name", "server_alias"],
                )
                for hit in self._flatten_hits(raw_hits):
                    if self._score_for_hit(hit) > similarity_threshold:
                        continue
                    entity = hit.get("entity") if isinstance(hit, dict) else None
                    server_alias = self._field(hit, entity, "server_alias") or ""
                    tool_name = self._field(hit, entity, "tool_name") or ""
                    # Try namespaced form first (server_alias__tool_name), then bare name
                    namespaced = f"{server_alias}__{tool_name}" if server_alias and tool_name else tool_name
                    for candidate in (namespaced, tool_name):
                        if candidate and candidate in available_set and candidate not in tool_names_found:
                            tool_names_found.append(candidate)
                            break
            except Exception as error:
                logger_internal.warning(
                    "resolve_tools_from_memory: tool_cache search failed request_id=%s error=%s",
                    effective_request_id,
                    error,
                )

        logger_internal.info(
            "Memory tool resolution: request_id=%s user=%s threshold=%.2f recalled=%s",
            effective_request_id,
            user_id,
            similarity_threshold,
            len(tool_names_found),
        )
        return tool_names_found

    def run_expiry_cleanup_if_due(
        self,
        *,
        force: bool = False,
        cleanup_expired_conversation_memory: bool = True,
        cleanup_expired_tool_cache: bool = True,
    ) -> dict[str, Any]:
        """Delete expired conversation/tool-cache records when cleanup is enabled.

        Cleanup is intentionally best-effort and fail-open. It removes expired SQL
        sidecar rows and attempts to delete expired Milvus rows by filter so
        retrieval does not accumulate stale vector records over time.
        """
        if not self.config.enable_expiry_cleanup:
            return {
                "ran": False,
                "skipped": True,
                "reason": "cleanup disabled",
            }

        if not cleanup_expired_conversation_memory and not cleanup_expired_tool_cache:
            return {
                "ran": False,
                "skipped": True,
                "reason": "no cleanup targets selected",
            }

        now = datetime.now(timezone.utc)
        if (
            not force
            and self._last_expiry_cleanup_at is not None
            and (now - self._last_expiry_cleanup_at).total_seconds()
            < max(self.config.expiry_cleanup_interval_s, 1.0)
        ):
            return {
                "ran": False,
                "skipped": True,
                "reason": "cleanup interval not elapsed",
                "last_cleanup_at": self._last_expiry_cleanup_at.isoformat(),
            }

        summary = {
            "ran": True,
            "conversation_deleted": 0,
            "tool_cache_deleted": 0,
            "conversation_vector_deleted": None,
            "tool_cache_vector_deleted": None,
            "reason": None,
            "cleaned_at": now.isoformat(),
        }

        try:
            if cleanup_expired_conversation_memory:
                summary["conversation_deleted"] = self.memory_persistence.expire_conversation_turns(
                    expired_as_of=now,
                )
            if cleanup_expired_tool_cache:
                summary["tool_cache_deleted"] = self.memory_persistence.expire_tool_cache_entries(
                    expired_as_of=now,
                )

            now_ts = int(now.timestamp())
            if cleanup_expired_conversation_memory and self.config.enable_conversation_memory:
                try:
                    summary["conversation_vector_deleted"] = self.milvus_store.delete_by_filter(
                        collection_key="conversation_memory",
                        generation=self.config.collection_generation,
                        filter_expression=f"expires_at < {now_ts}",
                    )
                except Exception as error:
                    logger_internal.warning(
                        "Conversation-memory vector cleanup failed: %s", error
                    )
                    summary["conversation_vector_deleted"] = {"error": str(error)}

            if cleanup_expired_tool_cache and self.config.enable_tool_cache:
                try:
                    summary["tool_cache_vector_deleted"] = self.milvus_store.delete_by_filter(
                        collection_key="tool_cache",
                        generation=self.config.collection_generation,
                        filter_expression=f"expires_at < {now_ts}",
                    )
                except Exception as error:
                    logger_internal.warning(
                        "Tool-cache vector cleanup failed: %s", error
                    )
                    summary["tool_cache_vector_deleted"] = {"error": str(error)}
        except Exception as error:
            logger_internal.warning("Expiry cleanup failed: %s", error)
            summary["reason"] = str(error)

        self._last_expiry_cleanup_at = now
        self._last_expiry_cleanup_summary = summary
        return summary

    async def health_status(self) -> dict[str, Any]:
        """Return a summary of memory subsystem readiness."""
        if not self.config.enabled:
            return {
                "enabled": False,
                "healthy": True,
                "degraded": False,
                "status": "disabled",
                "reason": "Memory is disabled by configuration",
                "warnings": [],
                "milvus_reachable": None,
                "embedding_available": None,
                "active_collections": [],
            }

        try:
            collections = list(self.milvus_store.list_collections())
            return {
                "enabled": True,
                "healthy": True,
                "degraded": False,
                "status": "healthy",
                "reason": None,
                "warnings": [],
                "milvus_reachable": True,
                "embedding_available": self.embedding_service is not None,
                "active_collections": collections,
                "expiry_cleanup": {
                    "enabled": self.config.enable_expiry_cleanup,
                    "interval_s": self.config.expiry_cleanup_interval_s,
                    "last_run_at": (
                        self._last_expiry_cleanup_at.isoformat()
                        if self._last_expiry_cleanup_at is not None
                        else None
                    ),
                    "last_summary": self._last_expiry_cleanup_summary,
                },
            }
        except Exception as error:
            return {
                "enabled": True,
                "healthy": False,
                "degraded": True,
                "status": "degraded",
                "reason": str(error),
                "warnings": ["Memory degraded mode is active"],
                "milvus_reachable": False,
                "embedding_available": self.embedding_service is not None,
                "active_collections": [],
                "expiry_cleanup": {
                    "enabled": self.config.enable_expiry_cleanup,
                    "interval_s": self.config.expiry_cleanup_interval_s,
                    "last_run_at": (
                        self._last_expiry_cleanup_at.isoformat()
                        if self._last_expiry_cleanup_at is not None
                        else None
                    ),
                    "last_summary": self._last_expiry_cleanup_summary,
                },
            }

    async def _retrieve_blocks(
        self,
        *,
        query_text: str,
        repo_id: str,
        user_id: str = "",
        workspace_scope: str = "",
        include_code_memory: bool = True,
    ) -> list[RetrievalBlock]:
        embedding_result = await self.embedding_service.embed_texts([query_text])
        query_vector = embedding_result.vectors[0]
        merged_hits: list[tuple[str, dict[str, Any]]] = []

        # Determine which collection keys to search:
        # - Always search code/doc memory collections from config.collection_keys
        # - Optionally search conversation_memory if enabled AND user_id is known
        collections_to_search = self._collections_to_search(user_id, include_code_memory=include_code_memory)

        for collection_key in collections_to_search:
            if collection_key == "conversation_memory":
                filter_expr = self._build_conversation_filter_expression(
                    user_id=user_id,
                    workspace_scope=workspace_scope,
                )
            else:
                filter_expr = self._build_filter_expression(repo_id)

            raw_hits = self.milvus_store.search(
                collection_key=collection_key,
                generation=self.config.collection_generation,
                query_vectors=[query_vector],
                limit=max(self.config.max_results, 1),
                filter_expression=filter_expr,
                output_fields=self._output_fields_for_collection(collection_key),
            )
            for hit in self._flatten_hits(raw_hits):
                merged_hits.append((collection_key, hit))

        merged_hits.sort(key=lambda item: self._score_for_hit(item[1]))
        capped_hits = merged_hits[: max(self.config.max_results, 0)]
        return [
            self._normalize_block(collection_key=collection_key, hit=hit)
            for collection_key, hit in capped_hits
        ]

    def _record_provenance(
        self,
        *,
        request_id: str,
        session_id: str,
        repo_id: str,
        query_text: str,
        query_hash: str,
        blocks: Sequence[RetrievalBlock],
        latency_ms: float,
    ) -> None:
        try:
            self.memory_persistence.record_retrieval_provenance(
                request_id=request_id,
                session_id=session_id,
                repo_id=repo_id or None,
                retrieval_scope="workspace",
                query_text=query_text,
                selected_count=len(blocks),
                selected_refs_json=[block.payload_ref for block in blocks],
                rationale_json={
                    "query_hash": query_hash,
                    "collection_keys": list(self.config.collection_keys),
                    "latency_ms": round(latency_ms, 3),
                },
            )
        except Exception as error:
            logger_internal.warning("Failed to record retrieval provenance: %s", error)

    def _build_query(self, text: str) -> str:
        return " ".join((text or "").split())[:512]

    def _collections_to_search(self, user_id: str, *, include_code_memory: bool = True) -> list[str]:
        collections_to_search = [
            key for key in self.config.collection_keys
            if include_code_memory or key not in ("code_memory", "doc_memory")
        ]
        # Use the same __anonymous__ convention as record_turn so anonymous
        # deployments can read back the turns they just wrote.
        if (
            self.config.enable_conversation_memory
            and "conversation_memory" not in collections_to_search
        ):
            collections_to_search.append("conversation_memory")
        return collections_to_search

    def _build_filter_expression(self, repo_id: str) -> str:
        if not repo_id:
            return ""
        escaped = repo_id.replace('"', '\\"')
        return f'repo_id == "{escaped}"'

    def _output_fields_for_collection(self, collection_key: str) -> list[str]:
        if collection_key == "code_memory":
            return [
                "payload_ref",
                "relative_path",
                "summary",
                "symbol_name",
                "start_line",
                "end_line",
            ]
        if collection_key == "doc_memory":
            return [
                "payload_ref",
                "source_path",
                "summary",
                "section",
            ]
        if collection_key == "conversation_memory":
            return [
                "payload_ref",
                "user_id",
                "session_id",
                "workspace_scope",
                "turn_number",
                "user_message",
                "assistant_summary",
                "tool_names",
            ]
        if collection_key == "tool_cache":
            return ["payload_ref", "tool_name", "server_alias"]
        return ["payload_ref", "summary"]

    def _build_conversation_filter_expression(
        self, *, user_id: str, workspace_scope: str
    ) -> str:
        """Build a Milvus filter expression that scopes to same-user (and
        optionally same workspace), ensuring cross-user recall is impossible.

        Empty ``user_id`` maps to the ``__anonymous__`` scope so that anonymous
        single-user deployments can recall their own past turns.
        """
        effective_uid = user_id or "__anonymous__"
        escaped_uid = effective_uid.replace('"', '\\"')
        parts = [f'user_id == "{escaped_uid}"']
        if workspace_scope:
            escaped_ws = workspace_scope.replace('"', '\\"')
            parts.append(f'workspace_scope == "{escaped_ws}"')
        parts.append(f"expires_at > {int(time.time())}")
        return " && ".join(parts)

    def _flatten_hits(self, raw_hits: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_hits, list):
            return []
        flattened: list[dict[str, Any]] = []
        for item in raw_hits:
            if isinstance(item, list):
                for nested in item:
                    if isinstance(nested, dict):
                        flattened.append(nested)
            elif isinstance(item, dict):
                flattened.append(item)
        return flattened

    def _normalize_block(self, *, collection_key: str, hit: dict[str, Any]) -> RetrievalBlock:
        entity = hit.get("entity") if isinstance(hit, dict) else None
        payload_ref = self._field(hit, entity, "payload_ref") or self._field(hit, entity, "id") or ""
        source_path = (
            self._field(hit, entity, "relative_path")
            or self._field(hit, entity, "source_path")
            or ""
        )
        # For conversation memory, synthesize a source_path from session/turn info
        if collection_key == "conversation_memory" and not source_path:
            session_id = self._field(hit, entity, "session_id") or ""
            turn_number = self._field(hit, entity, "turn_number")
            source_path = f"conversation:{session_id}:turn-{turn_number}" if session_id else "conversation:unknown"
        summary = (
            self._field(hit, entity, "summary")
            or self._field(hit, entity, "assistant_summary")
            or ""
        )
        snippet = summary[:500]
        score = self._score_for_hit(hit)
        return RetrievalBlock(
            payload_ref=payload_ref,
            collection=collection_key,
            score=score,
            snippet=snippet,
            source_path=source_path,
        )

    def _field(self, hit: dict[str, Any], entity: Any, key: str) -> Any:
        if isinstance(hit, dict) and key in hit:
            return hit.get(key)
        if isinstance(entity, dict):
            return entity.get(key)
        return None

    def _score_for_hit(self, hit: dict[str, Any]) -> float:
        raw_score = hit.get("distance", hit.get("score", 0.0)) if isinstance(hit, dict) else 0.0
        try:
            return float(raw_score)
        except (TypeError, ValueError):
            return 0.0

    def _query_hash(self, query_text: str) -> str:
        return hashlib.sha256(query_text.encode("utf-8")).hexdigest()[:16]

    def _request_id(self) -> str:
        return f"retrieval-{uuid.uuid4()}"

    def _preview_text(self, value: Any, *, max_length: int = 120) -> str:
        text = str(value or "")
        if len(text) <= max_length:
            return text
        return f"{text[: max_length - 1]}…"

    def _build_params_hash(self, tool_name: str, arguments: dict) -> str:
        """Deterministic SHA-256 prefix over (tool_name, sorted-JSON arguments).

        Sorting keys guarantees the same hash regardless of dict insertion order.
        """
        import json as _json
        normalised = _json.dumps({"tool": tool_name, "args": arguments}, sort_keys=True)
        return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:32]

    def _build_cache_scope_hash(self, user_id: str, workspace_scope: str) -> str:
        """Deterministic SHA-256 prefix over (user_id, workspace_scope).

        An empty user_id is hashed as the literal string "__anonymous__" so that
        anonymous scopes are never accidentally merged with a real user.
        """
        effective_uid = user_id or "__anonymous__"
        raw = f"{effective_uid}|{workspace_scope}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
