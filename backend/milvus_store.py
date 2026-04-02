"""Milvus collection and vector-store abstraction for memory features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from pymilvus import DataType, MilvusClient


class MilvusStoreError(Exception):
    """Base error for Milvus store failures."""


class MilvusCollectionConfigError(MilvusStoreError):
    """Raised when collection configuration is invalid."""


@dataclass(frozen=True)
class CollectionFieldSpec:
    name: str
    datatype: Any
    kwargs: dict[str, Any]


@dataclass(frozen=True)
class CollectionSpec:
    collection_key: str
    vector_field: str
    metric_type: str
    fields: list[CollectionFieldSpec]


CODE_MEMORY_SPEC = CollectionSpec(
    collection_key="code_memory",
    vector_field="embedding",
    metric_type="COSINE",
    fields=[
        CollectionFieldSpec("id", DataType.VARCHAR, {"is_primary": True, "max_length": 128}),
        CollectionFieldSpec("embedding", DataType.FLOAT_VECTOR, {}),
        CollectionFieldSpec("repo_id", DataType.VARCHAR, {"max_length": 256}),
        CollectionFieldSpec("relative_path", DataType.VARCHAR, {"max_length": 1024}),
        CollectionFieldSpec("symbol_name", DataType.VARCHAR, {"max_length": 256}),
        CollectionFieldSpec("symbol_kind", DataType.VARCHAR, {"max_length": 64}),
        CollectionFieldSpec("language", DataType.VARCHAR, {"max_length": 32}),
        CollectionFieldSpec("namespace", DataType.VARCHAR, {"max_length": 512}),
        CollectionFieldSpec("signature", DataType.VARCHAR, {"max_length": 2048}),
        CollectionFieldSpec("summary", DataType.VARCHAR, {"max_length": 2048}),
        CollectionFieldSpec("payload_ref", DataType.VARCHAR, {"max_length": 256}),
        CollectionFieldSpec("source_hash", DataType.VARCHAR, {"max_length": 128}),
        CollectionFieldSpec("start_line", DataType.INT64, {}),
        CollectionFieldSpec("end_line", DataType.INT64, {}),
        CollectionFieldSpec("updated_at", DataType.INT64, {}),
    ],
)

DOC_MEMORY_SPEC = CollectionSpec(
    collection_key="doc_memory",
    vector_field="embedding",
    metric_type="COSINE",
    fields=[
        CollectionFieldSpec("id", DataType.VARCHAR, {"is_primary": True, "max_length": 128}),
        CollectionFieldSpec("embedding", DataType.FLOAT_VECTOR, {}),
        CollectionFieldSpec("repo_id", DataType.VARCHAR, {"max_length": 256}),
        CollectionFieldSpec("source_type", DataType.VARCHAR, {"max_length": 64}),
        CollectionFieldSpec("source_path", DataType.VARCHAR, {"max_length": 1024}),
        CollectionFieldSpec("section", DataType.VARCHAR, {"max_length": 256}),
        CollectionFieldSpec("summary", DataType.VARCHAR, {"max_length": 2048}),
        CollectionFieldSpec("payload_ref", DataType.VARCHAR, {"max_length": 256}),
        CollectionFieldSpec("source_hash", DataType.VARCHAR, {"max_length": 128}),
        CollectionFieldSpec("updated_at", DataType.INT64, {}),
    ],
)

CONVERSATION_MEMORY_SPEC = CollectionSpec(
    collection_key="conversation_memory",
    vector_field="embedding",
    metric_type="COSINE",
    fields=[
        CollectionFieldSpec("id", DataType.VARCHAR, {"is_primary": True, "max_length": 128}),
        CollectionFieldSpec("embedding", DataType.FLOAT_VECTOR, {}),
        CollectionFieldSpec("user_id", DataType.VARCHAR, {"max_length": 64}),
        CollectionFieldSpec("session_id", DataType.VARCHAR, {"max_length": 64}),
        CollectionFieldSpec("workspace_scope", DataType.VARCHAR, {"max_length": 256}),
        CollectionFieldSpec("turn_number", DataType.INT64, {}),
        CollectionFieldSpec("user_message", DataType.VARCHAR, {"max_length": 4096}),
        CollectionFieldSpec("assistant_summary", DataType.VARCHAR, {"max_length": 4096}),
        CollectionFieldSpec("tool_names", DataType.VARCHAR, {"max_length": 1024}),
        CollectionFieldSpec("payload_ref", DataType.VARCHAR, {"max_length": 256}),
        CollectionFieldSpec("created_at", DataType.INT64, {}),
        CollectionFieldSpec("expires_at", DataType.INT64, {}),
    ],
)

TOOL_CACHE_SPEC = CollectionSpec(
    collection_key="tool_cache",
    vector_field="embedding",
    metric_type="COSINE",
    fields=[
        CollectionFieldSpec("id", DataType.VARCHAR, {"is_primary": True, "max_length": 128}),
        CollectionFieldSpec("embedding", DataType.FLOAT_VECTOR, {}),
        CollectionFieldSpec("tool_name", DataType.VARCHAR, {"max_length": 256}),
        CollectionFieldSpec("server_alias", DataType.VARCHAR, {"max_length": 128}),
        CollectionFieldSpec("normalized_params_hash", DataType.VARCHAR, {"max_length": 128}),
        CollectionFieldSpec("scope_hash", DataType.VARCHAR, {"max_length": 128}),
        CollectionFieldSpec("payload_ref", DataType.VARCHAR, {"max_length": 256}),
        CollectionFieldSpec("created_at", DataType.INT64, {}),
        CollectionFieldSpec("expires_at", DataType.INT64, {}),
        CollectionFieldSpec("source_version", DataType.VARCHAR, {"max_length": 128}),
        CollectionFieldSpec("is_cacheable", DataType.BOOL, {}),
    ],
)

COLLECTION_SPECS = {
    spec.collection_key: spec
    for spec in [CODE_MEMORY_SPEC, DOC_MEMORY_SPEC, CONVERSATION_MEMORY_SPEC, TOOL_CACHE_SPEC]
}


class MilvusStore:
    """Encapsulates Milvus collection lifecycle and vector operations."""

    def __init__(
        self,
        *,
        milvus_uri: Optional[str] = None,
        collection_prefix: str = "mcp_client",
        client: Optional[Any] = None,
        client_factory: Optional[Callable[..., Any]] = None,
    ):
        if not client and not milvus_uri:
            raise MilvusCollectionConfigError("milvus_uri is required when client is not provided")
        self.collection_prefix = collection_prefix
        self._client_factory = client_factory or MilvusClient
        self.client = client or self._client_factory(uri=milvus_uri)

    def build_collection_name(self, collection_key: str, generation: str) -> str:
        if collection_key not in COLLECTION_SPECS:
            raise MilvusCollectionConfigError(f"Unsupported collection key: {collection_key}")
        if not generation:
            raise MilvusCollectionConfigError("generation is required")
        return f"{self.collection_prefix}_{collection_key}_{generation}"

    def ensure_collection(self, *, collection_key: str, generation: str, dimension: int) -> str:
        if dimension <= 0:
            raise MilvusCollectionConfigError("dimension must be positive")

        collection_name = self.build_collection_name(collection_key, generation)
        if self.client.has_collection(collection_name):
            return collection_name

        spec = COLLECTION_SPECS[collection_key]
        schema = self._build_schema(spec, dimension)
        index_params = self._build_index_params(spec)
        self.client.create_collection(
            collection_name=collection_name,
            dimension=dimension,
            primary_field_name="id",
            id_type="string",
            vector_field_name=spec.vector_field,
            metric_type=spec.metric_type,
            auto_id=False,
            schema=schema,
            index_params=index_params,
        )
        return collection_name

    def describe_collection(self, *, collection_key: str, generation: str) -> Any:
        collection_name = self.build_collection_name(collection_key, generation)
        return self.client.describe_collection(collection_name)

    def upsert(
        self,
        *,
        collection_key: str,
        generation: str,
        dimension: int,
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        collection_name = self.ensure_collection(
            collection_key=collection_key,
            generation=generation,
            dimension=dimension,
        )
        self._validate_records(records, dimension=dimension)
        return self.client.upsert(collection_name=collection_name, data=records)

    def search(
        self,
        *,
        collection_key: str,
        generation: str,
        query_vectors: list[list[float]],
        limit: int = 5,
        filter_expression: str = "",
        output_fields: Optional[list[str]] = None,
        search_params: Optional[dict[str, Any]] = None,
    ) -> list[list[dict[str, Any]]]:
        if not query_vectors:
            raise MilvusCollectionConfigError("query_vectors must not be empty")
        collection_name = self.build_collection_name(collection_key, generation)
        return self.client.search(
            collection_name=collection_name,
            data=query_vectors,
            filter=filter_expression,
            limit=limit,
            output_fields=output_fields,
            search_params=search_params or {"metric_type": COLLECTION_SPECS[collection_key].metric_type},
            anns_field=COLLECTION_SPECS[collection_key].vector_field,
        )

    def delete_by_ids(self, *, collection_key: str, generation: str, ids: list[str]) -> dict[str, int]:
        collection_name = self.build_collection_name(collection_key, generation)
        return self.client.delete(collection_name=collection_name, ids=ids)

    def delete_by_filter(self, *, collection_key: str, generation: str, filter_expression: str) -> dict[str, int]:
        if not filter_expression:
            raise MilvusCollectionConfigError("filter_expression is required")
        collection_name = self.build_collection_name(collection_key, generation)
        return self.client.delete(collection_name=collection_name, filter=filter_expression)

    def drop_collection(self, *, collection_key: str, generation: str) -> None:
        collection_name = self.build_collection_name(collection_key, generation)
        if self.client.has_collection(collection_name):
            self.client.drop_collection(collection_name)

    def list_collections(self) -> list[str]:
        return list(self.client.list_collections())

    def _build_schema(self, spec: CollectionSpec, dimension: int) -> Any:
        schema = self._client_factory.create_schema(auto_id=False, enable_dynamic_field=False)
        for field in spec.fields:
            kwargs = dict(field.kwargs)
            if field.name == spec.vector_field:
                kwargs["dim"] = dimension
            schema.add_field(field.name, field.datatype, **kwargs)
        return schema

    def _build_index_params(self, spec: CollectionSpec) -> Any:
        index_params = self._client_factory.prepare_index_params()
        index_params.add_index(
            field_name=spec.vector_field,
            index_name=f"{spec.collection_key}_{spec.vector_field}_idx",
            index_type="AUTOINDEX",
            metric_type=spec.metric_type,
        )
        return index_params

    def _validate_records(self, records: list[dict[str, Any]], *, dimension: int) -> None:
        if not records:
            raise MilvusCollectionConfigError("records must not be empty")
        for record in records:
            embedding = record.get("embedding")
            if not isinstance(embedding, list) or len(embedding) != dimension:
                raise MilvusCollectionConfigError(
                    f"record embedding must be a list with dimension {dimension}"
                )
            if not record.get("id"):
                raise MilvusCollectionConfigError("record id is required")
