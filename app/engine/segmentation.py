"""Demand-frequency segmentation for the last 12 complete months."""

import pandas as pd


KEYS = ["sku_code", "supplier"]


def segment_skus(sales_monthly: pd.DataFrame, last_full_month: pd.Period) -> pd.DataFrame:
    """Classify SKUs as regular, sparse or dead exactly as defined in the plan."""

    last_full_month = pd.Period(last_full_month, freq="M")
    first_month = last_full_month - 11
    frame = sales_monthly.copy()
    frame["period"] = pd.PeriodIndex(frame["month"], freq="M")
    frame["qty"] = pd.to_numeric(frame["qty"], errors="coerce").fillna(0.0).clip(lower=0.0)
    window = frame.loc[frame["period"].between(first_month, last_full_month)]

    all_skus = frame[KEYS].drop_duplicates()
    summary = (
        window.groupby(KEYS, as_index=False)
        .agg(
            active_months=("qty", lambda values: int(values.gt(0).sum())),
            max_level=("qty", "max"),
        )
    )
    result = all_skus.merge(summary, on=KEYS, how="left")
    result["active_months"] = result["active_months"].fillna(0).astype(int)
    result["max_level"] = result["max_level"].fillna(0.0).astype(float)
    result["segment"] = "dead"
    result.loc[result["active_months"].between(1, 3), "segment"] = "sparse"
    result.loc[result["active_months"].ge(4), "segment"] = "regular"
    return result[[*KEYS, "segment", "active_months", "max_level"]]
