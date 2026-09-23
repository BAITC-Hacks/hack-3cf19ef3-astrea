from copy import deepcopy

import numpy as np
import pandas as pd

from app.config import EngineConfig
from app.engine.cleaning import clean_sales, detect_outliers
from app.engine.forecast import build_forecast_profiles, forecast_value
from app.engine.metrics import mdape, wape
from app.engine.order import round_to_moq
from app.engine.pipeline import build_recommendations, prepare_forecasts
from app.engine.segmentation import segment_skus
from app.engine.stockout import restore_stockouts


def _monthly_qty(sku: str, month: pd.Period) -> float:
    if sku == "SEASONAL-1":
        if month == pd.Period("2026-09", freq="M"):
            return 9999.0
        return 60.0 if month.month in (6, 7, 8) else 10.0
    if sku == "STOCKOUT-1":
        return 4.0 if month in (pd.Period("2026-03", freq="M"), pd.Period("2026-04", freq="M")) else 20.0
    if sku == "OUTLIER-1":
        return 215.0 if month == pd.Period("2026-03", freq="M") else 15.0
    if sku == "SPARSE-1":
        return {pd.Period("2026-07", freq="M"): 8.0, pd.Period("2026-08", freq="M"): 5.0}.get(month, 0.0)
    if sku == "SE-REGULAR-1":
        return 12.0
    return 0.0


def make_data() -> dict[str, pd.DataFrame]:
    sku_suppliers = {
        "SEASONAL-1": "IEK",
        "STOCKOUT-1": "IEK",
        "OUTLIER-1": "IEK",
        "SPARSE-1": "IEK",
        "DEAD-1": "IEK",
        "SE-REGULAR-1": "SE",
    }
    months = pd.period_range("2024-01", "2026-09", freq="M")
    monthly_rows = []
    stock_rows = []
    transaction_rows = []

    for sku_code, supplier in sku_suppliers.items():
        for month in months:
            qty = _monthly_qty(sku_code, month)
            monthly_rows.append(
                {"sku_code": sku_code, "supplier": supplier, "month": str(month), "qty": qty}
            )
            opening_stock = 0.0 if sku_code == "STOCKOUT-1" and month in (
                pd.Period("2026-03", freq="M"),
                pd.Period("2026-04", freq="M"),
            ) else 100.0
            stock_rows.append(
                {
                    "sku_code": sku_code,
                    "supplier": supplier,
                    "month": str(month),
                    "opening_stock": opening_stock,
                }
            )
            if qty > 0 and sku_code != "DEAD-1":
                transaction_qty = 15.0 if sku_code == "OUTLIER-1" else qty
                transaction_rows.append(
                    {
                        "date": month.to_timestamp() + pd.Timedelta(days=4),
                        "sku_code": sku_code,
                        "supplier": supplier,
                        "qty": transaction_qty,
                    }
                )

    transaction_rows.append(
        {
            "date": pd.Timestamp("2026-03-15"),
            "sku_code": "OUTLIER-1",
            "supplier": "IEK",
            "qty": 200.0,
        }
    )
    transaction_rows.append(
        {
            "date": pd.Timestamp("2026-09-22"),
            "sku_code": "OUTLIER-1",
            "supplier": "IEK",
            "qty": 15.0,
        }
    )

    keys = pd.DataFrame(
        [{"sku_code": sku, "supplier": supplier} for sku, supplier in sku_suppliers.items()]
    )
    sku_ref = keys.copy()
    sku_ref["name"] = sku_ref["sku_code"].str.replace("-", " ", regex=False)
    sku_ref["article"] = "A-" + pd.Series(range(1, len(sku_ref) + 1)).astype(str)
    sku_ref["unit"] = "шт"
    current_stock = keys.copy()
    current_stock["free_stock"] = 0.0
    current_stock["stock_unknown"] = False
    in_transit = keys.copy()
    in_transit["qty"] = 0.0
    moq = keys.copy()
    moq["moq"] = pd.Series([6, 1, 1, 1, 1, 1], dtype="Int64")

    return {
        "sales_tx": pd.DataFrame(transaction_rows)[["date", "sku_code", "supplier", "qty"]],
        "sales_monthly": pd.DataFrame(monthly_rows)[["sku_code", "supplier", "month", "qty"]],
        "stock_monthly": pd.DataFrame(stock_rows)[
            ["sku_code", "supplier", "month", "opening_stock"]
        ],
        "current_stock": current_stock[
            ["sku_code", "supplier", "free_stock", "stock_unknown"]
        ],
        "in_transit": in_transit[["sku_code", "supplier", "qty"]],
        "moq": moq[["sku_code", "supplier", "moq"]],
        "sku_ref": sku_ref[["sku_code", "supplier", "name", "article", "unit"]],
    }


