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
- optional input schema validation via jsonschema
- local $ref resolution for #/$defs/... and #/definitions/...
- object properties / required
- primitive types
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
- JSON Schema validation keywords like minimum, maximum, pattern, format,
  dependentRequired, unevaluatedProperties, etc. are not preserved.
- oneOf is mapped to a structural union, not strict exclusivity.
- allOf is handled for object-like schemas; other compositions may degrade to Any.
- External refs are not fetched automatically.
"""

from __future__ import annotations

from copy import deepcopy
from json_schema2salad.models import ArrayType, EnumType, RecordField, RecordType, SaladDocument
from jsonpointer import JsonPointer
from pathlib import Path
from pydantic import AnyUrl, BaseModel
from typing import Any, Dict, List, Optional

import json
import re


PRIMITIVE_MAP = {
    "string": "string",
    "integer": "int",
    "number": "float",
    "boolean": "boolean",
    "null": "null",
}


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


def stable_key(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, BaseModel):
        return json.dumps(value.model_dump(mode="json", by_alias=True, exclude_none=True), sort_keys=True)
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


# ---------------------------------------------------------------------------
# Conversion context
# ---------------------------------------------------------------------------

class ConversionContext:
    def __init__(self, root_schema: Dict[str, Any]) -> None:
        self.root_schema = root_schema
        self.types: List[EnumType | RecordType] = []
        self.emitted_names: set[str] = set()
        self.ref_map: Dict[str, str] = {}
        self.warnings: List[str] = []

    def reserve_name(self, preferred: str) -> str:
        base = safe_name(preferred)
        if base not in self.emitted_names:
            self.emitted_names.add(base)
            return base
        i = 2
        while f"{base}{i}" in self.emitted_names:
            i += 1
        final_name = f"{base}{i}"
        self.emitted_names.add(final_name)
        return final_name

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


def ref_name_from_json_pointer(ref: str, ctx: ConversionContext) -> str:
    if ref not in ctx.ref_map:
        if not ref.startswith("#"):
            suggested = to_camel_case(ref)
        else:
            fragment = ref[1:]
            pointer = JsonPointer(fragment)
            parts = pointer.get_parts()
            suggested = to_camel_case("_".join(str(part) for part in parts)) if parts else "Root"

        ctx.ref_map[ref] = ctx.reserve_name(suggested)
    return ctx.ref_map[ref]


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


def materialize_allof_record(schema: Dict[str, Any], ctx: ConversionContext, record_name: str) -> str:
    branches = schema.get("allOf", [])
    ref_bases: List[str] = []
    inline_objects: List[Dict[str, Any]] = []
    descriptions: List[Optional[str]] = [schema_doc(schema)]

    for branch in branches:
        descriptions.append(schema_doc(branch))

        if "$ref" in branch:
            ref_name = ref_name_from_json_pointer(branch["$ref"], ctx)
            ref_bases.append(ref_name)
            continue

        if is_object_like(branch):
            if "allOf" in branch:
                nested_name = ctx.reserve_name(f"{record_name}_Base")
                materialize_allof_record(branch, ctx, nested_name)
                ref_bases.append(nested_name)
            else:
                inline_objects.append(branch)
            continue

        fallback = RecordType(
            name=record_name,
            doc=merge_descriptions(descriptions),
            fields=[RecordField(name="value", type="Any", doc="Lossy fallback for unsupported allOf branch composition.")],
        )
        ctx.add_type(fallback)
        ctx.warn(f"Unsupported non-object allOf branch under record {record_name}")
        return record_name

    merged_inline = merge_object_schemas(inline_objects) if inline_objects else {
        "type": "object",
        "properties": {},
        "required": [],
    }

    record = RecordType(
        name=record_name,
        doc=merge_descriptions(descriptions + [schema_doc(merged_inline)]),
        extends=ref_bases if len(ref_bases) > 1 else (ref_bases[0] if ref_bases else None),
        fields=[],
    )

    required_fields = set(merged_inline.get("required", []))
    for prop_name, prop_schema in merged_inline.get("properties", {}).items():
        record.fields.append(make_field(prop_name, prop_schema, prop_name in required_fields, ctx, record_name))

    ctx.add_type(record)
    return record_name


def convert_type(schema: Dict[str, Any], ctx: ConversionContext, parent_name: str, field_name: Optional[str] = None) -> Any:
    if "$ref" in schema:
        return ref_name_from_json_pointer(schema["$ref"], ctx)

    if "oneOf" in schema:
        return convert_union_variants(schema["oneOf"], ctx, parent_name, field_name)

    if "anyOf" in schema:
        return convert_union_variants(schema["anyOf"], ctx, parent_name, field_name)

    if "allOf" in schema:
        nested_name = ctx.reserve_name(f"{parent_name}_{field_name or 'Composed'}")
        materialize_allof_record(schema, ctx, nested_name)
        return nested_name

    if "enum" in schema:
        enum_name = ctx.reserve_name(f"{parent_name}_{field_name or 'Enum'}")
        ctx.add_type(EnumType(name=enum_name, symbols=[str(v) for v in schema["enum"]], doc=schema_doc(schema)))
        return enum_name

    schema_type = schema.get("type")

    if isinstance(schema_type, list):
        converted: List[Any] = []
        for t in schema_type:
            if isinstance(t, str) and t in PRIMITIVE_MAP:
                converted.append(PRIMITIVE_MAP[t])
            elif t == "object":
                nested_name = ctx.reserve_name(f"{parent_name}_{field_name or 'Nested'}")
                emit_record(schema, ctx, nested_name)
                converted.append(nested_name)
            elif t == "array":
                items = schema.get("items", {})
                converted.append(ArrayType(items=convert_type(items, ctx, parent_name, field_name)))
            else:
                converted.append("Any")
                ctx.warn(f"Unsupported type variant {t!r} under {parent_name}")
        return dedupe_types(converted)

    if schema_type in PRIMITIVE_MAP:
        return PRIMITIVE_MAP[schema_type]

    if schema_type == "array":
        items = schema.get("items", {})
        return ArrayType(items=convert_type(items, ctx, parent_name, field_name))

    if schema_type == "object" or "properties" in schema:
        nested_name = ctx.reserve_name(f"{parent_name}_{field_name or 'Nested'}")
        emit_record(schema, ctx, nested_name)
        return nested_name

    if schema_type is None:
        if "properties" in schema:
            nested_name = ctx.reserve_name(f"{parent_name}_{field_name or 'Nested'}")
            emit_record(schema, ctx, nested_name)
            return nested_name
        if "items" in schema:
            return ArrayType(items=convert_type(schema.get("items", {}), ctx, parent_name, field_name))

    return "Any"


def make_field(field_name: str, field_schema: Dict[str, Any], required: bool, ctx: ConversionContext, parent_name: str) -> RecordField:
    field_type = convert_type(field_schema, ctx, parent_name, field_name)
    if not required:
        union = ensure_union(field_type)
        field_type = dedupe_types(union if "null" in union else ["null"] + union)

    kwargs: dict[str, Any] = {
        "name": safe_name(field_name),
        "type": field_type,
        "doc": schema_doc(field_schema),
    }
    if "default" in field_schema:
        kwargs["default"] = field_schema["default"]
    return RecordField(**kwargs)


def emit_record(schema: Dict[str, Any], ctx: ConversionContext, record_name: str) -> None:
    if ctx.get_type(record_name):
        return

    if "allOf" in schema:
        materialize_allof_record(schema, ctx, record_name)
        return

    properties = schema.get("properties", {})
    required_fields = set(schema.get("required", []))

    record = RecordType(name=record_name, doc=schema_doc(schema), fields=[])
    for prop_name, prop_schema in properties.items():
        record.fields.append(make_field(prop_name, prop_schema, prop_name in required_fields, ctx, record_name))
    ctx.add_type(record)


def emit_defs(schema: Dict[str, Any], ctx: ConversionContext) -> None:
    for bucket_name, ref_prefix in (("$defs", "#/$defs/"), ("definitions", "#/definitions/")):
        defs = schema.get(bucket_name, {})
        for def_name, def_schema in defs.items():
            salad_name = ref_name_from_json_pointer(f"{ref_prefix}{def_name}", ctx)
            if def_schema.get("type") == "object" or "properties" in def_schema or "allOf" in def_schema:
                emit_record(def_schema, ctx, salad_name)
            elif "enum" in def_schema:
                ctx.add_type(EnumType(name=salad_name, symbols=[str(v) for v in def_schema["enum"]], doc=schema_doc(def_schema)))
            else:
                wrapped = {
                    "type": "object",
                    "properties": {"value": deepcopy(def_schema)},
                    "required": ["value"],
                    "description": def_schema.get("description", def_schema.get("title", f"Wrapped definition for {def_name}")),
                }
                emit_record(wrapped, ctx, salad_name)


def convert_json_schema_to_salad(schema: Dict[str, Any]) -> tuple[SaladDocument, List[str]]:
    ctx = ConversionContext(schema)
    emit_defs(schema, ctx)

    root_name = ctx.reserve_name(to_camel_case(schema.get("title", "Root")))
    if schema.get("type") == "object" or "properties" in schema or "allOf" in schema:
        emit_record(schema, ctx, root_name)
    else:
        wrapped_root = {
            "type": "object",
            "properties": {"value": deepcopy(schema)},
            "required": ["value"],
            "description": schema.get("description", schema.get("title", "Wrapped non-object root schema")),
        }
        emit_record(wrapped_root, ctx, root_name)

    doc = SaladDocument(
        **{
            "$base": "https://example.org/",
            "$namespaces": {"sld": "https://w3id.org/cwl/salad#"},
            "$graph": ctx.types,
            "$comment": ("Warnings: " + " | ".join(ctx.warnings)) if ctx.warnings else None,
        }
    )
    return doc, ctx.warnings
