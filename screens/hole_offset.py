"""홀 틀어짐 분석."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from auth import render_auth_gate  # noqa: E402
from page_access import enforce_page  # noqa: E402

if not render_auth_gate():
    st.stop()

enforce_page("hole_offset")

try:
    import cv2  # noqa: F401
except ImportError:
    st.error("OpenCV가 필요합니다. 로컬에서 `pip install opencv-python-headless` 후 다시 실행하세요.")
    st.stop()

from hole_offset_page import render  # noqa: E402

render()
