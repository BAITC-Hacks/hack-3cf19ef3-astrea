"""Visual system for the Astrea AI Streamlit interface."""

import streamlit as st


THEME_CSS = """
<style>
:root {
  --astrea-ink: #17211c;
  --astrea-muted: #66736c;
  --astrea-border: #d8e0dc;
  --astrea-accent: #176b52;
  --astrea-accent-dark: #10513e;
  --astrea-surface: #ffffff;
  --astrea-soft: #eef3f0;
  --astrea-radius: 12px;
}

#MainMenu, footer, [data-testid="stHeader"], [data-testid="stToolbar"] {
  display: none !important;
}

[data-testid="stAppViewContainer"] > .main .block-container {
  max-width: 1320px;
  padding-top: 1.4rem;
  padding-bottom: 2.5rem;
}

h1, h2, h3 {
  color: var(--astrea-ink);
  letter-spacing: -0.025em;
}

h1 {
  font-size: clamp(1.75rem, 2.2vw, 2.35rem) !important;
  font-weight: 720 !important;
}

h2, h3 {
  font-weight: 680 !important;
}

[data-testid="stMetric"] {
  background: transparent;
  border-left: 2px solid var(--astrea-border);
  padding: 0.25rem 0 0.25rem 0.85rem;
}

[data-testid="stMetricLabel"] {
  color: var(--astrea-muted);
}

[data-testid="stMetricValue"] {
  color: var(--astrea-ink);
  font-variant-numeric: tabular-nums;
}

[data-testid="stExpander"], [data-testid="stForm"],
[data-testid="stVerticalBlockBorderWrapper"] {
  border-color: var(--astrea-border) !important;
  border-radius: var(--astrea-radius) !important;
  box-shadow: none !important;
}

.stButton > button, .stDownloadButton > button {
  min-height: 2.65rem;
  border-radius: 10px;
  font-weight: 650;
  transition: transform 120ms ease, border-color 120ms ease;
}

.stButton > button:active, .stDownloadButton > button:active {
  transform: translateY(1px);
}

.stButton > button[kind="primary"] {
  background: var(--astrea-accent);
  border-color: var(--astrea-accent);
  color: #f7faf8;
}

.stButton > button[kind="primary"]:hover {
  background: var(--astrea-accent-dark);
  border-color: var(--astrea-accent-dark);
}

[data-baseweb="input"] > div,
[data-baseweb="select"] > div,
[data-baseweb="textarea"] > div {
  border-radius: 10px !important;
}

[data-testid="stDataFrame"] {
  border: 1px solid var(--astrea-border);
  border-radius: var(--astrea-radius);
  overflow: hidden;
}

[data-testid="stTabs"] [data-baseweb="tab-list"] {
  gap: 1.3rem;
  border-bottom: 1px solid var(--astrea-border);
}

[data-testid="stTabs"] button[role="tab"] {
  padding-left: 0;
  padding-right: 0;
  font-weight: 650;
}

.st-key-auth_panel {
  max-width: 440px;
  margin: 8vh auto 0;
  background: var(--astrea-surface);
  padding: 1.25rem;
  box-shadow: 0 24px 70px rgba(24, 55, 43, 0.10);
}

.st-key-auth_panel h1 {
  margin-bottom: 0.15rem;
}

.st-key-auth_panel h3 {
  color: var(--astrea-muted);
  font-size: 1rem;
  font-weight: 500 !important;
  letter-spacing: 0;
  margin-top: 0;
}

.st-key-brand_header {
  padding-bottom: 0.75rem;
}

.st-key-brand_header p {
  color: var(--astrea-muted);
}

@media (max-width: 768px) {
  [data-testid="stAppViewContainer"] > .main .block-container {
    padding: 1rem;
  }
  .st-key-auth_panel {
    margin-top: 2rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .stButton > button, .stDownloadButton > button {
    transition: none;
  }
}
</style>
"""


def apply_theme() -> None:
    st.markdown(THEME_CSS, unsafe_allow_html=True)


__all__ = ["apply_theme"]
