"""Configuration values fixed by the approved phase-2 plan."""

from dataclasses import dataclass, field
from typing import Literal, Mapping, Optional

import pandas as pd


LEAD_TIME_DAYS = {"IEK": 24, "SE": 35}
COVERAGE_DAYS = 30
SERVICE_Z = 1.65
PLANNED_GROWTH = {"IEK": 0.0, "SE": 0.0}


@dataclass(frozen=True)
class EngineConfig:
    """Runtime overrides allowed by the calculation pipeline."""

    as_of: Optional[pd.Timestamp] = None
    lead_time_days: Mapping[str, int] = field(
        default_factory=lambda: dict(LEAD_TIME_DAYS)
    )
    coverage_days: int = COVERAGE_DAYS
    service_z: float = SERVICE_Z
    planned_growth: Mapping[str, float] = field(
        default_factory=lambda: dict(PLANNED_GROWTH)
    )
    forecast_method: Literal["formula", "ml"] = "formula"


def resolve_as_of(sales_tx: pd.DataFrame, config: EngineConfig) -> pd.Timestamp:
    """Use an explicit cutoff or the latest transaction in the loaded data."""

    value = config.as_of if config.as_of is not None else sales_tx["date"].max()
    if pd.isna(value):
        raise ValueError("AS_OF cannot be determined without a transaction date")
    return pd.Timestamp(value).normalize()
