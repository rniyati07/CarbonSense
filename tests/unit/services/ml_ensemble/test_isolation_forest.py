"""ENG-3d-2 — IsolationForestTrainer unit tests.

Covers:
- Trains without error on normal feature corpus
- Catches global outliers (decision score < 0 for outlier points)
- Per-building scaler is fitted and persisted as MLflow artifact
- TrainingRunResult carries correct metadata
- low_data_quality rows are excluded from training
- Minimum sample guard raises ValueError
"""

from __future__ import annotations

import numpy as np
import pytest

from models.feature_store.feature_set_v1 import FeatureSetV1
from models.training.isolation_forest import IsolationForestTrainer
from services.ml_ensemble.config import MLEnsembleConfig
from services.ml_ensemble.feature_assembly import assemble_feature_vector_matrix, collect_rule_ids
from tests.fixtures.ml_ensemble.golden_fixture import (
    BUILDING_ID,
    TENANT_ID,
    make_global_outlier_features,
    make_normal_features,
    make_training_corpus,
)
from tests.unit.services.ml_ensemble.conftest import BUILDING, TENANT


class TestIsolationForestTrainer:
    @pytest.fixture()
    def trainer(self) -> IsolationForestTrainer:
        return IsolationForestTrainer()

    @pytest.fixture()
    def fast_cfg(self) -> MLEnsembleConfig:
        return MLEnsembleConfig(n_estimators=10, contamination=0.05)

    def test_trains_on_normal_corpus(
        self,
        trainer: IsolationForestTrainer,
        training_corpus: list[FeatureSetV1],
        fast_cfg: MLEnsembleConfig,
        mlflow_tracking_uri: str,
    ) -> None:
        result = trainer.train(
            tenant_id=TENANT,
            building_id=BUILDING,
            features=training_corpus,
            config=fast_cfg,
            mlflow_tracking_uri=mlflow_tracking_uri,
        )
        assert result.mlflow_run_id != ""
        assert result.n_training_samples == len(training_corpus)
        assert result.model_type == "isolation_forest"

    def test_model_artifact_uri_is_set(
        self,
        trainer: IsolationForestTrainer,
        training_corpus: list[FeatureSetV1],
        fast_cfg: MLEnsembleConfig,
        mlflow_tracking_uri: str,
    ) -> None:
        result = trainer.train(
            tenant_id=TENANT,
            building_id=BUILDING,
            features=training_corpus,
            config=fast_cfg,
            mlflow_tracking_uri=mlflow_tracking_uri,
        )
        assert result.model_artifact.artifact_uri != ""
        assert result.scaler_artifact.artifact_uri != ""

    def test_scaler_artifact_logged_alongside_model(
        self,
        trainer: IsolationForestTrainer,
        training_corpus: list[FeatureSetV1],
        fast_cfg: MLEnsembleConfig,
        mlflow_tracking_uri: str,
    ) -> None:
        result = trainer.train(
            tenant_id=TENANT,
            building_id=BUILDING,
            features=training_corpus,
            config=fast_cfg,
            mlflow_tracking_uri=mlflow_tracking_uri,
        )
        assert result.model_artifact.run_id == result.scaler_artifact.run_id

    def test_rule_ids_used_is_sorted(
        self,
        trainer: IsolationForestTrainer,
        training_corpus: list[FeatureSetV1],
        fast_cfg: MLEnsembleConfig,
        mlflow_tracking_uri: str,
    ) -> None:
        result = trainer.train(
            tenant_id=TENANT,
            building_id=BUILDING,
            features=training_corpus,
            config=fast_cfg,
            mlflow_tracking_uri=mlflow_tracking_uri,
        )
        assert result.rule_ids_used == sorted(result.rule_ids_used)

    def test_catches_global_outliers(
        self,
        training_corpus: list[FeatureSetV1],
        fast_cfg: MLEnsembleConfig,
    ) -> None:
        """IF must assign negative scores to point anomalies with extreme magnitude.

        Trains in-memory (without MLflow) to isolate detection from artifact loading.
        MLflow artifact round-trip is covered by the integration test.
        """
        import numpy as np
        from sklearn.ensemble import IsolationForest
        from services.ml_ensemble.scaler import BuildingScaler

        rule_ids = collect_rule_ids(training_corpus)
        raw = np.array(assemble_feature_vector_matrix(training_corpus, rule_ids), dtype=float)
        scaler = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=rule_ids)
        scaled_train = scaler.fit_transform(raw)

        model = IsolationForest(
            n_estimators=fast_cfg.n_estimators,
            contamination=fast_cfg.contamination,
            random_state=fast_cfg.if_random_state,
        )
        model.fit(scaled_train)

        outliers = make_global_outlier_features(n_outliers=5)
        raw_out = np.array(assemble_feature_vector_matrix(outliers, rule_ids), dtype=float)
        scaled_out = scaler.transform(raw_out)
        scores = model.decision_function(scaled_out)
        anomaly_count = int(np.sum(scores < 0))
        assert anomaly_count >= 3, (
            f"IF flagged only {anomaly_count}/5 global outliers as anomalous. "
            "Expected at least 3 out of 5."
        )

    def test_low_data_quality_rows_excluded(
        self,
        trainer: IsolationForestTrainer,
        fast_cfg: MLEnsembleConfig,
        mlflow_tracking_uri: str,
    ) -> None:
        corpus = make_normal_features(n_days=10)
        # Mark half as low quality
        mixed: list[FeatureSetV1] = []
        for i, f in enumerate(corpus):
            if i % 2 == 0:
                mixed.append(f.model_copy(update={"low_data_quality": True}))
            else:
                mixed.append(f)
        usable_count = sum(1 for f in mixed if not f.low_data_quality)
        result = trainer.train(
            tenant_id=TENANT,
            building_id=BUILDING,
            features=mixed,
            config=fast_cfg,
            mlflow_tracking_uri=mlflow_tracking_uri,
        )
        assert result.n_training_samples == usable_count

    def test_insufficient_data_raises(
        self,
        trainer: IsolationForestTrainer,
        fast_cfg: MLEnsembleConfig,
        mlflow_tracking_uri: str,
    ) -> None:
        single = make_normal_features(n_days=1)[:1]
        with pytest.raises(ValueError, match="at least 2"):
            trainer.train(
                tenant_id=TENANT,
                building_id=BUILDING,
                features=single,
                config=fast_cfg,
                mlflow_tracking_uri=mlflow_tracking_uri,
            )

    def test_building_type_override_applied(
        self,
        trainer: IsolationForestTrainer,
        training_corpus: list[FeatureSetV1],
        mlflow_tracking_uri: str,
    ) -> None:
        cfg = MLEnsembleConfig(
            n_estimators=10,
            building_type_contamination_overrides={"office": 0.02},
        )
        result = trainer.train(
            tenant_id=TENANT,
            building_id=BUILDING,
            features=training_corpus,
            config=cfg,
            building_type="office",
            mlflow_tracking_uri=mlflow_tracking_uri,
        )
        assert result.metrics["contamination"] == pytest.approx(0.02)

    def test_per_tenant_isolation(
        self,
        trainer: IsolationForestTrainer,
        fast_cfg: MLEnsembleConfig,
        mlflow_tracking_uri: str,
    ) -> None:
        """Two tenants must produce independent run IDs (never pooled)."""
        from uuid import UUID

        other_tenant = UUID("deadbeef-dead-beef-dead-beefdeadbeef")
        corpus_a = make_normal_features(n_days=10)
        corpus_b = [f.model_copy(update={"tenant_id": other_tenant}) for f in corpus_a]

        result_a = trainer.train(
            tenant_id=TENANT,
            building_id=BUILDING,
            features=corpus_a,
            config=fast_cfg,
            mlflow_tracking_uri=mlflow_tracking_uri,
        )
        result_b = trainer.train(
            tenant_id=other_tenant,
            building_id=BUILDING,
            features=corpus_b,
            config=fast_cfg,
            mlflow_tracking_uri=mlflow_tracking_uri,
        )
        assert result_a.mlflow_run_id != result_b.mlflow_run_id
