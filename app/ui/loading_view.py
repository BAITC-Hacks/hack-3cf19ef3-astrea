"""Centered Astrea constellation progress overlay."""

from html import escape

import streamlit as st
from app.ui.memo import clear_all_caches


STARS = (
    (36, 78),
    (75, 38),
    (116, 62),
    (158, 28),
    (198, 70),
    (168, 112),
    (118, 98),
    (76, 132),
    (32, 116),
)
LINES = ((0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 2), (6, 7), (7, 8), (8, 0))


def _loading_markup(stage: str, fraction: float) -> str:
    progress = min(max(float(fraction), 0.0), 1.0)
    active_count = max(1, round(progress * len(STARS)))
    current = min(active_count - 1, len(STARS) - 1)
    lines = "".join(
        (
            f'<line x1="{STARS[start][0]}" y1="{STARS[start][1]}" '
            f'x2="{STARS[end][0]}" y2="{STARS[end][1]}" />'
        )
        for start, end in LINES
    )
    stars = "".join(
        (
            f'<circle class="astrea-star '
            f'{"is-active" if index < active_count else ""} '
            f'{"is-current" if index == current else ""}" '
            f' cx="{x}" cy="{y}" r="5" />'
        )
        for index, (x, y) in enumerate(STARS)
    )
    percentage = round(progress * 100)
    return f"""
<style>
.astrea-loading-layer {{
  position: fixed;
  inset: 0;
  z-index: 999999;
  display: grid;
  place-items: center;
  background: rgba(247, 249, 248, 0.92);
  backdrop-filter: blur(7px);
}}
.astrea-loading-card {{
  width: min(390px, calc(100vw - 2rem));
  padding: 2rem 2.1rem 1.8rem;
  border: 1px solid #d8e0dc;
  border-radius: 18px;
  background: #ffffff;
  box-shadow: 0 28px 80px rgba(23, 33, 28, 0.14);
  text-align: center;
}}
.astrea-constellation {{ width: 230px; max-width: 80%; }}
.astrea-constellation line {{ stroke: #ccd8d2; stroke-width: 1.5; }}
.astrea-star {{ fill: #d8e0dc; transition: fill 180ms ease; }}
.astrea-star.is-active {{ fill: #176b52; }}
.astrea-star.is-current {{
  fill: #d9a441;
  transform-box: fill-box;
  transform-origin: center;
  animation: astrea-pulse 1.1s ease-in-out infinite;
}}
.astrea-progress {{
  height: 7px;
  margin: 1.2rem 0 0.85rem;
  overflow: hidden;
  border-radius: 999px;
  background: #e7eeea;
}}
.astrea-progress > span {{
  display: block;
  width: {percentage}%;
  height: 100%;
  border-radius: inherit;
  background: #176b52;
  transition: width 180ms ease;
}}
.astrea-loading-copy {{
  margin: 0;
  color: #35443c;
  font: 600 0.9rem/1.35 sans-serif;
}}
@keyframes astrea-pulse {{
  50% {{ transform: scale(1.65); opacity: 0.65; }}
}}
@media (prefers-reduced-motion: reduce) {{
  .astrea-star.is-current {{ animation: none; }}
  .astrea-progress > span {{ transition: none; }}
}}
</style>
<div class="astrea-loading-layer" role="status" aria-live="polite">
  <div class="astrea-loading-card">
    <svg class="astrea-constellation" viewBox="0 0 230 155" aria-hidden="true">
      <g>{lines}</g><g>{stars}</g>
    </svg>
    <div class="astrea-progress"><span></span></div>
    <p class="astrea-loading-copy">{escape(stage)} · {percentage}%</p>
  </div>
</div>
"""


class LoadingView:
    """Small callback adapter accepted by engine and loader operations."""

    def __init__(self) -> None:
        self._placeholder = st.empty()

    def update(self, stage: str, fraction: float) -> None:
        self._placeholder.markdown(
            _loading_markup(stage, fraction), unsafe_allow_html=True
        )

    def close(self) -> None:
        self._placeholder.empty()


def render_loading_error(message: object, key: str) -> None:
    """Show a centered one-line failure with an explicit retry action."""

    with st.container(key=f"loading_error_{key}", border=True):
        st.error(str(message).splitlines()[0])
        if st.button("Повторить", key=f"retry_{key}", type="primary"):
            clear_all_caches()
            st.rerun()


__all__ = ["LoadingView", "_loading_markup", "render_loading_error"]
