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
from json_schema2salad.utils import InlineSchemaMerger, normalize_source_uri
from loguru import logger
from pathlib import Path

import click
import time


@click.command(context_settings={"show_default": True})
@click.argument(
    "sources",
    nargs=-1,
    type=click.STRING,
    required=True,
)
@click.option(
    "--output",
    type=click.Path(path_type=Path, file_okay=True, dir_okay=False),
    required=True,
    help="The final output file path",
)
def main(
    sources: tuple[str, ...],
    output: Path,
):
    """
    Transpiles one or more JSON Schemas into a single Schema Salad document.
    """
    start_time = time.time()

    try:
        normalized_sources = [normalize_source_uri(source) for source in sources]
        for source in normalized_sources:
            logger.info(f"Reading JSON Schema from {source}...")
        logger.info("Transpiling JSON Schemas and recursively inlining referenced schemas...")

        output.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Merged Schema Salad will be serialized to {output.resolve()}")

        merger = InlineSchemaMerger(output)
        merger.emit(normalized_sources)

        if merger.warnings:
            for warning in merger.warnings:
                logger.warning(warning)

        logger.success(
            "------------------------------------------------------------------------"
        )
        logger.success(f"SUCCESS Schema Salad(s) successfully serialized to {output.resolve()}.")
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
