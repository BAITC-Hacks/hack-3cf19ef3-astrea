"""Supplier order calculation page."""

from collections.abc import Callable
from pathlib import Path

import pandas as pd
import streamlit as st

from app.ui.order_view import (
    _filter_rows,
    _sort_orders,
    render_dead_tab,
    render_order_tab,
    render_summary,
)
from app.ui.settings_view import (
    _needs_calculation,
    calculate,
    load_data,
    render_controls,
)


def render(
    data_dir: Path,
    load_fn: Callable[..., dict[str, pd.DataFrame]] = load_data,
    calculate_fn: Callable[..., tuple[pd.DataFrame, pd.DataFrame]] = calculate,
) -> None:
    current_user = st.session_state["current_user"]
    connection_url = str(st.session_state["connection_url"])

    st.title("Заказ")
    try:
        data = load_fn(str(data_dir))
    except Exception as error:
        st.error(f"Не удалось загрузить данные: {error}")
        return

    as_of = pd.Timestamp(data["sales_tx"]["date"].max()).date()
    st.text(f"Данные на {as_of:%d.%m.%Y}")
    controls = render_controls(data, str(data_dir))

    if _needs_calculation(st.session_state, controls.recalculate):
        st.session_state["recommendation_result"] = calculate_fn(
            str(data_dir), *controls.calculation_key
        )
        st.session_state["calculation_parameters"] = controls.calculation_key

    if st.session_state.get("calculation_parameters") != controls.calculation_key:
        st.warning("Настройки изменены. Нажмите «Пересчитать»")

    orders, no_sales = st.session_state["recommendation_result"]
    visible_orders = _sort_orders(
        _filter_rows(orders, controls.supplier, controls.category, controls.query)
    )
    visible_no_sales = _filter_rows(
        no_sales, controls.supplier, controls.category, controls.query
    )

    render_summary(visible_orders)
    order_tab, no_sales_tab = st.tabs(
        [f"Заказ ({len(visible_orders)})", f"Без продаж ({len(visible_no_sales)})"]
    )
    with order_tab:
        render_order_tab(
            visible_orders,
            True,
            connection_url,
            current_user,
            as_of,
            controls.forecast_method,
            controls.approval_params,
        )
    with no_sales_tab:
        render_dead_tab(visible_no_sales)


__all__ = ["render"]
