"""ENG-6a — public-dataset CSV chunk reader.

Reads a long-format CSV (one row per meter/circuit reading -- the shape
public_dataset_config.py's SourceConfigs expect) in bounded-size chunks
rather than loading the whole file into memory, since Building Data
Genome 2/ASHRAE-scale exports run into the hundreds of MB.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def iter_csv_chunks(
    path: str | Path,
    chunk_size: int = 5000,
) -> Iterator[list[dict[str, Any]]]:
    """Yield successive lists of up to `chunk_size` raw CSV rows as dicts.

    Uses csv.DictReader (stdlib) directly against the file handle -- no
    pandas read_csv(chunksize=...) here, matching this repo's existing
    convention of using csv.DictReader for raw-row ingestion (see
    apps/api/routers/ingestion.py's CSV upload path) rather than
    introducing a second CSV-parsing approach for the same shape of data.
    """
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        chunk: list[dict[str, Any]] = []
        for row in reader:
            chunk.append(dict(row))
            if len(chunk) >= chunk_size:
                yield chunk
                chunk = []
        if chunk:
            yield chunk
