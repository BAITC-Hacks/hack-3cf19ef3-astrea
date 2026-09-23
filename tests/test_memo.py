import pandas as pd

from app.ui.memo import clear_all_caches, process_cache


def test_underscore_arguments_are_not_part_of_the_key():
    calls = []

    @process_cache(maxsize=4)
    def compute(value, _on_progress=None):
        calls.append(value)
        if _on_progress is not None:
            _on_progress("stage", 1.0)
        return value * 2

    progress = []
    assert compute(3, lambda *event: progress.append(event)) == 6
    assert compute(3, lambda *event: progress.append(("second", event))) == 6
    assert calls == [3]
    assert progress == [("stage", 1.0)]


def test_dataframes_are_returned_as_copies():
    @process_cache(maxsize=2)
    def load():
        return {"sales": pd.DataFrame({"qty": [1, 2]})}, pd.DataFrame({"x": [1]})

    tables, extra = load()
    tables["sales"].loc[0, "qty"] = 999
    extra["x"] = 0
    fresh_tables, fresh_extra = load()
    assert fresh_tables["sales"]["qty"].tolist() == [1, 2]
    assert fresh_extra["x"].tolist() == [1]


def test_lru_eviction_and_clear():
    calls = []

    @process_cache(maxsize=2, copy_result=False)
    def square(value):
        calls.append(value)
        return value * value

    square(1), square(2), square(3)
    square(1)
    assert calls == [1, 2, 3, 1]

    clear_all_caches()
    square(3)
    assert calls == [1, 2, 3, 1, 3]
