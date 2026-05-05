# Command line reference

The `json-schema2salad` command converts one or more
[JSON Schema](https://json-schema.org/) sources into a single
[Schema Salad](https://schema-salad.readthedocs.io/) document.

## Synopsis

```console
json-schema2salad --output OUTPUT SOURCE [SOURCE ...]
```

The command is installed from the Python package entry point:

```console
pip install json-schema2salad
```

## Arguments

`SOURCE`
: One or more JSON Schema sources to convert. A source can be a local path, a
  `file://` URI, or an `http://` / `https://` URI. Local paths are expanded and
  normalized to absolute paths before conversion starts.

## Options

`--output OUTPUT`
: Required. The file where the merged Salad document will be written. Parent
  directories are created automatically when needed.

## Source loading

Local files are parsed with YAML loading, which also accepts JSON because JSON
is a subset of YAML.

Remote `http://` and `https://` sources are fetched with redirects enabled. If
the response declares an `application/json` content type, it is parsed as JSON;
otherwise, the response body is parsed as YAML.

Resolved schema roots must be JSON objects.

## Reference resolution

The CLI recursively inlines supported external references into the same output
document. Relative references are resolved from the schema file that contains
the `$ref`.

References to document roots and top-level definitions are supported. Local
definitions such as `#/$defs/Thing` and `#/definitions/Thing` are converted to
stable Salad type names. External definition references such as
`shared.json#/$defs/Address` are resolved by loading the external document and
linking the field to the generated Salad type.

If a referenced schema has already been processed, it is reused rather than
loaded and emitted again.

## Run flow

For each schema, the merger:

1. Loads the schema document.
2. Plans stable Salad type names before conversion.
3. Converts the schema into Salad graph entries.
4. Recursively resolves supported external `$ref` values.
5. De-duplicates schemas and generated types that were already seen.
6. Writes the final merged Salad document to `--output`.

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

## Logging and warnings

The command logs the main phases of the run:

- normalized input sources;
- output path;
- recursive schema inlining;
- warnings produced during conversion;
- success or failure;
- total runtime and finish timestamp.

Warnings are also collected into the generated Salad document comment.

## Boundaries

The CLI follows the same boundaries as the converter itself. It focuses on
structural conversion and recursive merging, not complete preservation of every
JSON Schema validation keyword.

Unsupported external reference fragments raise a conversion error. External
references are expected to point to a document root or to a top-level definition
that can be planned and emitted.
