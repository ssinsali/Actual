"""월평균 추이 (조·공정 상승/유지/하락)."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from trend_page import render  # noqa: E402
from auth import render_auth_gate  # noqa: E402

st.set_page_config(page_title="월평균 추이", page_icon="📉", layout="wide")

if not render_auth_gate():
    st.stop()

render()
