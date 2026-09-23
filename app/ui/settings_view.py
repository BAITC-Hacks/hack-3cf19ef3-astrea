"""Data loading, calculation cache and compact application controls."""

from dataclasses import dataclass
from typing import Dict, Tuple

import pandas as pd
import streamlit as st

from app.config import COVERAGE_DAYS, LEAD_TIME_DAYS, EngineConfig
from app.engine.ml import build_training_frame, feature_importance, train_model
from app.engine.pipeline import build_recommendations, prepare_forecasts
from app.datasets import DatasetContext, load_dataset_context


SUPPLIER_OPTIONS = ("Оба", "IEK", "SE")
FORECAST_OPTIONS = {
    "Формула": "formula",
    "ML, экспериментально": "ml",
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
FILTER_DEFAULTS = {
    "filter_supplier": "Оба",
    "filter_category": "Все",
    "filter_query": "",
}


@dataclass(frozen=True)
class AppControls:
    supplier: str
    category: str
    query: str
    lead_time_iek: int
    lead_time_se: int
    coverage_days: int
    planned_growth_iek: float
    planned_growth_se: float
    forecast_method: str
    recalculate: bool

    @property
    def calculation_key(self) -> tuple[object, ...]:
        return (
            self.lead_time_iek,
            self.lead_time_se,
            self.coverage_days,
            self.planned_growth_iek,
            self.planned_growth_se,
            self.forecast_method,
        )

    @property
    def approval_params(self) -> dict[str, object]:
        return {
            "lead_time_days": {
                "IEK": self.lead_time_iek,
                "SE": self.lead_time_se,
            },
            "coverage_days": self.coverage_days,
            "planned_growth_percent": {
                "IEK": self.planned_growth_iek,
                "SE": self.planned_growth_se,
            },
        }


@st.cache_data(show_spinner="Загружаем данные из 1С")
def load_data(
    path_items: tuple[tuple[str, str, str], ...],
    dataset_key: tuple[object, object],
) -> Dict[str, pd.DataFrame]:
    del dataset_key
    context = DatasetContext({}, path_items, {})
    return load_dataset_context(context)


@st.cache_resource(show_spinner="Обучаем ML-модель")
def train_ml_resource(
    path_items: tuple[tuple[str, str, str], ...],
    dataset_key: tuple[object, object],
) -> Tuple[object, pd.DataFrame]:
    data = load_data(path_items, dataset_key)
    as_of = pd.Timestamp(data["sales_tx"]["date"].max())
    last_full_month = as_of.to_period("M") - 1
    _, segments, _, stockouts = prepare_forecasts(data, last_full_month)
    training = build_training_frame(
        stockouts.monthly, segments, data["sku_ref"], last_full_month
    )
    model = train_model(training)
    importance = feature_importance(model, training)
    return model, importance


@st.cache_data(show_spinner="Считаем рекомендации")
def calculate(
    path_items: tuple[tuple[str, str, str], ...],
    dataset_key: tuple[object, object],
    lead_time_iek: int,
    lead_time_se: int,
    coverage_days: int,
    planned_growth_iek_percent: float,
    planned_growth_se_percent: float,
    forecast_choice: str,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    config_values = {
        "lead_time_days": {"IEK": lead_time_iek, "SE": lead_time_se},
        "coverage_days": coverage_days,
        "planned_growth": {
            "IEK": planned_growth_iek_percent / 100.0,
            "SE": planned_growth_se_percent / 100.0,
        },
    }
    data = load_data(path_items, dataset_key)
    if forecast_choice == "formula":
        return build_recommendations(
            data, EngineConfig(**config_values, forecast_method="formula")
        )
    model, _ = train_ml_resource(path_items, dataset_key)
    return build_recommendations(
        data,
        EngineConfig(**config_values, forecast_method="ml"),
        ml_model=model,
    )


@st.cache_resource(show_spinner=False)
def initialize_database(connection_url: str) -> tuple[bool, str]:
    from app.db import ensure_schema

    if not connection_url:
        return False, "DATABASE_URL не задан"
    try:
        ensure_schema(connection_url)
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"
    return True, ""


def _category_label(category: object) -> str:
    value = "без категории" if pd.isna(category) else str(category)
    if value == "без категории":
        return value
    return f"SE, категория {value}"


def _display_importance(importance: pd.DataFrame) -> pd.DataFrame:
    display = importance.head(10).copy()
    positive = display["importance"].clip(lower=0)
    total = positive.sum()
    display["importance"] = positive / total * 100.0 if total else 0.0
    display["feature"] = display["feature"].map(FEATURE_LABELS).fillna(
        display["feature"]
    )
    return display.rename(
        columns={"feature": "Признак", "importance": "Доля важности"}
    )


def _needs_calculation(state: object, button_pressed: bool) -> bool:
    return button_pressed or "recommendation_result" not in state


def _categories(data: Dict[str, pd.DataFrame], supplier: str) -> list[str]:
    if supplier == "IEK":
        return ["Все"]
    source = data["sku_ref"]
    if supplier == "SE":
        source = source.loc[source["supplier"].eq("SE")]
    return ["Все", *sorted(source["category"].dropna().astype(str).unique())]


def _supplier_changed() -> None:
    st.session_state["filter_category"] = "Все"


def reset_filters() -> None:
    for key, value in FILTER_DEFAULTS.items():
        st.session_state[key] = value


def render_controls(
    data: Dict[str, pd.DataFrame],
    path_items: tuple[tuple[str, str, str], ...],
    dataset_key: tuple[object, object],
) -> AppControls:
    filter_columns = st.columns([1.0, 1.35, 3.2])
    with filter_columns[0]:
        supplier = st.selectbox(
            "Поставщик",
            SUPPLIER_OPTIONS,
            key="filter_supplier",
            on_change=_supplier_changed,
        )
    with filter_columns[1]:
        category = st.selectbox(
            "Категория",
            _categories(data, supplier),
            format_func=lambda value: (
                value if value == "Все" else _category_label(value)
            ),
            disabled=supplier == "IEK",
            key="filter_category",
        )
    with filter_columns[2]:
        query = st.text_input(
            "Поиск",
            placeholder="Код, артикул или наименование",
            key="filter_query",
        )

    with st.expander("Настройки расчёта", expanded=False):
        first_row = st.columns(4)
        with first_row[0]:
            forecast_label = st.selectbox(
                "Метод прогноза",
                list(FORECAST_OPTIONS),
                help="Формула используется по умолчанию. ML доступен для сравнения.",
            )
        with first_row[1]:
            coverage_days = int(
                st.number_input(
                    "Покрытие, дней",
                    min_value=1,
                    max_value=365,
                    value=COVERAGE_DAYS,
                )
            )
        with first_row[2]:
            lead_time_iek = int(
                st.number_input(
                    "Поставка IEK, дней",
                    min_value=1,
                    max_value=365,
                    value=LEAD_TIME_DAYS["IEK"],
                    help="24 дня по медиане документов в пути.",
                )
            )
        with first_row[3]:
            lead_time_se = int(
                st.number_input(
                    "Поставка SE, дней",
                    min_value=1,
                    max_value=365,
                    value=LEAD_TIME_DAYS["SE"],
                    help="35 дней, допущение из-за отсутствия дат поставки.",
                )
            )
        second_row = st.columns([1, 1, 2])
        with second_row[0]:
            planned_growth_iek = float(
                st.number_input(
                    "Прирост IEK, %",
                    min_value=-100.0,
                    max_value=500.0,
                    value=0.0,
                    step=1.0,
                )
            )
        with second_row[1]:
            planned_growth_se = float(
                st.number_input(
                    "Прирост SE, %",
                    min_value=-100.0,
                    max_value=500.0,
                    value=0.0,
                    step=1.0,
                )
            )
        with second_row[2]:
            st.write("")
            recalculate = st.button("Пересчитать", type="primary")

        forecast_method = FORECAST_OPTIONS[forecast_label]
        if forecast_method == "ml":
            st.warning(
                "ML занижает общий спрос примерно на 23% для IEK и 26% для SE."
            )
            _, importance = train_ml_resource(path_items, dataset_key)
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

    return AppControls(
        supplier=supplier,
        category=category,
        query=query,
        lead_time_iek=lead_time_iek,
        lead_time_se=lead_time_se,
        coverage_days=coverage_days,
        planned_growth_iek=planned_growth_iek,
        planned_growth_se=planned_growth_se,
        forecast_method=FORECAST_OPTIONS[forecast_label],
        recalculate=recalculate,
    )


__all__ = [
    "AppControls",
    "FORECAST_OPTIONS",
    "SUPPLIER_OPTIONS",
    "_category_label",
    "_display_importance",
    "_needs_calculation",
    "calculate",
    "initialize_database",
    "load_data",
    "render_controls",
    "reset_filters",
    "train_ml_resource",
]
