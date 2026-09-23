"""Historical forecast accuracy page."""

from pathlib import Path

import pandas as pd
import streamlit as st

from app.engine.backtest import run_backtest
from app.loaders import load_all


ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data" / "raw"
METHODS = (
    ("Формула", "our"),
    ("Методика партнёра", "partner"),
    ("ML", "ml"),
)
METRIC_COLUMNS = {
    "Метод": st.column_config.TextColumn(
        width="medium",
        help=(
            "Методика партнёра нестабильна для SKU с прогнозом выше 10 средних. "
            "ML экспериментальный: он системно занижает общий спрос."
        ),
    ),
    "WAPE": st.column_config.NumberColumn(
        width="small",
        format="%.2f%%",
        help="Суммарная абсолютная ошибка относительно суммарных продаж. Меньше лучше.",
    ),
    "MdAPE": st.column_config.NumberColumn(
        width="small",
        format="%.2f%%",
        help="Медианная абсолютная процентная ошибка по SKU. Меньше лучше.",
    ),
    "Смещение": st.column_config.NumberColumn(
        width="small",
        format="%+.2f%%",
        help="Отношение суммы прогноза к сумме факта минус 1. Ноль лучше.",
    ),
}


@st.cache_data(show_spinner="Сравниваем методы на истории")
def calculate_accuracy(
    data_dir: str, dataset_key: tuple[object, object]
) -> pd.DataFrame:
    """Run and cache the comparison for the selected pair of datasets."""

    del dataset_key
    return run_backtest(load_all(Path(data_dir)))


def _accuracy_table(row: pd.Series) -> pd.DataFrame:
    records = [
        {
            "Метод": label,
            "WAPE": float(row[f"{prefix}_wape"]) * 100,
            "MdAPE": float(row[f"{prefix}_mdape"]) * 100,
            "Смещение": float(row[f"{prefix}_bias"]) * 100,
        }
        for label, prefix in METHODS
    ]
    result = pd.DataFrame(records)
    best = result["WAPE"].idxmin()
    result.loc[best, "Метод"] = f"{result.loc[best, 'Метод']} · лучший"
    return result


def _highlight_best(row: pd.Series) -> list[str]:
    color = "background-color: #e7f2ec" if "лучший" in row["Метод"] else ""
    return [color] * len(row)


def render() -> None:
    st.title("Точность")
    dataset_key = tuple(st.session_state.get("dataset_ids", ("demo", "demo")))
    results = calculate_accuracy(str(DATA_DIR), dataset_key)

    columns = st.columns(2)
    for column, supplier in zip(columns, ("IEK", "SE")):
        row = results.loc[results["supplier"].eq(supplier)].iloc[0]
        with column:
            st.subheader(
                supplier,
                help=(
                    f"У методики партнёра {int(row['partner_outlier_sku_count'])} SKU "
                    "с прогнозом выше 10 средних. ML экспериментальный и не является "
                    "методом по умолчанию."
                ),
            )
            st.caption(
                "Обучение до 06.2026 · проверка на 07–08.2026 · "
                f"{int(row['sku_count'])} SKU"
            )
            table = _accuracy_table(row)
            st.dataframe(
                table.style.apply(_highlight_best, axis=1),
                column_config=METRIC_COLUMNS,
                hide_index=True,
                width="stretch",
            )


__all__ = ["METHODS", "_accuracy_table", "calculate_accuracy", "render"]
