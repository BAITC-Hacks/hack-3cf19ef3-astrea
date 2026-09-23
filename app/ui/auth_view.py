"""Streamlit authentication screen."""

import time
from typing import Optional

import streamlit as st

from app.auth import RegistrationError, authenticate, register


MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 30


def _record_failed_login(state: object, now: float) -> None:
    attempts = int(state.get("login_attempts", 0)) + 1
    state["login_attempts"] = attempts
    if attempts >= MAX_LOGIN_ATTEMPTS:
        state["login_locked_until"] = now + LOCKOUT_SECONDS
        state["login_attempts"] = 0


def _remaining_lockout(state: object, now: float) -> int:
    remaining = float(state.get("login_locked_until", 0.0)) - now
    return max(0, int(remaining + 0.999))


def render_auth_screen(connection_url: str) -> Optional[dict[str, object]]:
    """Render login/registration and return a newly authenticated user."""

    with st.container(key="auth_panel", border=True):
        st.title("Astrea AI")
        st.subheader("Автозаказ поставщикам")
        mode = st.segmented_control(
            "Режим",
            ["Вход", "Регистрация"],
            default="Вход",
            label_visibility="collapsed",
        )
        if mode == "Регистрация":
            with st.form("registration_form"):
                full_name = st.text_input("Имя")
                email = st.text_input("Email")
                password = st.text_input("Пароль", type="password")
                invite_code = st.text_input("Код приглашения", type="password")
                submitted = st.form_submit_button(
                    "Зарегистрироваться", type="primary", width="stretch"
                )
            if submitted:
                try:
                    return register(
                        email,
                        full_name,
                        password,
                        invite_code,
                        connection_url,
                    )
                except RegistrationError as error:
                    st.error(str(error))
                except Exception:
                    st.error("Сервис временно недоступен")
            return None

        now = time.time()
        remaining = _remaining_lockout(st.session_state, now)
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Пароль", type="password")
            submitted = st.form_submit_button(
                "Войти", type="primary", disabled=remaining > 0, width="stretch"
            )
        if remaining:
            st.error(f"Повторите попытку через {remaining} с")
        elif submitted:
            try:
                user = authenticate(email, password, connection_url)
            except Exception:
                st.error("Сервис временно недоступен")
                return None
            if user is None:
                _record_failed_login(st.session_state, now)
                st.error("Неверный email или пароль")
            else:
                st.session_state.pop("login_attempts", None)
                st.session_state.pop("login_locked_until", None)
                return user
    return None


__all__ = [
    "LOCKOUT_SECONDS",
    "MAX_LOGIN_ATTEMPTS",
    "_record_failed_login",
    "_remaining_lockout",
    "render_auth_screen",
]
