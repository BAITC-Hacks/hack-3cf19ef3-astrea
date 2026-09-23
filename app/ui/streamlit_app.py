"""Streamlit interface for calculating and exporting supplier orders."""

from pathlib import Path
import sys
from typing import Dict, Tuple

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import COVERAGE_DAYS, LEAD_TIME_DAYS, EngineConfig  # noqa: E402
from app.engine.pipeline import build_recommendations  # noqa: E402
from app.export import export_xlsx  # noqa: E402
from app.loaders import load_all  # noqa: E402


DATA_DIR = ROOT / "data" / "raw"
SUPPLIER_OPTIONS = ("Оба", "IEK", "SE")
ORDER_COLUMNS = {
    "sku_code": "Код 1С",
    "article": "Артикул",
    "name": "Наименование",
    "category": "Категория",
    "supplier": "Поставщик",
    "recommended_qty": "Рекомендуемое количество",
    "urgency": "Срочность",
    "explanation": "Обоснование",
}
REVIEW_COLUMNS = {
    "sku_code": "Код 1С",
    "article": "Артикул",
    "name": "Наименование",
    "category": "Категория",
    "supplier": "Поставщик",
    "reason": "Причина",
}
URGENCY_ORDER = {"высокая": 0, "средняя": 1, "низкая": 2}


@st.cache_data(show_spinner="Загружаем данные из 1С…")
def load_data(data_dir: str) -> Dict[str, pd.DataFrame]:
    """Load source workbooks once until their cache key changes."""

    return load_all(Path(data_dir))


