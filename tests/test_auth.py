import pytest
from streamlit.testing.v1 import AppTest

from app.auth import (
    RegistrationError,
    _validate_registration,
    hash_password,
    verify_password,
)
from app.ui.auth_view import _record_failed_login, _remaining_lockout


def test_hash_and_verify_password() -> None:
    stored = hash_password("длинный-пароль")

    assert stored.startswith("scrypt$16384$8$1$")
    assert verify_password("длинный-пароль", stored)
    assert not verify_password("неверный-пароль", stored)
    assert not verify_password("длинный-пароль", "повреждённая строка")


def test_password_hashes_use_unique_salts() -> None:
    assert hash_password("same-password") != hash_password("same-password")


def test_registration_does_not_require_invite_code() -> None:
    assert _validate_registration(
        "MANAGER@example.com", " Менеджер ", "password1"
    ) == ("manager@example.com", "Менеджер")


@pytest.mark.parametrize(
    ("email", "password", "message"),
    [
        ("not-an-email", "password1", "корректный email"),
        ("manager@example.com", "short", "не менее 8 символов"),
    ],
)
def test_registration_validates_credentials_before_database(
    email: str, password: str, message: str
) -> None:
    with pytest.raises(RegistrationError, match=message):
        _validate_registration(email, "Менеджер", password)


def test_registration_form_has_no_invite_code_field() -> None:
    app = AppTest.from_string(
        """
from app.ui.auth_view import render_auth_screen
render_auth_screen("postgresql://configured")
"""
    ).run(timeout=10)
    app.radio[0].set_value("Регистрация").run(timeout=10)

    assert not app.exception
    assert [field.label for field in app.text_input] == ["Имя", "Email", "Пароль"]


def test_fifth_failed_login_starts_thirty_second_pause() -> None:
    state = {}
    for _ in range(5):
        _record_failed_login(state, 100.0)

    assert _remaining_lockout(state, 100.0) == 30
    assert _remaining_lockout(state, 129.1) == 1
    assert _remaining_lockout(state, 130.0) == 0
