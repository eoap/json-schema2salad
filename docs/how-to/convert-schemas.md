# Convert JSON Schema documents

Use these guides when you already know the conversion task you want to complete.

## Convert a local schema

Pass one local JSON or YAML schema file and choose the merged Salad output path:

```console
json-schema2salad --output build/model.salad.yaml schemas/model.json
```

Local paths are expanded and normalized before conversion starts. Parent
directories for the output file are created automatically when needed.

## Convert a remote schema

Use an `http://` or `https://` source:

```console
json-schema2salad \
  --output build/remote.salad.yaml \
  https://example.org/schemas/root.yaml
```

Remote sources are fetched with redirects enabled. Responses with an
`application/json` content type are parsed as JSON; other responses are parsed
as YAML.

## Merge several schemas

Pass several independent sources. They are emitted into the same Salad document:

```console
json-schema2salad \
  --output catalog.salad.yaml \
  schemas/product.json \
  schemas/order.json \
  schemas/customer.json
```

Shared external schemas are de-duplicated across all inputs. If two inputs both
reference the same external schema, the shared types are emitted once.

## Inline an external reference

Use a normal JSON Schema `$ref` from one schema to another:

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

Then convert the root schema:

```console
json-schema2salad --output merged.salad.yaml root.json
```

The converter loads `child.json`, converts it, and places both the root type and
the referenced type in `merged.salad.yaml`.

External definition references such as `shared.json#/$defs/Address` are also
resolved when they point to top-level definitions that can be planned and
emitted.

## Preserve recognized string formats

Use a supported JSON Schema `format` value on a string field:

```json
{
  "title": "Root",
  "type": "object",
  "properties": {
    "published": {
      "type": "string",
      "format": "date"
    }
  },
  "required": ["published"]
}
```

The generated Salad document imports the EOAP string format schema and qualifies
the field type with the generated namespace:

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

## Review conversion warnings

Read the command output after each run. Warnings are logged when a JSON Schema
construct cannot be represented precisely and the converter falls back to a
broader type such as `Any`.

Warnings are also collected into the generated Salad document comment so the
output can be reviewed later.

For exact supported behavior, see the
[conversion rules reference](../reference/conversion-rules.md).
