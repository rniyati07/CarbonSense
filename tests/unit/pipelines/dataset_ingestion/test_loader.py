from __future__ import annotations

from pathlib import Path

import pytest

from pipelines.dataset_ingestion.loader import iter_csv_chunks

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "datasets" / "bdg2_sample.csv"


@pytest.mark.unit
class TestIterCsvChunks:
    def test_reads_all_rows_across_chunks(self) -> None:
        chunks = list(iter_csv_chunks(FIXTURE, chunk_size=2000))
        total_rows = sum(len(c) for c in chunks)
        # 3 real BDG2 buildings x 2866 real hourly readings each -- see
        # tests/fixtures/datasets/README.md for exact provenance.
        assert total_rows == 8598

    def test_respects_chunk_size(self) -> None:
        chunks = list(iter_csv_chunks(FIXTURE, chunk_size=2000))
        assert len(chunks) == 5  # 2000 x 4 + 598
        assert len(chunks[0]) == 2000
        assert len(chunks[-1]) == 598

    def test_rows_have_expected_columns(self) -> None:
        chunks = list(iter_csv_chunks(FIXTURE, chunk_size=10))
        first_row = chunks[0][0]
        assert set(first_row.keys()) == {"meter_id", "timestamp", "kwh", "circuit_type"}
