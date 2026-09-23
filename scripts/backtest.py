"""Compare the phase-2 forecast with the partner's recovered Excel method."""

from pathlib import Path
import sys
from time import perf_counter
from typing import Dict

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engine.forecast import forecast_months  # noqa: E402
from app.engine.metrics import mdape, wape  # noqa: E402
from app.engine.ml import (  # noqa: E402
    build_prediction_frame,
    build_training_frame,
    feature_importance,
    predict,
    train_model,
)
from app.engine.pipeline import prepare_forecasts  # noqa: E402
from app.loaders import load_all  # noqa: E402


KEYS = ["sku_code", "supplier"]
TRAIN_END = pd.Period("2026-06", freq="M")
TARGET_MONTHS = [pd.Period("2026-07", freq="M"), pd.Period("2026-08", freq="M")]


def _sum_periods(values: Dict[pd.Period, float], periods: list[pd.Period]) -> float:
    return sum(float(values.get(period, 0.0)) for period in periods)


def _partner_forecasts(monthly: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    frame = monthly.merge(eligible, on=KEYS, how="inner").copy()
    frame["period"] = pd.PeriodIndex(frame["month"], freq="M")
    frame["qty"] = pd.to_numeric(frame["qty"], errors="coerce").fillna(0.0).clip(lower=0.0)

    base_months = list(pd.period_range("2025-07", "2026-06", freq="M"))
    current_quarter = list(pd.period_range("2026-04", "2026-06", freq="M"))
    prior_quarter = list(pd.period_range("2025-04", "2025-06", freq="M"))
    next_season_prior_year = list(pd.period_range("2025-07", "2025-09", freq="M"))

    rows = []
    for key, sku_frame in frame.groupby(KEYS, sort=False):
        values = sku_frame.groupby("period")["qty"].sum().to_dict()
        average_12 = _sum_periods(values, base_months) / 12.0
        prior = _sum_periods(values, prior_quarter)
        growth_factor = 1.0 if prior == 0 else _sum_periods(values, current_quarter) / prior
        season_factor = (
            1.0 if prior == 0 else _sum_periods(values, next_season_prior_year) / prior
        )
        forecast = average_12 * growth_factor * season_factor
        for month in TARGET_MONTHS:
            rows.append(
                {
                    "sku_code": key[0],
                    "supplier": key[1],
                    "month": str(month),
                    "partner_forecast": forecast,
                }
            )
    return pd.DataFrame(rows)


def _average_monthly_sales_12(
    monthly: pd.DataFrame, eligible: pd.DataFrame
) -> pd.DataFrame:
    """Return the partner method's 12-month baseline for outlier reporting."""

    frame = monthly.merge(eligible, on=KEYS, how="inner").copy()
    frame["period"] = pd.PeriodIndex(frame["month"], freq="M")
    base_window = frame["period"].between(
        pd.Period("2025-07", freq="M"), TRAIN_END
    )
    totals = (
        frame.loc[base_window]
        .groupby(KEYS, as_index=False)["qty"]
        .sum()
        .rename(columns={"qty": "base_12_total"})
    )
    totals["average_monthly_12"] = totals.pop("base_12_total") / 12.0
    return totals


def _supplier_metrics(group: pd.DataFrame) -> Dict[str, object]:
    """Summarize accuracy and partner-instability diagnostics at SKU level."""

    aggregations = dict(
        actual=("actual", "sum"),
        our_forecast=("our_forecast", "sum"),
        partner_forecast=("partner_forecast", "sum"),
        partner_monthly_forecast=("partner_forecast", "first"),
        average_monthly_12=("average_monthly_12", "first"),
    )
    if "ml_forecast" in group:
        aggregations["ml_forecast"] = ("ml_forecast", "sum")
    by_sku = group.groupby(KEYS, as_index=False).agg(**aggregations)
    partner_error = (by_sku["actual"] - by_sku["partner_forecast"]).abs()
    partner_outlier = by_sku["partner_monthly_forecast"].gt(
        10 * by_sku["average_monthly_12"]
    )
    total_partner_error = float(partner_error.sum())
    outlier_error_share = (
        float(partner_error.loc[partner_outlier].sum() / total_partner_error)
        if total_partner_error
        else float("nan")
    )

    metrics = {
        "supplier": str(group["supplier"].iloc[0]),
        "sku_count": int(len(by_sku)),
        "our_wape": wape(by_sku["actual"].to_numpy(), by_sku["our_forecast"].to_numpy()),
        "our_mdape": mdape(
            by_sku["actual"].to_numpy(), by_sku["our_forecast"].to_numpy()
        ),
        "partner_wape": wape(
            by_sku["actual"].to_numpy(), by_sku["partner_forecast"].to_numpy()
        ),
        "partner_mdape": mdape(
            by_sku["actual"].to_numpy(), by_sku["partner_forecast"].to_numpy()
        ),
        "partner_outlier_sku_count": int(partner_outlier.sum()),
        "partner_outlier_error_share": outlier_error_share,
    }
    if "ml_forecast" in by_sku:
        metrics["ml_wape"] = wape(
            by_sku["actual"].to_numpy(), by_sku["ml_forecast"].to_numpy()
        )
        metrics["ml_mdape"] = mdape(
            by_sku["actual"].to_numpy(), by_sku["ml_forecast"].to_numpy()
        )
    return metrics


def run_backtest(data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return robust accuracy metrics and diagnostics for Jul-Aug 2026."""

    monthly = data["sales_monthly"].copy()
    monthly["period"] = pd.PeriodIndex(monthly["month"], freq="M")
    monthly["qty"] = pd.to_numeric(monthly["qty"], errors="coerce").fillna(0.0).clip(lower=0.0)
    eligibility_window = monthly["period"].between(
        pd.Period("2025-07", freq="M"), TRAIN_END
    )
    eligible = (
        monthly.loc[eligibility_window]
        .groupby(KEYS, as_index=False)["qty"]
        .agg(active_months=lambda values: int(values.gt(0).sum()))
    )
    eligible = eligible.loc[eligible["active_months"].ge(9), KEYS]

    profiles, segments, _, stockouts = prepare_forecasts(data, TRAIN_END)
    profiles = profiles.merge(eligible, on=KEYS, how="inner")
    ours = forecast_months(profiles, TARGET_MONTHS).rename(
        columns={"forecast": "our_forecast"}
    )
    partner = _partner_forecasts(monthly, eligible)
    training = build_training_frame(
        stockouts.monthly, segments, data["sku_ref"], TRAIN_END
    )
    training_started = perf_counter()
    model = train_model(training)
    training_seconds = perf_counter() - training_started
    ml_frame = build_prediction_frame(
        stockouts.monthly,
        segments,
        data["sku_ref"],
        TRAIN_END,
        range(1, 3),
    )
    ml = predict(model, ml_frame)
    average_12 = _average_monthly_sales_12(monthly, eligible)

    actual = monthly.loc[monthly["period"].isin(TARGET_MONTHS), [*KEYS, "month", "qty"]]
    actual = actual.groupby([*KEYS, "month"], as_index=False)["qty"].sum().rename(
        columns={"qty": "actual"}
    )
    comparison = actual.merge(ours, on=[*KEYS, "month"], how="inner").merge(
        partner, on=[*KEYS, "month"], how="inner"
    )
    comparison = comparison.merge(ml, on=[*KEYS, "month"], how="inner")
    comparison = comparison.merge(average_12, on=KEYS, how="left")

    rows = []
    for supplier in ("IEK", "SE"):
        group = comparison.loc[comparison["supplier"].eq(supplier)]
        rows.append(_supplier_metrics(group))
    results = pd.DataFrame(rows)
    results.attrs["ml_training_rows"] = len(training)
    results.attrs["ml_training_seconds"] = training_seconds
    results.attrs["feature_importance"] = feature_importance(model, training)
    return results


def main() -> None:
    results = run_backtest(load_all(ROOT / "data" / "raw"))
    print(
        f"ML training: rows={results.attrs['ml_training_rows']}, "
        f"seconds={results.attrs['ml_training_seconds']:.2f}"
    )
    for row in results.itertuples(index=False):
        print(f"{row.supplier}: SKU={row.sku_count}")
        print(
            f"  Formula: WAPE={row.our_wape:.4f} ({row.our_wape:.2%}), "
            f"MdAPE={row.our_mdape:.4f} ({row.our_mdape:.2%})"
        )
        print(
            f"  ML: WAPE={row.ml_wape:.4f} ({row.ml_wape:.2%}), "
            f"MdAPE={row.ml_mdape:.4f} ({row.ml_mdape:.2%})"
        )
        print(
            f"  Partner: WAPE={row.partner_wape:.4f} ({row.partner_wape:.2%}), "
            f"MdAPE={row.partner_mdape:.4f} ({row.partner_mdape:.2%})"
        )
        print(
            "  Partner outliers (>10× 12-month average): "
            f"{row.partner_outlier_sku_count} SKU, "
            f"{row.partner_outlier_error_share:.2%} of partner absolute error"
        )
    print("ML feature importance (top 10):")
    for item in results.attrs["feature_importance"].itertuples(index=False):
        print(f"  {item.feature}: {item.importance:.6f}")


if __name__ == "__main__":
    main()
