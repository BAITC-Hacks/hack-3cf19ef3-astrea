"""Compare the phase-2 forecast with the partner's recovered Excel method."""

from pathlib import Path
import sys
from typing import Dict

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engine.forecast import forecast_months  # noqa: E402
from app.engine.metrics import wape  # noqa: E402
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


def run_backtest(data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return WAPE for both methods and both suppliers on Jul-Aug 2026."""

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

    profiles, _, _, _ = prepare_forecasts(data, TRAIN_END)
    profiles = profiles.merge(eligible, on=KEYS, how="inner")
    ours = forecast_months(profiles, TARGET_MONTHS).rename(
        columns={"forecast": "our_forecast"}
    )
    partner = _partner_forecasts(monthly, eligible)

    actual = monthly.loc[monthly["period"].isin(TARGET_MONTHS), [*KEYS, "month", "qty"]]
    actual = actual.groupby([*KEYS, "month"], as_index=False)["qty"].sum().rename(
        columns={"qty": "actual"}
    )
    comparison = actual.merge(ours, on=[*KEYS, "month"], how="inner").merge(
        partner, on=[*KEYS, "month"], how="inner"
    )

    rows = []
    for supplier in ("IEK", "SE"):
        group = comparison.loc[comparison["supplier"].eq(supplier)]
        rows.append(
            {
                "supplier": supplier,
                "sku_count": int(group["sku_code"].nunique()),
                "our_wape": wape(group["actual"].to_numpy(), group["our_forecast"].to_numpy()),
                "partner_wape": wape(
                    group["actual"].to_numpy(), group["partner_forecast"].to_numpy()
                ),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    results = run_backtest(load_all(ROOT / "data" / "raw"))
    for row in results.itertuples(index=False):
        print(
            f"{row.supplier}: our WAPE={row.our_wape:.4f} ({row.our_wape:.2%}), "
            f"partner WAPE={row.partner_wape:.4f} ({row.partner_wape:.2%}), "
            f"SKU={row.sku_count}"
        )


if __name__ == "__main__":
    main()
