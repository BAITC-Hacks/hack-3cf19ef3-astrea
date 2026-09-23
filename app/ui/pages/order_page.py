"""Supplier order calculation page."""

from collections.abc import Callable
import logging
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
from app.ui.loading_view import LoadingView, render_loading_error


LOGGER = logging.getLogger(__name__)


def render(
    load_fn: Callable[..., dict[str, pd.DataFrame]] = load_data,
    calculate_fn: Callable[..., tuple[pd.DataFrame, pd.DataFrame]] = calculate,
) -> None:
    current_user = st.session_state["current_user"]
    connection_url = str(st.session_state["connection_url"])

    context = st.session_state["dataset_context"]
    dataset_key = context.cache_key
    path_items = context.path_items

    st.title("Заказ")
    loading = LoadingView()
    loading.update("Загружаем данные", 0.02)
    try:
        data = load_fn(path_items, dataset_key, loading.update)
    except Exception as error:
        loading.close()
        LOGGER.exception("Could not load the current dataset")
        render_loading_error(f"Не удалось загрузить данные: {error}", "data")
        return
    loading.close()

    as_of = pd.Timestamp(data["sales_tx"]["date"].max()).date()
    st.text(f"Данные на {as_of:%d.%m.%Y}")
    controls = render_controls(data, path_items, dataset_key)

    calculation_key = (*controls.calculation_key, *dataset_key)

    dataset_changed = st.session_state.get("calculation_dataset_key") != dataset_key
    if _needs_calculation(st.session_state, controls.recalculate) or dataset_changed:
        loading = LoadingView()
        loading.update("Считаем рекомендации", 0.02)
        try:
            st.session_state["recommendation_result"] = calculate_fn(
                path_items,
                dataset_key,
                *controls.calculation_key,
                loading.update,
            )
        except Exception as error:
            loading.close()
            LOGGER.exception("Could not build recommendations")
            render_loading_error(f"Не удалось выполнить расчёт: {error}", "calculation")
            return
        loading.close()
        st.session_state["calculation_parameters"] = calculation_key
        st.session_state["calculation_dataset_key"] = dataset_key

    if st.session_state.get("calculation_parameters") != calculation_key:
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
            context.dataset_ids,
        )
    with no_sales_tab:
        render_dead_tab(visible_no_sales)


__all__ = ["render"]
