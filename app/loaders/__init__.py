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

    combined = pd.concat(references, ignore_index=True)
    combined = combined.dropna(subset=["sku_code", "name"])
    return combined.drop_duplicates(["sku_code", "supplier"], keep="first").reset_index(
        drop=True
    )


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

    validate_model(tables)
    return tables


__all__ = ["load_all"]
