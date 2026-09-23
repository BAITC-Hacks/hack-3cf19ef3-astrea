"""Create a 1C-ready workbook from purchase recommendations."""

from io import BytesIO
from typing import Iterable, Tuple

import pandas as pd


SUPPLIERS: Tuple[str, ...] = ("IEK", "SE")
ORDER_COLUMNS = {
    "sku_code": "Код 1С",
    "article": "Артикул поставщика",
    "name": "Наименование",
    "unit": "Ед.",
    "category": "Категория",
    "export_qty": "Количество",
}
EXPLANATION_COLUMNS = {
    "sku_code": "Код 1С",
    "article": "Артикул поставщика",
    "name": "Наименование",
    "unit": "Ед.",
    "category": "Категория",
    "supplier": "Поставщик",
    "recommended_qty": "Количество",
    "urgency": "Срочность",
    "explanation": "Обоснование",
}
STOCK_REVIEW_COLUMNS = {
    **ORDER_COLUMNS,
    "explanation": "Обоснование",
}
APPROVED_EXPLANATION_COLUMNS = {
    "sku_code": "Код 1С",
    "article": "Артикул поставщика",
    "name": "Наименование",
    "unit": "Ед.",
    "category": "Категория",
    "supplier": "Поставщик",
    "recommended_qty": "Рекомендовано",
    "approved_qty": "Утверждено",
    "comment": "Комментарий",
    "urgency": "Срочность",
    "explanation": "Обоснование",
}


def _select_and_rename(frame: pd.DataFrame, columns: dict[str, str]) -> pd.DataFrame:
    missing = set(columns).difference(frame.columns)
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"Recommendations are missing export columns: {names}")
    return frame[list(columns)].rename(columns=columns)


def export_xlsx(
    recommendations: pd.DataFrame, suppliers: Iterable[str] = SUPPLIERS
) -> bytes:
    """Return an xlsx with one import sheet per supplier and an audit sheet."""

    supplier_names = tuple(dict.fromkeys(str(name) for name in suppliers))
    if not supplier_names:
        raise ValueError("At least one supplier sheet is required")

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame = recommendations.copy()
        has_approved_quantities = "approved_qty" in frame
        frame["export_qty"] = (
            frame["approved_qty"]
            if has_approved_quantities
            else frame["recommended_qty"]
        )
        if "comment" not in frame:
            frame["comment"] = ""
        stock_unknown = frame["stock_unknown"].fillna(False).astype(bool)
        if "stock_checked" in frame:
            stock_review = stock_unknown & ~frame["stock_checked"].fillna(False).astype(
                bool
            )
        else:
            stock_review = stock_unknown
        importable = frame.loc[~stock_review]
        for supplier in supplier_names:
            supplier_rows = importable.loc[
                importable["supplier"].eq(supplier)
            ]
            order_sheet = _select_and_rename(supplier_rows, ORDER_COLUMNS)
            order_sheet.to_excel(writer, sheet_name=supplier[:31], index=False)

        stock_review_sheet = _select_and_rename(
            frame.loc[stock_review], STOCK_REVIEW_COLUMNS
        )
        stock_review_sheet.to_excel(
            writer, sheet_name="Проверить остаток", index=False
        )

        explanation_sheet = _select_and_rename(
            frame,
            APPROVED_EXPLANATION_COLUMNS
            if has_approved_quantities
            else EXPLANATION_COLUMNS,
        )
        explanation_sheet.to_excel(writer, sheet_name="Обоснование", index=False)

        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for column_cells in worksheet.columns:
                values = ("" if cell.value is None else str(cell.value) for cell in column_cells)
                width = min(max((len(value) for value in values), default=0) + 2, 60)
                worksheet.column_dimensions[column_cells[0].column_letter].width = width

    return output.getvalue()


__all__ = ["export_xlsx"]
