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
Pydantic v2 models for a pragmatic subset of Schema Salad.

These models are aimed at *authoring* and *serializing* Salad schema
documents from Python code without manually editing raw dictionaries.

Covered Salad concepts:
- top-level document with $namespaces / $graph
- graph-level $import directives
- primitive types
- named type references
- array types
- enum types
- record types
- union types (expressed as lists of types)
- record fields
- record inheritance via extends
- optional field documentation and defaults

This is intentionally a practical subset tailored to JSON Schema -> Salad
conversion and similar builder workflows.

Requires:
    pip install "pydantic>=2"
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing_extensions import TypeAliasType


PrimitiveType: TypeAlias = Literal[
    "null",
    "boolean",
    "int",
    "long",
    "float",
    "double",
    "string",
    "bytes",
]


class SaladModel(BaseModel):
    """
    Base model for all Salad structures.

    - extra='forbid' catches typos early
    - populate_by_name=True allows using both aliases and Python attribute names
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        validate_assignment=True,
    )

    def as_salad(self) -> dict[str, Any]:
        """Dump as a Salad-compatible dictionary, preserving aliases like '$graph'."""
        return self.model_dump(by_alias=True, exclude_none=True)


class SpecializeDef(SaladModel):
    """
    Schema Salad specialization entry.

    Example:
        specialize:
          - specializeFrom: BaseType
            specializeTo: ConcreteType
    """

    specialize_from: str = Field(alias="specializeFrom")
    specialize_to: str = Field(alias="specializeTo")


class ArrayType(SaladModel):
    type: Literal["array"] = "array"
    items: "TypeExpr"


class ImportDirective(SaladModel):
    import_: str = Field(alias="$import")


class EnumType(SaladModel):
    type: Literal["enum"] = "enum"
    name: str
    symbols: list[str]
    doc: str | None = None
    json_ref_source: str | None = Field(default=None, exclude=True)


class RecordField(SaladModel):
    name: str
    type_: "TypeExpr" = Field(alias="type")
    doc: str | None = None
    default: Any | None = None
    jsonld_predicate: str | dict[str, Any] | None = Field(default=None, alias="jsonldPredicate")

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field name must not be empty")
        return value

    @property
    def type(self) -> "TypeExpr":
        """Convenience access mirroring the Salad key name."""
        return self.type_


class RecordType(SaladModel):
    type: Literal["record"] = "record"
    name: str
    fields: list[RecordField] = Field(default_factory=list)
    doc: str | None = None
    abstract: bool | None = None
    extends: str | list[str] | None = None
    specialize: list[SpecializeDef] | None = None
    json_ref_source: str | None = Field(default=None, exclude=True)

    @field_validator("name")
    @classmethod
    def record_name_must_not_be_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("record name must not be empty")
        return value


NamedTypeRef: TypeAlias = Annotated[str, Field(min_length=1)]

# Recursive Salad type expression:
# - primitive type string like "string"
# - named type reference like "Person"
# - array type
# - enum type
# - record type
# - union type as a list of type expressions
TypeExpr = TypeAliasType(
    "TypeExpr",
    PrimitiveType
    | NamedTypeRef
    | ArrayType
    | EnumType
    | RecordType
    | list["TypeExpr"],
)


GraphEntry: TypeAlias = ImportDirective | EnumType | RecordType


class SaladDocument(SaladModel):
    """
    Top-level Schema Salad document.

    Example keys:
      $namespaces
      $graph
    """

    namespaces: dict[str, str] | None = Field(default=None, alias="$namespaces")
    graph: list[GraphEntry] = Field(default_factory=list, alias="$graph")
    comment: str | None = Field(default=None, alias="$comment")

    def add(self, *types: GraphEntry) -> "SaladDocument":
        self.graph.extend(types)
        return self


# Resolve recursive annotations for Pydantic v2
ArrayType.model_rebuild()
ImportDirective.model_rebuild()
EnumType.model_rebuild()
RecordField.model_rebuild()
RecordType.model_rebuild()
SaladDocument.model_rebuild()
