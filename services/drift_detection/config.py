from __future__ import annotations

from typing import Dict, Optional
from pydantic import BaseModel, Field

class DriftThresholdConfig(BaseModel):
    """Configuration for Mann-Kendall trend detection thresholds."""
    p_value_threshold: float = Field(default=0.05, description="Significance level for trend test")
    min_window_days: int = Field(default=14, description="Minimum days of history required")
    min_data_points: int = Field(default=10, description="Minimum number of valid readings required")

class DriftDetectionConfig(BaseModel):
    """Configuration for Drift Detection Service."""
    
    default_threshold: DriftThresholdConfig = Field(default_factory=DriftThresholdConfig)
    
    # Keyed by "building_type:climate_zone" or just "building_type:default"
    overrides: Dict[str, DriftThresholdConfig] = Field(default_factory=dict)
    
    def get_threshold(self, building_type: str, climate_zone: Optional[str] = None) -> DriftThresholdConfig:
        """Get the drift threshold configuration for a specific building context."""
        if climate_zone:
            key = f"{building_type}:{climate_zone}"
            if key in self.overrides:
                return self.overrides[key]
        
        type_key = f"{building_type}:default"
        if type_key in self.overrides:
            return self.overrides[type_key]
            
        return self.default_threshold
