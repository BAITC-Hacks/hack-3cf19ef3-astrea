"""Upward-only restoration of demand lost during zero-stock months."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .forecast import seasonal_indices


KEYS = ["sku_code", "supplier"]


@dataclass
class StockoutResult:
    monthly: pd.DataFrame
    summary: pd.DataFrame


def restore_stockouts(
    monthly_clean: pd.DataFrame, stock_monthly: pd.DataFrame
) -> StockoutResult:
    """Identify stockouts and restore demand with a supplier seasonal estimate."""

    frame = monthly_clean.merge(
        stock_monthly[[*KEYS, "month", "opening_stock"]],
        on=[*KEYS, "month"],
        how="left",
    )
    frame["opening_stock"] = pd.to_numeric(
        frame["opening_stock"], errors="coerce"
    ).fillna(0.0)

    non_stock = frame["opening_stock"].ne(0.0)
    medians = (
        frame.loc[non_stock]
        .groupby(KEYS)["monthly_clean"]
        .median()
        .rename("non_stock_median")
        .reset_index()
    )
    frame = frame.merge(medians, on=KEYS, how="left")
    frame["non_stock_median"] = frame["non_stock_median"].fillna(0.0)

    seasonal_source = frame[[*KEYS, "month", "monthly_clean"]].rename(
        columns={"monthly_clean": "demand"}
    )
    seasons = seasonal_indices(seasonal_source)
    frame["month_num"] = pd.PeriodIndex(frame["month"], freq="M").month
    frame = frame.merge(seasons, on=[*KEYS, "month_num"], how="left")
    frame["seasonal_index"] = frame["seasonal_index"].fillna(1.0)

    frame["is_stockout"] = frame["opening_stock"].eq(0.0) & frame[
        "monthly_clean"
    ].lt(0.5 * frame["non_stock_median"])
    estimate = frame["non_stock_median"] * frame["seasonal_index"]
    frame["demand"] = frame["monthly_clean"]
    frame.loc[frame["is_stockout"], "demand"] = np.maximum(
        frame.loc[frame["is_stockout"], "monthly_clean"],
        estimate.loc[frame["is_stockout"]],
    )
    frame["stockout_added_qty"] = frame["demand"] - frame["monthly_clean"]

    summary = (
        frame.groupby(KEYS, as_index=False)
        .agg(
            stockout_months=("is_stockout", "sum"),
            stockout_added_qty=("stockout_added_qty", "sum"),
        )
    )
    summary["stockout_months"] = summary["stockout_months"].astype(int)
    columns = [*KEYS, "month", "monthly_clean", "opening_stock", "is_stockout", "demand"]
    return StockoutResult(frame[columns], summary)
