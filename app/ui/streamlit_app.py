"""Streamlit interface for calculating and exporting supplier orders."""

from pathlib import Path
import sys
from typing import Dict, Tuple

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import (  # noqa: E402
    COVERAGE_DAYS,
    DEFAULT_FORECAST_METHODS,
    LEAD_TIME_DAYS,
    EngineConfig,
)
from app.engine.ml import (  # noqa: E402
    build_training_frame,
    feature_importance,
    train_model,
)
from app.engine.pipeline import build_recommendations, prepare_forecasts  # noqa: E402
from app.export import export_xlsx  # noqa: E402
from app.loaders import load_all  # noqa: E402


DATA_DIR = ROOT / "data" / "raw"
SUPPLIER_OPTIONS = ("Оба", "IEK", "SE")
ORDER_COLUMNS = {
    "sku_code": "Код 1С",
    "name": "Наименование",
    "recommended_qty": "Количество",
    "urgency": "Срочность",
    "explanation": "Обоснование",
    "article": "Артикул",
    "category": "Категория",
}
REVIEW_COLUMNS = {
    "sku_code": "Код 1С",
    "name": "Наименование",
    "reason": "Причина",
    "article": "Артикул",
    "category": "Категория",
}
ORDER_COLUMN_CONFIG = {
    "Код 1С": st.column_config.TextColumn(width="small"),
    "Наименование": st.column_config.TextColumn(width="medium"),
    "Количество": st.column_config.NumberColumn(width="small", format="%d"),
    "Срочность": st.column_config.TextColumn(width="small"),
    "Обоснование": st.column_config.TextColumn(width="large"),
    "Артикул": st.column_config.TextColumn(width="medium"),
    "Категория": st.column_config.TextColumn(width="medium"),
}
REVIEW_COLUMN_CONFIG = {
    "Код 1С": st.column_config.TextColumn(width="small"),
    "Наименование": st.column_config.TextColumn(width="medium"),
    "Причина": st.column_config.TextColumn(width="large"),
    "Артикул": st.column_config.TextColumn(width="medium"),
    "Категория": st.column_config.TextColumn(width="medium"),
}
URGENCY_ORDER = {"высокая": 0, "средняя": 1, "низкая": 2}
FORECAST_OPTIONS = {
    "По умолчанию (формула)": "default",
    "Формула": "formula",
    "ML": "ml",
}
FEATURE_LABELS = {
    "demand_lag_0": "Продажи в последнем месяце",
    "demand_lag_1": "Продажи месяц назад",
    "demand_lag_2": "Продажи два месяца назад",
    "demand_lag_5": "Продажи пять месяцев назад",
    "demand_lag_11": "Продажи одиннадцать месяцев назад",
    "rolling_mean_3": "Средние продажи за 3 месяца",
    "rolling_mean_6": "Средние продажи за 6 месяцев",
    "same_month_last_year": "Продажи в тот же месяц год назад",
    "sku_season": "Сезонность товара",
    "supplier_season": "Сезонность поставщика",
    "growth_yoy": "Изменение спроса год к году",
    "zero_share_12": "Доля месяцев без продаж за 12 мес.",
    "stockout_months_12": "Месяцы с вероятным дефицитом за 12 мес.",
    "target_month": "Месяц прогноза",
    "horizon": "Горизонт прогноза",
    "supplier_feature": "Поставщик",
    "category_feature": "Категория",
}


@st.cache_data(show_spinner="Загружаем данные из 1С…")
def load_data(data_dir: str) -> Dict[str, pd.DataFrame]:
    """Load source workbooks once until their cache key changes."""

    return load_all(Path(data_dir))


@st.cache_resource(show_spinner="Обучаем ML-модель…")
def train_ml_resource(data_dir: str) -> Tuple[object, pd.DataFrame]:
    """Train the challenger once and cache its model and feature importance."""

    data = load_data(data_dir)
    as_of = pd.Timestamp(data["sales_tx"]["date"].max())
    last_full_month = as_of.to_period("M") - 1
    _, segments, _, stockouts = prepare_forecasts(data, last_full_month)
    training = build_training_frame(
        stockouts.monthly, segments, data["sku_ref"], last_full_month
    )
    model = train_model(training)
    importance = feature_importance(model, training)
    return model, importance


