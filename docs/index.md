# Introduction

`json-schema2salad` is an ongoing work in progress for translating
[JSON Schema](https://json-schema.org/) documents into a practical subset of
[Schema Salad](https://schema-salad.readthedocs.io/), the schema language used
by the [Common Workflow Language](https://www.commonwl.org/) ecosystem to
describe structured JSON/YAML documents, linked data semantics, validation
rules, imports, and type graphs.

The project is intentionally small, explicit, and evolving. It does not try to
be a complete semantic mirror of every JSON Schema keyword. Instead, it focuses
on producing useful Salad schema documents from the common structural features
that appear in EOAP-style schemas: objects, fields, primitive values, arrays,
enums, references, definitions, documentation, and selected string formats.

The generated document is a Salad document with a `$namespaces` section and a
`$graph` containing records, enums, and graph-level `$import` directives when
external Salad schemas are required. For example, recognized JSON Schema
`format` values for strings can reference the EOAP
[`string_format`](https://raw.githubusercontent.com/eoap/schemas/refs/heads/main/string_format.yaml)
schema through a namespace such as `string_format`, producing types like
`string_format:Date`.

!!! note "Development status"
    This tool is still being refined. Unsupported or lossy cases are preserved
    as far as possible, and the converter records warnings when it must fall
    back to a broader `Any` type. The current behavior should be treated as an
    implemented conversion policy, not yet as a full JSON Schema to Schema Salad
    specification.

## Implemented conversion rules

The converter currently applies these rules:

- **Document shape**: output is serialized as a Salad document with
  `$namespaces` and `$graph`. External Salad dependencies are not emitted under
  `$schemas`; they are imported once through `$import` entries inside `$graph`.

- **Namespaces and imports**: the built-in `sld` namespace points to
  `https://w3id.org/cwl/salad#`. External schema namespaces are derived from the
  imported file name, so `string_format.yaml` becomes `string_format`, and the
  namespace value ends with `#`.

- **Object schemas**: JSON Schema objects and schemas with `properties` become
  Salad `record` types. Required properties remain required; optional
  properties are represented as nullable unions by adding `null`.

- **Primitive types**: JSON Schema `string`, `integer`, `number`, `boolean`, and
  `null` map respectively to Salad `string`, `int`, `float`, `boolean`, and
  `null`.

- **String formats**: recognized string formats, such as `date`, `date-time`,
  `uri`, `uuid`, `email`, `ipv4`, and `ipv6`, are mapped to named types from the
  EOAP string format Salad schema. References are qualified with the generated
  namespace, for example `string_format:Date` or `string_format:URI`.

- **Arrays**: JSON Schema arrays are emitted as Salad array types, with `items`
  recursively converted using the same type rules.

- **Enums**: JSON Schema `enum` values become Salad `enum` definitions with
  stringified symbols.

- **References**: local `$ref` values into `#/$defs/...` and
  `#/definitions/...` are resolved to emitted Salad type names. The CLI merger
  can also recursively load external referenced schemas and inline their record
  or enum definitions into the final document.

- **Definitions**: `$defs` and `definitions` are predeclared so references can
  point to stable generated names. Object-like definitions become records,
  enum definitions become enums, and unsupported definition shapes are wrapped
  in a record with a required `value` field.

- **Compositions**: `oneOf` and `anyOf` become Salad unions. `allOf` is handled
  for object-like schemas by using `extends` when branches are references and
  by flattening inline object branches into a merged record.

- **Names**: record names are derived from schema titles when available, falling
  back to reference paths, field names, or source file hints. Names are
  sanitized for Salad compatibility and de-duplicated when the same preferred
  name appears more than once.

- **Documentation**: JSON Schema `description` is carried into Salad `doc`
  fields. When no description is present, `title` can be used as documentation.
  Example values are appended to field and enum docs when available.

- **Merging behavior**: when the CLI receives multiple sources, or a source
  references shared external schemas, it emits a single merged Salad document,
  de-duplicating schema loads and type definitions by source reference where
  possible.

- **Fallbacks and warnings**: unsupported type variants and unsupported
  non-object `allOf` branches degrade to `Any`, with warnings collected into the
  generated document comment.

## Scope

`json-schema2salad` is best understood as a converter for the structural center
of JSON Schema, not a validator and not a complete preservation layer for every
validation keyword. Constraints such as numeric ranges, regular expression
patterns, conditional validation, dependency rules, and unevaluated property
semantics are currently outside the implemented mapping.

The goal is to make the useful path pleasant: take a JSON Schema model, convert
its shape into a readable Salad type graph, keep documentation close to the
generated fields, import external Salad type libraries in the way Salad expects,
and leave clear warnings where the conversion still needs human review.
