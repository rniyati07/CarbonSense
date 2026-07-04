from __future__ import annotations

from pydantic_settings import BaseSettings


class CalibrationSettings(BaseSettings):
    model_config = {"env_prefix": "CALIBRATION_"}

    # Open Parameter: Minimum calibration sample threshold for exiting cold start
    # TODO(ENG-3f): Product/Data Science must ratify the final numeric threshold.
    min_calibration_samples: int = 30
    
    # Maximum window size for rolling calibration set
    max_history_samples: int = 500
    
    # Target confidence level for prediction intervals (e.g. 0.9 for 90% confidence)
    target_confidence_level: float = 0.9
