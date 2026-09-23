"""Company-wide supplier dataset upload, history and rollback page."""

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from app.datasets import (
    DatasetValidationError,
    FileReport,
    save_validated_dataset,
    validate_dataset,
)
from app.db import list_datasets, set_current_dataset
from app.ui.settings_view import load_data
from app.ui.loading_view import LoadingView, render_loading_error
from app.ui.memo import clear_all_caches


UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/app/uploads"))


def _supplier_stats(data: dict[str, pd.DataFrame], supplier: str) -> dict[str, object]:
    transactions = data["sales_tx"].loc[data["sales_tx"]["supplier"].eq(supplier)]
    references = data["sku_ref"].loc[data["sku_ref"]["supplier"].eq(supplier)]
    return {
        "data_as_of": pd.Timestamp(transactions["date"].max()).date(),
        "sku_count": int(references["sku_code"].nunique()),
        "sales_rows": int(len(transactions)),
    }


def _source_label(context: object, supplier: str) -> str:
    row = context.current_rows.get(supplier)
    if row is None:
        return "Демо-данные"
    uploaded_at = pd.Timestamp(row["uploaded_at"]).strftime("%d.%m.%Y %H:%M")
    uploader = str(row.get("uploaded_by_name") or "пользователь")
    return f"Загружено: {uploader}, {uploaded_at}"


def _render_reports(reports: tuple[FileReport, ...] | list[FileReport]) -> None:
    for report in reports:
        marker = "✓" if report.ok else "✗"
        st.write(f"{marker} {report.name}: {report.message}")


def _invalidate_calculation() -> None:
    for key in (
        "recommendation_result",
        "calculation_parameters",
        "calculation_dataset_key",
    ):
        st.session_state.pop(key, None)
    clear_all_caches()


def _render_cards(context: object, data: dict[str, pd.DataFrame]) -> None:
    columns = st.columns(2)
    for column, supplier in zip(columns, ("IEK", "SE")):
        stats = _supplier_stats(data, supplier)
        with column:
            with st.container(border=True, key=f"dataset_card_{supplier}"):
                st.subheader(supplier)
                st.caption(_source_label(context, supplier))
                metrics = st.columns(3)
                metrics[0].metric("Дата среза", stats["data_as_of"].strftime("%d.%m.%Y"))
                metrics[1].metric("SKU", f"{stats['sku_count']:,}".replace(",", " "))
                metrics[2].metric(
                    "Строк продаж", f"{stats['sales_rows']:,}".replace(",", " ")
                )


def _render_upload(connection_url: str, current_user: dict[str, object]) -> None:
    st.subheader("Загрузить комплект")
    supplier = st.selectbox("Поставщик", ("IEK", "SE"), key="upload_supplier")
    files = st.file_uploader(
        "Пять выгрузок из 1С",
        type="xlsx",
        accept_multiple_files=True,
        help=(
            "Транзакции, продажи по месяцам, остатки по месяцам, "
            "товар в пути и MOQ. Имена файлов не важны."
        ),
    )
    if not st.button(
        "Проверить и загрузить",
        type="primary",
        disabled=not files,
    ):
        return
    try:
        validated = validate_dataset(supplier, files)
        dataset_id = save_validated_dataset(
            validated,
            int(current_user["id"]),
            connection_url,
            UPLOAD_DIR,
        )
    except DatasetValidationError as error:
        st.error(str(error))
        _render_reports(list(error.reports))
        return
    except Exception as error:
        st.error(f"Не удалось сохранить набор: {error}")
        return

    st.session_state["dataset_feedback"] = {
        "message": f"Набор №{dataset_id} для {supplier} загружен",
        "reports": validated.reports,
    }
    _invalidate_calculation()
    st.rerun()


def _render_history(connection_url: str) -> None:
    st.subheader("История загрузок")
    history = list_datasets(connection_url)
    if history.empty:
        st.info("Загрузок пока нет")
    else:
        display = history.copy()
        display["uploaded_at"] = pd.to_datetime(display["uploaded_at"]).dt.strftime(
            "%d.%m.%Y %H:%M"
        )
        st.dataframe(
            display[
                [
                    "id",
                    "supplier",
                    "uploaded_by_name",
                    "uploaded_at",
                    "data_as_of",
                    "is_current",
                ]
            ].rename(
                columns={
                    "id": "№",
                    "supplier": "Поставщик",
                    "uploaded_by_name": "Загрузил",
                    "uploaded_at": "Когда",
                    "data_as_of": "Дата среза",
                    "is_current": "Текущий",
                }
            ),
            hide_index=True,
            width="stretch",
        )
        labels = {
            int(row.id): f"№{row.id}, {row.supplier}, {row.data_as_of}"
            for row in history.itertuples(index=False)
        }
        selected = st.selectbox(
            "Набор для отката",
            list(labels),
            format_func=labels.get,
        )
        selected_row = history.loc[history["id"].eq(selected)].iloc[0]
        if st.button("Сделать текущим", key="activate_dataset"):
            set_current_dataset(
                str(selected_row["supplier"]), int(selected), connection_url
            )
            _invalidate_calculation()
            st.rerun()

    demo_supplier = st.selectbox(
        "Поставщик для демо-данных",
        ("IEK", "SE"),
        key="demo_supplier",
    )
    if st.button("Вернуть демо-данные", key="use_demo_dataset"):
        set_current_dataset(demo_supplier, None, connection_url)
        _invalidate_calculation()
        st.rerun()


def render() -> None:
    st.title("Данные")
    context = st.session_state["dataset_context"]
    connection_url = str(st.session_state["connection_url"])
    current_user = st.session_state["current_user"]
    loading = LoadingView()
    loading.update("Загружаем данные", 0.02)
    try:
        data = load_data(context.path_items, context.cache_key, loading.update)
    except Exception as error:
        loading.close()
        render_loading_error(f"Не удалось загрузить данные: {error}", "datasets")
        return
    loading.close()

    feedback = st.session_state.pop("dataset_feedback", None)
    if feedback:
        st.success(feedback["message"])
        _render_reports(feedback["reports"])
    _render_cards(context, data)
    st.divider()
    _render_upload(connection_url, current_user)
    st.divider()
    _render_history(connection_url)


__all__ = ["_source_label", "_supplier_stats", "render"]
