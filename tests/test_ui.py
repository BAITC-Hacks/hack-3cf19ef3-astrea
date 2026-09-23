import pandas as pd

from app.ui.streamlit_app import (
    ORDER_COLUMNS,
    REVIEW_COLUMNS,
    _filter_rows,
    _needs_calculation,
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
