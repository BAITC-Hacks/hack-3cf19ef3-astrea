import numpy as np
import pandas as pd

from app.config import EngineConfig
from app.engine.ml import (
    FEATURE_COLUMNS,
    build_prediction_frame,
    build_training_frame,
    predict,
    train_model,
)
from app.engine.pipeline import build_recommendations


def _ml_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    keys = [
        ("IEK-1", "IEK", "без категории"),
        ("IEK-2", "IEK", "без категории"),
        ("SE-1", "SE", "1"),
        ("SE-2", "SE", "2"),
    ]
    months = pd.period_range("2024-01", "2026-08", freq="M")
    rows = []
    for sku_index, (sku_code, supplier, _) in enumerate(keys, start=1):
        for month_index, month in enumerate(months):
            rows.append(
                {
                    "sku_code": sku_code,
                    "supplier": supplier,
                    "month": str(month),
                    "demand": float(10 * sku_index + month.month + month_index % 3),
                    "is_stockout": False,
                }
            )
    demand = pd.DataFrame(rows)
    segments = pd.DataFrame(
        [
            {
                "sku_code": sku_code,
                "supplier": supplier,
                "segment": "regular",
                "active_months": 12,
                "max_level": 100.0,
            }
            for sku_code, supplier, _ in keys
        ]
    )
    sku_ref = pd.DataFrame(
        [
            {
                "sku_code": sku_code,
                "supplier": supplier,
                "name": sku_code,
                "article": sku_code,
                "unit": "шт",
                "category": category,
            }
            for sku_code, supplier, category in keys
        ]
    )
    return demand, segments, sku_ref


def _pipeline_data() -> dict[str, pd.DataFrame]:
    demand, _, sku_ref = _ml_inputs()
    monthly = demand.rename(columns={"demand": "qty"})[
        ["sku_code", "supplier", "month", "qty"]
    ]
    transactions = monthly.loc[monthly["qty"].gt(0)].copy()
    transactions["date"] = pd.PeriodIndex(
        transactions["month"], freq="M"
    ).to_timestamp() + pd.Timedelta(days=4)
    transactions = transactions[["date", "sku_code", "supplier", "qty"]]
    transactions = pd.concat(
        [
            transactions,
            pd.DataFrame(
                [
                    {
                        "date": pd.Timestamp("2026-09-22"),
                        "sku_code": "IEK-1",
                        "supplier": "IEK",
                        "qty": 10.0,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    stock = monthly.rename(columns={"qty": "opening_stock"}).copy()
    stock["opening_stock"] = 100.0
    keys = sku_ref[["sku_code", "supplier"]].copy()
    current_stock = keys.assign(free_stock=0.0, stock_unknown=False)
    in_transit = keys.assign(qty=0.0)
    moq = keys.assign(moq=pd.Series([1] * len(keys), dtype="Int64"))
    return {
        "sales_tx": transactions,
        "sales_monthly": monthly,
        "stock_monthly": stock,
        "current_stock": current_stock,
        "in_transit": in_transit,
        "moq": moq,
        "sku_ref": sku_ref,
    }


def test_prediction_features_do_not_use_future_demand() -> None:
    demand, segments, sku_ref = _ml_inputs()
    origin = pd.Period("2025-12", freq="M")
    baseline = build_prediction_frame(demand, segments, sku_ref, origin, [1, 2])
    changed = demand.copy()
    future = pd.PeriodIndex(changed["month"], freq="M") > origin
    changed.loc[future, "demand"] = 999999.0
    after = build_prediction_frame(changed, segments, sku_ref, origin, [1, 2])

    pd.testing.assert_frame_equal(baseline[FEATURE_COLUMNS], after[FEATURE_COLUMNS])


def test_training_frame_has_past_targets_and_complete_features() -> None:
    demand, segments, sku_ref = _ml_inputs()
    train_end = pd.Period("2026-06", freq="M")
    frame = build_training_frame(demand, segments, sku_ref, train_end)

    assert not frame.empty
    assert (pd.PeriodIndex(frame["month"], freq="M") <= train_end).all()
    assert not frame[FEATURE_COLUMNS + ["target"]].isna().any().any()


def test_model_produces_finite_non_negative_forecasts() -> None:
    demand, segments, sku_ref = _ml_inputs()
    training = build_training_frame(
        demand, segments, sku_ref, pd.Period("2026-06", freq="M")
    )
    model = train_model(training)
    prediction_frame = build_prediction_frame(
        demand, segments, sku_ref, pd.Period("2026-06", freq="M"), [1, 2]
    )
    forecasts = predict(model, prediction_frame)

    assert np.isfinite(forecasts["ml_forecast"]).all()
    assert forecasts["ml_forecast"].ge(0).all()


def test_ml_recommendations_include_both_forecasts() -> None:
    orders, _ = build_recommendations(
        _pipeline_data(), EngineConfig(forecast_method="ml")
    )

    assert not orders.empty
    assert orders["explanation"].str.contains("ML-прогноз").all()
    assert orders["explanation"].str.contains("формула").all()
