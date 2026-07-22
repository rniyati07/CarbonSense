"""ENG-6a -- reproduce tests/fixtures/datasets/bdg2_sample.csv from a raw
BDG2 `electricity_cleaned.csv` download.

BDG2's native distribution is wide format (one column per building, one
row per hourly timestamp) -- this pivots a chosen set of building columns
into the long format `pipelines/dataset_ingestion` and
`services/ingestion/normalization.py` already expect (one row per
meter_id/timestamp/reading), the same shape as the `bdg2` SourceConfig in
public_dataset_config.py. This is a one-time data-preparation step, not
part of the ingestion pipeline itself -- the pipeline's column-mapping
logic is unchanged and still does the real normalization work.

Usage:
    python scripts/training/prepare_bdg2_fixture.py \\
        --electricity-csv /path/to/electricity_cleaned.csv \\
        --buildings Robin_office_Dina Robin_lodging_Dorthy Robin_education_Zenia \\
        --out tests/fixtures/datasets/bdg2_sample.csv

Download `electricity_cleaned.csv` from
github.com/buds-lab/building-data-genome-project-2
(`data/meters/cleaned/electricity_cleaned.csv`, Git-LFS tracked).
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def pivot_bdg2_wide_to_long(
    src: Path,
    buildings: list[str],
    dst: Path,
    circuit_type: str = "electricity",
) -> tuple[int, int]:
    """Reads `src` (BDG2 wide-format CSV: a `timestamp` column plus one
    column per building) and writes `dst` as long-format rows
    (meter_id, timestamp, kwh, circuit_type) for just `buildings`,
    skipping missing readings (real BDG2 data has real gaps) and any
    trailing truncated line (relevant when `src` was produced by a
    byte-range download rather than a full file fetch).

    Returns (rows_read, rows_written).
    """
    with src.open(newline="", encoding="utf-8") as f_in:
        reader = csv.reader(f_in)
        header = next(reader)
        col_idx = {name: header.index(name) for name in buildings}
        ts_idx = header.index("timestamp")

        rows_read = 0
        out_rows: list[tuple[str, str, str]] = []
        for row in reader:
            rows_read += 1
            if len(row) != len(header):
                continue  # truncated trailing line
            ts = row[ts_idx]
            for name in buildings:
                val = row[col_idx[name]]
                if val:
                    out_rows.append((name, ts, val))

    with dst.open("w", newline="", encoding="utf-8") as f_out:
        writer = csv.writer(f_out)
        writer.writerow(["meter_id", "timestamp", "kwh", "circuit_type"])
        for meter_id, ts, kwh in out_rows:
            writer.writerow([meter_id, ts, kwh, circuit_type])

    return rows_read, len(out_rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pivot a raw BDG2 electricity_cleaned.csv slice into long format"
    )
    parser.add_argument("--electricity-csv", required=True, type=Path)
    parser.add_argument("--buildings", required=True, nargs="+")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    rows_read, rows_written = pivot_bdg2_wide_to_long(
        args.electricity_csv, args.buildings, args.out
    )
    print(  # noqa: T201
        f"Read {rows_read} timestamp rows, wrote {rows_written} long-format "
        f"readings for {len(args.buildings)} buildings to {args.out}"
    )


if __name__ == "__main__":
    main()
