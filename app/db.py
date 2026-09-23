"""Minimal PostgreSQL persistence for manager-approved purchase orders."""

import os
from pathlib import Path
from typing import Mapping, Optional, Tuple

import pandas as pd


MIGRATION_PATH = Path(__file__).resolve().parents[1] / "db" / "migrations" / "001_orders.sql"
ORDER_COLUMNS = [
    "id",
    "supplier",
    "approved_by",
    "approved_at",
    "data_as_of",
    "forecast_method",
    "params",
    "line_count",
    "total_qty",
]
LINE_COLUMNS = [
    "order_id",
    "supplier",
    "sku_code",
    "article",
    "name",
    "unit",
    "category",
    "moq",
    "recommended_qty",
    "approved_qty",
    "urgency",
    "stock_unknown",
    "explanation",
    "comment",
]


def database_url() -> Optional[str]:
    """Return a configured URL without inventing a local default."""

    value = os.getenv("DATABASE_URL", "").strip()
    return value or None


def _resolve_url(value: Optional[str]) -> str:
    resolved = value or database_url()
    if not resolved:
        raise RuntimeError("DATABASE_URL не задан")
    return resolved


def _driver() -> Tuple[object, object, object]:
    """Import the PostgreSQL driver only when database work is requested."""

    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb

    return psycopg, dict_row, Jsonb


def ensure_schema(connection_url: Optional[str] = None) -> bool:
    """Apply the idempotent order migration when PostgreSQL is configured."""

    if connection_url is None and database_url() is None:
        return False
    psycopg, _, _ = _driver()
    migration = MIGRATION_PATH.read_text(encoding="utf-8")
    with psycopg.connect(_resolve_url(connection_url)) as connection:
        connection.execute(migration)
    return True


def _line_records(lines: pd.DataFrame) -> list[tuple[object, ...]]:
    required = {
        "sku_code",
        "article",
        "name",
        "unit",
        "category",
        "moq",
        "recommended_qty",
        "approved_qty",
        "urgency",
        "stock_unknown",
        "explanation",
        "comment",
    }
    missing = required.difference(lines.columns)
    if missing:
        raise ValueError("Order lines are missing columns: " + ", ".join(sorted(missing)))

    records = []
    for row in lines.itertuples(index=False):
        records.append(
            (
                str(row.sku_code),
                None if pd.isna(row.article) else str(row.article),
                None if pd.isna(row.name) else str(row.name),
                None if pd.isna(row.unit) else str(row.unit),
                None if pd.isna(row.category) else str(row.category),
                int(row.moq),
                int(row.recommended_qty),
                int(row.approved_qty),
                None if pd.isna(row.urgency) else str(row.urgency),
                bool(row.stock_unknown),
                str(row.explanation),
                None if not str(row.comment).strip() else str(row.comment),
            )
        )
    return records


def save_order(
    supplier: str,
    approved_by: str,
    data_as_of: object,
    forecast_method: str,
    params: Mapping[str, object],
    lines: pd.DataFrame,
    connection_url: Optional[str] = None,
) -> int:
    """Save an order header and all lines atomically, returning its ID."""

    approver = approved_by.strip()
    if not approver:
        raise ValueError("Укажите, кто утверждает заказ")
    if supplier not in {"IEK", "SE"}:
        raise ValueError(f"Unknown supplier: {supplier}")
    records = _line_records(lines)
    if not records:
        raise ValueError("В заказе нет строк для утверждения")

    psycopg, _, Jsonb = _driver()
    with psycopg.connect(_resolve_url(connection_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO purchase_orders (
                    supplier, approved_by, data_as_of, forecast_method,
                    params, line_count, total_qty
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    supplier,
                    approver,
                    pd.Timestamp(data_as_of).date(),
                    forecast_method,
                    Jsonb(dict(params)),
                    len(records),
                    sum(int(record[7]) for record in records),
                ),
            )
            order_id = int(cursor.fetchone()[0])
            cursor.executemany(
                """
                INSERT INTO purchase_order_lines (
                    order_id, sku_code, article, name, unit, category, moq,
                    recommended_qty, approved_qty, urgency, stock_unknown,
                    explanation, comment
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                """,
                [(order_id, *record) for record in records],
            )
    return order_id


def list_orders(connection_url: Optional[str] = None) -> pd.DataFrame:
    """Return approved order headers, newest first."""

    psycopg, dict_row, _ = _driver()
    with psycopg.connect(_resolve_url(connection_url), row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT id, supplier, approved_by, approved_at, data_as_of,
                   forecast_method, params, line_count, total_qty
            FROM purchase_orders
            ORDER BY approved_at DESC, id DESC
            """
        ).fetchall()
    return pd.DataFrame(rows, columns=ORDER_COLUMNS)


def get_order_lines(
    order_id: int, connection_url: Optional[str] = None
) -> pd.DataFrame:
    """Return the stored lines for one approved order."""

    psycopg, dict_row, _ = _driver()
    with psycopg.connect(_resolve_url(connection_url), row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT l.order_id, o.supplier, l.sku_code, l.article, l.name,
                   l.unit, l.category, l.moq, l.recommended_qty,
                   l.approved_qty, l.urgency, l.stock_unknown,
                   l.explanation, l.comment
            FROM purchase_order_lines AS l
            JOIN purchase_orders AS o ON o.id = l.order_id
            WHERE l.order_id = %s
            ORDER BY l.sku_code
            """,
            (int(order_id),),
        ).fetchall()
    return pd.DataFrame(rows, columns=LINE_COLUMNS)


__all__ = [
    "database_url",
    "ensure_schema",
    "get_order_lines",
    "list_orders",
    "save_order",
]
