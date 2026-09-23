"""Astrea logo assets rendered as inline images."""

from base64 import b64encode
from functools import lru_cache
from pathlib import Path
from typing import Optional


BRAND_DIR = Path(__file__).resolve().parents[2] / "assets" / "brand"
FAVICON_PATH = BRAND_DIR / "favicon-32.png"
LOGO_PATH = BRAND_DIR / "astrea-logo.svg"
MARK_PATH = BRAND_DIR / "astrea-mark.svg"


@lru_cache(maxsize=None)
def _svg_data_uri(filename: str) -> Optional[str]:
    path = BRAND_DIR / filename
    if not path.is_file():
        return None
    encoded = b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def logo_html(height: int, variant: str = "logo") -> Optional[str]:
    """Return an <img> tag for the wordmark ("logo") or the icon ("mark")."""

    filename = "astrea-mark.svg" if variant == "mark" else "astrea-logo.svg"
    uri = _svg_data_uri(filename)
    if uri is None:
        return None
    return f'<img src="{uri}" alt="Astrea" height="{height}" style="display:block">'


def render_sidebar_logo() -> bool:
    """Put the logo at the top of the sidebar, above navigation. False without assets."""

    import streamlit as st

    if not (LOGO_PATH.is_file() and MARK_PATH.is_file()):
        return False
    st.logo(str(LOGO_PATH), size="large", icon_image=str(MARK_PATH))
    return True


def page_icon() -> str:
    """Tab icon for st.set_page_config, falling back to a letter without assets."""

    return str(FAVICON_PATH) if FAVICON_PATH.is_file() else "A"
