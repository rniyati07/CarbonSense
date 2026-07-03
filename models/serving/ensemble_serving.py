"""ENG-3d-4 — ML Ensemble serving microservice.

Loads the currently-promoted Isolation Forest and Windowed Autoencoder for a
given (tenant, building) pair and runs inference over a list of FeatureSetV1
rows, producing one EnsembleScoreRecord per input row.

Architecture constraints
------------------------
- Loading is always done through ModelRegistryProtocol so the serving layer is
  testable without a running MLflow server.
- The scaler travels with the model (ENG-3d-1 spec / DATA_AND_MODEL_STRATEGY §4.1).
  The serving layer does NOT maintain a separate scaler; it loads both together.
- One call per (tenant, building) pair — the caller is responsible for grouping.
- Latency target: contributes to the overall < 5-minute analysis pipeline target
  from TRD §9.1.  All I/O is at load time; inference is in-process (numpy/torch).
- This module must NOT import from apps/api — the boundary runs the other way.
"""

from __future__ import annotations

import logging
from uuid import UUID

import numpy as np

from models.feature_store.feature_set_v1 import FeatureSetV1
from models.training.autoencoder import _build_windows
from services.ml_ensemble.feature_assembly import (
    assemble_feature_vector_matrix,
    collect_rule_ids,
)
from services.ml_ensemble.interfaces import ModelRegistryProtocol
from services.ml_ensemble.models import (
    AutoencoderWindowScore,
    EnsembleScoreRecord,
    IsolationForestScore,
)

logger = logging.getLogger(__name__)