@st.cache_data(show_spinner="Рассчитываем рекомендации…")
def calculate(
    data_dir: str,
    lead_time_iek: int,
    lead_time_se: int,
    coverage_days: int,
    planned_growth_iek_percent: float,
    planned_growth_se_percent: float,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Cache each calculation parameter combination on top of cached loading."""

    config = EngineConfig(
        lead_time_days={"IEK": lead_time_iek, "SE": lead_time_se},
        coverage_days=coverage_days,
        planned_growth={
            "IEK": planned_growth_iek_percent / 100.0,
            "SE": planned_growth_se_percent / 100.0,
        },
    )
    return build_recommendations(load_data(data_dir), config)


def _filter_rows(
    frame: pd.DataFrame,
    supplier_choice: str,
    category_choice: str,
    sku_query: str,
) -> pd.DataFrame:
    result = frame
    if supplier_choice != "Оба":
        result = result.loc[result["supplier"].eq(supplier_choice)]
    if category_choice != "Все":
        result = result.loc[result["category"].eq(category_choice)]
    query = sku_query.strip()
    if query:
        searchable = result[["sku_code", "article", "name"]].fillna("").astype(str)
        matches = searchable.apply(
            lambda column: column.str.contains(query, case=False, regex=False)
        ).any(axis=1)
        result = result.loc[matches]
    return result.copy()


def _sort_orders(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.assign(
        _stock_unknown_rank=frame["stock_unknown"].fillna(False).astype(int),
        _urgency_rank=frame["urgency"].map(URGENCY_ORDER).fillna(len(URGENCY_ORDER)),
    )
    return result.sort_values(
        ["_stock_unknown_rank", "_urgency_rank", "supplier", "recommended_qty"],
        ascending=[True, True, True, False],
    ).drop(columns=["_stock_unknown_rank", "_urgency_rank"])


def _show_grouped(frame: pd.DataFrame, columns: dict[str, str]) -> None:
    if frame.empty:
        st.info("По выбранным фильтрам строк нет.")
        return
    for supplier, supplier_rows in frame.groupby("supplier", sort=False):
        st.subheader(str(supplier))
        display = supplier_rows[list(columns)].rename(columns=columns)
        unknown_indices = set(
            supplier_rows.index[
                supplier_rows.get("stock_unknown", pd.Series(False, index=supplier_rows.index))
                .fillna(False)
                .astype(bool)
            ]
        )
        if unknown_indices:
            st.caption(
                "Жёлтым выделены строки с неизвестным текущим остатком — "
                "их нужно сверить с 1С."
            )
            display = display.style.apply(
                lambda row: (
                    ["background-color: #fff3cd"] * len(row)
                    if row.name in unknown_indices
                    else [""] * len(row)
                ),
                axis=1,
            )
        st.dataframe(
            display,
            width="stretch",
            hide_index=True,
        )


def main() -> None:
    st.set_page_config(page_title="Автозаказ", page_icon="📦", layout="wide")
    st.title("Автозаказ поставщикам")
    st.caption("Расчёт выполняется локально. Заказ поставщику не отправляется.")

    try:
        data = load_data(str(DATA_DIR))
    except Exception as error:
        st.error(f"Не удалось загрузить данные из {DATA_DIR}: {error}")
        st.stop()

    as_of = pd.Timestamp(data["sales_tx"]["date"].max()).date()
    st.info(f"Дата среза данных: {as_of:%d.%m.%Y}")

    with st.sidebar:
        st.header("Параметры расчёта")
        supplier_choice = st.selectbox("Поставщик", SUPPLIER_OPTIONS)
        categories = [
            "Все",
            *sorted(data["sku_ref"]["category"].dropna().astype(str).unique()),
        ]
        category_choice = st.selectbox("Категория", categories)
        sku_query = st.text_input("Фильтр по коду, артикулу или наименованию")
        lead_time_iek = int(
            st.number_input(
                "Срок поставки IEK, дней",
                min_value=1,
                max_value=365,
                value=LEAD_TIME_DAYS["IEK"],
            )
        )
        st.caption("IEK: 24 дня по датам документов «в пути» (медиана по объёму).")
        lead_time_se = int(
            st.number_input(
                "Срок поставки SE, дней",
                min_value=1,
                max_value=365,
                value=LEAD_TIME_DAYS["SE"],
            )
        )
        st.caption("SE: 35 дней — допущение, дат поставки в данных нет.")
        planned_growth_iek = float(
            st.number_input(
                "Плановый прирост IEK, %",
                min_value=-100.0,
                max_value=500.0,
                value=0.0,
                step=1.0,
            )
        )
        planned_growth_se = float(
            st.number_input(
                "Плановый прирост SE, %",
                min_value=-100.0,
                max_value=500.0,
                value=0.0,
                step=1.0,
            )
        )
        coverage_days = int(
            st.number_input(
                "Период покрытия, дней",
                min_value=1,
                max_value=365,
                value=COVERAGE_DAYS,
            )
        )
        run_calculation = st.button(
            "Рассчитать", type="primary", width="stretch"
        )

    if run_calculation:
        st.session_state["recommendation_result"] = calculate(
            str(DATA_DIR),
            lead_time_iek,
            lead_time_se,
            coverage_days,
            planned_growth_iek,
            planned_growth_se,
        )
        st.session_state["calculation_parameters"] = (
            lead_time_iek,
            lead_time_se,
            coverage_days,
            planned_growth_iek,
            planned_growth_se,
        )

    if "recommendation_result" not in st.session_state:
        st.write("Задайте параметры и нажмите «Рассчитать».")
        return

    previous_parameters = st.session_state.get("calculation_parameters")
    current_parameters = (
        lead_time_iek,
        lead_time_se,
        coverage_days,
        planned_growth_iek,
        planned_growth_se,
    )
    if previous_parameters != current_parameters:
        st.warning("Параметры изменены. Нажмите «Рассчитать», чтобы обновить результат.")

    orders, review_needed = st.session_state["recommendation_result"]
    visible_orders = _sort_orders(
        _filter_rows(orders, supplier_choice, category_choice, sku_query)
    )
    visible_review = _filter_rows(
        review_needed, supplier_choice, category_choice, sku_query
    )

    recommendations_tab, review_tab = st.tabs(
        [f"Рекомендации ({len(visible_orders)})", f"На проверку ({len(visible_review)})"]
    )
    with recommendations_tab:
        _show_grouped(visible_orders, ORDER_COLUMNS)
        workbook = export_xlsx(visible_orders)
        st.download_button(
            "Скачать xlsx для 1С",
            data=workbook,
            file_name=f"avtozakaz_{as_of:%Y-%m-%d}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with review_tab:
        _show_grouped(visible_review, REVIEW_COLUMNS)


if __name__ == "__main__":
    main()
