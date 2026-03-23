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

from __future__ import annotations

from datetime import datetime
from httpx import Client
from json_schema2salad import convert_json_schema_to_salad
from json_schema2salad.models import SaladDocument
from jsonref import load_uri
from loguru import logger
from pathlib import Path

import click
import json
import time
import yaml


def httpx_json_loader(uri: str, **kwargs: object) -> object:
    with Client(follow_redirects=True) as client:
        response = client.get(uri)
        response.raise_for_status()
        return json.loads(response.text, **kwargs)


@click.command(context_settings={"show_default": True})
@click.argument(
    "source",
    type=click.STRING,
    required=True,
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    required=True,
    help="The output file path",
)
def main(
    source: str,
    output: Path,
):
    """
    Transpiles the input JSON Schema to Schema Salad.
    """
    start_time = time.time()

    try:
        logger.info(f"Reading JSON Schema from {source}...")

        resolved = load_uri(
            uri=source,
            loader=httpx_json_loader,
            jsonschema=True,
            proxies=False,
            lazy_load=False,
            merge_props=True
        )

        if not isinstance(resolved, dict):
            raise TypeError("Resolved schema root must be a JSON object")

        schema_salad, warnings = convert_json_schema_to_salad(resolved)

        if warnings:
            for warning in warnings:
                logger.warning(warning)

        logger.success("JSON Schema successfully transpiled to Schema Salad!")
        logger.info("Serializing Schema Salad...")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w") as output_stream:
            yaml.dump(schema_salad.as_salad(), output_stream, sort_keys=False)

        logger.success(
            "------------------------------------------------------------------------"
        )
        logger.success(f"SUCCESS Schema Salad successfully serialized to {output.absolute()}.")
        logger.success(
            "------------------------------------------------------------------------"
        )
    except Exception as e:
        logger.error(
            "------------------------------------------------------------------------"
        )
        logger.error("FAIL")
        logger.error(e)
        logger.error(
            "------------------------------------------------------------------------"
        )

    end_time = time.time()

    logger.info(f"Total time: {end_time - start_time:.4f} seconds")
    logger.info(
        f"Finished at: {datetime.fromtimestamp(end_time).isoformat(timespec='milliseconds')}"
    )
