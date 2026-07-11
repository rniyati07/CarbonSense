from __future__ import annotations

from services.calibration.dto import FeedbackLabel
from services.calibration.mapie_wrapper import ConformalPredictor


def _labels(n: int) -> list[FeedbackLabel]:
    # Two classes present, spread across the score range -- enough for
    # SplitConformalClassifier to conformalize on.
    return [
        FeedbackLabel(
            action="confirmed" if i % 3 else "dismissed",
            ml_anomaly_score=0.1 * (i % 10),
        )
        for i in range(1, n + 1)
    ]


class TestConformalPredictor:
    """Regression coverage for the pre-ENG-4 integration audit finding:
    this branch was written against mapie 0.x's MapieClassifier(cv="prefit"),
    which was removed in the installed mapie 1.4.1 in favor of
    SplitConformalClassifier -- ConformalPredictor could not be imported at
    all before this fix. No test file existed for this module previously
    (test_service.py mocks ConformalPredictor out entirely), so the migration
    itself was unverified beyond "does it import."
    """

    def test_fit_and_predict_produce_real_calibrated_bands(self) -> None:
        predictor = ConformalPredictor(target_confidence_level=0.9)
        predictor.fit(_labels(40))

        assert predictor._fitted is True

        bands = predictor.predict([0.2, 0.5, 0.8])

        assert len(bands) == 3
        for lower, upper in bands:
            assert 0.0 <= lower <= upper <= 1.0
        # A genuinely fitted predictor should not degenerate to the (0.0, 1.0)
        # wide fallback band for every input -- that would mean fit() silently
        # failed and predict() fell through to its fallback path.
        assert bands != [(0.0, 1.0)] * 3

    def test_empty_calibration_set_stays_unfit(self) -> None:
        predictor = ConformalPredictor()
        predictor.fit([])

        assert predictor._fitted is False
        assert predictor.predict([0.3, 0.7]) == [(0.0, 1.0), (0.0, 1.0)]

    def test_single_class_calibration_set_falls_back_to_wide_bands(self) -> None:
        """MAPIE requires >=2 classes to conformalize; a building whose
        feedback so far is all-confirmed or all-dismissed must degrade to
        the cold-start-style wide band rather than raise."""
        predictor = ConformalPredictor()
        predictor.fit([FeedbackLabel(action="confirmed", ml_anomaly_score=0.5)] * 10)

        assert predictor._fitted is False
        assert predictor.predict([0.5]) == [(0.0, 1.0)]

    def test_predict_before_fit_returns_wide_bands(self) -> None:
        predictor = ConformalPredictor()
        assert predictor.predict([0.1, 0.9]) == [(0.0, 1.0), (0.0, 1.0)]
