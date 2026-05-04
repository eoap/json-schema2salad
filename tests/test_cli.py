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

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from click.testing import CliRunner

import json_schema2salad.cli as cli
import json_schema2salad.utils as utils
import yaml


STRING_FORMAT_SCHEMA_URI = (
    "https://raw.githubusercontent.com/eoap/schemas/refs/heads/main/string_format.yaml"
)
STRING_FORMAT_NAMESPACE_URI = f"{STRING_FORMAT_SCHEMA_URI}#"
SALAD_NAMESPACE_URI = "https://w3id.org/cwl/salad#"


class HttpxJsonLoaderTests(unittest.TestCase):
    def test_loader_uses_httpx_with_redirects_and_parses_json(self) -> None:
        payload = {"name": "example", "value": 1}
        response = SimpleNamespace(
            headers={"Content-Type": "application/json"},
            json=lambda: payload,
            text=json.dumps(payload),
            raise_for_status=lambda: None,
        )

        client = SimpleNamespace(get=lambda uri: response)
        recorded: dict[str, object] = {}

        class FakeClient:
            def __init__(self, **kwargs: object) -> None:
                recorded.update(kwargs)

            def __enter__(self) -> SimpleNamespace:
                return client

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

        with patch("json_schema2salad.utils.Client", FakeClient):
            loaded = utils.httpx_json_loader("https://example.test/schema.json")

        self.assertEqual(payload, loaded)
        self.assertEqual({"follow_redirects": True}, recorded)

    def test_loader_falls_back_to_yaml(self) -> None:
        response = SimpleNamespace(
            headers={"Content-Type": "application/yaml"},
            text="name: example\nvalue: 1\n",
            raise_for_status=lambda: None,
        )

        class FakeClient:
            def __init__(self, **kwargs: object) -> None:
                pass

            def __enter__(self) -> SimpleNamespace:
                return SimpleNamespace(get=lambda uri: response)

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

        with patch("json_schema2salad.utils.Client", FakeClient):
            loaded = utils.httpx_json_loader("https://example.test/schema.yaml")

        self.assertEqual({"name": "example", "value": 1}, loaded)


class LoadJsonSchemaTests(unittest.TestCase):
    def test_load_json_schema_supports_local_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            schema_path = Path(tmpdir) / "schema.yaml"
            schema_path.write_text("title: Example\ntype: object\n", encoding="utf-8")

            loaded = utils.load_json_schema(str(schema_path))

        self.assertEqual({"title": "Example", "type": "object"}, loaded)


