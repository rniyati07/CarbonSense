"""models.feature_store — Versioned feature contract definitions.

ENG-3c-2 seed: FeatureSetV1STLFields defines the STL-derived columns
that ENG-3c contributes to feature_set_v1.

ENG-3d-1 will add the remaining columns (rolling stats, rule-fire
indicators, calendar features) and publish the finalised contract.
"""

from models.feature_store.feature_set_v1 import FeatureSetV1STLFields

__all__ = [
    "FeatureSetV1STLFields",
]
