"""ENG-6b — chronological train/validation/test split.

A random split would leak future information into the training set for
time-series anomaly detection (a model could effectively "see the future"
via interpolation between adjacent, randomly-shuffled windows). The split
is chronological instead: earliest rows train, a middle slice validates,
the most recent slice tests -- consistent with how retraining itself
works (train on history, evaluate against what's most recently observed).
"""

from __future__ import annotations

from dataclasses import dataclass

from models.feature_store.feature_set_v1 import FeatureSetV1


@dataclass(frozen=True)
class DatasetSplit:
    train: list[FeatureSetV1]
    validation: list[FeatureSetV1]
    test: list[FeatureSetV1]


def chronological_split(
    features: list[FeatureSetV1],
    train_frac: float = 0.7,
    validation_frac: float = 0.15,
) -> DatasetSplit:
    """Split `features` into chronological train/validation/test sets.

    Parameters
    ----------
    features:
        Any order; sorted by timestamp internally before splitting.
    train_frac, validation_frac:
        Fractions of the total row count. The remainder (1 - train_frac -
        validation_frac) becomes the test set. Must each be in (0, 1) and
        sum to less than 1.
    """
    if not (0.0 < train_frac < 1.0) or not (0.0 < validation_frac < 1.0):
        raise ValueError("train_frac and validation_frac must each be in (0, 1)")
    if train_frac + validation_frac >= 1.0:
        raise ValueError("train_frac + validation_frac must be < 1.0 to leave a test set")

    ordered = sorted(features, key=lambda f: f.ts)
    n = len(ordered)
    train_end = int(n * train_frac)
    validation_end = train_end + int(n * validation_frac)

    return DatasetSplit(
        train=ordered[:train_end],
        validation=ordered[train_end:validation_end],
        test=ordered[validation_end:],
    )