class EnsembleServingService:
    """Lightweight inference service for the ML Ensemble.

    Loads models from the registry once per call (at construction time the
    registry is injected; models are loaded lazily on the first score() call
    for a given (tenant, building) pair and can be cached by the caller).

    Parameters
    ----------
    registry:
        Implementation of ModelRegistryProtocol.  In production this is
        MLflowModelRegistry; in tests an InMemoryModelRegistry is injected.
    """

    def __init__(self, registry: ModelRegistryProtocol) -> None:
        self._registry = registry

    def score(
        self,
        tenant_id: UUID,
        building_id: UUID,
        features: list[FeatureSetV1],
        window_length_hours: int = 24,
        max_batch_size: int = 512,
    ) -> list[EnsembleScoreRecord]:
        """Run IF + AE inference over a list of FeatureSetV1 rows.

        Both models are attempted.  If one fails to load (e.g., not yet
        trained), its scores are set to None and the flag defaults to False.

        Parameters
        ----------
        tenant_id, building_id:
            Identifies which (tenant, building) model pair to load.
        features:
            FeatureSetV1 rows to score, in any order.  Will be sorted by ts
            internally for window alignment.
        window_length_hours:
            Must match the window_length_hours used at training time.
            Sourced from MLEnsembleConfig by the caller.
        max_batch_size:
            Maximum number of rows processed per numpy batch (for memory safety).

        Returns
        -------
        list[EnsembleScoreRecord]
            One record per input feature row, sorted by ascending ts.
            low_data_quality rows are passed through with anomaly flags=False.
        """
        if not features:
            return []

        sorted_features = sorted(features, key=lambda f: f.ts)

        if_scores_map: dict[int, IsolationForestScore] = {}
        ae_scores_map: dict[int, AutoencoderWindowScore] = {}

        if_scores_map = self._run_isolation_forest(
            tenant_id, building_id, sorted_features, max_batch_size
        )
        ae_scores_map = self._run_autoencoder(
            tenant_id, building_id, sorted_features, window_length_hours
        )

        records: list[EnsembleScoreRecord] = []
        for idx, feat in enumerate(sorted_features):
            if_rec = if_scores_map.get(idx)
            ae_rec = ae_scores_map.get(idx)

            if_score_val = if_rec.if_score if if_rec else None
            if_flag = if_rec.is_anomalous if if_rec else False
            ae_err = ae_rec.reconstruction_error if ae_rec else None
            ae_flag = ae_rec.is_anomalous if ae_rec else False

            records.append(
                EnsembleScoreRecord(
                    tenant_id=feat.tenant_id,
                    circuit_id=feat.circuit_id,
                    ts=feat.ts,
                    if_score=if_score_val,
                    if_is_anomalous=if_flag,
                    ae_reconstruction_error=ae_err,
                    ae_is_anomalous=ae_flag,
                    ensemble_is_anomalous=if_flag or ae_flag,
                    low_data_quality=feat.low_data_quality,
                )
            )

        return records

    # ------------------------------------------------------------------ #
    # Internal inference methods
    # ------------------------------------------------------------------ #

    def _run_isolation_forest(
        self,
        tenant_id: UUID,
        building_id: UUID,
        sorted_features: list[FeatureSetV1],
        max_batch_size: int,
    ) -> dict[int, IsolationForestScore]:
        try:
            model, _scaler, rule_ids = self._registry.load_isolation_forest(
                tenant_id, building_id
            )
        except Exception:
            logger.warning(
                "IF model not available for tenant=%s building=%s — skipping IF scores",
                tenant_id,
                building_id,
            )
            return {}

        result: dict[int, IsolationForestScore] = {}
        usable_indices = [i for i, f in enumerate(sorted_features) if not f.low_data_quality]
        if not usable_indices:
            return result

        for batch_start in range(0, len(usable_indices), max_batch_size):
            batch_idxs = usable_indices[batch_start : batch_start + max_batch_size]
            batch_feats = [sorted_features[i] for i in batch_idxs]
            raw_matrix = np.array(assemble_feature_vector_matrix(batch_feats, rule_ids), dtype=float)
            scaled = _scaler.transform(raw_matrix)
            scores = model.decision_function(scaled)
            for local_i, global_i in enumerate(batch_idxs):
                feat = sorted_features[global_i]
                result[global_i] = IsolationForestScore(
                    tenant_id=feat.tenant_id,
                    circuit_id=feat.circuit_id,
                    ts=feat.ts,
                    if_score=float(scores[local_i]),
                    is_anomalous=bool(scores[local_i] < 0),
                )

        return result

    def _run_autoencoder(
        self,
        tenant_id: UUID,
        building_id: UUID,
        sorted_features: list[FeatureSetV1],
        window_length_hours: int,
    ) -> dict[int, AutoencoderWindowScore]:
        try:
            ae, _scaler, rule_ids = self._registry.load_autoencoder(tenant_id, building_id)
        except Exception:
            logger.warning(
                "AE model not available for tenant=%s building=%s — skipping AE scores",
                tenant_id,
                building_id,
            )
            return {}

        usable_indices = [i for i, f in enumerate(sorted_features) if not f.low_data_quality]
        if len(usable_indices) < window_length_hours:
            return {}

        usable_feats = [sorted_features[i] for i in usable_indices]
        raw_matrix = np.array(assemble_feature_vector_matrix(usable_feats, rule_ids), dtype=float)
        scaled_matrix = _scaler.transform(raw_matrix)
        windows = _build_windows(scaled_matrix, window_length_hours)
        if len(windows) == 0:
            return {}

        errors = ae.reconstruct(windows)
        anomaly_flags = ae.is_anomalous(errors)

        result: dict[int, AutoencoderWindowScore] = {}
        for win_i, global_i in enumerate(usable_indices[window_length_hours - 1 :]):
            window_start_global = usable_indices[win_i]
            window_end_feat = sorted_features[global_i]
            window_start_feat = sorted_features[window_start_global]
            result[global_i] = AutoencoderWindowScore(
                tenant_id=window_end_feat.tenant_id,
                circuit_id=window_end_feat.circuit_id,
                window_start=window_start_feat.ts,
                window_end=window_end_feat.ts,
                reconstruction_error=float(errors[win_i]),
                is_anomalous=bool(anomaly_flags[win_i]),
            )

        return result
