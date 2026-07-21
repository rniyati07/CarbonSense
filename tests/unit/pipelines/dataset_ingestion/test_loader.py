from __future__ import annotations

from pathlib import Path

import pytest

from pipelines.dataset_ingestion.loader import iter_csv_chunks

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "datasets" / "combed_sample.csv"


@pytest.mark.unit
class TestIterCsvChunks:
    def test_reads_all_rows_across_chunks(self) -> None:
        chunks = list(iter_csv_chunks(FIXTURE, chunk_size=50))
        total_rows = sum(len(c) for c in chunks)
        assert total_rows == 144  # 2 meters x 72 hours, see the fixture generator

    def test_respects_chunk_size(self) -> None:
        chunks = list(iter_csv_chunks(FIXTURE, chunk_size=50))
        assert len(chunks) == 3  # 50 + 50 + 44
        assert len(chunks[0]) == 50
        assert len(chunks[-1]) == 44

    def test_rows_have_expected_columns(self) -> None:
        chunks = list(iter_csv_chunks(FIXTURE, chunk_size=10))
        first_row = chunks[0][0]
        assert set(first_row.keys()) == {"meter_id", "timestamp", "kwh", "circuit_type"}
