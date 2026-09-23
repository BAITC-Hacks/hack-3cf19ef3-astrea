"""Seasonal, year-over-year demand forecasts for regular SKUs."""

from typing import Iterable, List

import numpy as np
import pandas as pd


KEYS = ["sku_code", "supplier"]
FULL_SEASONAL_YEARS = (2024, 2025)


def supplier_seasonal_indices(
    monthly: pd.DataFrame, value_column: str = "demand"
) -> pd.DataFrame:
    """Calculate supplier month indices from complete 2024 and 2025 totals."""

    frame = monthly.copy()
    frame["period"] = pd.PeriodIndex(frame["month"], freq="M")
    frame["year"] = frame["period"].dt.year
    frame["month_num"] = frame["period"].dt.month
    frame = frame.loc[frame["year"].isin(FULL_SEASONAL_YEARS)]
    totals = frame.groupby(["supplier", "year", "month_num"])[value_column].sum()

    rows = []
    suppliers = monthly["supplier"].drop_duplicates()
    for supplier in suppliers:
        yearly_indices = []
        for year in FULL_SEASONAL_YEARS:
            month_values = np.array(
                [float(totals.get((supplier, year, month), 0.0)) for month in range(1, 13)]
            )
            mean = month_values.mean()
            if mean > 0:
                yearly_indices.append(month_values / mean)
        average = (
            np.mean(yearly_indices, axis=0) if yearly_indices else np.ones(12, dtype=float)
        )
        for month, index in enumerate(average, start=1):
            rows.append(
                {"supplier": supplier, "month_num": month, "supplier_season": float(index)}
            )
    return pd.DataFrame(rows)


def seasonal_indices(demand: pd.DataFrame) -> pd.DataFrame:
    """Return the approved 50/50 SKU/supplier seasonal index for every month."""

    frame = demand.copy()
    frame["period"] = pd.PeriodIndex(frame["month"], freq="M")
    frame["year"] = frame["period"].dt.year
    frame["month_num"] = frame["period"].dt.month
    totals = frame.groupby([*KEYS, "year", "month_num"])["demand"].sum()
    supplier_indices = supplier_seasonal_indices(demand, "demand")
    supplier_map = supplier_indices.set_index(["supplier", "month_num"])[
        "supplier_season"
    ].to_dict()

    rows = []
    for key, _ in frame.groupby(KEYS, sort=False):
        sku_code, supplier = key
        yearly_indices = []
        both_years_have_sales = True
        for year in FULL_SEASONAL_YEARS:
            values = np.array(
                [float(totals.get((sku_code, supplier, year, month), 0.0)) for month in range(1, 13)]
            )
            if values.sum() <= 0:
                both_years_have_sales = False
                break
            yearly_indices.append(values / values.mean())

        for month in range(1, 13):
            supplier_season = float(supplier_map.get((supplier, month), 1.0))
            sku_season = (
                float(np.mean(yearly_indices, axis=0)[month - 1])
                if both_years_have_sales
                else supplier_season
            )
            season = float(np.clip(0.5 * sku_season + 0.5 * supplier_season, 0.3, 3.0))
            rows.append(
                {
                    "sku_code": sku_code,
                    "supplier": supplier,
                    "month_num": month,
                    "seasonal_index": season,
                }
            )
    return pd.DataFrame(rows)


def build_forecast_profiles(
    demand: pd.DataFrame,
    segments: pd.DataFrame,
    last_full_month: pd.Period,
) -> pd.DataFrame:
    """Build L, year-over-year growth, sigma and 12 seasonal factors per SKU."""

    last_full_month = pd.Period(last_full_month, freq="M")
    regular = segments.loc[segments["segment"].eq("regular"), KEYS]
    frame = demand.merge(regular, on=KEYS, how="inner")
    frame["period"] = pd.PeriodIndex(frame["month"], freq="M")
    frame = frame.loc[frame["period"].le(last_full_month)].copy()
    seasons = seasonal_indices(frame)
    season_map = seasons.set_index([*KEYS, "month_num"])["seasonal_index"].to_dict()

    rows = []
    history_months = [last_full_month - offset for offset in range(11, -1, -1)]
    recent_months = [last_full_month - offset for offset in range(2, -1, -1)]
    prior_year_months = [month - 12 for month in recent_months]

    for key, sku_frame in frame.groupby(KEYS, sort=False):
        sku_code, supplier = key
        demand_map = sku_frame.groupby("period")["demand"].sum().to_dict()
        history = np.array([float(demand_map.get(month, 0.0)) for month in history_months])
        deseasonalized = np.array(
            [
                value / season_map.get((sku_code, supplier, month.month), 1.0)
                for value, month in zip(history, history_months)
            ]
        )
        positive_months = np.flatnonzero(history > 0)
        first_sale_index = int(positive_months[0]) if positive_months.size else 0
        level_start = min(first_sale_index, len(history) - 4)
        level = float(deseasonalized[level_start:].mean())
        recent = sum(float(demand_map.get(month, 0.0)) for month in recent_months)
        prior = sum(float(demand_map.get(month, 0.0)) for month in prior_year_months)
        growth = 1.0 if prior == 0 else recent / prior
        growth = float(np.clip(growth, 0.5, 2.0))

        row = {
            "sku_code": sku_code,
            "supplier": supplier,
            "level": level,
            "growth": growth,
            "sigma": float(history.std(ddof=0)),
            "simple_average": float(history.mean()),
        }
        for month in range(1, 13):
            row[f"season_{month}"] = float(
                season_map.get((sku_code, supplier, month), 1.0)
            )
        rows.append(row)

    columns = [*KEYS, "level", "growth", "sigma", "simple_average"] + [
        f"season_{month}" for month in range(1, 13)
    ]
    return pd.DataFrame(rows, columns=columns)


def forecast_value(profile: pd.Series, month: pd.Period) -> float:
    """Forecast one SKU/month from its prepared profile."""

    month = pd.Period(month, freq="M")
    return float(profile["level"] * profile["growth"] * profile[f"season_{month.month}"])


def forecast_months(profiles: pd.DataFrame, months: Iterable[pd.Period]) -> pd.DataFrame:
    """Expand profiles to a long table of monthly forecasts."""

    periods: List[pd.Period] = [pd.Period(month, freq="M") for month in months]
    rows = []
    for _, profile in profiles.iterrows():
        for month in periods:
            rows.append(
                {
                    "sku_code": profile["sku_code"],
                    "supplier": profile["supplier"],
                    "month": str(month),
                    "forecast": forecast_value(profile, month),
                }
            )
    return pd.DataFrame(rows, columns=[*KEYS, "month", "forecast"])
