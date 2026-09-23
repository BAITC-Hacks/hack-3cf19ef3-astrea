import os
from uuid import uuid4

import pandas as pd
import pytest

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="DATABASE_URL не задан — интеграционный тест пропущен"
)

if DATABASE_URL:
    import psycopg

    from app.auth import RegistrationError, authenticate, register
    from app.db import ensure_schema, get_order_lines, list_orders, save_order
    from app.db import (
        allocate_dataset_id,
        current_datasets,
        list_datasets,
        save_dataset,
        set_current_dataset,
    )


def _lines(duplicate: bool = False) -> pd.DataFrame:
    rows = [
        {
            "sku_code": "DB-SKU-1",
            "article": "A-1",
            "name": "Тестовый товар",
            "unit": "шт",
            "category": "без категории",
            "moq": 6,
            "recommended_qty": 12,
            "approved_qty": 18,
            "urgency": "высокая",
            "stock_unknown": False,
            "explanation": "Тест",
            "comment": "Корректировка",
        }
    ]
    if duplicate:
        rows.append(dict(rows[0]))
    return pd.DataFrame(rows)


def test_ensure_schema_is_idempotent() -> None:
    assert ensure_schema(DATABASE_URL)
    assert ensure_schema(DATABASE_URL)


def test_save_and_read_order() -> None:
    ensure_schema(DATABASE_URL)
    approved_by = f"pytest-{uuid4()}"
    order_id = save_order(
        "IEK",
        approved_by,
        "2026-09-22",
        "formula",
        {"coverage_days": 30},
        _lines(),
        DATABASE_URL,
    )
    try:
        orders = list_orders(DATABASE_URL).set_index("id")
        lines = get_order_lines(order_id, DATABASE_URL)

        assert orders.loc[order_id, "approved_by"] == approved_by
        assert orders.loc[order_id, "line_count"] == 1
        assert orders.loc[order_id, "total_qty"] == 18
        assert lines.loc[0, "recommended_qty"] == 12
        assert lines.loc[0, "approved_qty"] == 18
        assert lines.loc[0, "comment"] == "Корректировка"
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("DELETE FROM purchase_orders WHERE id = %s", (order_id,))


def test_line_failure_rolls_back_order_header() -> None:
    ensure_schema(DATABASE_URL)
    approved_by = f"pytest-rollback-{uuid4()}"

    with pytest.raises(psycopg.errors.UniqueViolation):
        save_order(
            "IEK",
            approved_by,
            "2026-09-22",
            "formula",
            {},
            _lines(duplicate=True),
            DATABASE_URL,
        )

    orders = list_orders(DATABASE_URL)
    assert not orders["approved_by"].eq(approved_by).any()


def test_register_authenticate_and_reject_duplicate_email(monkeypatch) -> None:
    ensure_schema(DATABASE_URL)
    monkeypatch.setenv("INVITE_CODE", "pytest-invite")
    email = f"pytest-{uuid4()}@example.com"
    try:
        user = register(
            email.upper(),
            "Тестовый пользователь",
            "correct-password",
            "pytest-invite",
            DATABASE_URL,
        )

        assert user["email"] == email
        assert authenticate(email, "wrong-password", DATABASE_URL) is None
        assert authenticate(email, "correct-password", DATABASE_URL) == user
        with pytest.raises(RegistrationError, match="Такой email уже есть"):
            register(
                email,
                "Другой пользователь",
                "correct-password",
                "pytest-invite",
                DATABASE_URL,
            )
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("DELETE FROM users WHERE email = %s", (email,))


def test_order_records_current_user_id(monkeypatch) -> None:
    ensure_schema(DATABASE_URL)
    monkeypatch.setenv("INVITE_CODE", "pytest-invite")
    email = f"pytest-order-{uuid4()}@example.com"
    user = register(
        email,
        "Утверждающий",
        "correct-password",
        "pytest-invite",
        DATABASE_URL,
    )
    order_id = save_order(
        "IEK",
        str(user["full_name"]),
        "2026-09-22",
        "formula",
        {},
        _lines(),
        DATABASE_URL,
        approved_by_user_id=int(user["id"]),
    )
    try:
        order = list_orders(DATABASE_URL).set_index("id").loc[order_id]
        assert order["approved_by"] == user["full_name"]
        assert order["approved_by_user_id"] == user["id"]
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("DELETE FROM purchase_orders WHERE id = %s", (order_id,))
            connection.execute("DELETE FROM users WHERE id = %s", (user["id"],))


def test_dataset_activation_and_rollback(monkeypatch) -> None:
    ensure_schema(DATABASE_URL)
    monkeypatch.setenv("INVITE_CODE", "pytest-invite")
    email = f"pytest-dataset-{uuid4()}@example.com"
    user = register(
        email,
        "Загрузивший",
        "correct-password",
        "pytest-invite",
        DATABASE_URL,
    )
    first_id = allocate_dataset_id(DATABASE_URL)
    second_id = allocate_dataset_id(DATABASE_URL)
    try:
        save_dataset(
            first_id,
            "IEK",
            int(user["id"]),
            "2026-08-31",
            f"/tmp/{first_id}",
            {"sales_tx": {"name": "first.xlsx"}},
            DATABASE_URL,
        )
        save_dataset(
            second_id,
            "IEK",
            int(user["id"]),
            "2026-09-22",
            f"/tmp/{second_id}",
            {"sales_tx": {"name": "second.xlsx"}},
            DATABASE_URL,
        )

        active = current_datasets(DATABASE_URL)
        assert active.loc[active["supplier"].eq("IEK"), "id"].tolist() == [second_id]

        set_current_dataset("IEK", first_id, DATABASE_URL)
        active = current_datasets(DATABASE_URL)
        assert active.loc[active["supplier"].eq("IEK"), "id"].tolist() == [first_id]

        set_current_dataset("IEK", None, DATABASE_URL)
        assert not current_datasets(DATABASE_URL)["supplier"].eq("IEK").any()
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "DELETE FROM datasets WHERE id IN (%s, %s)",
                (first_id, second_id),
            )
            connection.execute("DELETE FROM users WHERE id = %s", (user["id"],))


def test_order_records_dataset_ids() -> None:
    ensure_schema(DATABASE_URL)
    approved_by = f"pytest-datasets-{uuid4()}"
    order_id = save_order(
        "SE",
        approved_by,
        "2026-09-22",
        "formula",
        {},
        _lines(),
        DATABASE_URL,
        dataset_ids={"IEK": 10, "SE": 20},
    )
    try:
        order = list_orders(DATABASE_URL).set_index("id").loc[order_id]
        assert order["dataset_ids"] == {"IEK": 10, "SE": 20}
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("DELETE FROM purchase_orders WHERE id = %s", (order_id,))
