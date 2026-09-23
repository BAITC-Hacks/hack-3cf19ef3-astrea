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
    LEAD_TIME_DAYS,
    EngineConfig,
)
from app.engine.ml import (  # noqa: E402
    build_training_frame,
    feature_importance,
    train_model,
)
from app.engine.pipeline import build_recommendations, prepare_forecasts  # noqa: E402
from app.db import (  # noqa: E402
    database_url,
    ensure_schema,
    get_order_lines,
    list_orders,
    save_order,
)
from app.export import export_xlsx  # noqa: E402
from app.loaders import load_all  # noqa: E402
from app.orders import (  # noqa: E402
    apply_corrections,
    approvable_lines,
    default_edits,
    order_totals,
)


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
    "Формула (по умолчанию)": "formula",
    "ML (экспериментально)": "ml",
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
DATABASE_DISABLED_MESSAGE = (
    "PostgreSQL недоступен: утверждение и история отключены. "
    "Расчёт, корректировка и выгрузка продолжают работать."
)
EDITOR_COLUMN_ORDER = [
    "sku_code",
    "name",
    "recommended_qty",
    "approved_qty",
    "urgency",
    "explanation",
    "comment",
    "stock_checked",
    "article",
    "category_display",
    "moq",
]
EDITABLE_COLUMNS = {"approved_qty", "comment", "stock_checked"}
EDITOR_COLUMN_CONFIG = {
    "sku_code": st.column_config.TextColumn("Код 1С", width="small"),
    "name": st.column_config.TextColumn("Наименование", width="medium"),
    "recommended_qty": st.column_config.NumberColumn(
        "Рекомендовано", width="small", format="%d"
    ),
    "approved_qty": st.column_config.NumberColumn(
        "Утверждённое количество", min_value=0, step=1, width="small", format="%d"
    ),
    "urgency": st.column_config.TextColumn("Срочность", width="small"),
    "explanation": st.column_config.TextColumn("Обоснование", width="large"),
    "comment": st.column_config.TextColumn("Комментарий", width="large"),
    "stock_checked": st.column_config.CheckboxColumn(
        "Остаток сверен", help="Обязательно для строк с неизвестным остатком."
    ),
    "article": st.column_config.TextColumn("Артикул", width="medium"),
    "category_display": st.column_config.TextColumn("Категория", width="medium"),
    "moq": st.column_config.NumberColumn("MOQ", width="small", format="%d"),
    "supplier": None,
    "stock_unknown": None,
    "unit": None,
    "category": None,
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


@st.cache_resource(show_spinner=False)
def initialize_database(connection_url: str) -> Tuple[bool, str]:
    """Apply the schema once while keeping no-database startup non-fatal."""

    if not connection_url:
        return False, "DATABASE_URL не задан"
    try:
        ensure_schema(connection_url)
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"
    return True, ""


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
    if forecast_choice == "formula":
        return build_recommendations(
            data, EngineConfig(**config_values, forecast_method="formula")
        )

    model, _ = train_ml_resource(data_dir)
    ml_result = build_recommendations(
        data,
        EngineConfig(**config_values, forecast_method="ml"),
        ml_model=model,
    )
    return ml_result


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


def _category_label(category: object) -> str:
    value = "без категории" if pd.isna(category) else str(category)
    if value == "без категории":
        return value
    return f"SE, категория {value}"


def _export_suppliers(supplier_choice: str) -> tuple[str, ...]:
    if supplier_choice == "Оба":
        return ("IEK", "SE")
    return (supplier_choice,)


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
        if "Категория" in display:
            display["Категория"] = display["Категория"].map(_category_label)
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


def _approval_controls(
    supplier: str, database_ready: bool
) -> tuple[str, bool]:
    """Render approval controls, disabled when PostgreSQL is unavailable."""

    if not database_ready:
        st.info(DATABASE_DISABLED_MESSAGE)
    approved_by = st.text_input(
        "Кто утверждает",
        key=f"approved_by_{supplier}",
        disabled=not database_ready,
    )
    pressed = st.button(
        f"Утвердить заказ {supplier}",
        key=f"approve_order_{supplier}",
        type="primary",
        disabled=not database_ready,
    )
    return approved_by, pressed


def _editor_view(lines: pd.DataFrame) -> pd.DataFrame:
    view = lines[
        [
            "sku_code",
            "supplier",
            "name",
            "recommended_qty",
            "approved_qty",
            "urgency",
            "explanation",
            "comment",
            "stock_checked",
            "article",
            "category",
            "moq",
            "stock_unknown",
            "unit",
        ]
    ].copy()
    view["category_display"] = view["category"].map(_category_label)
    return view


def _restore_draft(
    recommendations: pd.DataFrame, drafts: dict[str, dict[str, object]]
) -> pd.DataFrame:
    edits = default_edits(recommendations)
    for index, row in edits.iterrows():
        saved = drafts.get(str(row["sku_code"]))
        if saved:
            for column in EDITABLE_COLUMNS:
                edits.at[index, column] = saved[column]
    return edits


def _draft_changes(
    defaults: pd.DataFrame, edited: pd.DataFrame
) -> dict[str, dict[str, object]]:
    baseline = defaults.set_index(["sku_code", "supplier"])
    changes: dict[str, dict[str, object]] = {}
    for row in edited.itertuples(index=False):
        key = (row.sku_code, row.supplier)
        original = baseline.loc[key]
        approved_qty = row.approved_qty
        comment = "" if pd.isna(row.comment) else str(row.comment)
        stock_checked = bool(row.stock_checked)
        if (
            approved_qty != original["approved_qty"]
            or comment != str(original["comment"])
            or stock_checked != bool(original["stock_checked"])
        ):
            changes[str(row.sku_code)] = {
                "approved_qty": approved_qty,
                "comment": comment,
                "stock_checked": stock_checked,
            }
    return changes


def _show_order_editor(
    supplier: str,
    supplier_rows: pd.DataFrame,
    database_ready: bool,
    connection_url: str,
    data_as_of: object,
    forecast_method: str,
    params: dict[str, object],
) -> pd.DataFrame:
    """Render one supplier editor and optionally persist its approved order."""

    st.subheader(str(supplier))
    draft_key = f"approval_draft_{supplier}"
    saved_drafts = st.session_state.get(draft_key, {})
    defaults = default_edits(supplier_rows)
    initial = apply_corrections(
        supplier_rows, _restore_draft(supplier_rows, saved_drafts)
    )
    view = _editor_view(initial)
    changed_indices = set(initial.index[initial["changed"]])
    styled = view.style.apply(
        lambda row: (
            ["background-color: #fff3cd"] * len(row)
            if row.name in changed_indices
            else [""] * len(row)
        ),
        axis=1,
    )
    edited = st.data_editor(
        styled,
        key=f"order_editor_{supplier}",
        column_order=EDITOR_COLUMN_ORDER,
        column_config=EDITOR_COLUMN_CONFIG,
        disabled=[
            column for column in view.columns if column not in EDITABLE_COLUMNS
        ],
        width="stretch",
        hide_index=True,
    )
    visible_changes = _draft_changes(defaults, edited)
    updated_drafts = dict(saved_drafts)
    for sku_code in supplier_rows["sku_code"].astype(str):
        updated_drafts.pop(sku_code, None)
    updated_drafts.update(visible_changes)
    if updated_drafts != saved_drafts:
        st.session_state[draft_key] = updated_drafts
        st.rerun()
    try:
        corrected = apply_corrections(supplier_rows, edited)
    except ValueError as error:
        st.error(str(error))
        corrected = initial

    totals = order_totals(corrected)
    st.markdown(
        f"**Итого: рекомендовано {totals['recommended_qty']:,} шт. → "
        f"к утверждению {totals['approved_qty']:,} шт.; "
        f"изменено строк: {totals['changed_lines']}.**".replace(",", " ")
    )
    if totals["excluded_lines"]:
        st.caption(
            f"Не войдут в заказ без сверки остатка: {totals['excluded_lines']} строк."
        )
    warning_rows = corrected.loc[
        corrected["approval_warning"].str.len().gt(0),
        ["sku_code", "approval_warning"],
    ]
    if not warning_rows.empty:
        st.warning(f"Предупреждений по корректировкам: {len(warning_rows)}")
        with st.expander("Показать предупреждения"):
            st.dataframe(
                warning_rows.rename(
                    columns={
                        "sku_code": "Код 1С",
                        "approval_warning": "Предупреждение",
                    }
                ),
                width="stretch",
                hide_index=True,
            )

    approved_by, approve_pressed = _approval_controls(supplier, database_ready)
    approved_lines = approvable_lines(corrected)
    if approve_pressed:
        if not approved_by.strip():
            st.error("Укажите, кто утверждает заказ.")
        elif approved_lines.empty:
            st.error("В заказе нет строк для утверждения.")
        else:
            try:
                order_id = save_order(
                    supplier,
                    approved_by,
                    data_as_of,
                    forecast_method,
                    params,
                    approved_lines,
                    connection_url,
                )
            except Exception as error:
                st.error(f"Не удалось сохранить заказ: {error}")
            else:
                st.session_state[f"saved_order_{supplier}"] = {
                    "id": order_id,
                    "lines": approved_lines,
                }
                st.success(
                    f"Заказ №{order_id} сохранён. Поставщику ничего не отправлено."
                )

    saved_order = st.session_state.get(f"saved_order_{supplier}")
    if saved_order:
        st.download_button(
            f"Скачать утверждённый заказ №{saved_order['id']}",
            data=export_xlsx(saved_order["lines"], suppliers=(supplier,)),
            file_name=f"approved_order_{saved_order['id']}_{supplier}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"download_saved_{supplier}",
        )
    return corrected


def _show_order_history(database_ready: bool, connection_url: str) -> None:
    """Render stored order headers, lines and repeatable approved export."""

    if not database_ready:
        st.info(DATABASE_DISABLED_MESSAGE)
        return
    try:
        orders = list_orders(connection_url)
    except Exception as error:
        st.error(f"Не удалось загрузить историю заказов: {error}")
        return
    if orders.empty:
        st.info("Утверждённых заказов пока нет.")
        return

    history = orders.copy()
    history["approved_at"] = pd.to_datetime(history["approved_at"]).dt.strftime(
        "%d.%m.%Y %H:%M"
    )
    st.dataframe(
        history[
            [
                "id",
                "supplier",
                "approved_by",
                "approved_at",
                "line_count",
                "total_qty",
                "forecast_method",
            ]
        ].rename(
            columns={
                "id": "№",
                "supplier": "Поставщик",
                "approved_by": "Утвердил",
                "approved_at": "Дата утверждения",
                "line_count": "Позиций",
                "total_qty": "Количество",
                "forecast_method": "Метод прогноза",
            }
        ),
        width="stretch",
        hide_index=True,
    )
    labels = {
        int(row.id): (
            f"№{row.id} · {row.supplier} · {row.approved_at} · "
            f"{row.approved_by}"
        )
        for row in history.itertuples(index=False)
    }
    selected_order = st.selectbox(
        "Открыть заказ",
        list(labels),
        format_func=labels.get,
    )
    try:
        lines = get_order_lines(int(selected_order), connection_url)
    except Exception as error:
        st.error(f"Не удалось загрузить строки заказа: {error}")
        return
    st.dataframe(
        lines[
            [
                "sku_code",
                "name",
                "recommended_qty",
                "approved_qty",
                "comment",
                "urgency",
                "article",
                "category",
            ]
        ].rename(
            columns={
                "sku_code": "Код 1С",
                "name": "Наименование",
                "recommended_qty": "Рекомендовано",
                "approved_qty": "Утверждено",
                "comment": "Комментарий",
                "urgency": "Срочность",
                "article": "Артикул",
                "category": "Категория",
            }
        ),
        width="stretch",
        hide_index=True,
    )
    lines["stock_checked"] = True
    supplier = str(lines["supplier"].iloc[0])
    st.download_button(
        f"Скачать заказ №{selected_order}",
        data=export_xlsx(lines, suppliers=(supplier,)),
        file_name=f"approved_order_{selected_order}_{supplier}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def main() -> None:
    st.set_page_config(page_title="Автозаказ", page_icon="📦", layout="wide")
    st.title("Автозаказ поставщикам")
    st.caption("Расчёт выполняется локально. Заказ поставщику не отправляется.")

    connection_url = database_url() or ""
    database_ready, database_error = initialize_database(connection_url)
    if not database_ready:
        st.caption(f"Режим без базы: {database_error}.")

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
        st.caption(
            "Бэктест июль–август 2026: формула — WAPE 39,11% (IEK) и "
            "25,25% (SE), MdAPE 58,08% и 48,90%; ML — WAPE 34,53% и "
            "31,45%, MdAPE 44,51% и 36,33%."
        )
        category_choice = "Все"
        if supplier_choice != "IEK":
            category_source = data["sku_ref"]
            if supplier_choice == "SE":
                category_source = category_source.loc[
                    category_source["supplier"].eq("SE")
                ]
            categories = [
                "Все",
                *sorted(
                    category_source["category"].dropna().astype(str).unique()
                ),
            ]
            category_choice = st.selectbox(
                "Категория",
                categories,
                format_func=lambda value: (
                    value if value == "Все" else _category_label(value)
                ),
            )
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
    approval_params = {
        "lead_time_days": {"IEK": lead_time_iek, "SE": lead_time_se},
        "coverage_days": coverage_days,
        "planned_growth_percent": {
            "IEK": planned_growth_iek,
            "SE": planned_growth_se,
        },
    }
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
    recommendations_tab, review_tab, history_tab = st.tabs(
        [
            f"Рекомендации ({len(visible_orders)})",
            f"На проверку ({len(visible_review)})",
            "История заказов",
        ]
    )
    with recommendations_tab:
        corrected_groups = []
        if visible_orders.empty:
            st.info("По выбранным фильтрам строк нет.")
        else:
            for supplier, supplier_rows in visible_orders.groupby(
                "supplier", sort=False
            ):
                corrected_groups.append(
                    _show_order_editor(
                        str(supplier),
                        supplier_rows,
                        database_ready,
                        connection_url,
                        as_of,
                        forecast_choice,
                        approval_params,
                    )
                )
        corrected_orders = (
            pd.concat(corrected_groups, ignore_index=True)
            if corrected_groups
            else apply_corrections(visible_orders)
        )
        workbook = export_xlsx(
            corrected_orders, suppliers=_export_suppliers(supplier_choice)
        )
        stock_review_count = int(
            (
                corrected_orders["stock_unknown"].fillna(False).astype(bool)
                & ~corrected_orders["stock_checked"].fillna(False).astype(bool)
            ).sum()
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
    with history_tab:
        _show_order_history(database_ready, connection_url)


if __name__ == "__main__":
    main()
