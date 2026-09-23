"""Minimal PostgreSQL persistence for manager-approved purchase orders."""

import os
from pathlib import Path
from typing import Mapping, Optional, Tuple

import pandas as pd


MIGRATION_DIR = Path(__file__).resolve().parents[1] / "db" / "migrations"
ORDER_COLUMNS = [
    "id",
    "supplier",
    "approved_by",
    "approved_by_user_id",
    "approved_at",
    "data_as_of",
    "forecast_method",
    "params",
    "line_count",
    "total_qty",
    "dataset_ids",
]
DATASET_COLUMNS = [
    "id",
    "supplier",
    "uploaded_by",
    "uploaded_by_name",
    "uploaded_at",
    "data_as_of",
    "storage_dir",
    "files",
    "is_current",
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
    """Apply all idempotent migrations when PostgreSQL is configured."""

    if connection_url is None and database_url() is None:
        return False
    psycopg, _, _ = _driver()
    with psycopg.connect(_resolve_url(connection_url)) as connection:
        for migration_path in sorted(MIGRATION_DIR.glob("*.sql")):
            connection.execute(migration_path.read_text(encoding="utf-8"))
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
                (
                    None
                    if pd.isna(row.comment) or not str(row.comment).strip()
                    else str(row.comment)
                ),
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
    approved_by_user_id: Optional[int] = None,
    dataset_ids: Optional[Mapping[str, object]] = None,
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
                    params, line_count, total_qty, approved_by_user_id,
                    dataset_ids
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    approved_by_user_id,
                    Jsonb(dict(dataset_ids or {})),
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
            SELECT id, supplier, approved_by, approved_by_user_id, approved_at,
                   data_as_of, forecast_method, params, line_count, total_qty,
                   dataset_ids
            FROM purchase_orders
            ORDER BY approved_at DESC, id DESC
            """
        ).fetchall()
    return pd.DataFrame(rows, columns=ORDER_COLUMNS)


def allocate_dataset_id(connection_url: Optional[str] = None) -> int:
    """Reserve an ID used as the permanent upload directory name."""

    psycopg, _, _ = _driver()
    with psycopg.connect(_resolve_url(connection_url)) as connection:
        row = connection.execute(
            "SELECT nextval(pg_get_serial_sequence('datasets', 'id'))"
        ).fetchone()
    return int(row[0])


def save_dataset(
    dataset_id: int,
    supplier: str,
    uploaded_by: int,
    data_as_of: object,
    storage_dir: str,
    files: Mapping[str, object],
    connection_url: Optional[str] = None,
) -> int:
    """Insert and activate a validated supplier dataset atomically."""

    if supplier not in {"IEK", "SE"}:
        raise ValueError(f"Unknown supplier: {supplier}")
    psycopg, _, Jsonb = _driver()
    with psycopg.connect(_resolve_url(connection_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE datasets SET is_current = false WHERE supplier = %s",
                (supplier,),
            )
            cursor.execute(
                """
                INSERT INTO datasets (
                    id, supplier, uploaded_by, data_as_of, storage_dir, files,
                    is_current
                ) VALUES (%s, %s, %s, %s, %s, %s, true)
                """,
                (
                    int(dataset_id),
                    supplier,
                    int(uploaded_by),
                    pd.Timestamp(data_as_of).date(),
                    storage_dir,
                    Jsonb(dict(files)),
                ),
            )
    return int(dataset_id)


def list_datasets(connection_url: Optional[str] = None) -> pd.DataFrame:
    """Return all uploaded datasets with uploader names, newest first."""

    psycopg, dict_row, _ = _driver()
    with psycopg.connect(_resolve_url(connection_url), row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT d.id, d.supplier, d.uploaded_by, u.full_name AS uploaded_by_name,
                   d.uploaded_at, d.data_as_of, d.storage_dir, d.files, d.is_current
            FROM datasets AS d
            LEFT JOIN users AS u ON u.id = d.uploaded_by
            ORDER BY d.uploaded_at DESC, d.id DESC
            """
        ).fetchall()
    return pd.DataFrame(rows, columns=DATASET_COLUMNS)


def current_datasets(connection_url: Optional[str] = None) -> pd.DataFrame:
    """Return at most one active upload for each supplier."""

    datasets = list_datasets(connection_url)
    if datasets.empty:
        return datasets
    return datasets.loc[datasets["is_current"].astype(bool)].reset_index(drop=True)


def set_current_dataset(
    supplier: str,
    dataset_id: Optional[int],
    connection_url: Optional[str] = None,
) -> None:
    """Activate a previous upload, or use demo data when ID is None."""

    if supplier not in {"IEK", "SE"}:
        raise ValueError(f"Unknown supplier: {supplier}")
    psycopg, _, _ = _driver()
    with psycopg.connect(_resolve_url(connection_url)) as connection:
        with connection.cursor() as cursor:
            if dataset_id is not None:
                row = cursor.execute(
                    "SELECT supplier FROM datasets WHERE id = %s",
                    (int(dataset_id),),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Набор №{dataset_id} не найден")
                if row[0] != supplier:
                    raise ValueError("Набор относится к другому поставщику")
            cursor.execute(
                "UPDATE datasets SET is_current = false WHERE supplier = %s",
                (supplier,),
            )
            if dataset_id is not None:
                cursor.execute(
                    "UPDATE datasets SET is_current = true WHERE id = %s",
                    (int(dataset_id),),
                )


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
    "allocate_dataset_id",
    "current_datasets",
    "database_url",
    "ensure_schema",
    "get_order_lines",
    "list_orders",
    "list_datasets",
    "save_dataset",
    "save_order",
    "set_current_dataset",
]