def test_r1_less_in_transit_increases_order_quantity() -> None:
    baseline = make_data()
    with_transit = deepcopy(baseline)
    with_transit["in_transit"].loc[
        with_transit["in_transit"]["sku_code"].eq("OUTLIER-1"), "qty"
    ] = 20.0

    baseline_orders, _ = build_recommendations(baseline)
    transit_orders, _ = build_recommendations(with_transit)
    baseline_qty = baseline_orders.set_index("sku_code").loc["OUTLIER-1", "recommended_qty"]
    transit_qty = transit_orders.set_index("sku_code").loc["OUTLIER-1", "recommended_qty"]
    assert baseline_qty - transit_qty == 20


def test_r2_seasonal_peak_forecast_exceeds_simple_average() -> None:
    data = make_data()
    last_full = pd.Period("2026-05", freq="M")
    profiles, _, _, _ = prepare_forecasts(data, last_full)
    profile = profiles.loc[profiles["sku_code"].eq("SEASONAL-1")].iloc[0]

    july_forecast = forecast_value(profile, pd.Period("2026-07", freq="M"))
    assert july_forecast >= 1.3 * profile["simple_average"]


def test_r3_stockout_restoration_increases_demand_by_twenty_percent() -> None:
    data = make_data()
    last_full = pd.Period("2026-08", freq="M")
    cleaning = clean_sales(data["sales_monthly"], data["sales_tx"], last_full)
    restored = restore_stockouts(cleaning.monthly, data["stock_monthly"])
    rows = restored.monthly.loc[
        restored.monthly["sku_code"].eq("STOCKOUT-1")
        & restored.monthly["month"].isin(["2026-03", "2026-04"])
    ]

    assert rows["demand"].sum() >= 1.2 * rows["monthly_clean"].sum()


def test_r4_invoice_outlier_changes_recommendation_by_at_most_ten_percent() -> None:
    with_outlier = make_data()
    without_outlier = deepcopy(with_outlier)
    without_outlier["sales_tx"] = without_outlier["sales_tx"].loc[
        ~(
            without_outlier["sales_tx"]["sku_code"].eq("OUTLIER-1")
            & without_outlier["sales_tx"]["qty"].eq(200.0)
        )
    ]
    without_outlier["sales_monthly"].loc[
        without_outlier["sales_monthly"]["sku_code"].eq("OUTLIER-1")
        & without_outlier["sales_monthly"]["month"].eq("2026-03"),
        "qty",
    ] = 15.0

    orders_with, _ = build_recommendations(with_outlier)
    orders_without, _ = build_recommendations(without_outlier)
    qty_with = orders_with.set_index("sku_code").loc["OUTLIER-1", "recommended_qty"]
    qty_without = orders_without.set_index("sku_code").loc["OUTLIER-1", "recommended_qty"]
    assert abs(qty_with - qty_without) / qty_without <= 0.10


