"""Robust removal of one-off invoice and historical monthly outliers."""

from dataclasses import dataclass

import numpy as np
import pandas as pd


KEYS = ["sku_code", "supplier"]
ROBUST_SCALE = 1.4826


@dataclass
class CleaningResult:
    monthly: pd.DataFrame
    transactions: pd.DataFrame
    summary: pd.DataFrame


def detect_outliers(sales_tx: pd.DataFrame, last_full_month: pd.Period) -> pd.DataFrame:
    """Flag exceptionally large invoice lines using median/MAD and SKU share."""

    cutoff = pd.Period(last_full_month, freq="M").end_time
    frame = sales_tx.loc[sales_tx["date"].le(cutoff)].copy()
    frame["qty"] = pd.to_numeric(frame["qty"], errors="coerce").fillna(0.0).clip(lower=0.0)

    median = frame.groupby(KEYS)["qty"].transform("median")
    absolute_deviation = (frame["qty"] - median).abs()
    mad = absolute_deviation.groupby([frame[column] for column in KEYS]).transform("median")
    mad_floor = mad.clip(lower=1.0)
    total = frame.groupby(KEYS)["qty"].transform("sum")
    robust_z = (frame["qty"] - median) / (ROBUST_SCALE * mad_floor)
    share = frame["qty"].div(total.where(total.ne(0), np.nan)).fillna(0.0)

    frame["is_outlier"] = robust_z.gt(10.0) & share.gt(0.2)
    frame["robust_z"] = robust_z
    frame["sku_share"] = share
    return frame


def clean_sales(
    sales_monthly: pd.DataFrame,
    sales_tx: pd.DataFrame,
    last_full_month: pd.Period,
) -> CleaningResult:
    """Connect transaction outliers to the monthly history and cap older months."""

    last_full_month = pd.Period(last_full_month, freq="M")
    monthly = sales_monthly.copy()
    monthly["period"] = pd.PeriodIndex(monthly["month"], freq="M")
    monthly = monthly.loc[monthly["period"].le(last_full_month)].copy()
    monthly["monthly_clean"] = (
        pd.to_numeric(monthly["qty"], errors="coerce").fillna(0.0).clip(lower=0.0)
    )

    transactions = detect_outliers(sales_tx, last_full_month)
    transactions["period"] = transactions["date"].dt.to_period("M")
    outlier_rows = transactions.loc[transactions["is_outlier"]]
    excluded = (
        outlier_rows.groupby([*KEYS, "period"], as_index=False)["qty"]
        .sum()
        .rename(columns={"qty": "excluded_qty"})
    )
    monthly = monthly.merge(excluded, on=[*KEYS, "period"], how="left")
    monthly["excluded_qty"] = monthly["excluded_qty"].fillna(0.0)
    monthly["monthly_clean"] = (monthly["monthly_clean"] - monthly["excluded_qty"]).clip(
        lower=0.0
    )

    first_transaction = (
        transactions.groupby(KEYS, as_index=False)["period"]
        .min()
        .rename(columns={"period": "first_tx_period"})
    )
    monthly = monthly.merge(first_transaction, on=KEYS, how="left")
    group_median = monthly.groupby(KEYS)["monthly_clean"].transform("median")
    deviation = (monthly["monthly_clean"] - group_median).abs()
    group_mad = deviation.groupby([monthly[column] for column in KEYS]).transform("median")
    cap = group_median + 5.0 * ROBUST_SCALE * group_mad.clip(lower=1.0)
    before_transactions = monthly["first_tx_period"].isna() | monthly["period"].lt(
        monthly["first_tx_period"]
    )
    monthly.loc[before_transactions, "monthly_clean"] = np.minimum(
        monthly.loc[before_transactions, "monthly_clean"], cap.loc[before_transactions]
    )

    if outlier_rows.empty:
        summary = pd.DataFrame(
            columns=[*KEYS, "excluded_outlier_qty", "outlier_count", "outlier_dates"]
        )
    else:
        summary = (
            outlier_rows.groupby(KEYS, as_index=False)
            .agg(
                excluded_outlier_qty=("qty", "sum"),
                outlier_count=("qty", "size"),
                outlier_dates=(
                    "date",
                    lambda values: ", ".join(
                        sorted({pd.Timestamp(value).strftime("%d.%m.%Y") for value in values})
                    ),
                ),
            )
        )

    monthly["month"] = monthly["period"].astype("string")
    columns = [*KEYS, "month", "monthly_clean", "excluded_qty"]
    return CleaningResult(monthly[columns], transactions, summary)
