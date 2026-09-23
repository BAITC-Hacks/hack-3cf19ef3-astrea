"""Convert forecast profiles into MOQ-rounded purchase quantities."""

import math

import numpy as np
import pandas as pd

from app.config import EngineConfig

from .forecast import forecast_value


KEYS = ["sku_code", "supplier"]


def round_to_moq(need: float, moq: int) -> int:
    """Round a positive need upward to the supplier's shipment multiple."""

    multiple = max(int(moq), 1)
    return int(math.ceil(max(float(need), 0.0) / multiple) * multiple)


def _urgency(stock: float, in_transit: float, monthly_forecast: float, lead_time: int, coverage: int) -> str:
    daily = monthly_forecast / 30.0
    cover_days = math.inf if daily <= 0 else (stock + in_transit) / daily
    if cover_days < lead_time:
        return "высокая"
    if cover_days < lead_time + coverage:
        return "средняя"
    return "низкая"


def calculate_orders(
    profiles: pd.DataFrame,
    segments: pd.DataFrame,
    current_stock: pd.DataFrame,
    in_transit: pd.DataFrame,
    moq: pd.DataFrame,
    as_of: pd.Timestamp,
    config: EngineConfig,
) -> pd.DataFrame:
    """Apply coverage window, safety stock, inventory and MOQ rules."""

    estimated_stock_keys = set(current_stock.attrs.get("estimated_keys", ()))
    base = segments.loc[segments["segment"].ne("dead")].copy()
    base = base.merge(profiles, on=KEYS, how="left")
    base = base.merge(current_stock, on=KEYS, how="left")
    base = base.merge(
        in_transit.rename(columns={"qty": "in_transit"}), on=KEYS, how="left"
    )
    base = base.merge(moq, on=KEYS, how="left")
    base["free_stock"] = base["free_stock"].fillna(0.0).astype(float)
    base["stock_unknown"] = base["stock_unknown"].fillna(False).astype(bool)
    base["in_transit"] = base["in_transit"].fillna(0.0).astype(float)
    base["moq"] = base["moq"].fillna(1).astype(int)

    rows = []
    as_of = pd.Timestamp(as_of).normalize()
    for _, item in base.iterrows():
        supplier = str(item["supplier"])
        lead_time = int(config.lead_time_days[supplier])
        planned_growth = float(config.planned_growth.get(supplier, 0.0))
        forecast_multiplier = max(1.0 + planned_growth, 0.0)
        window_days = lead_time + int(config.coverage_days)
        stock = float(item["free_stock"])
        transit = float(item["in_transit"])
        stock_unknown = bool(item["stock_unknown"])

        if item["segment"] == "regular":
            days = pd.date_range(as_of, periods=window_days, freq="D")
            demand_window = sum(
                forecast_value(item, day.to_period("M")) / day.days_in_month for day in days
            ) * forecast_multiplier
            safety_stock = float(
                config.service_z * float(item["sigma"]) * math.sqrt(lead_time / 30.0)
            )
            current_forecast = (
                forecast_value(item, as_of.to_period("M")) * forecast_multiplier
            )
            current_season = float(item[f"season_{as_of.month}"])
            level = float(item["level"])
            growth = float(item["growth"])
            sigma = float(item["sigma"])
        else:
            demand_window = float(item["max_level"]) * forecast_multiplier
            safety_stock = 0.0
            current_forecast = float(item["max_level"]) * forecast_multiplier
            current_season = np.nan
            level = np.nan
            growth = np.nan
            sigma = np.nan

        need = demand_window + safety_stock - stock - transit
        recommended_qty = round_to_moq(need, int(item["moq"]))
        rows.append(
            {
                "sku_code": item["sku_code"],
                "supplier": supplier,
                "segment": item["segment"],
                "active_months": int(item["active_months"]),
                "max_level": float(item["max_level"]),
                "level": level,
                "growth": growth,
                "sigma": sigma,
                "seasonal_index": current_season,
                "forecast_monthly": current_forecast,
                "planned_growth": planned_growth,
                "window_days": window_days,
                "demand_window": float(demand_window),
                "safety_stock": safety_stock,
                "free_stock": stock,
                "stock_unknown": stock_unknown,
                "stock_estimated": (item["sku_code"], supplier) in estimated_stock_keys
                or supplier == "IEK",
                "in_transit": transit,
                "raw_need": float(need),
                "moq": int(item["moq"]),
                "recommended_qty": recommended_qty,
                "urgency": (
                    "проверить остаток"
                    if stock_unknown
                    else _urgency(
                        stock,
                        transit,
                        current_forecast,
                        lead_time,
                        int(config.coverage_days),
                    )
                ),
            }
        )
    return pd.DataFrame(rows)
