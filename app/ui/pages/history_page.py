"""Approved orders page."""

import streamlit as st

from app.ui.history_view import render_history


def render() -> None:
    st.title("История заказов")
    render_history(str(st.session_state["connection_url"]))


__all__ = ["render"]
