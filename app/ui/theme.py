"""Visual system for the Astrea Streamlit interface."""

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

[data-testid="stSidebar"] {
  border-right: 1px solid var(--astrea-border);
}

[data-testid="stSidebarLogo"] {
  height: 2.6rem;
  max-width: 100%;
}

[data-testid="stSidebarHeader"] {
  padding-top: 1.25rem;
  padding-bottom: 0.5rem;
}

[data-testid="stSidebarContent"] {
  position: relative;
  height: 100dvh;
  min-height: 0;
  padding-bottom: 9rem;
  box-sizing: border-box;
}

.st-key-sidebar_brand {
  padding: 0.35rem 0.5rem 1rem;
  border-bottom: 1px solid var(--astrea-border);
}

.st-key-sidebar_brand h2 {
  margin: 0;
  font-size: 1.35rem !important;
  letter-spacing: -0.035em;
}

.st-key-sidebar_brand [data-testid="stCaptionContainer"] {
  color: var(--astrea-muted);
}

[data-testid="stSidebarNav"] a {
  border-radius: 9px;
  margin: 0.15rem 0;
  font-weight: 600;
}

[data-testid="stSidebarNav"] a[aria-current="page"] {
  background: var(--astrea-soft);
  color: var(--astrea-accent-dark);
}

.st-key-sidebar_profile {
  position: absolute;
  right: 1rem;
  bottom: 1rem;
  left: 1rem;
  width: calc(100% - 2rem);
  max-width: calc(100% - 2rem);
  overflow: hidden;
  box-sizing: border-box;
  padding-top: 0.9rem;
  border-top: 1px solid var(--astrea-border);
}

.st-key-sidebar_profile .stButton,
.st-key-sidebar_profile .stButton > button {
  width: 100% !important;
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
}

.astrea-profile {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  margin-bottom: 0.7rem;
}

.astrea-avatar {
  display: grid;
  width: 2.25rem;
  height: 2.25rem;
  flex: 0 0 2.25rem;
  place-items: center;
  border-radius: 50%;
  background: var(--astrea-accent-dark);
  color: #f7faf8;
  font-size: 0.78rem;
  font-weight: 750;
}

.astrea-profile-copy {
  min-width: 0;
  display: grid;
  line-height: 1.25;
}

.astrea-profile-copy strong,
.astrea-profile-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

[class*="st-key-loading_error_"] {
  position: fixed;
  top: 50%;
  left: 50%;
  z-index: 999999;
  width: min(420px, calc(100vw - 2rem));
  padding: 1rem;
  transform: translate(-50%, -50%);
  background: var(--astrea-surface);
  box-shadow: 0 28px 80px rgba(23, 33, 28, 0.16);
}

[class*="st-key-loading_error_"]::before {
  content: "";
  position: fixed;
  inset: -100vh -100vw;
  z-index: -1;
  background: rgba(247, 249, 248, 0.92);
  backdrop-filter: blur(7px);
}

.astrea-profile-copy strong {
  color: var(--astrea-ink);
  font-size: 0.88rem;
}

.astrea-profile-copy small {
  color: var(--astrea-muted);
  font-size: 0.74rem;
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
