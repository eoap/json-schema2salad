# Command line interface

The `json-schema2salad` command converts one or more
[JSON Schema](https://json-schema.org/) sources into a single
[Schema Salad](https://schema-salad.readthedocs.io/) document.

It is designed as a merger as much as a converter: the command reads the input
schema, follows supported external references, converts every discovered schema
into Salad records and enums, and writes one final YAML document at the path you
choose.

## Usage

```console
json-schema2salad --output OUTPUT SOURCE [SOURCE ...]
```

The command is installed from the Python package entry point:

```console
pip install json-schema2salad
```

Then invoke it with at least one source and a required output file:

```console
json-schema2salad --output schema.salad.yaml schema.json
```

## Arguments and options

`SOURCE`
: One or more JSON Schema sources to convert. A source can be a local path, a
  `file://` URI, or an `http://` / `https://` URI. Local paths are expanded and
  normalized to absolute paths before conversion starts.

`--output OUTPUT`
: Required. The file where the merged Salad document will be written. Parent
  directories are created automatically when needed.

## What happens during a run

When the CLI starts, it normalizes every source URI and logs the schemas it is
about to read. It then creates an inline merger and processes each source in
order.

For each schema, the merger:

1. Loads the schema document.
2. Plans stable Salad type names before conversion.
3. Converts the schema into Salad graph entries.
4. Recursively resolves supported external `$ref` values.
5. De-duplicates schemas and generated types that were already seen.
6. Writes the final merged Salad document to `--output`.

This means the CLI is useful both for a single schema and for a small family of
schemas that reference one another.

## Source loading

Local files are parsed with YAML loading, which also accepts JSON because JSON is
a subset of YAML:

```console
json-schema2salad --output build/model.salad.yaml schemas/model.json
```

Remote `http://` and `https://` sources are fetched with redirects enabled. If
the response declares an `application/json` content type, it is parsed as JSON;
otherwise, the response body is parsed as YAML.

```console
json-schema2salad \
  --output build/remote.salad.yaml \
  https://example.org/schemas/root.yaml
```

## Reference resolution

The CLI recursively inlines supported external references into the same output
document. Relative references are resolved from the schema file that contains
the `$ref`.

For example, if `root.json` contains:

```json
{
  "title": "Root",
  "type": "object",
  "properties": {
    "child": { "$ref": "child.json" }
  },
  "required": ["child"]
}
```

Then this command:

```console
json-schema2salad --output merged.salad.yaml root.json
```

loads `child.json`, converts it, and places both `Root` and the child type in
`merged.salad.yaml`.

References to document roots and top-level definitions are supported. Local
definitions such as `#/$defs/Thing` and `#/definitions/Thing` are converted to
stable Salad type names. External definition references such as
`shared.json#/$defs/Address` are resolved by loading the external document and
linking the field to the generated Salad type.

If a referenced schema has already been processed, it is reused rather than
loaded and emitted again.

## Multiple inputs

You can pass several independent sources. They are merged into the same Salad
document:

```console
json-schema2salad \
  --output catalog.salad.yaml \
  schemas/product.json \
  schemas/order.json \
  schemas/customer.json
```

Shared external schemas are de-duplicated across all inputs. If two inputs both
reference the same `shared.json`, the shared types are emitted only once.

## Output structure

The CLI writes YAML using the Schema Salad document shape used by the converter:

```yaml
$namespaces:
  sld: https://w3id.org/cwl/salad#
$graph:
  - type: record
    name: Root
    fields:
      - name: id
        type: string
```

When an external Salad schema is required, it is declared as a graph-level
`$import` and qualified through `$namespaces`:

```yaml
$namespaces:
  sld: https://w3id.org/cwl/salad#
  string_format: https://raw.githubusercontent.com/eoap/schemas/refs/heads/main/string_format.yaml#
$graph:
  - $import: https://raw.githubusercontent.com/eoap/schemas/refs/heads/main/string_format.yaml
  - type: record
    name: Root
    fields:
      - name: published
        type: string_format:Date
```

See the [implemented conversion rules](index.md#implemented-conversion-rules)
for the current mapping from JSON Schema constructs to Salad records, enums,
arrays, unions, imports, and documentation.

## Logging and warnings

The command logs the main phases of the run:

- the normalized input sources;
- the output path;
- recursive schema inlining;
- warnings produced during conversion;
- success or failure;
- total runtime and finish timestamp.

Warnings are also collected into the generated Salad document comment. They are
used when the converter has to preserve a shape less precisely, for example by
falling back to `Any` for unsupported type variants or unsupported non-object
`allOf` branches.

## Current boundaries

The CLI follows the same boundaries as the converter itself. It focuses on
structural conversion and recursive merging, not complete preservation of every
JSON Schema validation keyword. Unsupported external reference fragments raise a
conversion error; currently, external references are expected to point to a
document root or to a top-level definition that can be planned and emitted.
