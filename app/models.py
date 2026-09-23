"""Canonical DataFrame schemas shared by all supplier loaders."""

from collections.abc import Mapping

import pandas as pd


TABLE_COLUMNS = {
    "sales_tx": ("date", "sku_code", "supplier", "qty"),
    "sales_monthly": ("sku_code", "supplier", "month", "qty"),
    "stock_monthly": ("sku_code", "supplier", "month", "opening_stock"),
    "current_stock": ("sku_code", "supplier", "free_stock", "stock_unknown"),
    "in_transit": ("sku_code", "supplier", "qty"),
    "moq": ("sku_code", "supplier", "moq"),
    "sku_ref": ("sku_code", "supplier", "name", "article", "unit", "category"),
}


def validate_model(tables: Mapping[str, pd.DataFrame]) -> None:
    """Raise a useful error when a loader breaks the canonical model."""

    missing_tables = set(TABLE_COLUMNS).difference(tables)
    if missing_tables:
        names = ", ".join(sorted(missing_tables))
        raise ValueError(f"Missing model tables: {names}")

    for table_name, expected_columns in TABLE_COLUMNS.items():
        actual_columns = tuple(tables[table_name].columns)
        if actual_columns != expected_columns:
            raise ValueError(
                f"{table_name} columns are {actual_columns}, expected {expected_columns}"
            )
