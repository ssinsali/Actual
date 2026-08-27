"""종합 실적 분석 (조·주/야·공정)."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from summary_page import render  # noqa: E402
from auth import render_auth_gate  # noqa: E402

st.set_page_config(page_title="종합 실적 분석", page_icon="📈", layout="wide")

if not render_auth_gate():
    st.stop()

render()
