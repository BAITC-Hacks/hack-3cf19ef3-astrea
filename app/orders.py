"""Pure order-correction rules used before a manager approves an order."""

from typing import Dict, Optional

import numpy as np
import pandas as pd


KEYS = ["sku_code", "supplier"]
EDIT_COLUMNS = ["approved_qty", "comment", "stock_checked"]


def default_edits(recommendations: pd.DataFrame) -> pd.DataFrame:
    """Return editable defaults without mutating calculated recommendations."""

    edits = recommendations[KEYS].copy()
    edits["approved_qty"] = recommendations["recommended_qty"].astype(int)
    edits["comment"] = ""
    edits["stock_checked"] = ~recommendations["stock_unknown"].fillna(False).astype(
        bool
    )
    return edits


def _validated_quantities(frame: pd.DataFrame) -> pd.Series:
    values = pd.to_numeric(frame["approved_qty"], errors="coerce")
    invalid = values.isna() | ~np.isfinite(values) | values.lt(0)
    fractional = values.notna() & ~np.isclose(values, np.round(values))
    invalid |= fractional
    if invalid.any():
        sku_codes = ", ".join(frame.loc[invalid, "sku_code"].astype(str))
        raise ValueError(
            "Утверждённое количество должно быть целым и неотрицательным: "
            f"{sku_codes}"
        )
    return values.round().astype(int)


def apply_corrections(
    recommendations: pd.DataFrame,
    edits: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Apply manager edits and attach non-blocking warnings and eligibility."""

    missing = set([*KEYS, "recommended_qty", "moq", "stock_unknown"]).difference(
        recommendations.columns
    )
    if missing:
        raise ValueError(
            "Recommendations are missing correction columns: "
            + ", ".join(sorted(missing))
        )

    result = recommendations.copy().reset_index(drop=True)
    selected_edits = default_edits(result) if edits is None else edits.copy()
    edit_missing = set([*KEYS, *EDIT_COLUMNS]).difference(selected_edits.columns)
    if edit_missing:
        raise ValueError(
            "Edits are missing columns: " + ", ".join(sorted(edit_missing))
        )
    if selected_edits.duplicated(KEYS).any():
        raise ValueError("Edits contain duplicate SKU and supplier keys")

    result = result.merge(
        selected_edits[[*KEYS, *EDIT_COLUMNS]],
        on=KEYS,
        how="left",
        validate="one_to_one",
    )
    result["approved_qty"] = _validated_quantities(result)
    result["comment"] = result["comment"].fillna("").astype(str)
    result["stock_checked"] = result["stock_checked"].fillna(False).astype(bool)
    result["changed"] = result["approved_qty"].ne(
        result["recommended_qty"].astype(int)
    )
    result["included_in_order"] = (
        ~result["stock_unknown"].fillna(False).astype(bool)
        | result["stock_checked"]
    )

    warnings = []
    for row in result.itertuples(index=False):
        row_warnings = []
        multiple = max(int(row.moq), 1)
        if int(row.approved_qty) % multiple:
            row_warnings.append(f"количество не кратно MOQ {multiple}")
        if bool(row.changed) and not str(row.comment).strip():
            row_warnings.append("укажите причину корректировки")
        if bool(row.stock_unknown) and not bool(row.stock_checked):
            row_warnings.append(
                "остаток не сверен с 1С — строка не войдёт в заказ"
            )
        warnings.append("; ".join(row_warnings))
    result["approval_warning"] = warnings
    return result


def order_totals(lines: pd.DataFrame) -> Dict[str, int]:
    """Summarize corrected quantities shown above the approval editor."""

    return {
        "recommended_qty": int(lines["recommended_qty"].sum()),
        "approved_qty": int(
            lines.loc[lines["included_in_order"], "approved_qty"].sum()
        ),
        "changed_lines": int(lines["changed"].sum()),
        "excluded_lines": int((~lines["included_in_order"]).sum()),
    }


def approvable_lines(lines: pd.DataFrame) -> pd.DataFrame:
    """Return lines allowed into an approved order."""

    return lines.loc[lines["included_in_order"]].copy().reset_index(drop=True)


__all__ = [
    "apply_corrections",
    "approvable_lines",
    "default_edits",
    "order_totals",
]
