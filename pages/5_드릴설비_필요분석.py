"""드릴설비 필요 분석 — 월별 수량 × 가공시간."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="드릴설비 필요 분석", page_icon="🛠️", layout="wide")

_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))


def _load_local(name: str):
    path = _APP_DIR / f"{name}.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_needed = ("drill_engine", "drill_page", "auth")
_missing = [f"{n}.py" for n in _needed if not (_APP_DIR / f"{n}.py").is_file()]
if _missing:
    st.error(
        "GitHub 저장소 **루트**(실적분석통계.py와 같은 위치)에 아래 파일이 없습니다. "
        "`pages/` 폴더가 아니라 한 단계 위에 올려 주세요."
    )
    st.code("\n".join(_missing), language="text")
    st.caption(f"현재 앱 폴더: `{_APP_DIR}`")
    st.stop()

for _name in ("drill_engine", "drill_page"):
    if _name not in sys.modules:
        _load_local(_name)

from drill_page import render  # noqa: E402
from auth import render_auth_gate  # noqa: E402

if not render_auth_gate():
    st.stop()

render()
