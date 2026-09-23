import pytest

from app.auth import RegistrationError, hash_password, register, verify_password
from app.ui.auth_view import _record_failed_login, _remaining_lockout


def test_hash_and_verify_password() -> None:
    stored = hash_password("длинный-пароль")

    assert stored.startswith("scrypt$16384$8$1$")
    assert verify_password("длинный-пароль", stored)
    assert not verify_password("неверный-пароль", stored)
    assert not verify_password("длинный-пароль", "повреждённая строка")


def test_password_hashes_use_unique_salts() -> None:
    assert hash_password("same-password") != hash_password("same-password")


def test_registration_is_closed_without_invite_code(monkeypatch) -> None:
    monkeypatch.delenv("INVITE_CODE", raising=False)

    with pytest.raises(RegistrationError, match="Регистрация закрыта"):
        register("manager@example.com", "Менеджер", "password1", "")


def test_registration_rejects_wrong_invite_code(monkeypatch) -> None:
    monkeypatch.setenv("INVITE_CODE", "secret-code")

    with pytest.raises(RegistrationError, match="Неверный код приглашения"):
        register("manager@example.com", "Менеджер", "password1", "wrong")


@pytest.mark.parametrize(
    ("email", "password", "message"),
    [
        ("not-an-email", "password1", "корректный email"),
        ("manager@example.com", "short", "не менее 8 символов"),
    ],
)
def test_registration_validates_credentials_before_database(
    monkeypatch, email: str, password: str, message: str
) -> None:
    monkeypatch.setenv("INVITE_CODE", "secret-code")

    with pytest.raises(RegistrationError, match=message):
        register(email, "Менеджер", password, "secret-code")


def test_fifth_failed_login_starts_thirty_second_pause() -> None:
    state = {}
    for _ in range(5):
        _record_failed_login(state, 100.0)

    assert _remaining_lockout(state, 100.0) == 30
    assert _remaining_lockout(state, 129.1) == 1
    assert _remaining_lockout(state, 130.0) == 0
