"""Compact order table, line details, edits and approval controls."""

from math import isfinite
import pandas as pd
import streamlit as st

from app.db import save_order
from app.export import export_xlsx
from app.orders import apply_corrections, approvable_lines, default_edits, order_totals
from app.ui.settings_view import _category_label


ORDER_COLUMNS = {
    "sku_code": "Код 1С",
    "name": "Наименование",
    "approved_qty": "Количество",
    "urgency_display": "Срочность",
    "article": "Артикул",
    "category_display": "Категория",
}
REVIEW_COLUMNS = {
    "sku_code": "Код 1С",
    "name": "Наименование",
    "article": "Артикул",
    "category_display": "Категория",
}
ORDER_COLUMN_CONFIG = {
    "Код 1С": st.column_config.TextColumn(width="small"),
    "Наименование": st.column_config.TextColumn(width="large"),
    "Количество": st.column_config.NumberColumn(width="small", format="%d"),
    "Срочность": st.column_config.TextColumn(width="small"),
    "Артикул": st.column_config.TextColumn(width="medium"),
    "Категория": st.column_config.TextColumn(width="small"),
}
REVIEW_COLUMN_CONFIG = {
    "Код 1С": st.column_config.TextColumn(width="small"),
    "Наименование": st.column_config.TextColumn(width="large"),
    "Артикул": st.column_config.TextColumn(width="medium"),
    "Категория": st.column_config.TextColumn(width="small"),
}
URGENCY_ORDER = {"высокая": 0, "средняя": 1, "низкая": 2}
URGENCY_LABELS = {
    "высокая": "Срочно",
    "средняя": "Средне",
    "низкая": "Низкая",
    "проверить остаток": "Сверить",
}
EDITABLE_COLUMNS = {"approved_qty", "comment", "stock_checked"}
DATABASE_DISABLED_MESSAGE = "Утверждение и история временно недоступны"


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


def _summary_metrics(frame: pd.DataFrame) -> dict[str, int]:
    stock_unknown = frame.get(
        "stock_unknown", pd.Series(False, index=frame.index)
    ).fillna(False).astype(bool)
    return {
        "positions": int(len(frame)),
        "quantity": int(frame["recommended_qty"].sum()),
        "high_urgency": int(frame["urgency"].eq("высокая").sum()),
        "stock_unknown": int(stock_unknown.sum()),
    }


def render_summary(frame: pd.DataFrame) -> None:
    metrics = _summary_metrics(frame)
    columns = st.columns(4)
    columns[0].metric("Позиций", f"{metrics['positions']:,}".replace(",", " "))
    columns[1].metric("Штук", f"{metrics['quantity']:,}".replace(",", " "))
    columns[2].metric("Срочно", f"{metrics['high_urgency']:,}".replace(",", " "))
    columns[3].metric("Сверить остаток", f"{metrics['stock_unknown']:,}".replace(",", " "))


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
        original = baseline.loc[(row.sku_code, row.supplier)]
        comment = "" if pd.isna(row.comment) else str(row.comment)
        if (
            row.approved_qty != original["approved_qty"]
            or comment != str(original["comment"])
            or bool(row.stock_checked) != bool(original["stock_checked"])
        ):
            changes[str(row.sku_code)] = {
                "approved_qty": row.approved_qty,
                "comment": comment,
                "stock_checked": bool(row.stock_checked),
            }
    return changes


def _number(value: object, digits: int = 0) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "0"
    if not isfinite(numeric):
        return "0"
    return f"{numeric:,.{digits}f}".replace(",", " ")


