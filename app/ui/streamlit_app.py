"""Astrea AI Streamlit application assembly."""

from pathlib import Path
import sys

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import database_url  # noqa: E402
from app.ui.auth_view import render_auth_screen  # noqa: E402
from app.ui.history_view import render_history  # noqa: E402
from app.ui.order_view import (  # noqa: E402
    ORDER_COLUMNS,
    REVIEW_COLUMNS,
    _approval_controls,
    _details_points,
    _draft_changes,
    _export_suppliers,
    _filter_rows,
    _restore_draft,
    _sort_orders,
    _summary_metrics,
    render_dead_tab,
    render_order_tab,
    render_summary,
)
from app.ui.settings_view import (  # noqa: E402
    FORECAST_OPTIONS,
    _category_label,
    _display_importance,
    _needs_calculation,
    calculate,
    initialize_database,
    load_data,
    render_controls,
    train_ml_resource,
)
from app.ui.theme import apply_theme  # noqa: E402


DATA_DIR = ROOT / "data" / "raw"


def _brand_header(current_user: dict[str, object], as_of: object) -> None:
    with st.container(key="brand_header"):
        title, account = st.columns([4, 1])
        with title:
            st.title("Astrea AI")
            st.text(f"Автозаказ поставщикам  |  данные на {as_of:%d.%m.%Y}")
        with account:
            st.text(str(current_user["full_name"]))
            if st.button("Выйти", width="stretch"):
                st.session_state.clear()
                st.rerun()


def _authenticate(connection_url: str) -> dict[str, object] | None:
    current_user = st.session_state.get("current_user")
    if current_user is not None:
        return current_user
    current_user = render_auth_screen(connection_url)
    if current_user is None:
        return None
    st.session_state["current_user"] = current_user
    st.rerun()
    return None


def main() -> None:
    st.set_page_config(page_title="Astrea AI", page_icon="A", layout="wide")
    apply_theme()

    connection_url = database_url() or ""
    database_ready, _ = initialize_database(connection_url)
    if not database_ready:
        with st.container(key="auth_panel", border=True):
            st.title("Astrea AI")
            st.error("Сервис временно недоступен")
        return

    current_user = _authenticate(connection_url)
    if current_user is None:
        return

    try:
        data = load_data(str(DATA_DIR))
    except Exception as error:
        st.error(f"Не удалось загрузить данные: {error}")
        return

    as_of = pd.Timestamp(data["sales_tx"]["date"].max()).date()
    _brand_header(current_user, as_of)
    controls = render_controls(data, str(DATA_DIR))

    if _needs_calculation(st.session_state, controls.recalculate):
        st.session_state["recommendation_result"] = calculate(
            str(DATA_DIR), *controls.calculation_key
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
    order_tab, no_sales_tab, history_tab = st.tabs(
        [
            f"Заказ ({len(visible_orders)})",
            f"Без продаж ({len(visible_no_sales)})",
            "История",
        ]
    )
    with order_tab:
        render_order_tab(
            visible_orders,
            database_ready,
            connection_url,
            current_user,
            as_of,
            controls.forecast_method,
            controls.approval_params,
        )
    with no_sales_tab:
        render_dead_tab(visible_no_sales)
    with history_tab:
        render_history(connection_url)


if __name__ == "__main__":
    main()
