# json-schema2salad

`json-schema2salad` translates
[JSON Schema](https://json-schema.org/) documents into a practical subset of
[Schema Salad](https://schema-salad.readthedocs.io/), the schema language used
by the [Common Workflow Language](https://www.commonwl.org/) ecosystem.

The documentation is organized with the
[Diataxis](https://diataxis.fr/) approach:

- [Tutorials](tutorials/first-conversion.md) help you learn the tool by making
  one successful conversion.
- [How-to guides](how-to/convert-schemas.md) help you complete specific
  conversion tasks.
- [Reference](reference/cli.md) gives exact command-line and conversion-rule
  details.
- [Explanation](explanation/conversion-model.md) describes the conversion model,
  trade-offs, and current scope.

!!! note "Development status"
    This tool is still being refined. Unsupported or lossy cases are preserved
    as far as possible, and the converter records warnings when it must fall
    back to a broader `Any` type. The current behavior should be treated as an
    implemented conversion policy, not yet as a full JSON Schema to Schema Salad
    specification.

## Start here

If you are new to the tool, begin with
[Convert your first JSON Schema](tutorials/first-conversion.md).

If you already know what you need to do, go straight to
[Convert JSON Schema documents](how-to/convert-schemas.md).

If you need exact behavior, use the
[command line reference](reference/cli.md) and
[conversion rules reference](reference/conversion-rules.md).
