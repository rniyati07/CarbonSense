from __future__ import annotations

import logging
from collections.abc import Sequence

import numpy as np
from mapie.classification import SplitConformalClassifier
from sklearn.linear_model import LogisticRegression

from services.calibration.dto import FeedbackLabel

logger = logging.getLogger(__name__)


class ConformalPredictor:
    def __init__(self, target_confidence_level: float = 0.9) -> None:
        """
        Initializes the Mapie-based conformal predictor.
        Target confidence level defaults to 90% (alpha = 0.1).
        """
        self.target_confidence_level = target_confidence_level
        self.alpha = 1.0 - target_confidence_level
        # Using a simple logistic regression as the base estimator to map
        # ML ensemble anomaly scores to confirmation probabilities.
        #
        # DEPENDENCY FIX (pre-ENG-4 integration audit): pyproject.toml pins
        # mapie>=0.9, which is too loose -- 0.9's MapieClassifier(cv="prefit")
        # API was removed in mapie 1.x in favor of SplitConformalClassifier.
        # This branch was written against the 0.x API and could not import at
        # all against the installed 1.4.1. SplitConformalClassifier(prefit=True)
        # is the direct replacement for cv="prefit": it still expects a
        # pre-fit estimator and skips its own .fit() step.
        self._estimator = SplitConformalClassifier(
            estimator=LogisticRegression(),
            confidence_level=target_confidence_level,
            prefit=True,
        )
        # Kept separately rather than read back off self._estimator: 1.x's
        # SplitConformalClassifier does not expose the wrapped estimator as a
        # public .estimator attribute the way 0.x's MapieClassifier did.
        self._base_estimator: LogisticRegression | None = None
        self._fitted = False

    def fit(self, labels: Sequence[FeedbackLabel]) -> None:
        """
        Fits the conformal predictor on the rolling calibration set.
        """
        if not labels:
            logger.warning("Empty calibration set provided to ConformalPredictor.fit()")
            return

        # Prepare x (anomaly scores) and y (binary labels: confirmed=1, dismissed=0)
        x = np.array([[label.ml_anomaly_score] for label in labels])
        y = np.array([1 if label.action == "confirmed" else 0 for label in labels])

        # Fit the base estimator manually first (since prefit=True).
        # In a real scenario with complex features, a more robust model might be used,
        # but LogisticRegression is sufficient for 1D score calibration.
        base_lr = LogisticRegression()

        # If there's only one class present in the labels, we cannot fit properly.
        if len(np.unique(y)) < 2:
            logger.warning(
                "Only one class present in calibration set, fallback to dummy estimator."
            )
            # MAPIE requires at least 2 classes for fitting.
            # In a true implementation, we might skip conformal calibration for this building
            # and use cold-start bounds. We'll leave the estimator unfit.
            return

        base_lr.fit(x, y)
        # SplitConformalClassifier(prefit=True) takes the pre-fit estimator,
        # and .conformalize() replaces the old cv="prefit" .fit(X, y) call as
        # the actual conformalization step against the 1.x API.
        self._estimator = SplitConformalClassifier(
            estimator=base_lr,
            confidence_level=self.target_confidence_level,
            prefit=True,
        )
        self._estimator.conformalize(x, y)
        self._base_estimator = base_lr
        self._fitted = True

    def predict(self, anomaly_scores: list[float]) -> list[tuple[float, float]]:
        """
        Returns confidence bands (lower_bound, upper_bound) for the given scores.
        """
        if not self._fitted or self._base_estimator is None:
            # Not fitted (e.g., due to single-class calibration set)
            # Return wide fallback bands.
            return [(0.0, 1.0) for _ in anomaly_scores]

        x = np.array([[score] for score in anomaly_scores])

        try:
            # predict_set returns (y_pred, y_pss); y_pss is the boolean
            # prediction-set array, shape (n_samples, n_classes) at this
            # single confidence_level -- the 1.x equivalent of the old
            # y_pis[:, :, alpha_idx] slice.
            _, y_pss = self._estimator.predict_set(x)

            # Since TRD asks for "confidence interval/percentage", extract the
            # predicted probability from the base estimator and widen/narrow
            # it depending on whether the conformal prediction set includes
            # the "confirmed" class -- same heuristic mapping as before the
            # dependency migration, just against the 1.x return shape.
            probs = self._base_estimator.predict_proba(x)[:, 1]

            results = []
            for i, prob in enumerate(probs):
                class1_included = bool(y_pss[i, 1])
                if class1_included:
                    lower = max(0.0, prob - (1 - self.target_confidence_level))
                    upper = min(1.0, prob + (1 - self.target_confidence_level))
                else:
                    lower, upper = 0.0, max(0.0, prob)
                results.append((float(lower), float(upper)))
            return results

        except Exception as e:
            logger.error("Error during Mapie prediction: %s", e)
            return [(0.0, 1.0) for _ in anomaly_scores]
