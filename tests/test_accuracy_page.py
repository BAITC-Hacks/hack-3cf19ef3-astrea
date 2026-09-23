import pandas as pd
from streamlit.testing.v1 import AppTest

from app.ui.pages.accuracy_page import _accuracy_table


def _result_row(supplier: str) -> dict[str, object]:
    return {
        "supplier": supplier,
        "sku_count": 10,
        "our_wape": 0.30,
        "our_mdape": 0.20,
        "our_bias": 0.05,
        "partner_wape": 1.20,
        "partner_mdape": 0.40,
        "partner_bias": 0.80,
        "partner_outlier_sku_count": 2,
        "partner_outlier_error_share": 0.70,
        "ml_wape": 0.25,
        "ml_mdape": 0.22,
        "ml_bias": -0.23,
    }


def test_accuracy_table_contains_three_methods_and_marks_best() -> None:
    table = _accuracy_table(pd.Series(_result_row("IEK")))

    assert len(table) == 3
    assert table["Метод"].tolist() == [
        "Формула",
        "Методика партнёра",
        "ML · лучший",
    ]
    assert table["WAPE"].tolist() == [30.0, 120.0, 25.0]


def test_accuracy_page_shows_three_methods_for_each_supplier() -> None:
    app = AppTest.from_string(
        """
import pandas as pd
import app.ui.pages.accuracy_page as page

page.calculate_accuracy = lambda data_dir, dataset_key: pd.DataFrame([
    {
        "supplier": supplier, "sku_count": 10,
        "our_wape": 0.30, "our_mdape": 0.20, "our_bias": 0.05,
        "partner_wape": 1.20, "partner_mdape": 0.40, "partner_bias": 0.80,
        "partner_outlier_sku_count": 2,
        "partner_outlier_error_share": 0.70,
        "ml_wape": 0.25, "ml_mdape": 0.22, "ml_bias": -0.23,
    }
    for supplier in ("IEK", "SE")
])
page.render()
"""
    ).run(timeout=10)

    assert not app.exception
    assert [heading.value for heading in app.subheader] == ["IEK", "SE"]
    assert len(app.dataframe) == 2
    assert all(len(table.value) == 3 for table in app.dataframe)
