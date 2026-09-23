import pandas as pd
from streamlit.testing.v1 import AppTest

from app.ui.streamlit_app import (
    NAVIGATION_TITLES,
    ORDER_COLUMNS,
    REVIEW_COLUMNS,
    FORECAST_OPTIONS,
    _category_label,
    _details_points,
    _display_importance,
    _draft_changes,
    _export_filename,
    _export_suppliers,
    _filter_rows,
    _initials,
    _needs_calculation,
    _restore_draft,
    _sort_orders,
    _summary_metrics,
)
import app.ui.streamlit_app as application
from app.ui.settings_view import reset_filters


def test_grouped_table_columns_prioritize_decision_fields() -> None:
    assert list(ORDER_COLUMNS.values()) == [
        "Код 1С",
        "Наименование",
        "Количество",
        "Срочность",
        "Артикул",
        "Категория",
    ]
    assert list(REVIEW_COLUMNS.values()) == [
        "Код 1С",
        "Наименование",
        "Артикул",
        "Категория",
    ]
    assert "Обоснование" not in ORDER_COLUMNS.values()
    assert "Причина" not in REVIEW_COLUMNS.values()
    assert "supplier" not in ORDER_COLUMNS
    assert "supplier" not in REVIEW_COLUMNS


def test_authenticated_navigation_has_four_expected_pages(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_page(function, **kwargs):
        return {"function": function, **kwargs}

    def fake_navigation(pages, **kwargs):
        captured["pages"] = pages
        captured["options"] = kwargs
        return "navigation"

    monkeypatch.setattr(application.st, "Page", fake_page)
    monkeypatch.setattr(application.st, "navigation", fake_navigation)

    assert application._navigation() == "navigation"
    assert NAVIGATION_TITLES == (
        "Заказ",
        "Данные",
        "История заказов",
        "Точность",
    )
    assert [page["title"] for page in captured["pages"]] == list(
        NAVIGATION_TITLES
    )
    assert captured["options"] == {"position": "sidebar", "expanded": True}
    assert captured["pages"][0]["default"] is True


def test_profile_initials_use_first_two_name_parts() -> None:
    assert _initials("Павел Иванов") == "ПИ"
    assert _initials("") == "A"


def test_first_open_triggers_calculation() -> None:
    assert _needs_calculation({}, button_pressed=False)
    assert not _needs_calculation(
        {"recommendation_result": object()}, button_pressed=False
    )
    assert _needs_calculation(
        {"recommendation_result": object()}, button_pressed=True
    )


def test_reset_filters_restores_defaults(monkeypatch) -> None:
    state = {
        "filter_supplier": "SE",
        "filter_category": "5",
        "filter_query": "автомат",
    }
    monkeypatch.setattr("app.ui.settings_view.st.session_state", state)

    reset_filters()

    assert state == {
        "filter_supplier": "Оба",
        "filter_category": "Все",
        "filter_query": "",
    }


def test_summary_metrics_describe_supplier_orders() -> None:
    rows = pd.DataFrame(
        {
            "recommended_qty": [12, 8, 5],
            "urgency": ["высокая", "низкая", "проверить остаток"],
            "stock_unknown": [False, False, True],
        }
    )

    assert _summary_metrics(rows) == {
        "positions": 3,
        "quantity": 25,
        "high_urgency": 1,
        "stock_unknown": 1,
    }


def test_ml_importance_uses_russian_labels_and_percentage_shares() -> None:
    importance = pd.DataFrame(
        {
            "feature": ["zero_share_12", "same_month_last_year", "horizon"],
            "importance": [0.04, 0.01, -0.01],
        }
    )

    display = _display_importance(importance)

    assert display["Признак"].tolist() == [
        "Доля месяцев без продаж за 12 мес.",
        "Продажи в тот же месяц год назад",
        "Горизонт прогноза",
    ]
    assert display["Доля важности"].tolist() == [80.0, 20.0, 0.0]


def test_category_labels_explain_se_category_codes() -> None:
    assert _category_label("1") == "SE, категория 1"
    assert _category_label(5) == "SE, категория 5"
    assert _category_label("без категории") == "без категории"


def test_forecast_options_mark_default_and_experimental_methods() -> None:
    assert FORECAST_OPTIONS == {
        "Формула": "formula",
        "ML, экспериментально": "ml",
    }


def test_export_suppliers_follow_supplier_filter() -> None:
    assert _export_suppliers("Оба") == ("IEK", "SE")
    assert _export_suppliers("IEK") == ("IEK",)
    assert _export_suppliers("SE") == ("SE",)


def test_export_filename_uses_astrea_and_snapshot_date() -> None:
    assert _export_filename("2026-09-22") == "astrea_2026-09-22.xlsx"


def test_category_filter_changes_rows_and_unknown_stock_sorts_last() -> None:
    rows = pd.DataFrame(
        [
            {
                "sku_code": "NORMAL-LOW",
                "article": "A-1",
                "name": "Обычный",
                "supplier": "SE",
                "category": "1",
                "recommended_qty": 5,
                "urgency": "низкая",
                "stock_unknown": False,
            },
            {
                "sku_code": "UNKNOWN-HIGH",
                "article": "A-2",
                "name": "Неизвестный остаток",
                "supplier": "IEK",
                "category": "1",
                "recommended_qty": 1000,
                "urgency": "проверить остаток",
                "stock_unknown": True,
            },
            {
                "sku_code": "OTHER-CATEGORY",
                "article": "A-3",
                "name": "Другая категория",
                "supplier": "SE",
                "category": "2",
                "recommended_qty": 20,
                "urgency": "высокая",
                "stock_unknown": False,
            },
        ]
    )

    filtered = _filter_rows(rows, "Оба", "1", "")
    sorted_rows = _sort_orders(filtered)

    assert list(filtered["sku_code"]) == ["NORMAL-LOW", "UNKNOWN-HIGH"]
    assert list(sorted_rows["sku_code"]) == ["NORMAL-LOW", "UNKNOWN-HIGH"]


def test_approval_is_disabled_without_database() -> None:
    app = AppTest.from_string(
        """
from app.ui.streamlit_app import _approval_controls
_approval_controls("IEK", False)
"""
    ).run(timeout=10)

    assert not app.exception
    assert app.button[0].disabled
    assert "временно недоступны" in app.info[0].value


def test_editor_draft_restores_changed_quantities() -> None:
    recommendations = pd.DataFrame(
        [
            {
                "sku_code": "SKU-1",
                "supplier": "IEK",
                "recommended_qty": 12,
                "stock_unknown": False,
            }
        ]
    )
    drafts = {
        "SKU-1": {
            "approved_qty": 18,
            "comment": "Увеличить запас",
            "stock_checked": True,
        }
    }

    restored = _restore_draft(recommendations, drafts)
    changes = _draft_changes(
        _restore_draft(recommendations, {}), restored
    )

    assert restored.loc[0, "approved_qty"] == 18
    assert changes == drafts


def test_order_details_use_structured_calculation_fields() -> None:
    row = pd.Series(
        {
            "level": 120.4,
            "growth": 1.15,
            "seasonal_index": 1.2,
            "excluded_outlier_qty": 50,
            "stockout_added_qty": 25,
            "window_days": 54,
            "demand_window": 260,
            "safety_stock": 40,
            "free_stock": 30,
            "in_transit": 20,
            "moq": 6,
            "recommended_qty": 252,
        }
    )

    points = _details_points(row)

    assert len(points) == 7
    assert "база 120 шт./мес." in points[0]
    assert "исключено 50 шт." in points[0]
    assert "восстановлено 25 шт." in points[0]
    assert "Рост год к году: +15%" in points[1]
    assert points[-1] == "MOQ 6 шт., итог 252 шт."


def test_unauthenticated_page_does_not_load_partner_data() -> None:
    app = AppTest.from_string(
        """
import app.ui.streamlit_app as application

application.database_url = lambda: "postgresql://configured"
application.initialize_database = lambda connection_url: (True, "")
application.render_auth_screen = lambda connection_url: None

def forbidden_load(data_dir):
    raise AssertionError("load_data must not run before login")

application.load_data = forbidden_load
application.main()
"""
    ).run(timeout=10)

    assert not app.exception
    assert not app.dataframe


def test_authenticated_page_shows_summary_and_order_table() -> None:
    app = AppTest.from_string(
        """
import pandas as pd
import streamlit as st
import app.ui.streamlit_app as application

application.database_url = lambda: "postgresql://configured"
application.initialize_database = lambda connection_url: (True, "")
class DatasetContext:
    cache_key = ("demo", "demo")
    path_items = ()
    dataset_ids = {"IEK": None, "SE": None}
    current_rows = {}
application.resolve_dataset_context = lambda connection_url, data_dir: DatasetContext()
application.load_data = lambda *args: {
    "sales_tx": pd.DataFrame({"date": [pd.Timestamp("2026-09-22")]}),
    "sku_ref": pd.DataFrame({
        "supplier": ["IEK"], "category": ["без категории"]
    }),
}
order = pd.DataFrame([{
    "sku_code": "SKU-1", "article": "ART-1", "name": "Товар",
    "unit": "шт", "category": "без категории", "supplier": "IEK",
    "recommended_qty": 12, "stock_unknown": False, "urgency": "высокая",
    "explanation": "Расчёт", "moq": 6, "level": 4.0, "growth": 1.0,
    "seasonal_index": 1.0, "excluded_outlier_qty": 0.0,
    "stockout_added_qty": 0.0, "window_days": 54, "demand_window": 8.0,
    "safety_stock": 4.0, "free_stock": 0.0, "in_transit": 0.0,
}])
no_sales = pd.DataFrame(columns=[
    "sku_code", "article", "name", "unit", "category", "supplier"
])
application.calculate = lambda *args: (order, no_sales)
application.render_history = lambda connection_url: None
st.session_state["current_user"] = {
    "id": 1, "email": "manager@example.com", "full_name": "Менеджер"
}
application.main()
"""
    ).run(timeout=15)

    assert not app.exception
    assert [metric.value for metric in app.metric] == ["1", "12", "1", "0"]
    assert app.dataframe
    assert "Обоснование" not in app.dataframe[0].value.columns


def test_line_details_panel_contains_reasoning_and_edit_fields() -> None:
    app = AppTest.from_string(
        """
import pandas as pd
from app.ui.order_view import render_line_details

render_line_details("IEK", pd.Series({
    "sku_code": "SKU-1", "supplier": "IEK", "recommended_qty": 12,
    "approved_qty": 12, "comment": "", "stock_checked": True,
    "stock_unknown": False, "moq": 6, "level": 4.0, "growth": 1.0,
    "seasonal_index": 1.0, "excluded_outlier_qty": 0.0,
    "stockout_added_qty": 0.0, "window_days": 54, "demand_window": 8.0,
    "safety_stock": 4.0, "free_stock": 0.0, "in_transit": 0.0,
}))
"""
    ).run(timeout=10)

    assert not app.exception
    assert app.subheader[0].value == "Почему 12 шт."
    assert app.number_input[0].label == "Количество"
    assert app.text_input[0].label == "Комментарий"
