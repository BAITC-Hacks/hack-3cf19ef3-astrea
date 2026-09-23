from app.ui.loading_view import _loading_markup


def test_loading_markup_contains_real_percentage_and_reduced_motion() -> None:
    markup = _loading_markup("Очистка продаж", 0.42)

    assert "Очистка продаж · 42%" in markup
    assert markup.count("<circle") == 9
    assert "prefers-reduced-motion: reduce" in markup
    assert "width: 42%" in markup
