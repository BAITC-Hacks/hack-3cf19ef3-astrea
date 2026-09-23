"""Authenticated multi-page entry point for Astrea."""

from html import escape
from pathlib import Path
import sys

import streamlit as st


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import database_url  # noqa: E402
from app.datasets import resolve_dataset_context  # noqa: E402
from app.ui.auth_view import render_auth_screen  # noqa: E402
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
)
from app.ui.pages import accuracy_page, data_page, history_page, order_page  # noqa: E402
from app.ui.settings_view import (  # noqa: E402
    FORECAST_OPTIONS,
    _category_label,
    _display_importance,
    _needs_calculation,
    calculate,
    initialize_database,
    load_data,
    train_ml_resource,
)
from app.ui.theme import apply_theme  # noqa: E402


DATA_DIR = ROOT / "data" / "raw"
UPLOAD_DIR = Path("/app/uploads")
NAVIGATION_TITLES = ("Заказ", "Данные", "История заказов", "Точность")


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


def _initials(full_name: object) -> str:
    parts = str(full_name).strip().split()
    return "".join(part[0].upper() for part in parts[:2]) or "A"


def _render_sidebar_brand() -> None:
    with st.sidebar:
        with st.container(key="sidebar_brand"):
            st.markdown("## Astrea")
            st.caption("Расчёт заказов поставщикам")


def _render_sidebar_profile(current_user: dict[str, object]) -> None:
    full_name = escape(str(current_user["full_name"]))
    email = escape(str(current_user["email"]))
    initials = escape(_initials(current_user["full_name"]))
    with st.sidebar:
        with st.container(key="sidebar_profile"):
            st.markdown(
                (
                    '<div class="astrea-profile">'
                    f'<span class="astrea-avatar">{initials}</span>'
                    '<span class="astrea-profile-copy">'
                    f'<strong>{full_name}</strong><small>{email}</small>'
                    "</span></div>"
                ),
                unsafe_allow_html=True,
            )
            if st.button(
                "Выйти",
                key="logout",
                icon=":material/logout:",
                width="stretch",
            ):
                st.session_state.clear()
                st.rerun()


def _render_order_page() -> None:
    order_page.render(load_data, calculate)


def _navigation() -> object:
    pages = [
        st.Page(
            _render_order_page,
            title="Заказ",
            icon=":material/shopping_cart:",
            url_path="order",
            default=True,
        ),
        st.Page(
            data_page.render,
            title="Данные",
            icon=":material/database:",
            url_path="data",
        ),
        st.Page(
            history_page.render,
            title="История заказов",
            icon=":material/history:",
            url_path="history",
        ),
        st.Page(
            accuracy_page.render,
            title="Точность",
            icon=":material/monitoring:",
            url_path="accuracy",
        ),
    ]
    return st.navigation(pages, position="sidebar", expanded=True)


def main() -> None:
    st.set_page_config(page_title="Astrea", page_icon="A", layout="wide")
    apply_theme()

    connection_url = database_url() or ""
    database_ready, _ = initialize_database(connection_url)
    if not database_ready:
        with st.container(key="auth_panel", border=True):
            st.title("Astrea")
            st.error("Сервис временно недоступен")
        return

    current_user = _authenticate(connection_url)
    if current_user is None:
        return

    st.session_state["connection_url"] = connection_url
    try:
        dataset_context = resolve_dataset_context(connection_url, DATA_DIR)
    except Exception as error:
        st.error(f"Не удалось определить текущие данные: {error}")
        return
    st.session_state["dataset_context"] = dataset_context
    st.session_state["dataset_ids"] = dataset_context.cache_key
    _render_sidebar_brand()
    page = _navigation()
    _render_sidebar_profile(current_user)
    page.run()


if __name__ == "__main__":
    main()


__all__ = [
    "FORECAST_OPTIONS",
    "NAVIGATION_TITLES",
    "ORDER_COLUMNS",
    "REVIEW_COLUMNS",
    "_approval_controls",
    "_category_label",
    "_details_points",
    "_display_importance",
    "_draft_changes",
    "_export_suppliers",
    "_filter_rows",
    "_initials",
    "_needs_calculation",
    "_restore_draft",
    "_sort_orders",
    "_summary_metrics",
    "main",
]
