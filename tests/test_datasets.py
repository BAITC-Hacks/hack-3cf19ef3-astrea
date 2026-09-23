from io import BytesIO
from pathlib import Path

import pytest

from app.datasets import DatasetValidationError, detect_file_type, validate_dataset


RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


def _expected_type(path: Path) -> str:
    name = path.name.lower()
    if "сезонность" in name:
        return "seasonality"
    if "динамика продаж" in name:
        return "sales_tx"
    if "ежемесячные продажи" in name:
        return "sales_monthly"
    if "ежемесячные остатки" in name:
        return "stock_monthly"
    if "moq" in name:
        return "moq"
    return "in_transit"


@pytest.mark.parametrize("path", sorted(RAW.glob("*/*.xlsx")), ids=lambda path: path.name)
def test_detects_all_real_workbooks_by_headers(path: Path) -> None:
    assert detect_file_type(path) == _expected_type(path)


@pytest.mark.parametrize(
    ("supplier", "directory"),
    [("IEK", "IEK"), ("SE", "Systeme electric")],
)
def test_validates_complete_real_supplier_dataset(
    supplier: str, directory: str
) -> None:
    result = validate_dataset(supplier, sorted((RAW / directory).glob("*.xlsx")))

    assert result.supplier == supplier
    assert result.sales_rows > 0
    assert result.sku_count > 0
    assert result.data_as_of.isoformat() == "2026-09-22"
    assert set(result.payloads) == {
        "sales_tx",
        "sales_monthly",
        "stock_monthly",
        "in_transit",
        "moq",
    }
    assert any(report.file_type == "seasonality" for report in result.reports)


def test_rejects_incomplete_dataset_with_missing_type_names() -> None:
    sources = [
        path
        for path in (RAW / "IEK").glob("*.xlsx")
        if "MOQ" not in path.name
    ]

    with pytest.raises(DatasetValidationError, match="MOQ"):
        validate_dataset("IEK", sources)


def test_corrupt_workbook_error_contains_original_name() -> None:
    broken = BytesIO(b"not an xlsx workbook")
    broken.name = "испорченный.xlsx"

    with pytest.raises(DatasetValidationError, match="испорченный.xlsx"):
        validate_dataset("IEK", [broken])
