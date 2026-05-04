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

"""
Convert JSON Schema to a practical subset of Schema Salad using Pydantic v2.

Supported features:
- description/title -> doc fallback
- field and enum docs enriched with example values
- root type names can derive from source hints to avoid ambiguous generic names
- optional input schema validation via jsonschema
- local $ref resolution for #/$defs/... and #/definitions/...
- external $ref handling via caller-provided recursive resolvers
- object properties / required
- primitive types
- known string formats -> EOAP string_format Salad references
- nullable unions
- array.items
- enum
- oneOf -> SALAD union
- anyOf -> SALAD union
- allOf -> extends and/or flattened merged record
- $defs / definitions
- simple local $ref passthrough to emitted named types

Limitations:
- This is not a full semantic-preserving converter.
- JSON Schema validation keywords like minimum, maximum, pattern,
  dependentRequired, unevaluatedProperties, etc. are not preserved.
- oneOf is mapped to a structural union, not strict exclusivity.
- allOf is handled for object-like schemas; other compositions may degrade to Any.
- External refs are only materialized when the caller provides a resolver.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field as dataclass_field
from json_schema2salad.models import (
    ArrayType,
    EnumType,
    ImportDirective,
    RecordField,
    RecordType,
    SaladDocument,
)
from pathlib import PurePosixPath
from pydantic import BaseModel
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import unquote, urldefrag, urlparse

import json
import re


PRIMITIVE_MAP = {
    "string": "string",
    "integer": "int",
    "number": "float",
    "boolean": "boolean",
    "null": "null",
}

STRING_FORMAT_SCHEMA_URI = (
    "https://raw.githubusercontent.com/eoap/schemas/refs/heads/main/string_format.yaml"
)

SALAD_NAMESPACE_URI = "https://w3id.org/cwl/salad#"

STRING_FORMAT_RECORDS = {
    "date": "Date",
    "date-time": "DateTime",
    "duration": "Duration",
    "email": "Email",
    "hostname": "Hostname",
    "idn-email": "IDNEmail",
    "idn-hostname": "IDNHostname",
    "ipv4": "IPv4",
    "ipv6": "IPv6",
    "iri": "IRI",
    "iri-reference": "IRIReference",
    "json-pointer": "JsonPointer",
    "password": "Password",
    "relative-json-pointer": "RelativeJsonPointer",
    "uuid": "UUID",
    "uri": "URI",
    "uri-reference": "URIReference",
    "uri-template": "URITemplate",
    "time": "Time",
}

GENERIC_ROOT_TITLES = {"root"}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def to_camel_case(name: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", name)
    parts = [p for p in parts if p]
    if not parts:
        return "GeneratedType"
    return "".join(p[:1].upper() + p[1:] for p in parts)


def safe_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not name:
        name = "field"
    if name[0].isdigit():
        name = "_" + name
    return name


def external_schema_document_uri(schema_uri: str) -> str:
    doc_uri, _ = urldefrag(schema_uri)
    return doc_uri or schema_uri


def external_schema_namespace(schema_uri: str) -> str:
    doc_uri = external_schema_document_uri(schema_uri)
    parsed = urlparse(doc_uri)
    if parsed.path:
        candidate = PurePosixPath(unquote(parsed.path)).stem
    else:
        candidate = parsed.netloc or doc_uri
    return safe_name(candidate or "schema")


def external_schema_namespace_uri(schema_uri: str) -> str:
    return f"{external_schema_document_uri(schema_uri)}#"


def register_external_schema_import(
    imported_schemas: dict[str, str], schema_uri: str
) -> str:
    doc_uri = external_schema_document_uri(schema_uri)
    for namespace, imported_uri in imported_schemas.items():
        if imported_uri == doc_uri:
            return namespace

    base_namespace = external_schema_namespace(doc_uri)
    namespace = base_namespace
    suffix = 2
    while namespace in imported_schemas:
        namespace = f"{base_namespace}_{suffix}"
        suffix += 1
    imported_schemas[namespace] = doc_uri
    return namespace


def build_salad_document(
    imported_schemas: dict[str, str],
    graph_types: list[EnumType | RecordType],
    warnings: list[str],
) -> SaladDocument:
    namespaces = {"sld": SALAD_NAMESPACE_URI}
    namespaces.update(
        {
            namespace: external_schema_namespace_uri(schema_uri)
            for namespace, schema_uri in sorted(imported_schemas.items())
        }
    )
    imports = [
        ImportDirective(**{"$import": schema_uri})
        for _, schema_uri in sorted(imported_schemas.items())
    ]
    return SaladDocument(
        **{
            "$namespaces": namespaces,
            "$graph": imports + graph_types,
            "$comment": ("Warnings: " + " | ".join(warnings)) if warnings else None,
        }
    )


def stable_key(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, BaseModel):
        return json.dumps(
            value.model_dump(mode="json", by_alias=True, exclude_none=True),
            sort_keys=True,
        )
    return str(value)


def dedupe_types(values: List[Any]) -> List[Any]:
    out: List[Any] = []
    seen = set()
    for v in values:
        k = stable_key(v)
        if k not in seen:
            seen.add(k)
            out.append(v)
    return out


def ensure_union(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return [value]


def schema_doc(schema: Dict[str, Any]) -> Optional[str]:
    description = schema.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()

    title = schema.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()

    return None


def schema_example_text(schema: Dict[str, Any]) -> Optional[str]:
    if "example" not in schema:
        return None

    example = schema["example"]
    if example is None:
        return None

    if isinstance(example, str):
        example_text = example.strip()
        return example_text or None

    try:
        return json.dumps(example, sort_keys=True)
    except TypeError:
        return str(example)


def schema_doc_with_example(schema: Dict[str, Any]) -> Optional[str]:
    description = schema.get("description")
    if isinstance(description, str) and description.strip():
        example_text = schema_example_text(schema)
        if example_text:
            return f"{description.strip()}\n\nExample: {example_text}"
        return description.strip()

    example_text = schema_example_text(schema)
    if example_text:
        return f"Example: {example_text}"

    title = schema.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()

    return None


def string_format_type(schema: Dict[str, Any], ctx: "ConversionContext") -> str:
    format_name = schema.get("format")
    if isinstance(format_name, str):
        record_name = STRING_FORMAT_RECORDS.get(format_name)
        if record_name:
            namespace = ctx.import_schema(STRING_FORMAT_SCHEMA_URI)
            return f"{namespace}:{record_name}"
    return PRIMITIVE_MAP["string"]


def primitive_type_to_salad(
    json_type: str, schema: Dict[str, Any], ctx: "ConversionContext"
) -> str:
    if json_type == "string":
        return string_format_type(schema, ctx)
    return PRIMITIVE_MAP[json_type]


def schema_title_name(schema: Dict[str, Any]) -> Optional[str]:
    title = schema.get("title")
    if isinstance(title, str) and title.strip():
        return safe_name(title.strip())
    return None


def preferred_record_name(schema: Dict[str, Any], fallback: str) -> str:
    return schema_title_name(schema) or fallback


def inline_record_identity_key(schema: Dict[str, Any]) -> str | None:
    title_name = schema_title_name(schema)
    if not title_name:
        return None
    return stable_key(schema)


def preferred_root_name(
    schema: Dict[str, Any], root_name_hint: str | None = None
) -> str:
    title_name = schema_title_name(schema)
    if title_name:
        if title_name.lower() not in GENERIC_ROOT_TITLES:
            return title_name
        if root_name_hint:
            return to_camel_case(root_name_hint)
        return title_name

    if root_name_hint:
        return to_camel_case(root_name_hint)

    return "Root"


def is_object_like(schema: Dict[str, Any]) -> bool:
    if "$ref" in schema:
        return True
    if schema.get("type") == "object":
        return True
    if "properties" in schema:
        return True
    if "allOf" in schema:
        return True
    return False


def merge_descriptions(parts: List[Optional[str]]) -> Optional[str]:
    clean = [p.strip() for p in parts if p and p.strip()]
    if not clean:
        return None
    return "\n\n".join(dict.fromkeys(clean))


def json_pointer_parts(fragment: str) -> List[str]:
    if not fragment:
        return []
    if not fragment.startswith("/"):
        raise ValueError(f"Unsupported JSON Pointer fragment: {fragment!r}")
    return [
        part.replace("~1", "/").replace("~0", "~") for part in fragment[1:].split("/")
    ]


# ---------------------------------------------------------------------------
# Conversion context
# ---------------------------------------------------------------------------


class ConversionContext:
    def __init__(
        self,
        root_schema: Dict[str, Any],
        *,
        base_uri: str | None = None,
        external_ref_handler: Callable[[str, "ConversionContext"], str] | None = None,
        reserved_names: set[str] | None = None,
        source_ref_to_name: dict[str, str] | None = None,
    ) -> None:
        self.root_schema = root_schema
        self.base_uri = base_uri
        self.external_ref_handler = external_ref_handler
        self.types: List[EnumType | RecordType] = []
        self.emitted_names: set[str] = set(reserved_names or set())
        self.ref_map: Dict[str, str] = {}
        self.source_ref_to_name: dict[str, str] = dict(source_ref_to_name or {})
        self.inline_record_key_to_name: dict[str, str] = {}
        self.imported_schemas: dict[str, str] = {}
        self.warnings: List[str] = []

    def json_ref_source(self, ref: str | None = None) -> str | None:
        if self.base_uri is None:
            return None
        if not ref:
            return self.base_uri
        if ref.startswith("#"):
            return f"{self.base_uri}{ref}"
        return ref

    def reserve_name(self, preferred: str, source_ref: str | None = None) -> str:
        if source_ref and source_ref in self.source_ref_to_name:
            existing_name = self.source_ref_to_name[source_ref]
            self.emitted_names.add(existing_name)
            return existing_name

        base = safe_name(preferred)
        if base not in self.emitted_names:
            self.emitted_names.add(base)
            if source_ref:
                self.source_ref_to_name[source_ref] = base
            return base
        i = 2
        while f"{base}{i}" in self.emitted_names:
            i += 1
        final_name = f"{base}{i}"
        self.emitted_names.add(final_name)
        if source_ref:
            self.source_ref_to_name[source_ref] = final_name
        return final_name

    def reserve_record_name(
        self,
        schema: Dict[str, Any],
        fallback: str,
        source_ref: str | None = None,
    ) -> str:
        inline_key = None if source_ref else inline_record_identity_key(schema)
        if inline_key and inline_key in self.inline_record_key_to_name:
            existing_name = self.inline_record_key_to_name[inline_key]
            self.emitted_names.add(existing_name)
            return existing_name

        record_name = self.reserve_name(
            preferred_record_name(schema, fallback), source_ref=source_ref
        )
        if inline_key:
            self.inline_record_key_to_name[inline_key] = record_name
        return record_name

    def add_type(self, type_def: EnumType | RecordType) -> None:
        if self.get_type(type_def.name) is None:
            self.types.append(type_def)

    def get_type(self, name: str) -> Optional[EnumType | RecordType]:
        for t in self.types:
            if t.name == name:
                return t
        return None

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def import_schema(self, schema_uri: str) -> str:
        return register_external_schema_import(self.imported_schemas, schema_uri)


@dataclass(frozen=True)
class ConversionPlan:
    root_name: str
    ref_map: Dict[str, str]
    source_ref_map: Dict[str, str]


@dataclass(frozen=True)
class ConvertedSchema:
    document: SaladDocument
    warnings: List[str]
    root_name: str
    ref_map: Dict[str, str]
    source_ref_map: Dict[str, str]
    imported_schemas: dict[str, str] = dataclass_field(default_factory=dict)


def ref_name_from_json_pointer(ref: str, ctx: ConversionContext) -> str:
    if ref not in ctx.ref_map:
        source_ref = ctx.json_ref_source(ref)
        ctx.ref_map[ref] = ctx.reserve_name(
            suggested_name_from_ref(ref), source_ref=source_ref
        )
    return ctx.ref_map[ref]


def suggested_name_from_ref(ref: str) -> str:
    if not ref.startswith("#"):
        return to_camel_case(ref)

    fragment = ref[1:]
    parts = json_pointer_parts(fragment)
    return to_camel_case("_".join(str(part) for part in parts)) if parts else "Root"


def predeclare_defs(schema: Dict[str, Any], ctx: ConversionContext) -> None:
    for bucket_name, ref_prefix in (
        ("$defs", "#/$defs/"),
        ("definitions", "#/definitions/"),
    ):
        defs = schema.get(bucket_name, {})
        for def_name, def_schema in defs.items():
            ref = f"{ref_prefix}{def_name}"
            source_ref = ctx.json_ref_source(ref)
            if is_object_like(def_schema):
                ctx.ref_map[ref] = ctx.reserve_name(
                    preferred_record_name(def_schema, suggested_name_from_ref(ref)),
                    source_ref=source_ref,
                )
            else:
                ref_name_from_json_pointer(ref, ctx)


def plan_conversion_names(
    schema: Dict[str, Any],
    *,
    base_uri: str | None = None,
    root_name_hint: str | None = None,
    reserved_names: set[str] | None = None,
    source_ref_to_name: dict[str, str] | None = None,
) -> ConversionPlan:
    ctx = ConversionContext(
        schema,
        base_uri=base_uri,
        reserved_names=reserved_names,
        source_ref_to_name=source_ref_to_name,
    )
    predeclare_defs(schema, ctx)
    root_name = ctx.reserve_name(
        preferred_root_name(schema, root_name_hint),
        source_ref=ctx.json_ref_source(),
    )
    return ConversionPlan(
        root_name=root_name,
        ref_map=dict(ctx.ref_map),
        source_ref_map=dict(ctx.source_ref_to_name),
    )


def resolve_ref_name(ref: str, ctx: ConversionContext) -> str:
    if ref.startswith("#"):
        return ref_name_from_json_pointer(ref, ctx)
    if ctx.external_ref_handler is not None:
        return ctx.external_ref_handler(ref, ctx)
    return ref_name_from_json_pointer(ref, ctx)


def convert_union_variants(
    variants: List[Dict[str, Any]],
    ctx: ConversionContext,
    parent_name: str,
    field_name: Optional[str] = None,
) -> List[Any]:
    converted: List[Any] = []
    for i, variant in enumerate(variants, start=1):
        branch_name = f"{parent_name}_{field_name or 'Variant'}{i}"
        branch_type = convert_type(variant, ctx, branch_name, field_name)
        if isinstance(branch_type, list):
            converted.extend(branch_type)
        else:
            converted.append(branch_type)
    return dedupe_types(converted)


def merge_object_schemas(schemas: List[Dict[str, Any]]) -> Dict[str, Any]:
    merged_properties: Dict[str, Dict[str, Any]] = {}
    merged_required: List[str] = []
    descriptions: List[Optional[str]] = []

    for schema in schemas:
        descriptions.append(schema_doc(schema))
        for prop_name, prop_schema in schema.get("properties", {}).items():
            if prop_name in merged_properties:
                prev = merged_properties[prop_name]
                if stable_key(prev) != stable_key(prop_schema):
                    merged_properties[prop_name] = {"oneOf": [prev, prop_schema]}
            else:
                merged_properties[prop_name] = deepcopy(prop_schema)

        for req in schema.get("required", []):
            if req not in merged_required:
                merged_required.append(req)

    merged: Dict[str, Any] = {
        "type": "object",
        "properties": merged_properties,
        "required": merged_required,
    }
    doc = merge_descriptions(descriptions)
    if doc:
        merged["description"] = doc
    return merged


def materialize_allof_record(
    schema: Dict[str, Any],
    ctx: ConversionContext,
    record_name: str,
    source_ref: str | None = None,
) -> str:
    branches = schema.get("allOf", [])
    ref_bases: List[str] = []
    inline_objects: List[Dict[str, Any]] = []
    descriptions: List[Optional[str]] = [schema_doc(schema)]

    for branch in branches:
        descriptions.append(schema_doc(branch))

        if "$ref" in branch:
            ref_name = resolve_ref_name(branch["$ref"], ctx)
            ref_bases.append(ref_name)
            continue

        if is_object_like(branch):
            if "allOf" in branch:
                nested_name = ctx.reserve_record_name(branch, f"{record_name}_Base")
                materialize_allof_record(branch, ctx, nested_name)
                ref_bases.append(nested_name)
            else:
                inline_objects.append(branch)
            continue

        fallback = RecordType(
            name=record_name,
            json_ref_source=source_ref,
            doc=merge_descriptions(descriptions),
            fields=[
                RecordField(
                    name="value",
                    type="Any",
                    doc="Lossy fallback for unsupported allOf branch composition.",
                )
            ],
        )
        ctx.add_type(fallback)
        ctx.warn(f"Unsupported non-object allOf branch under record {record_name}")
        return record_name

    merged_inline = (
        merge_object_schemas(inline_objects)
        if inline_objects
        else {
            "type": "object",
            "properties": {},
            "required": [],
        }
    )

    record = RecordType(
        name=record_name,
        json_ref_source=source_ref,
        doc=merge_descriptions(descriptions + [schema_doc(merged_inline)]),
        extends=ref_bases
        if len(ref_bases) > 1
        else (ref_bases[0] if ref_bases else None),
        fields=[],
    )

    required_fields = set(merged_inline.get("required", []))
    for prop_name, prop_schema in merged_inline.get("properties", {}).items():
        record.fields.append(
            make_field(
                prop_name, prop_schema, prop_name in required_fields, ctx, record_name
            )
        )

    ctx.add_type(record)
    return record_name


def convert_type(
    schema: Dict[str, Any],
    ctx: ConversionContext,
    parent_name: str,
    field_name: Optional[str] = None,
) -> Any:
    if "$ref" in schema:
        return resolve_ref_name(schema["$ref"], ctx)

    if "oneOf" in schema:
        return convert_union_variants(schema["oneOf"], ctx, parent_name, field_name)

    if "anyOf" in schema:
        return convert_union_variants(schema["anyOf"], ctx, parent_name, field_name)

    if "allOf" in schema:
        nested_name = ctx.reserve_record_name(
            schema, f"{parent_name}_{field_name or 'Composed'}"
        )
        materialize_allof_record(schema, ctx, nested_name)
        return nested_name

    if "enum" in schema:
        enum_name = ctx.reserve_name(f"{parent_name}_{field_name or 'Enum'}")
        ctx.add_type(
            EnumType(
                name=enum_name,
                symbols=[str(v) for v in schema["enum"]],
                doc=schema_doc_with_example(schema),
            )
        )
        return enum_name

    schema_type = schema.get("type")

    if isinstance(schema_type, list):
        converted: List[Any] = []
        for t in schema_type:
            if isinstance(t, str) and t in PRIMITIVE_MAP:
                converted.append(primitive_type_to_salad(t, schema, ctx))
            elif t == "object":
                nested_name = ctx.reserve_record_name(
                    schema, f"{parent_name}_{field_name or 'Nested'}"
                )
                emit_record(schema, ctx, nested_name)
                converted.append(nested_name)
            elif t == "array":
                items = schema.get("items", {})
                converted.append(
                    ArrayType(items=convert_type(items, ctx, parent_name, field_name))
                )
            else:
                converted.append("Any")
                ctx.warn(f"Unsupported type variant {t!r} under {parent_name}")
        return dedupe_types(converted)

    if schema_type in PRIMITIVE_MAP:
        return primitive_type_to_salad(schema_type, schema, ctx)

    if schema_type == "array":
        items = schema.get("items", {})
        return ArrayType(items=convert_type(items, ctx, parent_name, field_name))

    if schema_type == "object" or "properties" in schema:
        nested_name = ctx.reserve_record_name(
            schema, f"{parent_name}_{field_name or 'Nested'}"
        )
        emit_record(schema, ctx, nested_name)
        return nested_name

    if schema_type is None:
        if "properties" in schema:
            nested_name = ctx.reserve_record_name(
                schema, f"{parent_name}_{field_name or 'Nested'}"
            )
            emit_record(schema, ctx, nested_name)
            return nested_name
        if "items" in schema:
            return ArrayType(
                items=convert_type(
                    schema.get("items", {}), ctx, parent_name, field_name
                )
            )

    return "Any"


def make_field(
    field_name: str,
    field_schema: Dict[str, Any],
    required: bool,
    ctx: ConversionContext,
    parent_name: str,
) -> RecordField:
    field_type = convert_type(field_schema, ctx, parent_name, field_name)
    if not required:
        union = ensure_union(field_type)
        field_type = dedupe_types(union if "null" in union else ["null"] + union)

    kwargs: dict[str, Any] = {
        "name": safe_name(field_name),
        "type": field_type,
        "doc": schema_doc_with_example(field_schema),
    }
    if "default" in field_schema:
        kwargs["default"] = field_schema["default"]
    return RecordField(**kwargs)


def emit_record(
    schema: Dict[str, Any],
    ctx: ConversionContext,
    record_name: str,
    source_ref: str | None = None,
) -> None:
    if ctx.get_type(record_name):
        return

    if "allOf" in schema:
        materialize_allof_record(schema, ctx, record_name, source_ref=source_ref)
        return

    properties = schema.get("properties", {})
    required_fields = set(schema.get("required", []))

    record = RecordType(
        name=record_name, json_ref_source=source_ref, doc=schema_doc(schema), fields=[]
    )
    for prop_name, prop_schema in properties.items():
        record.fields.append(
            make_field(
                prop_name, prop_schema, prop_name in required_fields, ctx, record_name
            )
        )
    ctx.add_type(record)


def emit_defs(schema: Dict[str, Any], ctx: ConversionContext) -> None:
    for bucket_name, ref_prefix in (
        ("$defs", "#/$defs/"),
        ("definitions", "#/definitions/"),
    ):
        defs = schema.get(bucket_name, {})
        for def_name, def_schema in defs.items():
            ref = f"{ref_prefix}{def_name}"
            source_ref = ctx.json_ref_source(ref)
            salad_name = ref_name_from_json_pointer(ref, ctx)
            if (
                def_schema.get("type") == "object"
                or "properties" in def_schema
                or "allOf" in def_schema
            ):
                emit_record(def_schema, ctx, salad_name, source_ref=source_ref)
            elif "enum" in def_schema:
                ctx.add_type(
                    EnumType(
                        name=salad_name,
                        symbols=[str(v) for v in def_schema["enum"]],
                        doc=schema_doc_with_example(def_schema),
                        json_ref_source=source_ref,
                    )
                )
            else:
                wrapped = {
                    "type": "object",
                    "properties": {"value": deepcopy(def_schema)},
                    "required": ["value"],
                    "description": def_schema.get(
                        "description",
                        def_schema.get("title", f"Wrapped definition for {def_name}"),
                    ),
                }
                emit_record(wrapped, ctx, salad_name, source_ref=source_ref)


def convert_json_schema_to_salad(
    schema: Dict[str, Any],
) -> tuple[SaladDocument, List[str]]:
    converted = convert_json_schema_to_salad_details(schema)
    return converted.document, converted.warnings


def convert_json_schema_to_salad_details(
    schema: Dict[str, Any],
    *,
    base_uri: str | None = None,
    external_ref_handler: Callable[[str, ConversionContext], str] | None = None,
    plan: ConversionPlan | None = None,
    reserved_names: set[str] | None = None,
    source_ref_to_name: dict[str, str] | None = None,
) -> ConvertedSchema:
    active_plan = plan or plan_conversion_names(
        schema,
        base_uri=base_uri,
        reserved_names=reserved_names,
        source_ref_to_name=source_ref_to_name,
    )
    ctx = ConversionContext(
        schema,
        base_uri=base_uri,
        external_ref_handler=external_ref_handler,
        reserved_names=reserved_names,
        source_ref_to_name=active_plan.source_ref_map,
    )
    ctx.ref_map.update(active_plan.ref_map)
    ctx.emitted_names.update(active_plan.ref_map.values())
    ctx.emitted_names.add(active_plan.root_name)

    emit_defs(schema, ctx)

    if schema.get("type") == "object" or "properties" in schema or "allOf" in schema:
        emit_record(
            schema, ctx, active_plan.root_name, source_ref=ctx.json_ref_source()
        )
    else:
        wrapped_root = {
            "type": "object",
            "properties": {"value": deepcopy(schema)},
            "required": ["value"],
            "description": schema.get(
                "description", schema.get("title", "Wrapped non-object root schema")
            ),
        }
        emit_record(
            wrapped_root, ctx, active_plan.root_name, source_ref=ctx.json_ref_source()
        )

    document = build_salad_document(ctx.imported_schemas, ctx.types, ctx.warnings)
    return ConvertedSchema(
        document=document,
        warnings=ctx.warnings,
        root_name=active_plan.root_name,
        ref_map=dict(ctx.ref_map),
        source_ref_map=dict(ctx.source_ref_to_name),
        imported_schemas=dict(ctx.imported_schemas),
    )
