import pandas as pd
import pytest

from app.orders import apply_corrections, approvable_lines, order_totals


@pytest.fixture
def recommendations() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "sku_code": "KNOWN",
                "supplier": "IEK",
                "recommended_qty": 12,
                "moq": 6,
                "stock_unknown": False,
            },
            {
                "sku_code": "UNKNOWN",
                "supplier": "IEK",
                "recommended_qty": 10,
                "moq": 5,
                "stock_unknown": True,
            },
        ]
    )


def test_default_corrections_keep_quantities_and_exclude_unknown_stock(
    recommendations: pd.DataFrame,
) -> None:
    result = apply_corrections(recommendations)

    assert result["approved_qty"].tolist() == [12, 10]
    assert result["comment"].tolist() == ["", ""]
    assert result["included_in_order"].tolist() == [True, False]
    assert "остаток не сверен с 1С" in result.iloc[1]["approval_warning"]


def test_correction_warnings_do_not_block_manager_decision(
    recommendations: pd.DataFrame,
) -> None:
    edits = pd.DataFrame(
        [
            {
                "sku_code": "KNOWN",
                "supplier": "IEK",
                "approved_qty": 7,
                "comment": "",
                "stock_checked": True,
            },
            {
                "sku_code": "UNKNOWN",
                "supplier": "IEK",
                "approved_qty": 15,
                "comment": "Остаток проверен",
                "stock_checked": True,
            },
        ]
    )

    result = apply_corrections(recommendations, edits)

    assert result["included_in_order"].all()
    assert "не кратно MOQ 6" in result.iloc[0]["approval_warning"]
    assert "укажите причину корректировки" in result.iloc[0]["approval_warning"]
    assert result.iloc[1]["approval_warning"] == ""
    assert approvable_lines(result)["sku_code"].tolist() == ["KNOWN", "UNKNOWN"]


@pytest.mark.parametrize("invalid", [-1, 1.5, "не число"])
def test_approved_quantity_must_be_non_negative_integer(
    recommendations: pd.DataFrame, invalid: object
) -> None:
    edits = pd.DataFrame(
        [
            {
                "sku_code": "KNOWN",
                "supplier": "IEK",
                "approved_qty": invalid,
                "comment": "",
                "stock_checked": True,
            },
            {
                "sku_code": "UNKNOWN",
                "supplier": "IEK",
                "approved_qty": 10,
                "comment": "",
                "stock_checked": False,
            },
        ]
    )

    with pytest.raises(ValueError, match="целым и неотрицательным"):
        apply_corrections(recommendations, edits)


def test_order_totals_include_only_stock_checked_lines(
    recommendations: pd.DataFrame,
) -> None:
    result = apply_corrections(recommendations)

    assert order_totals(result) == {
        "recommended_qty": 22,
        "approved_qty": 12,
        "changed_lines": 0,
        "excluded_lines": 1,
    }
