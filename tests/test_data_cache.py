from pathlib import Path

import pandas as pd

from app.data_cache import load_with_disk_cache
from app.datasets import DatasetContext


def _context(iek_id: int) -> DatasetContext:
    return DatasetContext(
        {"IEK": iek_id, "SE": None},
        (("IEK", "sales_tx", f"/uploads/{iek_id}/sales_tx.xlsx"),),
        {},
    )


def test_disk_cache_reuses_exact_dataset_id_key(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[object, object]] = []

    def fake_load(context, on_progress=None):
        calls.append(context.cache_key)
        return {"sales_tx": pd.DataFrame({"qty": [context.dataset_ids["IEK"]]})}

    monkeypatch.setattr("app.data_cache.load_dataset_context", fake_load)
    first = load_with_disk_cache(_context(10), tmp_path)
    second = load_with_disk_cache(_context(10), tmp_path)
    changed = load_with_disk_cache(_context(11), tmp_path)

    assert calls == [(10, "demo"), (11, "demo")]
    assert first["sales_tx"].equals(second["sales_tx"])
    assert changed["sales_tx"].iloc[0, 0] == 11


def test_disk_cache_progress_finishes_on_hit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.data_cache.load_dataset_context",
        lambda context, on_progress=None: {"sales_tx": pd.DataFrame({"qty": [1]})},
    )
    context = _context(20)
    load_with_disk_cache(context, tmp_path)
    progress: list[tuple[str, float]] = []

    load_with_disk_cache(
        context,
        tmp_path,
        lambda stage, fraction: progress.append((stage, fraction)),
    )

    assert progress == [("Готовим данные", 1.0)]