def _details_points(row: pd.Series) -> list[str]:
    excluded = float(row.get("excluded_outlier_qty", 0) or 0)
    restored = float(row.get("stockout_added_qty", 0) or 0)
    base_parts = [f"база {_number(row.get('level'))} шт./мес."]
    if excluded > 0:
        base_parts.append(f"исключено {_number(excluded)} шт.")
    if restored > 0:
        base_parts.append(f"восстановлено {_number(restored)} шт.")
    points = ["Спрос: " + ", ".join(base_parts)]

    growth = float(row.get("growth", 1) or 1)
    points.append(f"Рост год к году: {(growth - 1) * 100:+.0f}%")
    points.append(f"Сезонность: ×{float(row.get('seasonal_index', 1) or 1):.2f}")
    points.append(
        f"Потребность на {int(row.get('window_days', 0) or 0)} дн.: "
        f"{_number(row.get('demand_window'))} шт."
    )
    points.append(f"Страховой запас: {_number(row.get('safety_stock'))} шт.")
    points.append(
        f"Свободный остаток {_number(row.get('free_stock'))} шт., "
        f"в пути {_number(row.get('in_transit'))} шт."
    )
    points.append(
        f"MOQ {int(row.get('moq', 1) or 1)} шт., итог "
        f"{int(row.get('recommended_qty', 0) or 0)} шт."
    )
    return points


def _order_table(lines: pd.DataFrame) -> pd.DataFrame:
    view = lines.copy()
    view["urgency_display"] = view["urgency"].map(URGENCY_LABELS).fillna(
        view["urgency"]
    )
    view["category_display"] = view["category"].map(_category_label)
    return view[list(ORDER_COLUMNS)].rename(columns=ORDER_COLUMNS)


def _selected_position(event: object) -> int | None:
    selection = getattr(event, "selection", None)
    rows = getattr(selection, "rows", None)
    if rows is None and isinstance(selection, dict):
        rows = selection.get("rows", [])
    return int(rows[0]) if rows else None


def _save_draft(supplier: str, row: pd.Series) -> None:
    draft_key = f"approval_draft_{supplier}"
    drafts = dict(st.session_state.get(draft_key, {}))
    drafts[str(row["sku_code"])] = {
        "approved_qty": int(row["approved_qty"]),
        "comment": str(row["comment"]),
        "stock_checked": bool(row["stock_checked"]),
    }
    st.session_state[draft_key] = drafts


def render_line_details(supplier: str, row: pd.Series) -> None:
    with st.container(border=True, key=f"line_details_{supplier}"):
        st.subheader(f"Почему {int(row['recommended_qty'])} шт.")
        st.markdown("\n".join(f"- {point}" for point in _details_points(row)))
        with st.form(f"line_edit_{supplier}_{row['sku_code']}"):
            fields = st.columns([1, 2, 1])
            with fields[0]:
                approved_qty = st.number_input(
                    "Количество",
                    min_value=0,
                    step=1,
                    value=int(row["approved_qty"]),
                )
            with fields[1]:
                comment = st.text_input("Комментарий", value=str(row["comment"]))
            with fields[2]:
                stock_checked = bool(row["stock_checked"])
                if bool(row["stock_unknown"]):
                    stock_checked = st.checkbox(
                        "Остаток сверен с 1С",
                        value=stock_checked,
                    )
            submitted = st.form_submit_button("Сохранить правку", type="primary")
        if submitted:
            changed = row.copy()
            changed["approved_qty"] = approved_qty
            changed["comment"] = comment
            changed["stock_checked"] = stock_checked
            try:
                edits = pd.DataFrame([changed])[
                    [
                        "sku_code",
                        "supplier",
                        "approved_qty",
                        "comment",
                        "stock_checked",
                    ]
                ]
                apply_corrections(pd.DataFrame([row]), edits)
            except ValueError as error:
                st.error(str(error))
            else:
                _save_draft(supplier, changed)
                st.rerun()


def _approval_controls(supplier: str, database_ready: bool) -> bool:
    if not database_ready:
        st.info(DATABASE_DISABLED_MESSAGE)
    return st.button(
        f"Утвердить заказ {supplier}",
        key=f"approve_order_{supplier}",
        type="primary",
        disabled=not database_ready,
        width="stretch",
    )


