from io import BytesIO

import openpyxl
import pandas as pd

from app.export import export_xlsx


def test_export_has_supplier_sheets_and_explanation_sheet() -> None:
    recommendations = pd.DataFrame(
        [
            {
                "sku_code": "SKU-1",
                "article": "ART-1",
                "name": "Тестовый товар",
                "unit": "шт",
                "supplier": "IEK",
                "recommended_qty": 12,
                "urgency": "высокая",
                "explanation": "Расчётное обоснование",
            }
        ]
    )

    workbook = openpyxl.load_workbook(BytesIO(export_xlsx(recommendations)))

    assert workbook.sheetnames == ["IEK", "SE", "Обоснование"]
    assert [cell.value for cell in workbook["IEK"][1]] == [
        "Код 1С",
        "Артикул поставщика",
        "Наименование",
        "Ед.",
        "Количество",
    ]
    assert [cell.value for cell in workbook["SE"][1]] == [
        "Код 1С",
        "Артикул поставщика",
        "Наименование",
        "Ед.",
        "Количество",
    ]
    assert [cell.value for cell in workbook["Обоснование"][1]][-3:] == [
        "Количество",
        "Срочность",
        "Обоснование",
    ]
    assert all(not sheet.merged_cells.ranges for sheet in workbook.worksheets)
