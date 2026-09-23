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
                "category": "1",
                "supplier": "IEK",
                "recommended_qty": 12,
                "stock_unknown": False,
                "urgency": "высокая",
                "explanation": "Расчётное обоснование",
            },
            {
                "sku_code": "SKU-2",
                "article": "ART-2",
                "name": "Товар с неизвестным остатком",
                "unit": "шт",
                "category": "без категории",
                "supplier": "IEK",
                "recommended_qty": 24,
                "stock_unknown": True,
                "urgency": "проверить остаток",
                "explanation": "Сверить остаток с 1С",
            },
        ]
    )

    workbook = openpyxl.load_workbook(BytesIO(export_xlsx(recommendations)))

    assert workbook.sheetnames == [
        "IEK",
        "SE",
        "Проверить остаток",
        "Обоснование",
    ]
    assert [cell.value for cell in workbook["IEK"][1]] == [
        "Код 1С",
        "Артикул поставщика",
        "Наименование",
        "Ед.",
        "Категория",
        "Количество",
    ]
    assert [cell.value for cell in workbook["SE"][1]] == [
        "Код 1С",
        "Артикул поставщика",
        "Наименование",
        "Ед.",
        "Категория",
        "Количество",
    ]
    assert [cell.value for cell in workbook["Обоснование"][1]][-3:] == [
        "Количество",
        "Срочность",
        "Обоснование",
    ]
    assert workbook["IEK"].max_row == 2
    assert workbook["IEK"]["A2"].value == "SKU-1"
    assert workbook["Проверить остаток"].max_row == 2
    assert workbook["Проверить остаток"]["A2"].value == "SKU-2"
    assert workbook["Проверить остаток"]["G1"].value == "Обоснование"
    assert workbook["Обоснование"].max_row == 3
    assert all(not sheet.merged_cells.ranges for sheet in workbook.worksheets)
