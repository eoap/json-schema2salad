# Copyright 2026 Terradue
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

from dataclasses import dataclass
from httpx import Client
from json_schema2salad import (
    build_salad_document,
    convert_json_schema_to_salad_details,
    plan_conversion_names,
    ref_name_from_json_pointer,
)
from json_schema2salad.models import EnumType, RecordType, SaladDocument
from loguru import logger
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin, urlparse

import yaml


def httpx_json_loader(uri: str, **kwargs: object) -> object:
    with Client(follow_redirects=True) as client:
        response = client.get(uri)
        response.raise_for_status()

        headers = getattr(response, "headers", {})
        content_type = headers.get("Content-Type", "") if headers else ""
        if "application/json" in content_type:
            return response.json()

        return yaml.safe_load(response.text)


def document_uri(uri: str) -> str:
    return urldefrag(uri)[0]


def split_reference(uri: str) -> tuple[str, str]:
    doc_uri, fragment = urldefrag(uri)
    return doc_uri, f"#{fragment}" if fragment else ""


def normalize_source_uri(source: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https", "file"}:
        return source
    return str(Path(source).expanduser().resolve())


def source_uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    return Path(uri)


def resolve_reference_uri(base_uri: str, ref: str) -> str:
    base_doc_uri = document_uri(base_uri)
    if ref.startswith("#"):
        return f"{base_doc_uri}{ref}"

    ref_doc_uri, ref_fragment = split_reference(ref)
    parsed_ref = urlparse(ref_doc_uri)
    if parsed_ref.scheme in {"http", "https", "file"}:
        return ref

    parsed_base = urlparse(base_doc_uri)
    if parsed_base.scheme in {"http", "https", "file"}:
        return urljoin(base_doc_uri, ref)

    resolved_doc_uri = str((Path(base_doc_uri).parent / ref_doc_uri).resolve()) if ref_doc_uri else base_doc_uri
    return f"{resolved_doc_uri}{ref_fragment}"


def load_json_schema(uri: str) -> dict[str, object]:
    normalized_uri = normalize_source_uri(uri)
    parsed = urlparse(normalized_uri)

    if parsed.scheme in {"http", "https"}:
        loaded = httpx_json_loader(normalized_uri)
    else:
        schema_path = source_uri_to_path(normalized_uri)
        with schema_path.open(encoding="utf-8") as input_stream:
            loaded = yaml.safe_load(input_stream)

    if not isinstance(loaded, dict):
        raise TypeError(f"Resolved schema root must be a JSON object: {normalized_uri}")

    return loaded


def serialize_salad_document(document: SaladDocument, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output_stream:
        yaml.dump(document.as_salad(), output_stream, sort_keys=False)


def safe_output_stem(source_uri: str) -> str:
    parsed = urlparse(source_uri)
    if parsed.scheme in {"http", "https", "file"}:
        candidate = Path(unquote(parsed.path)).stem or parsed.netloc or "schema"
    else:
        candidate = Path(source_uri).stem or "schema"

    sanitized = "".join(char if char.isalnum() or char in "._-" else "_" for char in candidate).strip("._-")
    return sanitized or "schema"


def schema_name_hint_from_uri(source_uri: str) -> str:
    return safe_output_stem(source_uri)


@dataclass
class MergedSchema:
    source_uri: str
    root_name: str
    ref_map: dict[str, str]
    source_ref_map: dict[str, str]
    merged: bool = False


class InlineSchemaMerger:
    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path.resolve()
        self.merged_schemas: dict[str, MergedSchema] = {}
        self.reserved_type_names: set[str] = set()
        self.graph_types: list[EnumType | RecordType] = []
        self.type_index: dict[str, EnumType | RecordType] = {}
        self.type_source_index: dict[str, str] = {}
        self.source_ref_to_name: dict[str, str] = {}
        self.imported_schemas: dict[str, str] = {}
        self.warnings: list[str] = []

    def emit(self, sources: list[str]) -> SaladDocument:
        normalized_sources = [normalize_source_uri(source) for source in sources]

        for source in normalized_sources:
            self._merge_schema(source)

        document = build_salad_document(self.imported_schemas, self.graph_types, self.warnings)
        serialize_salad_document(document, self.output_path)
        return document

    def _merge_schema(self, source_uri: str) -> MergedSchema:
        normalized_source_uri = normalize_source_uri(source_uri)
        doc_uri = document_uri(normalized_source_uri)

        existing = self.merged_schemas.get(doc_uri)
        if existing is not None:
            logger.info(f"Schema {doc_uri} already merged into {self.output_path}")
            return existing

        schema = load_json_schema(doc_uri)
        plan = plan_conversion_names(
            schema,
            base_uri=doc_uri,
            root_name_hint=schema_name_hint_from_uri(doc_uri),
            reserved_names=self.reserved_type_names,
            source_ref_to_name=self.source_ref_to_name,
        )
        self.source_ref_to_name.update(plan.source_ref_map)
        self.reserved_type_names.update(plan.ref_map.values())
        self.reserved_type_names.add(plan.root_name)

        merged_schema = MergedSchema(
            source_uri=doc_uri,
            root_name=plan.root_name,
            ref_map=dict(plan.ref_map),
            source_ref_map=dict(plan.source_ref_map),
        )
        self.merged_schemas[doc_uri] = merged_schema

        logger.info(f"Schema {doc_uri} will be inlined into {self.output_path}")
        converted = convert_json_schema_to_salad_details(
            schema,
            base_uri=doc_uri,
            plan=plan,
            external_ref_handler=lambda ref, ctx, current_doc_uri=doc_uri: self._resolve_external_ref(
                ref,
                ctx,
                current_doc_uri,
            ),
            reserved_names=self.reserved_type_names,
        )

        merged_schema.root_name = converted.root_name
        merged_schema.ref_map = converted.ref_map
        merged_schema.source_ref_map = converted.source_ref_map
        merged_schema.merged = True

        self._merge_types(converted.document.graph)
        self._merge_imported_schemas(converted.imported_schemas)
        self.source_ref_to_name.update(converted.source_ref_map)
        self.reserved_type_names.update(converted.ref_map.values())
        self.reserved_type_names.add(converted.root_name)
        self.reserved_type_names.update(
            type_def.name
            for type_def in converted.document.graph
            if isinstance(type_def, (EnumType, RecordType))
        )
        self._record_warnings(doc_uri, converted.warnings)
        return merged_schema

    def _merge_imported_schemas(self, imported_schemas: dict[str, str]) -> None:
        for namespace, schema_uri in imported_schemas.items():
            if namespace in self.imported_schemas and self.imported_schemas[namespace] != schema_uri:
                raise ValueError(
                    f"External schema namespace {namespace!r} maps to both "
                    f"{self.imported_schemas[namespace]!r} and {schema_uri!r}."
                )
            self.imported_schemas[namespace] = schema_uri

    def _merge_types(self, types: list[object]) -> None:
        for type_def in types:
            if not isinstance(type_def, (EnumType, RecordType)):
                continue
            source_ref = type_def.json_ref_source
            if source_ref and source_ref in self.type_source_index:
                existing_name = self.type_source_index[source_ref]
                if existing_name != type_def.name:
                    self._warn_once(
                        f"Duplicate JSON reference source {source_ref!r} encountered as "
                        f"{type_def.name!r}; using existing type {existing_name!r}."
                    )
                continue

            existing = self.type_index.get(type_def.name)
            if existing is None:
                self.type_index[type_def.name] = type_def
                self.graph_types.append(type_def)
                if source_ref:
                    self.type_source_index[source_ref] = type_def.name
                    self.source_ref_to_name[source_ref] = type_def.name
                continue

            if existing.as_salad() != type_def.as_salad():
                self._warn_once(
                    f"Duplicate type name {type_def.name!r} encountered with differing definitions; keeping the first definition."
                )

    def _record_warnings(self, source_uri: str, warnings: list[str]) -> None:
        for warning in warnings:
            self._warn_once(f"{source_uri}: {warning}")

    def _warn_once(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def _resolve_external_ref(
        self,
        ref: str,
        ctx: object,
        current_doc_uri: str,
    ) -> str:
        resolved_ref = resolve_reference_uri(current_doc_uri, ref)
        ref_doc_uri, fragment = split_reference(resolved_ref)

        if ref_doc_uri == current_doc_uri:
            if not fragment:
                return self.merged_schemas[current_doc_uri].root_name
            return ref_name_from_json_pointer(fragment, ctx)

        logger.info(f"Schema inline requested by {current_doc_uri}: {resolved_ref}")
        merged_schema = self._merge_schema(ref_doc_uri)

        if not fragment:
            return merged_schema.root_name
        if fragment in merged_schema.ref_map:
            return merged_schema.ref_map[fragment]
        if resolved_ref in self.source_ref_to_name:
            return self.source_ref_to_name[resolved_ref]

        raise ValueError(
            f"Unsupported external reference fragment {fragment!r} in {resolved_ref}. "
            "Only document roots and top-level definitions are currently supported."
        )
