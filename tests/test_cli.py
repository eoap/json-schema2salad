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


class HttpxJsonLoaderTests(unittest.TestCase):
    def test_loader_uses_httpx_with_redirects_and_parses_json(self) -> None:
        payload = {"name": "example", "value": 1}
        response = SimpleNamespace(
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

        with patch('json_schema2salad.cli.Client', FakeClient):
            loaded = cli.httpx_json_loader('https://example.test/schema.json')

        self.assertEqual(payload, loaded)
        self.assertEqual({'follow_redirects': True}, recorded)

    def test_loader_passes_json_kwargs_through(self) -> None:
        response = SimpleNamespace(
            text='{"number": 1.5}',
            raise_for_status=lambda: None,
        )

        class FakeClient:
            def __init__(self, **kwargs: object) -> None:
                pass

            def __enter__(self) -> SimpleNamespace:
                return SimpleNamespace(get=lambda uri: response)

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

        with patch('json_schema2salad.cli.Client', FakeClient):
            loaded = cli.httpx_json_loader('https://example.test/schema.json', parse_float=str)

        self.assertEqual({'number': '1.5'}, loaded)


class MainCommandTests(unittest.TestCase):
    def test_main_passes_httpx_loader_to_load_uri(self) -> None:
        runner = CliRunner()
        expected_document = {"type": "object", "properties": {}}
        recorded: dict[str, object] = {}

        def fake_load_uri(**kwargs: object) -> dict[str, object]:
            recorded.update(kwargs)
            return expected_document

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / 'result.yaml'
            with patch('json_schema2salad.cli.load_uri', side_effect=fake_load_uri), patch(
                'json_schema2salad.cli.convert_json_schema_to_salad',
                return_value=(SimpleNamespace(as_salad=lambda: {"$graph": []}), []),
            ):
                result = runner.invoke(cli.main, ['--output', str(output), 'https://example.test/schema.json'])

        self.assertEqual(0, result.exit_code, result.output)
        self.assertIs(recorded.get('loader'), cli.httpx_json_loader)
        self.assertEqual('https://example.test/schema.json', recorded.get('uri'))
        self.assertTrue(recorded.get('jsonschema'))
        self.assertFalse(recorded.get('proxies'))
        self.assertFalse(recorded.get('lazy_load'))
        self.assertTrue(recorded.get('merge_props'))


if __name__ == '__main__':
    unittest.main()
