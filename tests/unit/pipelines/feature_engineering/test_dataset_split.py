from __future__ import annotations

import datetime
from uuid import uuid4

import pytest

from models.feature_store.feature_set_v1 import FeatureSetV1
from pipelines.feature_engineering.dataset_split import chronological_split


def _features(n: int) -> list[FeatureSetV1]:
    tenant_id, circuit_id = uuid4(), uuid4()
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    return [
        FeatureSetV1(
            tenant_id=tenant_id,
            circuit_id=circuit_id,
            ts=start + datetime.timedelta(hours=i),
            day_type="business_day",
        )
        for i in range(n)
    ]


@pytest.mark.unit
class TestChronologicalSplit:
    def test_splits_respect_fractions(self) -> None:
        features = _features(100)
        result = chronological_split(features, train_frac=0.7, validation_frac=0.15)
        assert len(result.train) == 70
        assert len(result.validation) == 15
        assert len(result.test) == 15

    def test_train_set_is_strictly_earlier_than_test_set(self) -> None:
        features = _features(20)
        result = chronological_split(features, train_frac=0.5, validation_frac=0.25)
        assert max(f.ts for f in result.train) < min(f.ts for f in result.test)

    def test_handles_unordered_input(self) -> None:
        features = _features(10)
        shuffled = list(reversed(features))
        result = chronological_split(shuffled, train_frac=0.6, validation_frac=0.2)
        assert result.train[0].ts == features[0].ts

    def test_rejects_fractions_summing_to_one_or_more(self) -> None:
        with pytest.raises(ValueError, match="must be < 1.0"):
            chronological_split(_features(10), train_frac=0.7, validation_frac=0.3)

    def test_rejects_out_of_range_fraction(self) -> None:
        with pytest.raises(ValueError, match=r"must each be in \(0, 1\)"):
            chronological_split(_features(10), train_frac=1.5, validation_frac=0.1)
