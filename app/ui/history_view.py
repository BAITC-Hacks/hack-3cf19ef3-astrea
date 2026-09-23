"""Approved-order history for the Streamlit application."""

import pandas as pd
import streamlit as st

from app.db import get_order_lines, list_orders
from app.export import export_xlsx


def render_history(connection_url: str) -> None:
    try:
        orders = list_orders(connection_url)
    except Exception as error:
        st.error(f"Не удалось загрузить историю: {error}")
        return
    if orders.empty:
        st.info("Утверждённых заказов пока нет")
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
                "approved_at": "Дата",
                "line_count": "Позиций",
                "total_qty": "Количество",
                "forecast_method": "Метод",
            }
        ),
        width="stretch",
        hide_index=True,
    )
    labels = {
        int(row.id): f"№{row.id}, {row.supplier}, {row.approved_at}, {row.approved_by}"
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
        st.error(f"Не удалось загрузить заказ: {error}")
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
            ]
        ].rename(
            columns={
                "sku_code": "Код 1С",
                "name": "Наименование",
                "recommended_qty": "Рекомендовано",
                "approved_qty": "Утверждено",
                "comment": "Комментарий",
                "urgency": "Срочность",
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


__all__ = ["render_history"]
