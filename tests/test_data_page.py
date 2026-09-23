from types import SimpleNamespace

import pandas as pd

from app.ui.pages.data_page import _source_label, _supplier_stats


def test_dataset_card_stats_are_scoped_to_supplier() -> None:
    data = {
        "sales_tx": pd.DataFrame(
            {
                "supplier": ["IEK", "IEK", "SE"],
                "sku_code": ["I-1", "I-2", "S-1"],
                "date": pd.to_datetime(["2026-09-20", "2026-09-22", "2026-09-21"]),
            }
        ),
        "sku_ref": pd.DataFrame(
            {
                "supplier": ["IEK", "IEK", "SE"],
                "sku_code": ["I-1", "I-2", "S-1"],
            }
        ),
    }

    stats = _supplier_stats(data, "IEK")

    assert stats == {
        "data_as_of": pd.Timestamp("2026-09-22").date(),
        "sku_count": 2,
        "sales_rows": 2,
    }


def test_source_label_distinguishes_demo_and_uploaded_data() -> None:
    demo = SimpleNamespace(current_rows={})
    uploaded = SimpleNamespace(
        current_rows={
            "IEK": {
                "uploaded_by_name": "Павел",
                "uploaded_at": pd.Timestamp("2026-09-23 10:30"),
            }
        }
    )

    assert _source_label(demo, "IEK") == "Демо-данные"
    assert _source_label(uploaded, "IEK") == "Загружено: Павел, 23.09.2026 10:30"
