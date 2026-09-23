import pandas as pd
from streamlit.testing.v1 import AppTest

from app.ui.streamlit_app import (
    ORDER_COLUMNS,
    REVIEW_COLUMNS,
    FORECAST_OPTIONS,
    _category_label,
    _display_importance,
    _draft_changes,
    _export_suppliers,
    _filter_rows,
    _needs_calculation,
    _restore_draft,
    _sort_orders,
    _summary_metrics,
)


def test_grouped_table_columns_prioritize_decision_fields() -> None:
    assert list(ORDER_COLUMNS.values()) == [
        "Код 1С",
        "Наименование",
        "Количество",
        "Срочность",
        "Обоснование",
        "Артикул",
        "Категория",
    ]
    assert list(REVIEW_COLUMNS.values()) == [
        "Код 1С",
        "Наименование",
        "Причина",
        "Артикул",
        "Категория",
    ]
    assert "supplier" not in ORDER_COLUMNS
    assert "supplier" not in REVIEW_COLUMNS


def test_first_open_triggers_calculation() -> None:
    assert _needs_calculation({}, button_pressed=False)
    assert not _needs_calculation(
        {"recommendation_result": object()}, button_pressed=False
    )
    assert _needs_calculation(
        {"recommendation_result": object()}, button_pressed=True
    )


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
        "Формула (по умолчанию)": "formula",
        "ML (экспериментально)": "ml",
    }


def test_export_suppliers_follow_supplier_filter() -> None:
    assert _export_suppliers("Оба") == ("IEK", "SE")
    assert _export_suppliers("IEK") == ("IEK",)
    assert _export_suppliers("SE") == ("SE",)


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
    assert app.text_input[0].disabled
    assert "утверждение и история отключены" in app.info[0].value


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