class MainCommandTests(unittest.TestCase):
    def test_main_inlines_external_schema_into_single_output_document(self) -> None:
        runner = CliRunner()

        root_schema = {
            "title": "Root",
            "type": "object",
            "properties": {
                "child": {"$ref": "child.json"},
            },
            "required": ["child"],
        }
        child_schema = {
            "title": "Child",
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source = tmp_path / "root.json"
            child = tmp_path / "child.json"
            output = tmp_path / "merged.yaml"
            source.write_text(json.dumps(root_schema), encoding="utf-8")
            child.write_text(json.dumps(child_schema), encoding="utf-8")

            result = runner.invoke(cli.main, ["--output", str(output), str(source)])

            self.assertEqual(0, result.exit_code, result.output)
            self.assertTrue(output.exists(), result.output)
            self.assertFalse((tmp_path / "child.yaml").exists(), result.output)

            merged_document = yaml.safe_load(output.read_text(encoding="utf-8"))

        graph_names = [
            item.get("name") for item in merged_document["$graph"] if "name" in item
        ]
        root_record = next(
            item for item in merged_document["$graph"] if item.get("name") == "Root"
        )

        self.assertIn("Child", graph_names)
        self.assertEqual("Child", root_record["fields"][0]["type"])

    def test_main_imports_string_format_schema_when_format_references_are_used(
        self,
    ) -> None:
        runner = CliRunner()

        root_schema = {
            "title": "Root",
            "type": "object",
            "properties": {
                "published": {
                    "type": "string",
                    "format": "date",
                },
            },
            "required": ["published"],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source = tmp_path / "root.json"
            output = tmp_path / "merged.yaml"
            source.write_text(json.dumps(root_schema), encoding="utf-8")

            result = runner.invoke(cli.main, ["--output", str(output), str(source)])

            self.assertEqual(0, result.exit_code, result.output)
            merged_document = yaml.safe_load(output.read_text(encoding="utf-8"))

        root_record = next(
            item for item in merged_document["$graph"] if item.get("name") == "Root"
        )

        self.assertNotIn("$schemas", merged_document)
        self.assertEqual(
            {
                "sld": SALAD_NAMESPACE_URI,
                "string_format": STRING_FORMAT_NAMESPACE_URI,
            },
            merged_document["$namespaces"],
        )
        self.assertEqual(
            {"$import": STRING_FORMAT_SCHEMA_URI}, merged_document["$graph"][0]
        )
        self.assertEqual("string_format:Date", root_record["fields"][0]["type"])

    def test_main_inlines_external_definition_refs_into_single_output_document(
        self,
    ) -> None:
        runner = CliRunner()

        root_schema = {
            "title": "Root",
            "type": "object",
            "properties": {
                "address": {"$ref": "shared.json#/$defs/Address"},
            },
            "required": ["address"],
        }
        shared_schema = {
            "title": "Shared",
            "$defs": {
                "Address": {
                    "type": "object",
                    "properties": {
                        "street": {"type": "string"},
                    },
                    "required": ["street"],
                }
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source = tmp_path / "root.json"
            shared = tmp_path / "shared.json"
            output = tmp_path / "merged.yaml"
            source.write_text(json.dumps(root_schema), encoding="utf-8")
            shared.write_text(json.dumps(shared_schema), encoding="utf-8")

            result = runner.invoke(cli.main, ["--output", str(output), str(source)])

            self.assertEqual(0, result.exit_code, result.output)
            merged_document = yaml.safe_load(output.read_text(encoding="utf-8"))

        graph_names = [
            item.get("name") for item in merged_document["$graph"] if "name" in item
        ]
        root_record = next(
            item for item in merged_document["$graph"] if item.get("name") == "Root"
        )

        self.assertIn("DefsAddress", graph_names)
        self.assertEqual("DefsAddress", root_record["fields"][0]["type"])

    def test_main_merges_multiple_input_schemas_into_one_document(self) -> None:
        runner = CliRunner()

        first_schema = {
            "title": "First",
            "type": "object",
            "properties": {
                "value": {"type": "string"},
            },
            "required": ["value"],
        }
        second_schema = {
            "title": "Second",
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
            },
            "required": ["count"],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            first = tmp_path / "first.json"
            second = tmp_path / "second.json"
            output = tmp_path / "merged.yaml"
            first.write_text(json.dumps(first_schema), encoding="utf-8")
            second.write_text(json.dumps(second_schema), encoding="utf-8")

            result = runner.invoke(
                cli.main, ["--output", str(output), str(first), str(second)]
            )

            self.assertEqual(0, result.exit_code, result.output)
            merged_document = yaml.safe_load(output.read_text(encoding="utf-8"))

        graph_names = [
            item.get("name") for item in merged_document["$graph"] if "name" in item
        ]

        self.assertIn("First", graph_names)
        self.assertIn("Second", graph_names)

    def test_main_dedupes_shared_external_schema_loaded_from_multiple_entities(
        self,
    ) -> None:
        runner = CliRunner()

        first_schema = {
            "title": "First",
            "type": "object",
            "properties": {
                "shared": {"$ref": "shared.json"},
            },
            "required": ["shared"],
        }
        second_schema = {
            "title": "Second",
            "type": "object",
            "properties": {
                "shared": {"$ref": "shared.json"},
            },
            "required": ["shared"],
        }
        shared_schema = {
            "title": "Shared",
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            first = tmp_path / "first.json"
            second = tmp_path / "second.json"
            shared = tmp_path / "shared.json"
            output = tmp_path / "merged.yaml"
            first.write_text(json.dumps(first_schema), encoding="utf-8")
            second.write_text(json.dumps(second_schema), encoding="utf-8")
            shared.write_text(json.dumps(shared_schema), encoding="utf-8")

            result = runner.invoke(
                cli.main, ["--output", str(output), str(first), str(second)]
            )

            self.assertEqual(0, result.exit_code, result.output)
            merged_document = yaml.safe_load(output.read_text(encoding="utf-8"))

        graph_names = [
            item.get("name") for item in merged_document["$graph"] if "name" in item
        ]
        first_record = next(
            item for item in merged_document["$graph"] if item.get("name") == "First"
        )
        second_record = next(
            item for item in merged_document["$graph"] if item.get("name") == "Second"
        )

        self.assertEqual(1, graph_names.count("Shared"))
        self.assertEqual("Shared", first_record["fields"][0]["type"])
        self.assertEqual("Shared", second_record["fields"][0]["type"])

    def test_main_qualifies_external_extends_with_source_filename(self) -> None:
        runner = CliRunner()

        root_schema = {
            "title": "Derived",
            "allOf": [
                {"$ref": "base.json"},
                {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                    },
                    "required": ["name"],
                },
            ],
        }
        base_schema = {
            "title": "Base",
            "type": "object",
            "properties": {
                "id": {"type": "string"},
            },
            "required": ["id"],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source = tmp_path / "derived.json"
            base = tmp_path / "base.json"
            output = tmp_path / "merged.yaml"
            source.write_text(json.dumps(root_schema), encoding="utf-8")
            base.write_text(json.dumps(base_schema), encoding="utf-8")

            result = runner.invoke(cli.main, ["--output", str(output), str(source)])

            self.assertEqual(0, result.exit_code, result.output)
            merged_document = yaml.safe_load(output.read_text(encoding="utf-8"))

        derived_record = next(
            item for item in merged_document["$graph"] if item.get("name") == "Derived"
        )

        self.assertEqual("Base", derived_record["extends"])


if __name__ == "__main__":
    unittest.main()
