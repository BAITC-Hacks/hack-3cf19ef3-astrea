"""Public entry point for loading both suppliers into one data model."""

from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd

from app.models import validate_model

from . import iek, se


def _find_one(directory: Path, fragments: Iterable[str]) -> Path:
    candidates: List[Path] = []
    lowered_fragments = tuple(fragment.lower() for fragment in fragments)
    for path in directory.glob("*.xlsx"):
        name = path.name.lower()
        if not name.startswith("~$") and all(fragment in name for fragment in lowered_fragments):
            candidates.append(path)

    if len(candidates) != 1:
        matches = ", ".join(path.name for path in candidates) or "none"
        raise FileNotFoundError(
            f"Expected one xlsx matching {lowered_fragments} in {directory}; found {matches}"
        )
    return candidates[0]


def _supplier_paths(data_dir: Path) -> Dict[str, Dict[str, Path]]:
    iek_dir = data_dir / "IEK"
    se_dir = data_dir / "Systeme electric"
    return {
        "IEK": {
            "sales_tx": _find_one(iek_dir, ("динамика продаж",)),
            "sales_monthly": _find_one(iek_dir, ("ежемесячные продажи",)),
            "stock_monthly": _find_one(iek_dir, ("ежемесячные остатки",)),
            "in_transit": _find_one(iek_dir, ("путь",)),
            "moq": _find_one(iek_dir, ("moq",)),
        },
        "SE": {
            "sales_tx": _find_one(se_dir, ("динамика продаж",)),
            "sales_monthly": _find_one(se_dir, ("ежемесячные продажи",)),
            "stock_monthly": _find_one(se_dir, ("ежемесячные остатки",)),
            "in_transit": _find_one(se_dir, ("товар в пути",)),
            "moq": _find_one(se_dir, ("moq",)),
        },
    }


def _combine_references(paths: Dict[str, Dict[str, Path]]) -> pd.DataFrame:
    references = []
    for supplier, loader in (("IEK", iek), ("SE", se)):
        for table_name in ("sales_monthly", "stock_monthly", "in_transit", "moq"):
            references.append(loader.load_sku_ref(paths[supplier][table_name]))

    combined = pd.concat(references, ignore_index=True).dropna(subset=["sku_code", "name"])

    def first_nonempty(values: pd.Series) -> str:
        present = values.astype("string").fillna("")
        present = present.loc[present.str.strip().ne("")]
        return "" if present.empty else str(present.iloc[0])

    return (
        combined.groupby(["sku_code", "supplier"], as_index=False, sort=False)
        .agg({"name": first_nonempty, "article": first_nonempty, "unit": first_nonempty})
        [["sku_code", "supplier", "name", "article", "unit"]]
    )


def _build_current_stock(
    sku_ref: pd.DataFrame,
    stock_monthly: pd.DataFrame,
    sales_tx: pd.DataFrame,
    se_snapshot: pd.DataFrame,
) -> pd.DataFrame:
    """Combine the SE snapshot with a conservative month-to-date fallback."""

    as_of = sales_tx["date"].max()
    if pd.isna(as_of):
        raise ValueError("Cannot calculate current stock without sales transaction dates")
    current_month = pd.Timestamp(as_of).strftime("%Y-%m")
    month_start = pd.Timestamp(as_of).to_period("M").start_time

    opening = (
        stock_monthly.loc[stock_monthly["month"].eq(current_month)]
        .groupby(["sku_code", "supplier"], as_index=False)["opening_stock"]
        .sum()
    )
    sales = (
        sales_tx.loc[sales_tx["date"].between(month_start, as_of)]
        .groupby(["sku_code", "supplier"], as_index=False)["qty"]
        .sum()
        .rename(columns={"qty": "month_sales"})
    )

    result = sku_ref[["sku_code", "supplier"]].merge(
        opening, on=["sku_code", "supplier"], how="left"
    )
    result = result.merge(sales, on=["sku_code", "supplier"], how="left")
    result["free_stock"] = (
        result["opening_stock"].fillna(0.0) - result["month_sales"].fillna(0.0)
    ).clip(lower=0.0)

    snapshot = se_snapshot.rename(columns={"free_stock": "snapshot_stock"})
    result = result.merge(snapshot, on=["sku_code", "supplier"], how="left")
    use_snapshot = result["supplier"].eq("SE") & result["snapshot_stock"].notna()
    result.loc[use_snapshot, "free_stock"] = result.loc[use_snapshot, "snapshot_stock"]
    result["free_stock"] = result["free_stock"].astype(float)
    result["stock_unknown"] = (
        result["supplier"].eq("IEK")
        & result["month_sales"].fillna(0.0).gt(result["opening_stock"].fillna(0.0))
    )
    final = result[["sku_code", "supplier", "free_stock", "stock_unknown"]].copy()
    final.attrs["estimated_keys"] = list(
        result.loc[~use_snapshot, ["sku_code", "supplier"]].itertuples(index=False, name=None)
    )
    return final


def load_all(data_dir: Path) -> Dict[str, pd.DataFrame]:
    """Load IEK and Systeme Electric workbooks into canonical DataFrames."""

    data_dir = Path(data_dir)
    paths = _supplier_paths(data_dir)

    tables: Dict[str, pd.DataFrame] = {}
    for table_name, function_name in (
        ("sales_tx", "load_sales_tx"),
        ("sales_monthly", "load_sales_monthly"),
        ("stock_monthly", "load_stock_monthly"),
        ("in_transit", "load_in_transit"),
    ):
        tables[table_name] = pd.concat(
            [
                getattr(iek, function_name)(paths["IEK"][table_name]),
                getattr(se, function_name)(paths["SE"][table_name]),
            ],
            ignore_index=True,
        )

    tables["sku_ref"] = _combine_references(paths)
    raw_moq = pd.concat(
        [iek.load_moq(paths["IEK"]["moq"]), se.load_moq(paths["SE"]["moq"])],
        ignore_index=True,
    )
    tables["moq"] = tables["sku_ref"][["sku_code", "supplier"]].merge(
        raw_moq, on=["sku_code", "supplier"], how="left"
    )
    tables["moq"]["moq"] = tables["moq"]["moq"].fillna(1).astype("Int64")
    tables["current_stock"] = _build_current_stock(
        tables["sku_ref"],
        tables["stock_monthly"],
        tables["sales_tx"],
        se.load_current_stock(paths["SE"]["in_transit"]),
    )

    validate_model(tables)
    return tables


__all__ = ["load_all"]