def render_supplier_order(
    supplier: str,
    supplier_rows: pd.DataFrame,
    database_ready: bool,
    connection_url: str,
    current_user: dict[str, object],
    data_as_of: object,
    forecast_method: str,
    params: dict[str, object],
) -> pd.DataFrame:
    st.subheader(supplier)
    drafts = st.session_state.get(f"approval_draft_{supplier}", {})
    corrected = apply_corrections(
        supplier_rows, _restore_draft(supplier_rows, drafts)
    )
    event = st.dataframe(
        _order_table(corrected),
        column_config=ORDER_COLUMN_CONFIG,
        width="stretch",
        height=390,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"order_table_{supplier}",
    )
    selected = _selected_position(event)
    if selected is not None:
        render_line_details(supplier, corrected.iloc[selected])

    totals = order_totals(corrected)
    st.markdown(
        f"**{totals['recommended_qty']:,} шт. рекомендовано → "
        f"{totals['approved_qty']:,} шт. к утверждению, "
        f"правок: {totals['changed_lines']}**".replace(",", " ")
    )
    action_columns = st.columns(2)
    with action_columns[0]:
        approve_pressed = _approval_controls(supplier, database_ready)
    with action_columns[1]:
        st.download_button(
            "Скачать xlsx",
            data=export_xlsx(corrected, suppliers=(supplier,)),
            file_name=f"avtozakaz_{data_as_of:%Y-%m-%d}_{supplier}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"download_order_{supplier}",
            width="stretch",
        )

    approved_lines = approvable_lines(corrected)
    if approve_pressed:
        if approved_lines.empty:
            st.error("В заказе нет строк для утверждения")
        else:
            try:
                order_id = save_order(
                    supplier,
                    str(current_user["full_name"]),
                    data_as_of,
                    forecast_method,
                    params,
                    approved_lines,
                    connection_url,
                    approved_by_user_id=int(current_user["id"]),
                )
            except Exception as error:
                st.error(f"Не удалось сохранить заказ: {error}")
            else:
                st.success(f"Заказ №{order_id} сохранён. Отправки поставщику не было")
    return corrected


def render_order_tab(
    orders: pd.DataFrame,
    database_ready: bool,
    connection_url: str,
    current_user: dict[str, object],
    data_as_of: object,
    forecast_method: str,
    params: dict[str, object],
) -> list[pd.DataFrame]:
    if orders.empty:
        st.info("Нет позиций по фильтру")
        return []
    corrected = []
    for supplier, supplier_rows in orders.groupby("supplier", sort=False):
        corrected.append(
            render_supplier_order(
                str(supplier),
                supplier_rows,
                database_ready,
                connection_url,
                current_user,
                data_as_of,
                forecast_method,
                params,
            )
        )
    return corrected


def render_dead_tab(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.info("Нет позиций по фильтру")
        return
    for supplier, rows in frame.groupby("supplier", sort=False):
        st.subheader(str(supplier))
        display = rows.copy()
        display["category_display"] = display["category"].map(_category_label)
        st.dataframe(
            display[list(REVIEW_COLUMNS)].rename(columns=REVIEW_COLUMNS),
            column_config=REVIEW_COLUMN_CONFIG,
            width="stretch",
            hide_index=True,
        )


def _export_suppliers(supplier_choice: str) -> tuple[str, ...]:
    return ("IEK", "SE") if supplier_choice == "Оба" else (supplier_choice,)


__all__ = [
    "ORDER_COLUMNS",
    "REVIEW_COLUMNS",
    "_approval_controls",
    "_details_points",
    "_draft_changes",
    "_export_suppliers",
    "_filter_rows",
    "_restore_draft",
    "_sort_orders",
    "_summary_metrics",
    "render_dead_tab",
    "render_line_details",
    "render_order_tab",
    "render_summary",
]
