"""End-to-end orchestration of the approved demand and order formulas."""

from typing import Dict, Optional, Tuple

import pandas as pd

from app.config import EngineConfig, resolve_as_of
from app.models import validate_model

from .cleaning import CleaningResult, clean_sales
from .explain import add_explanations
from .forecast import build_forecast_profiles
from .order import calculate_orders
from .segmentation import segment_skus
from .stockout import StockoutResult, restore_stockouts


KEYS = ["sku_code", "supplier"]


def prepare_forecasts(
    data: Dict[str, pd.DataFrame], last_full_month: pd.Period
) -> Tuple[pd.DataFrame, pd.DataFrame, CleaningResult, StockoutResult]:
    """Prepare segments and regular-SKU profiles through an explicit full month."""

    segments = segment_skus(data["sales_monthly"], last_full_month)
    cleaning = clean_sales(data["sales_monthly"], data["sales_tx"], last_full_month)
    stock = data["stock_monthly"].copy()
    stock["period"] = pd.PeriodIndex(stock["month"], freq="M")
    stock = stock.loc[stock["period"].le(pd.Period(last_full_month, freq="M"))].drop(
        columns="period"
    )
    stockouts = restore_stockouts(cleaning.monthly, stock)
    profiles = build_forecast_profiles(stockouts.monthly, segments, last_full_month)
    return profiles, segments, cleaning, stockouts


def build_recommendations(
    data: Dict[str, pd.DataFrame], config: Optional[EngineConfig] = None
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Build human-reviewable orders and a separate list of dead SKUs."""

    validate_model(data)
    config = config or EngineConfig()
    as_of = resolve_as_of(data["sales_tx"], config)
    last_full_month = as_of.to_period("M") - 1
    profiles, segments, cleaning, stockouts = prepare_forecasts(data, last_full_month)

    calculations = calculate_orders(
        profiles,
        segments,
        data["current_stock"],
        data["in_transit"],
        data["moq"],
        as_of,
        config,
    )
    explained = add_explanations(calculations, cleaning.summary, stockouts.summary)
    explained = explained.merge(data["sku_ref"], on=KEYS, how="left")
    orders = explained.loc[explained["recommended_qty"].gt(0)].copy()

    leading = [
        "sku_code",
        "article",
        "name",
        "unit",
        "supplier",
        "segment",
        "recommended_qty",
        "urgency",
        "explanation",
    ]
    remaining = [column for column in orders.columns if column not in leading]
    orders = orders[leading + remaining].sort_values(
        ["supplier", "recommended_qty"], ascending=[True, False]
    ).reset_index(drop=True)

    review_needed = segments.loc[segments["segment"].eq("dead")].merge(
        data["sku_ref"], on=KEYS, how="left"
    )
    review_needed["reason"] = "Нет продаж за последние 12 полных месяцев"
    review_needed = review_needed[
        ["sku_code", "article", "name", "unit", "supplier", "segment", "reason"]
    ].reset_index(drop=True)
    return orders, review_needed
