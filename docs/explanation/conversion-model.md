# Conversion model and scope

`json-schema2salad` is an ongoing work in progress for translating JSON Schema
documents into Schema Salad documents.

The project is intentionally small, explicit, and evolving. It does not try to
be a complete semantic mirror of every JSON Schema keyword. Instead, it focuses
on producing useful Salad schema documents from the common structural features
that appear in EOAP-style schemas: objects, fields, primitive values, arrays,
enums, references, definitions, documentation, and selected string formats.

## Why the output is a Salad graph

The generated document is a Salad document with a `$namespaces` section and a
`$graph` containing records, enums, and graph-level `$import` directives when
external Salad schemas are required.

For example, recognized JSON Schema `format` values for strings can reference
the EOAP
[`string_format`](https://raw.githubusercontent.com/eoap/schemas/refs/heads/main/string_format.yaml)
schema through a namespace such as `string_format`, producing types like
`string_format:Date`.

This keeps generated records close to their type graph while still declaring
external Salad type libraries in the way Salad expects.

## What the converter optimizes for

The converter is best understood as a converter for the structural center of
JSON Schema, not a validator and not a complete preservation layer for every
validation keyword.

The goal is to make the useful path pleasant: take a JSON Schema model, convert
its shape into a readable Salad type graph, keep documentation close to the
generated fields, import external Salad type libraries in the expected place,
and leave clear warnings where the conversion still needs human review.

## What is outside the current scope

Constraints such as numeric ranges, regular expression patterns, conditional
validation, dependency rules, and unevaluated property semantics are currently
outside the implemented mapping.

Unsupported or lossy cases are preserved as far as possible. When the converter
cannot represent a JSON Schema construct precisely, it records a warning and
falls back to a broader `Any` type.

For exact behavior, see the
[conversion rules reference](../reference/conversion-rules.md).
