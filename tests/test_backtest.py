import pandas as pd
import pytest

from app.engine.backtest import _supplier_metrics


def test_supplier_metrics_are_per_sku_and_diagnose_partner_outliers() -> None:
    comparison = pd.DataFrame(
        [
            {
                "sku_code": "NORMAL",
                "supplier": "IEK",
                "actual": 50,
                "our_forecast": 45,
                "partner_forecast": 50,
                "average_monthly_12": 10,
            },
            {
                "sku_code": "NORMAL",
                "supplier": "IEK",
                "actual": 50,
                "our_forecast": 45,
                "partner_forecast": 50,
                "average_monthly_12": 10,
            },
            {
                "sku_code": "OUTLIER",
                "supplier": "IEK",
                "actual": 10,
                "our_forecast": 15,
                "partner_forecast": 200,
                "average_monthly_12": 10,
            },
            {
                "sku_code": "OUTLIER",
                "supplier": "IEK",
                "actual": 10,
                "our_forecast": 15,
                "partner_forecast": 200,
                "average_monthly_12": 10,
            },
        ]
    )

    metrics = _supplier_metrics(comparison)

    assert metrics["sku_count"] == 2
    assert metrics["our_mdape"] == pytest.approx(0.3)
    assert metrics["our_bias"] == 0.0
    assert metrics["partner_mdape"] == pytest.approx(9.5)
    assert metrics["partner_bias"] == pytest.approx(500 / 120 - 1)
    assert metrics["partner_outlier_sku_count"] == 1
    assert metrics["partner_outlier_error_share"] == 1.0
