# Conversion rules reference

The converter currently applies these rules.

## Document shape

Output is serialized as a Salad document with `$namespaces` and `$graph`.
External Salad dependencies are not emitted under `$schemas`; they are imported
once through `$import` entries inside `$graph`.

## Namespaces and imports

The built-in `sld` namespace points to `https://w3id.org/cwl/salad#`. External
schema namespaces are derived from the imported file name, so
`string_format.yaml` becomes `string_format`, and the namespace value ends with
`#`.

## Object schemas

JSON Schema objects and schemas with `properties` become Salad `record` types.
Required properties remain required. Optional properties are represented as
nullable unions by adding `null`.

## Primitive types

JSON Schema primitive types map to Salad primitive types as follows:

| JSON Schema type | Salad type |
| --- | --- |
| `string` | `string` |
| `integer` | `int` |
| `number` | `float` |
| `boolean` | `boolean` |
| `null` | `null` |

## String formats

Recognized string formats, such as `date`, `date-time`, `uri`, `uuid`, `email`,
`ipv4`, and `ipv6`, are mapped to named types from the EOAP string format Salad
schema. References are qualified with the generated namespace, for example
`string_format:Date` or `string_format:URI`.

## Arrays

JSON Schema arrays are emitted as Salad array types, with `items` recursively
converted using the same type rules.

## Enums

JSON Schema `enum` values become Salad `enum` definitions with stringified
symbols.

## References

Local `$ref` values into `#/$defs/...` and `#/definitions/...` are resolved to
emitted Salad type names. The CLI merger can also recursively load external
referenced schemas and inline their record or enum definitions into the final
document.

## Definitions

`$defs` and `definitions` are predeclared so references can point to stable
generated names. Object-like definitions become records, enum definitions become
enums, and unsupported definition shapes are wrapped in a record with a
required `value` field.

## Compositions

`oneOf` and `anyOf` become Salad unions. `allOf` is handled for object-like
schemas by using `extends` when branches are references and by flattening inline
object branches into a merged record.

## Names

Record names are derived from schema titles when available, falling back to
reference paths, field names, or source file hints. Names are sanitized for
Salad compatibility and de-duplicated when the same preferred name appears more
than once.

## Documentation

JSON Schema `description` is carried into Salad `doc` fields. When no
description is present, `title` can be used as documentation. Example values
are appended to field and enum docs when available.

## Merging behavior

When the CLI receives multiple sources, or a source references shared external
schemas, it emits a single merged Salad document, de-duplicating schema loads
and type definitions by source reference where possible.

## Fallbacks and warnings

Unsupported type variants and unsupported non-object `allOf` branches degrade
to `Any`, with warnings collected into the generated document comment.
