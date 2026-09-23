from app.ui.theme import THEME_CSS


def test_sidebar_logout_fits_visible_sidebar() -> None:
    assert 'height: 100dvh;' in THEME_CSS
    assert '.st-key-sidebar_profile .stButton > button' in THEME_CSS
    assert 'max-width: calc(100% - 2rem);' in THEME_CSS
