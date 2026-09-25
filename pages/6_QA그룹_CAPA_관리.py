"""QA그룹 CAPA 관리 — 월별 치수·홀 필요대수·가동율."""
from __future__ import annotations

import importlib.util
import sys
import traceback
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="QA그룹 CAPA 관리", page_icon="📊", layout="wide")

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


_needed = ("capa_engine", "capa_page", "auth", "drill_engine", "sim_engine", "app_common")
_missing = [f"{n}.py" for n in _needed if not (_APP_DIR / f"{n}.py").is_file()]
if _missing:
    st.error(
        "GitHub 저장소 **루트**(실적분석통계.py와 같은 위치)에 아래 파일이 없습니다. "
        "`pages/` 폴더가 아니라 한 단계 위에 올려 주세요."
    )
    st.code("\n".join(_missing), language="text")
    st.caption(f"현재 앱 폴더: `{_APP_DIR}`")
    st.stop()

try:
    for _name in ("drill_engine", "sim_engine", "capa_engine", "capa_page"):
        if _name not in sys.modules:
            _load_local(_name)
    from auth import render_auth_gate  # noqa: E402
    from capa_page import render  # noqa: E402
except Exception as e:
    st.error("QA그룹 CAPA 관리 모듈을 불러오지 못했습니다.")
    st.code(f"{type(e).__name__}: {e}")
    st.code(traceback.format_exc())
    st.caption(
        "GitHub 루트에 capa_engine.py, capa_page.py가 있고, "
        "drill_engine.py / sim_engine.py도 최신인지 확인하세요."
    )
    st.stop()

if not render_auth_gate():
    st.stop()

render()
