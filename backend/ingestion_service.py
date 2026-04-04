"""Code and documentation ingestion pipeline for Milvus-backed memory."""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from tree_sitter import Language, Parser
import tree_sitter_c as ts_c
import tree_sitter_cpp as ts_cpp

logger_internal = logging.getLogger("mcp_client.internal")
logger_external = logging.getLogger("mcp_client.external")

_C_LANGUAGE = Language(ts_c.language())
_CPP_LANGUAGE = Language(ts_cpp.language())

_CODE_EXTENSIONS = {".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp"}
_DOC_EXTENSIONS = {".md", ".txt", ".rst"}
_DEFAULT_EXCLUDED_DIRS = {".git", ".svn", ".hg", "node_modules", "venv", ".venv", "build", "dist", "out", "vendor", "__pycache__"}
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


@dataclass(frozen=True)
class IngestionChunk:
    chunk_id: str
    collection_key: str
    payload_ref: str
    payload_kind: str
    source_path: str
    relative_path: str
    payload_text: str
    summary: str
    source_hash: str
    metadata: dict[str, Any]
    store_record: dict[str, Any]


class IngestionService:
    """Scans code/doc roots, chunks content, and writes vectors plus sidecar records."""

    def __init__(
        self,
        *,
        embedding_service: Any,
        milvus_store: Any,
        memory_persistence: Any,
        repo_roots: Optional[list[str]] = None,
        doc_roots: Optional[list[str]] = None,
        collection_generation: str = "v1",
        collection_prefix: str = "mcp_client",
        excluded_dirs: Optional[set[str]] = None,
        max_chunk_chars: int = 2000,
    ):
        self.embedding_service = embedding_service
        self.milvus_store = milvus_store
        self.memory_persistence = memory_persistence
        self.repo_roots = [Path(root) for root in (repo_roots or [])]
        self.doc_roots = [Path(root) for root in (doc_roots or [])]
        self.collection_generation = collection_generation
        self.collection_prefix = collection_prefix
        self.excluded_dirs = set(excluded_dirs or _DEFAULT_EXCLUDED_DIRS)
        self.max_chunk_chars = max_chunk_chars

    def ingest_workspace(self, *, repo_id: str, requested_by_user_id: Optional[str] = None) -> dict[str, Any]:
        job = self.memory_persistence.create_ingestion_job(
            job_type="workspace_ingestion",
            status="running",
            repo_id=repo_id,
            requested_by_user_id=requested_by_user_id,
            scope_json={
                "repo_roots": [str(path) for path in self.repo_roots],
                "doc_roots": [str(path) for path in self.doc_roots],
            },
        )

        errors: list[str] = []
        all_chunks: list[IngestionChunk] = []
        source_count = 0

        for root in self.repo_roots:
            for path in self._iter_files(root, _CODE_EXTENSIONS.keys()):
                source_count += 1
                try:
                    all_chunks.extend(self._ingest_code_file(path=path, root=root, repo_id=repo_id))
                except Exception as error:
                    message = f"{path}: {error}"
                    logger_internal.warning("Ingestion code-file failure: %s", message)
                    errors.append(message)

        for root in self.doc_roots:
            for path in self._iter_files(root, _DOC_EXTENSIONS):
                source_count += 1
                try:
                    all_chunks.extend(self._ingest_doc_file(path=path, root=root, repo_id=repo_id))
                except Exception as error:
                    message = f"{path}: {error}"
                    logger_internal.warning("Ingestion doc-file failure: %s", message)
                    errors.append(message)

        chunk_count = len(all_chunks)
        current_refs_by_collection: dict[str, set[str]] = {}
        for chunk in all_chunks:
            current_refs_by_collection.setdefault(chunk.collection_key, set()).add(chunk.payload_ref)

        code_chunks = [chunk for chunk in all_chunks if chunk.collection_key == "code_memory"]
        doc_chunks = [chunk for chunk in all_chunks if chunk.collection_key == "doc_memory"]

        if code_chunks:
            self._store_chunks(code_chunks)
        if doc_chunks:
            self._store_chunks(doc_chunks)

        deleted_count = 0
        for collection_key in {"code_memory", "doc_memory"}:
            deleted_count += self._remove_stale_chunks(
                repo_id=repo_id,
                collection_key=collection_key,
                current_payload_refs=current_refs_by_collection.get(collection_key, set()),
            )

        status = "completed" if not errors else "completed_with_errors"
        updated_job = self.memory_persistence.update_ingestion_job(
            job.job_id,
            status=status,
            source_count=source_count,
            chunk_count=chunk_count,
            error_count=len(errors),
            error_summary="\n".join(errors[:10]) if errors else None,
            finished_at=self._now(),
        )

        return {
            "job_id": updated_job.job_id,
            "status": updated_job.status,
            "source_count": source_count,
            "chunk_count": chunk_count,
            "deleted_count": deleted_count,
            "error_count": len(errors),
            "errors": errors,
        }

    def _store_chunks(self, chunks: list[IngestionChunk]) -> None:
        texts = [chunk.summary for chunk in chunks]
        embeddings = self.embedding_service.embed_texts(texts) if not self._is_async_embedding() else None
        # Async embedding service from current implementation
        if embeddings is None:
            raise RuntimeError("Embedding service must be awaited; use ingest_workspace_async or inject sync-compatible test double")

    async def ingest_workspace_async(self, *, repo_id: str, requested_by_user_id: Optional[str] = None) -> dict[str, Any]:
        job = self.memory_persistence.create_ingestion_job(
            job_type="workspace_ingestion",
            status="running",
            repo_id=repo_id,
            requested_by_user_id=requested_by_user_id,
            scope_json={
                "repo_roots": [str(path) for path in self.repo_roots],
                "doc_roots": [str(path) for path in self.doc_roots],
            },
        )

        errors: list[str] = []
        all_chunks: list[IngestionChunk] = []
        source_count = 0

        for root in self.repo_roots:
            for path in self._iter_files(root, _CODE_EXTENSIONS.keys()):
                source_count += 1
                try:
                    all_chunks.extend(self._ingest_code_file(path=path, root=root, repo_id=repo_id))
                except Exception as error:
                    message = f"{path}: {error}"
                    logger_internal.warning("Ingestion code-file failure: %s", message)
                    errors.append(message)

        for root in self.doc_roots:
            for path in self._iter_files(root, _DOC_EXTENSIONS):
                source_count += 1
                try:
                    all_chunks.extend(self._ingest_doc_file(path=path, root=root, repo_id=repo_id))
                except Exception as error:
                    message = f"{path}: {error}"
                    logger_internal.warning("Ingestion doc-file failure: %s", message)
                    errors.append(message)

        chunk_count = len(all_chunks)
        current_refs_by_collection: dict[str, set[str]] = {}
        for chunk in all_chunks:
            current_refs_by_collection.setdefault(chunk.collection_key, set()).add(chunk.payload_ref)

        for collection_key in ("code_memory", "doc_memory"):
            selected = [chunk for chunk in all_chunks if chunk.collection_key == collection_key]
            if selected:
                await self._store_chunks_async(selected)

        deleted_count = 0
        for collection_key in {"code_memory", "doc_memory"}:
            deleted_count += self._remove_stale_chunks(
                repo_id=repo_id,
                collection_key=collection_key,
                current_payload_refs=current_refs_by_collection.get(collection_key, set()),
            )

        status = "completed" if not errors else "completed_with_errors"
        updated_job = self.memory_persistence.update_ingestion_job(
            job.job_id,
            status=status,
            source_count=source_count,
            chunk_count=chunk_count,
            error_count=len(errors),
            error_summary="\n".join(errors[:10]) if errors else None,
            finished_at=self._now(),
        )

        return {
            "job_id": updated_job.job_id,
            "status": updated_job.status,
            "source_count": source_count,
            "chunk_count": chunk_count,
            "deleted_count": deleted_count,
            "error_count": len(errors),
            "errors": errors,
        }

    async def _store_chunks_async(self, chunks: list[IngestionChunk]) -> None:
        collection_key = chunks[0].collection_key
        repo_ids = sorted({str(chunk.store_record.get("repo_id") or "<none>") for chunk in chunks})
        logger_external.info(
            "\n"
            "┌─── MILVUS INGESTION ─── %s START ───────────────────────────────────\n"
            "│  chunks     : %s\n"
            "│  repo_ids   : %s\n"
            "│  generation : %s\n"
            "└───────────────────────────────────────────────────────────────────────",
            collection_key,
            len(chunks),
            ", ".join(repo_ids),
            self.collection_generation,
        )
        embeddings = await self.embedding_service.embed_texts([chunk.summary for chunk in chunks])
        records = []
        for chunk, vector in zip(chunks, embeddings.vectors):
            record = dict(chunk.store_record)
            record["embedding"] = vector
            records.append(record)
            self.memory_persistence.upsert_payload_ref(
                payload_ref=chunk.payload_ref,
                payload_kind=chunk.payload_kind,
                payload_text=chunk.payload_text,
                memory_id=chunk.chunk_id,
                collection_key=chunk.collection_key,
                repo_id=record.get("repo_id"),
                relative_path=chunk.relative_path,
                source_path=chunk.source_path,
                source_type=chunk.metadata.get("source_type"),
                section=chunk.metadata.get("section"),
                symbol_name=chunk.metadata.get("symbol_name"),
                symbol_kind=chunk.metadata.get("symbol_kind"),
                language=chunk.metadata.get("language"),
                namespace=chunk.metadata.get("namespace"),
                signature=chunk.metadata.get("signature"),
                summary=chunk.summary,
                source_hash=chunk.source_hash,
                start_line=chunk.metadata.get("start_line"),
                end_line=chunk.metadata.get("end_line"),
                metadata_json=chunk.metadata,
            )

        self.milvus_store.upsert(
            collection_key=collection_key,
            generation=self.collection_generation,
            dimension=embeddings.dimensions,
            records=records,
        )
        logger_external.info(
            "\n"
            "┌─── MILVUS INGESTION ─── %s COMPLETE ────────────────────────────────\n"
            "│  chunks     : %s\n"
            "│  dimension  : %s\n"
            "│  repo_ids   : %s\n"
            "└───────────────────────────────────────────────────────────────────────",
            collection_key,
            len(records),
            embeddings.dimensions,
            ", ".join(repo_ids),
        )

    def _remove_stale_chunks(self, *, repo_id: str, collection_key: str, current_payload_refs: set[str]) -> int:
        existing_rows = self.memory_persistence.list_payload_refs(
            collection_key=collection_key,
            repo_id=repo_id,
        )
        stale_rows = [row for row in existing_rows if row.payload_ref not in current_payload_refs]
        if not stale_rows:
            return 0
        stale_ids = [row.memory_id for row in stale_rows if row.memory_id]
        if stale_ids:
            self.milvus_store.delete_by_ids(
                collection_key=collection_key,
                generation=self.collection_generation,
                ids=stale_ids,
            )
        self.memory_persistence.delete_payload_refs([row.payload_ref for row in stale_rows])
        return len(stale_rows)

    def _iter_files(self, root: Path, extensions: Iterable[str]) -> Iterable[Path]:
        if not root.exists():
            return []
        extension_set = {ext.lower() for ext in extensions}
        paths = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in self.excluded_dirs for part in path.parts):
                continue
            if path.suffix.lower() in extension_set:
                paths.append(path)
        return sorted(paths)

    def _ingest_code_file(self, *, path: Path, root: Path, repo_id: str) -> list[IngestionChunk]:
        text = path.read_text(encoding="utf-8")
        relative_path = str(path.relative_to(root))
        language = _CODE_EXTENSIONS[path.suffix.lower()]
        symbol_chunks = self._extract_code_chunks(text=text, relative_path=relative_path, repo_id=repo_id, language=language)
        return symbol_chunks or [self._build_fallback_code_chunk(text=text, relative_path=relative_path, repo_id=repo_id, language=language)]

    def _ingest_doc_file(self, *, path: Path, root: Path, repo_id: str) -> list[IngestionChunk]:
        text = path.read_text(encoding="utf-8")
        relative_path = str(path.relative_to(root))
        source_type = self._detect_doc_source_type(path)
        return self._extract_doc_chunks(text=text, relative_path=relative_path, repo_id=repo_id, source_type=source_type)

    def _extract_code_chunks(self, *, text: str, relative_path: str, repo_id: str, language: str) -> list[IngestionChunk]:
        parser = Parser(_C_LANGUAGE if language == "c" else _CPP_LANGUAGE)
        tree = parser.parse(text.encode("utf-8"))
        chunks: list[IngestionChunk] = []
        seen_ranges: set[tuple[int, int]] = set()
        for child in tree.root_node.children:
            if child.type not in {"function_definition", "declaration", "class_specifier", "struct_specifier", "enum_specifier", "namespace_definition"}:
                continue
            start_byte, end_byte = child.start_byte, child.end_byte
            if (start_byte, end_byte) in seen_ranges:
                continue
            seen_ranges.add((start_byte, end_byte))
            chunk_text = text.encode("utf-8")[start_byte:end_byte].decode("utf-8").strip()
            if not chunk_text:
                continue
            for chunk_text_part, start_line_offset in self._split_large_chunk(chunk_text, child.start_point[0] + 1):
                metadata = self._symbol_metadata(child=child, chunk_text=chunk_text_part, language=language)
                start_line = start_line_offset
                end_line = start_line + chunk_text_part.count("\n")
                symbol_name = metadata.get("symbol_name") or "anonymous"
                payload_ref = f"payload://code/{repo_id}/{relative_path}#{symbol_name}:{start_line}-{end_line}"
                chunk_id = self._stable_id(f"code::{repo_id}::{relative_path}::{symbol_name}::{start_line}::{end_line}")
                summary = self._summary_from_text(chunk_text_part)
                source_hash = self._stable_id(chunk_text_part)
                store_record = {
                    "id": chunk_id,
                    "repo_id": repo_id,
                    "relative_path": relative_path,
                    "symbol_name": symbol_name,
                    "symbol_kind": metadata.get("symbol_kind", "symbol"),
                    "language": language,
                    "namespace": metadata.get("namespace", ""),
                    "signature": metadata.get("signature", summary),
                    "summary": summary,
                    "payload_ref": payload_ref,
                    "source_hash": source_hash,
                    "start_line": start_line,
                    "end_line": end_line,
                    "updated_at": int(self._now().timestamp()),
                }
                chunks.append(
                    IngestionChunk(
                        chunk_id=chunk_id,
                        collection_key="code_memory",
                        payload_ref=payload_ref,
                        payload_kind="code_chunk",
                        source_path=relative_path,
                        relative_path=relative_path,
                        payload_text=chunk_text_part,
                        summary=summary,
                        source_hash=source_hash,
                        metadata={
                            "language": language,
                            "symbol_name": symbol_name,
                            "symbol_kind": metadata.get("symbol_kind", "symbol"),
                            "namespace": metadata.get("namespace"),
                            "signature": metadata.get("signature"),
                            "start_line": start_line,
                            "end_line": end_line,
                        },
                        store_record=store_record,
                    )
                )
        return chunks

    def _build_fallback_code_chunk(self, *, text: str, relative_path: str, repo_id: str, language: str) -> IngestionChunk:
        summary = self._summary_from_text(text)
        source_hash = self._stable_id(text)
        payload_ref = f"payload://code/{repo_id}/{relative_path}#file"
        chunk_id = self._stable_id(f"code::{repo_id}::{relative_path}::file")
        line_count = text.count("\n") + 1
        return IngestionChunk(
            chunk_id=chunk_id,
            collection_key="code_memory",
            payload_ref=payload_ref,
            payload_kind="code_chunk",
            source_path=relative_path,
            relative_path=relative_path,
            payload_text=text,
            summary=summary,
            source_hash=source_hash,
            metadata={
                "language": language,
                "symbol_name": Path(relative_path).name,
                "symbol_kind": "file",
                "start_line": 1,
                "end_line": line_count,
            },
            store_record={
                "id": chunk_id,
                "repo_id": repo_id,
                "relative_path": relative_path,
                "symbol_name": Path(relative_path).name,
                "symbol_kind": "file",
                "language": language,
                "namespace": "",
                "signature": summary,
                "summary": summary,
                "payload_ref": payload_ref,
                "source_hash": source_hash,
                "start_line": 1,
                "end_line": line_count,
                "updated_at": int(self._now().timestamp()),
            },
        )

    def _extract_doc_chunks(self, *, text: str, relative_path: str, repo_id: str, source_type: str) -> list[IngestionChunk]:
        lines = text.splitlines()
        sections: list[tuple[str, list[str]]] = []
        current_heading = "document"
        current_lines: list[str] = []
        for line in lines:
            heading_match = _HEADING_RE.match(line)
            if heading_match:
                if current_lines:
                    sections.append((current_heading, current_lines))
                current_heading = heading_match.group(2)
                current_lines = []
            else:
                current_lines.append(line)
        if current_lines or not sections:
            sections.append((current_heading, current_lines))

        chunks: list[IngestionChunk] = []
        for heading, section_lines in sections:
            chunk_text = "\n".join(section_lines).strip() or heading
            summary = self._summary_from_text(chunk_text)
            source_hash = self._stable_id(chunk_text)
            chunk_id = self._stable_id(f"doc::{repo_id}::{relative_path}::{heading}")
            payload_ref = f"payload://doc/{repo_id}/{relative_path}#{self._slug(heading)}"
            chunks.append(
                IngestionChunk(
                    chunk_id=chunk_id,
                    collection_key="doc_memory",
                    payload_ref=payload_ref,
                    payload_kind="doc_chunk",
                    source_path=relative_path,
                    relative_path=relative_path,
                    payload_text=chunk_text,
                    summary=summary,
                    source_hash=source_hash,
                    metadata={
                        "source_type": source_type,
                        "section": heading,
                    },
                    store_record={
                        "id": chunk_id,
                        "repo_id": repo_id,
                        "source_type": source_type,
                        "source_path": relative_path,
                        "section": heading,
                        "summary": summary,
                        "payload_ref": payload_ref,
                        "source_hash": source_hash,
                        "updated_at": int(self._now().timestamp()),
                    },
                )
            )
        return chunks

    def _detect_doc_source_type(self, path: Path) -> str:
        lowered = path.name.lower()
        if lowered.startswith("readme"):
            return "readme"
        if "requirement" in lowered:
            return "requirements"
        if "architecture" in lowered or "hld" in lowered:
            return "architecture"
        if "runbook" in lowered:
            return "runbook"
        if "guide" in lowered:
            return "guide"
        return "other"

    def _symbol_metadata(self, *, child: Any, chunk_text: str, language: str) -> dict[str, Any]:
        symbol_kind = {
            "function_definition": "function",
            "class_specifier": "class",
            "struct_specifier": "struct",
            "enum_specifier": "enum",
            "namespace_definition": "namespace",
            "declaration": "declaration",
        }.get(child.type, "symbol")
        symbol_name = self._find_identifier_text(child, chunk_text)
        signature = chunk_text.split("{", 1)[0].strip().splitlines()[0][:2048]
        return {
            "symbol_kind": symbol_kind,
            "symbol_name": symbol_name,
            "namespace": None,
            "signature": signature,
        }

    def _find_identifier_text(self, node: Any, chunk_text: str) -> str:
        target_types = {"identifier", "field_identifier", "type_identifier", "namespace_identifier"}
        found = self._find_descendant(node, target_types)
        if found is not None:
            try:
                return found.text.decode("utf-8")
            except Exception:
                pass
        fallback = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(|\{|:|$)", chunk_text)
        return fallback.group(1) if fallback else "anonymous"

    def _find_descendant(self, node: Any, target_types: set[str]) -> Optional[Any]:
        if node.type in target_types:
            return node
        for child in node.children:
            result = self._find_descendant(child, target_types)
            if result is not None:
                return result
        return None

    def _split_large_chunk(self, chunk_text: str, start_line: int) -> list[tuple[str, int]]:
        if len(chunk_text) <= self.max_chunk_chars:
            return [(chunk_text, start_line)]
        parts: list[tuple[str, int]] = []
        lines = chunk_text.splitlines()
        buffer: list[str] = []
        current_start = start_line
        current_length = 0
        line_number = start_line
        for line in lines:
            proposed = current_length + len(line) + 1
            if buffer and proposed > self.max_chunk_chars:
                parts.append(("\n".join(buffer), current_start))
                buffer = []
                current_start = line_number
                current_length = 0
            buffer.append(line)
            current_length += len(line) + 1
            line_number += 1
        if buffer:
            parts.append(("\n".join(buffer), current_start))
        return parts

    def _summary_from_text(self, text: str) -> str:
        normalized = " ".join(text.split())
        return normalized[:240]

    def _stable_id(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _slug(self, text: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
        return slug or "section"

    def _is_async_embedding(self) -> bool:
        return hasattr(self.embedding_service, "embed_texts")

    def _now(self):
        from datetime import datetime, timezone
        return datetime.now(timezone.utc)
