# Convert your first JSON Schema

In this tutorial, we will convert a small JSON Schema document into a Schema
Salad document and check the generated output.

## Install the command

Install the package so the `json-schema2salad` command is available:

```console
pip install json-schema2salad
```

## Create a schema

Create a file named `person.schema.json`:

```json
{
  "title": "Person",
  "type": "object",
  "description": "A person record.",
  "properties": {
    "name": {
      "type": "string",
      "description": "The person's display name."
    },
    "age": {
      "type": "integer"
    }
  },
  "required": ["name"]
}
```

This schema has one required field, `name`, and one optional field, `age`.

## Run the converter

Run the command with the schema as the source and choose an output file:

```console
json-schema2salad --output person.salad.yaml person.schema.json
```

The command writes one Schema Salad document to `person.salad.yaml`.

## Inspect the result

Open `person.salad.yaml`. The generated document should look like this:

```yaml
$namespaces:
  sld: https://w3id.org/cwl/salad#
$graph:
- type: record
  name: Person
  fields:
  - name: name
    type: string
    doc: The person's display name.
  - name: age
    type:
    - 'null'
    - int
  doc: A person record.
```

Notice that the required `name` field remains a plain `string`, while the
optional `age` field becomes a union with `null`.

## Convert a formatted string

Add a `published` field with the JSON Schema `date` format:

```json
{
  "title": "Person",
  "type": "object",
  "properties": {
    "name": { "type": "string" },
    "published": {
      "type": "string",
      "format": "date"
    }
  },
  "required": ["name", "published"]
}
```

Run the converter again:

```console
json-schema2salad --output person.salad.yaml person.schema.json
```

The output now includes the EOAP string format schema as a graph-level import
and uses the generated namespace in the field type:

```yaml
$namespaces:
  sld: https://w3id.org/cwl/salad#
  string_format: https://raw.githubusercontent.com/eoap/schemas/refs/heads/main/string_format.yaml#
$graph:
- $import: https://raw.githubusercontent.com/eoap/schemas/refs/heads/main/string_format.yaml
- type: record
  name: Person
  fields:
  - name: name
    type: string
  - name: published
    type: string_format:Date
```

You have now converted a JSON Schema object into a Salad record, checked an
optional field, and seen how recognized string formats become named Salad
types.

Next, use the [how-to guides](../how-to/convert-schemas.md) for task-focused
commands, or the [conversion rules reference](../reference/conversion-rules.md)
for the full implemented mapping.