@st.cache_data(show_spinner="Рассчитываем рекомендации…")
def calculate(
    data_dir: str,
    lead_time_iek: int,
    lead_time_se: int,
    coverage_days: int,
    planned_growth_iek_percent: float,
    planned_growth_se_percent: float,
    forecast_choice: str,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Cache each calculation parameter combination on top of cached loading."""

    config_values = {
        "lead_time_days": {"IEK": lead_time_iek, "SE": lead_time_se},
        "coverage_days": coverage_days,
        "planned_growth": {
            "IEK": planned_growth_iek_percent / 100.0,
            "SE": planned_growth_se_percent / 100.0,
        },
    }
    data = load_data(data_dir)
    if forecast_choice == "formula" or (
        forecast_choice == "default"
        and set(DEFAULT_FORECAST_METHODS.values()) == {"formula"}
    ):
        return build_recommendations(
            data, EngineConfig(**config_values, forecast_method="formula")
        )

    model, _ = train_ml_resource(data_dir)
    ml_result = build_recommendations(
        data,
        EngineConfig(**config_values, forecast_method="ml"),
        ml_model=model,
    )
    if forecast_choice == "ml":
        return ml_result

    formula_orders, review_needed = build_recommendations(
        data, EngineConfig(**config_values, forecast_method="formula")
    )
    ml_orders, _ = ml_result
    orders = pd.concat(
        [
            ml_orders.loc[
                ml_orders["supplier"].map(DEFAULT_FORECAST_METHODS).eq("ml")
            ],
            formula_orders.loc[
                formula_orders["supplier"]
                .map(DEFAULT_FORECAST_METHODS)
                .eq("formula")
            ],
        ],
        ignore_index=True,
    )
    return orders, review_needed


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


def _needs_calculation(state: object, button_pressed: bool) -> bool:
    """Calculate on first open and whenever the user explicitly requests it."""

    return button_pressed or "recommendation_result" not in state


def _summary_metrics(frame: pd.DataFrame) -> dict[str, int]:
    """Return the four order metrics used in each supplier summary."""

    stock_unknown = frame.get(
        "stock_unknown", pd.Series(False, index=frame.index)
    ).fillna(False).astype(bool)
    return {
        "positions": int(len(frame)),
        "quantity": int(frame["recommended_qty"].sum()),
        "high_urgency": int(frame["urgency"].eq("высокая").sum()),
        "stock_unknown": int(stock_unknown.sum()),
    }


def _show_summary(frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    st.subheader("Сводка")
    for supplier, supplier_rows in frame.groupby("supplier", sort=False):
        st.markdown(f"**{supplier}**")
        metrics = _summary_metrics(supplier_rows)
        columns = st.columns(4)
        columns[0].metric("Позиций к заказу", metrics["positions"])
        columns[1].metric("Штук всего", metrics["quantity"])
        columns[2].metric("Высокая срочность", metrics["high_urgency"])
        columns[3].metric("Проверить остаток", metrics["stock_unknown"])


def _display_importance(importance: pd.DataFrame) -> pd.DataFrame:
    """Translate ML features and express their positive importance as shares."""

    display = importance[["feature", "importance"]].copy()
    positive = display["importance"].clip(lower=0.0)
    total = float(positive.sum())
    display["importance"] = positive / total * 100.0 if total else 0.0
    display["feature"] = display["feature"].map(FEATURE_LABELS).fillna(
        display["feature"]
    )
    return display.rename(
        columns={"feature": "Признак", "importance": "Доля важности"}
    )


def _show_grouped(
    frame: pd.DataFrame,
    columns: dict[str, str],
    column_config: dict[str, object],
) -> None:
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
            column_config=column_config,
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
        forecast_label = st.selectbox("Метод прогноза", list(FORECAST_OPTIONS))
        forecast_choice = FORECAST_OPTIONS[forecast_label]
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

    if forecast_choice == "ml":
        st.warning(
            "ML на истории занижает общий спрос на ~23% (IEK) и ~26% (SE); "
            "используйте для сравнения."
        )

    current_parameters = (
        lead_time_iek,
        lead_time_se,
        coverage_days,
        planned_growth_iek,
        planned_growth_se,
        forecast_choice,
    )
    if _needs_calculation(st.session_state, run_calculation):
        st.session_state["recommendation_result"] = calculate(
            str(DATA_DIR),
            lead_time_iek,
            lead_time_se,
            coverage_days,
            planned_growth_iek,
            planned_growth_se,
            forecast_choice,
        )
        st.session_state["calculation_parameters"] = current_parameters

    previous_parameters = st.session_state.get("calculation_parameters")
    if previous_parameters != current_parameters:
        st.warning("Параметры изменены. Нажмите «Рассчитать», чтобы обновить результат.")

    orders, review_needed = st.session_state["recommendation_result"]
    visible_orders = _sort_orders(
        _filter_rows(orders, supplier_choice, category_choice, sku_query)
    )
    visible_review = _filter_rows(
        review_needed, supplier_choice, category_choice, sku_query
    )

    _show_summary(visible_orders)
    recommendations_tab, review_tab = st.tabs(
        [f"Рекомендации ({len(visible_orders)})", f"На проверку ({len(visible_review)})"]
    )
    with recommendations_tab:
        _show_grouped(visible_orders, ORDER_COLUMNS, ORDER_COLUMN_CONFIG)
        workbook = export_xlsx(visible_orders)
        stock_review_count = int(
            visible_orders["stock_unknown"].fillna(False).astype(bool).sum()
        )
        st.caption(
            f"На отдельный лист «Проверить остаток» ушло позиций: "
            f"{stock_review_count}."
        )
        st.download_button(
            "Скачать xlsx для 1С",
            data=workbook,
            file_name=f"avtozakaz_{as_of:%Y-%m-%d}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        if forecast_choice == "ml":
            _, importance = train_ml_resource(str(DATA_DIR))
            with st.expander("Что влияет на ML-прогноз"):
                st.dataframe(
                    _display_importance(importance),
                    column_config={
                        "Признак": st.column_config.TextColumn(width="large"),
                        "Доля важности": st.column_config.NumberColumn(
                            width="small", format="%.1f%%"
                        ),
                    },
                    width="stretch",
                    hide_index=True,
                )
    with review_tab:
        _show_grouped(visible_review, REVIEW_COLUMNS, REVIEW_COLUMN_CONFIG)


if __name__ == "__main__":
    main()
