"""Disk cache for canonical 1C tables, keyed by current dataset IDs."""

from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from app.datasets import DatasetContext, load_dataset_context


CACHE_VERSION = 1


def cache_path(cache_dir: Path, dataset_key: tuple[object, object]) -> Path:
    """Return a stable cache filename for one IEK/SE dataset pair."""

    if tuple(dataset_key) == ("demo", "demo"):
        return Path(cache_dir) / "model.pkl"
    safe = "_".join(str(value).replace("/", "_") for value in dataset_key)
    return Path(cache_dir) / f"model_{safe}.pkl"


def read_cache(
    cache_dir: Path, dataset_key: tuple[object, object]
) -> dict[str, pd.DataFrame] | None:
    """Read only a cache created for the exact current dataset IDs."""

    path = cache_path(cache_dir, dataset_key)
    if not path.exists():
        return None
    try:
        payload = pd.read_pickle(path)
    except Exception:
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("version") != CACHE_VERSION
        or tuple(payload.get("dataset_key", ())) != tuple(dataset_key)
    ):
        return None
    tables = payload.get("tables")
    return tables if isinstance(tables, dict) else None


def write_cache(
    cache_dir: Path,
    dataset_key: tuple[object, object],
    tables: dict[str, pd.DataFrame],
) -> Path:
    """Atomically persist canonical tables for a dataset pair."""

    path = cache_path(cache_dir, dataset_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    pd.to_pickle(
        {
            "version": CACHE_VERSION,
            "dataset_key": tuple(dataset_key),
            "tables": tables,
        },
        temporary,
    )
    temporary.replace(path)
    return path


def load_with_disk_cache(
    context: DatasetContext,
    cache_dir: Path,
    on_progress: Optional[Callable[[str, float], None]] = None,
) -> dict[str, pd.DataFrame]:
    """Load an exact ID-keyed pickle, or rebuild it from supplier workbooks."""

    key = context.cache_key
    cached = read_cache(cache_dir, key)
    if cached is not None:
        if on_progress is not None:
            on_progress("Готовим данные", 1.0)
        return cached
    tables = load_dataset_context(context, on_progress)
    write_cache(cache_dir, key, tables)
    return tables


__all__ = [
    "cache_path",
    "load_with_disk_cache",
    "read_cache",
    "write_cache",
]
