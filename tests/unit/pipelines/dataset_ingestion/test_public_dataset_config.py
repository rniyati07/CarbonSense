from __future__ import annotations

import pytest

from pipelines.dataset_ingestion.public_dataset_config import (
    BDG2_SOURCE_ID,
    COMBED_SOURCE_ID,
    get_public_dataset_source,
)


@pytest.mark.unit
class TestGetPublicDatasetSource:
    def test_combed_source_resolves(self) -> None:
        config = get_public_dataset_source(COMBED_SOURCE_ID)
        assert config.source_id == COMBED_SOURCE_ID
        assert "meter_id" in config.required_fields

    def test_bdg2_source_resolves(self) -> None:
        config = get_public_dataset_source(BDG2_SOURCE_ID)
        assert config.source_id == BDG2_SOURCE_ID

    def test_unknown_source_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown public dataset source_id"):
            get_public_dataset_source("not-a-real-dataset")
