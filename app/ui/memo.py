"""In-process cache for heavy calculations that report progress to the UI.

Streamlit's st.cache_data/st.cache_resource record Streamlit calls made inside
the cached function so they can be replayed later. A progress callback that
updates a placeholder created outside the function breaks that replay on the
first (uncached) run. This cache stores results only, so callbacks are free to
touch the UI. Arguments whose names start with "_" are excluded from the key,
the same convention Streamlit uses.
"""

from collections import OrderedDict
from functools import wraps
import inspect
import threading
from typing import Any, Callable, Dict, List

import pandas as pd


_ALL_CACHES: List["_ProcessCache"] = []


def _copy_result(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    if isinstance(value, dict):
        return {key: _copy_result(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_copy_result(item) for item in value)
    return value


class _ProcessCache:
    def __init__(self, function: Callable[..., Any], maxsize: int, copy_result: bool):
        self._function = function
        self._signature = inspect.signature(function)
        self._maxsize = maxsize
        self._copy = copy_result
        self._values: "OrderedDict[tuple, Any]" = OrderedDict()
        self._key_locks: Dict[tuple, threading.Lock] = {}
        self._lock = threading.Lock()

    def _key(self, args: tuple, kwargs: dict) -> tuple:
        bound = self._signature.bind(*args, **kwargs)
        bound.apply_defaults()
        return tuple(
            (name, value)
            for name, value in bound.arguments.items()
            if not name.startswith("_")
        )

    def _hit(self, key: tuple) -> tuple[bool, Any]:
        with self._lock:
            if key in self._values:
                self._values.move_to_end(key)
                return True, self._values[key]
            return False, None

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        key = self._key(args, kwargs)
        found, value = self._hit(key)
        if not found:
            with self._lock:
                key_lock = self._key_locks.setdefault(key, threading.Lock())
            with key_lock:
                found, value = self._hit(key)
                if not found:
                    value = self._function(*args, **kwargs)
                    with self._lock:
                        self._values[key] = value
                        self._values.move_to_end(key)
                        while len(self._values) > self._maxsize:
                            self._values.popitem(last=False)
                        self._key_locks.pop(key, None)
        return _copy_result(value) if self._copy else value

    def clear(self) -> None:
        with self._lock:
            self._values.clear()


def process_cache(maxsize: int = 8, copy_result: bool = True) -> Callable[[Callable], Callable]:
    """Memoize by non-underscore arguments without Streamlit element replay."""

    def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
        cache = _ProcessCache(function, maxsize, copy_result)
        _ALL_CACHES.append(cache)

        @wraps(function)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return cache(*args, **kwargs)

        wrapper.clear = cache.clear  # type: ignore[attr-defined]
        return wrapper

    return decorator


def clear_all_caches() -> None:
    """Drop every process cache and Streamlit's data cache (dataset changed, retry)."""

    for cache in _ALL_CACHES:
        cache.clear()
    try:
        import streamlit as st

        st.cache_data.clear()
    except Exception:
        pass


__all__ = ["clear_all_caches", "process_cache"]