def test_sparse_outlier_uses_cleaned_monthly_maximum() -> None:
    data = make_data()
    july = data["sales_monthly"]["sku_code"].eq("SPARSE-1") & data[
        "sales_monthly"
    ]["month"].eq("2026-07")
    data["sales_monthly"].loc[july, "qty"] += 400.0
    data["sales_tx"] = pd.concat(
        [
            data["sales_tx"],
            pd.DataFrame(
                [
                    {
                        "date": pd.Timestamp("2026-07-10"),
                        "sku_code": "SPARSE-1",
                        "supplier": "IEK",
                        "qty": 400.0,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    orders, _ = build_recommendations(data)
    sparse_order = orders.set_index("sku_code").loc["SPARSE-1"]

    assert sparse_order["recommended_qty"] == 8
    assert sparse_order["max_level"] == 8


def test_unknown_stock_changes_warning_not_order_quantity() -> None:
    known_data = make_data()
    unknown_data = deepcopy(known_data)
    unknown_data["current_stock"].loc[
        unknown_data["current_stock"]["sku_code"].eq("OUTLIER-1"),
        "stock_unknown",
    ] = True

    known_orders, _ = build_recommendations(known_data)
    unknown_orders, _ = build_recommendations(unknown_data)
    known = known_orders.set_index("sku_code").loc["OUTLIER-1"]
    unknown = unknown_orders.set_index("sku_code").loc["OUTLIER-1"]

    assert unknown["recommended_qty"] == known["recommended_qty"]
    assert bool(unknown["stock_unknown"])
    assert unknown["urgency"] == "проверить остаток"
    assert "сверьте с 1С перед заказом" in unknown["explanation"]


def test_r5_every_order_has_explanation_and_supplier_grouping_is_lossless() -> None:
    orders, _ = build_recommendations(make_data())

    assert orders["explanation"].str.strip().ne("").all()
    assert orders.groupby("supplier").size().sum() == len(orders)
    assert set(orders["supplier"]) == {"IEK", "SE"}


def test_r6_rounds_need_up_to_moq() -> None:
    assert round_to_moq(14, 6) == 18


def test_segmentation_separates_regular_sparse_and_dead() -> None:
    data = make_data()
    segments = segment_skus(data["sales_monthly"], pd.Period("2026-08", freq="M"))
    by_sku = segments.set_index("sku_code")["segment"]

    assert by_sku["SEASONAL-1"] == "regular"
    assert by_sku["SPARSE-1"] == "sparse"
    assert by_sku["DEAD-1"] == "dead"


def test_incomplete_as_of_month_does_not_affect_level_or_growth() -> None:
    high_september = make_data()
    zero_september = deepcopy(high_september)
    zero_september["sales_monthly"].loc[
        zero_september["sales_monthly"]["month"].eq("2026-09"), "qty"
    ] = 0.0
    last_full = pd.Period("2026-08", freq="M")

    high_profile = prepare_forecasts(high_september, last_full)[0].set_index("sku_code")
    zero_profile = prepare_forecasts(zero_september, last_full)[0].set_index("sku_code")
    assert high_profile.loc["SEASONAL-1", "level"] == zero_profile.loc["SEASONAL-1", "level"]
    assert high_profile.loc["SEASONAL-1", "growth"] == zero_profile.loc["SEASONAL-1", "growth"]


def test_mad_floor_does_not_flag_constant_unit_sales() -> None:
    transactions = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=12, freq="7D"),
            "sku_code": "UNIT-1",
            "supplier": "IEK",
            "qty": 1.0,
        }
    )
    flagged = detect_outliers(transactions, pd.Period("2026-08", freq="M"))
    assert not flagged["is_outlier"].any()


def test_nan_opening_stock_is_treated_as_stockout() -> None:
    data = make_data()
    last_full = pd.Period("2026-08", freq="M")
    cleaning = clean_sales(data["sales_monthly"], data["sales_tx"], last_full)
    stock = data["stock_monthly"].copy()
    stock.loc[
        stock["sku_code"].eq("STOCKOUT-1") & stock["month"].eq("2026-03"),
        "opening_stock",
    ] = np.nan
    restored = restore_stockouts(cleaning.monthly, stock)
    march = restored.monthly.loc[
        restored.monthly["sku_code"].eq("STOCKOUT-1")
        & restored.monthly["month"].eq("2026-03")
    ].iloc[0]
    assert bool(march["is_stockout"])


def test_growth_is_year_over_year_and_clipped() -> None:
    data = make_data()
    profiles, segments, cleaning, stockouts = prepare_forecasts(
        data, pd.Period("2026-08", freq="M")
    )
    rebuilt = build_forecast_profiles(
        stockouts.monthly, segments, pd.Period("2026-08", freq="M")
    )
    seasonal = rebuilt.set_index("sku_code").loc["SEASONAL-1"]
    assert seasonal["growth"] == 1.0


def test_wape() -> None:
    assert wape(np.array([100, 50]), np.array([90, 70])) == 0.2


def test_mdape_ignores_zero_actuals() -> None:
    actual = np.array([100, 50, 0])
    forecast = np.array([90, 70, 1000])

    assert mdape(actual, forecast) == 0.25
