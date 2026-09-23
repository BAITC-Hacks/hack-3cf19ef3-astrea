"""Human-readable calculation explanations for every recommendation."""

import pandas as pd


KEYS = ["sku_code", "supplier"]


def _number(value: float) -> str:
    return f"{float(value):.1f}".rstrip("0").rstrip(".")


def add_explanations(
    calculations: pd.DataFrame,
    cleaning_summary: pd.DataFrame,
    stockout_summary: pd.DataFrame,
) -> pd.DataFrame:
    """Attach the mandatory explanation text to regular and sparse calculations."""

    frame = calculations.merge(cleaning_summary, on=KEYS, how="left")
    frame = frame.merge(stockout_summary, on=KEYS, how="left")
    frame["excluded_outlier_qty"] = pd.to_numeric(
        frame["excluded_outlier_qty"], errors="coerce"
    ).fillna(0.0)
    frame["outlier_count"] = pd.to_numeric(
        frame["outlier_count"], errors="coerce"
    ).fillna(0).astype(int)
    frame["outlier_dates"] = frame["outlier_dates"].astype("string").fillna("")
    frame["stockout_months"] = pd.to_numeric(
        frame["stockout_months"], errors="coerce"
    ).fillna(0).astype(int)
    frame["stockout_added_qty"] = pd.to_numeric(
        frame["stockout_added_qty"], errors="coerce"
    ).fillna(0.0)

    explanations = []
    for _, item in frame.iterrows():
        if item["segment"] == "sparse":
            text = (
                f"Редкий спрос: продажи в {item['active_months']} мес. из 12, "
                f"уровень max {_number(item['max_level'])}; "
                f"потребность {_number(item['max_level'])} − остаток {_number(item['free_stock'])} "
                f"− в пути {_number(item['in_transit'])} = {_number(item['raw_need'])} → "
                f"кратность {item['moq']} → {item['recommended_qty']} шт."
            )
        else:
            growth_percent = (float(item["growth"]) - 1.0) * 100.0
            formula_parts = (
                f"уровень {_number(item['level'])} шт./мес., "
                f"рост {growth_percent:+.0f}% г/г, сезонность текущего месяца "
                f"×{float(item['seasonal_index']):.2f}"
            )
            if item["forecast_method"] == "ml":
                text = (
                    f"Регулярный спрос: ML-прогноз "
                    f"{_number(item['ml_forecast_monthly'])} шт./мес.; формула "
                    f"{_number(item['formula_forecast_monthly'])} шт./мес. "
                    f"({formula_parts}); "
                )
                if bool(item["ml_fallback_used"]):
                    text += (
                        "месяцы за горизонтом ML 6 мес. рассчитаны по формуле; "
                    )
            else:
                text = f"Регулярный спрос: {formula_parts}; "
            if item["outlier_count"]:
                text += (
                    f"исключено разовых продаж {_number(item['excluded_outlier_qty'])} шт. "
                    f"({item['outlier_dates']}); "
                )
            if item["stockout_months"]:
                text += (
                    f"{item['stockout_months']} мес. дефицита восстановлены "
                    f"(+{_number(item['stockout_added_qty'])} шт.); "
                )
            text += (
                f"потребность на {item['window_days']} дн. {_number(item['demand_window'])} "
                f"+ страховой {_number(item['safety_stock'])} − остаток "
                f"{_number(item['free_stock'])} − в пути {_number(item['in_transit'])} "
                f"= {_number(item['raw_need'])} → кратность {item['moq']} → "
                f"{item['recommended_qty']} шт."
            )
        planned_growth = float(item["planned_growth"])
        if planned_growth != 0:
            text += f" Плановый прирост {planned_growth:+.0%} применён к прогнозу."
        if bool(item["stock_estimated"]):
            text += " Остаток оценён: начало месяца минус продажи; приходы за месяц неизвестны."
        if bool(item["stock_unknown"]):
            text += (
                " В сентябре были приходы, остаток в данных неизвестен — "
                "сверьте с 1С перед заказом."
            )
        explanations.append(text)
    frame["explanation"] = explanations
    return frame
