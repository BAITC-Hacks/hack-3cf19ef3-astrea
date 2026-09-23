"""Evaluation metrics shared by tests and the real-data backtest."""

import numpy as np


def wape(actual: np.ndarray, forecast: np.ndarray) -> float:
    """Weighted absolute percentage error; return NaN when actual demand is zero."""

    actual_values = np.asarray(actual, dtype=float)
    forecast_values = np.asarray(forecast, dtype=float)
    denominator = np.abs(actual_values).sum()
    if denominator == 0:
        return float("nan")
    return float(np.abs(actual_values - forecast_values).sum() / denominator)
