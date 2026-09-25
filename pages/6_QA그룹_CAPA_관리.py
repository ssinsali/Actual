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
    # 파일 내용이 바뀌었을 때 이전 모듈 잔존을 피한다
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _check_capa_files() -> list[str]:
    """파일이 뒤바뀌었거나 옛 버전인지 검사."""
    problems: list[str] = []
    engine = _APP_DIR / "capa_engine.py"
    page = _APP_DIR / "capa_page.py"
    if not engine.is_file():
        problems.append("capa_engine.py 없음")
    else:
        text = engine.read_text(encoding="utf-8", errors="replace")
        if "from capa_engine import" in text or "def render() -> None" in text:
            problems.append(
                "capa_engine.py 내용이 capa_page.py 와 같습니다. "
                "GitHub에서 capa_engine.py 를 로컬 capa_engine.py 로 다시 올려 주세요."
            )
        if "def calc_qa_capa" not in text:
            problems.append("capa_engine.py 에 calc_qa_capa 가 없습니다. 최신 파일을 올려 주세요.")
    if not page.is_file():
        problems.append("capa_page.py 없음")
    else:
        text = page.read_text(encoding="utf-8", errors="replace")
        if "def calc_qa_capa" in text and "def render() -> None" not in text:
            problems.append(
                "capa_page.py 내용이 capa_engine.py 와 같습니다. "
                "파일 이름이 뒤바뀌었는지 확인하세요."
            )
    return problems


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

_file_problems = _check_capa_files()
if _file_problems:
    st.error("QA CAPA 파일이 잘못 올라갔습니다.")
    for p in _file_problems:
        st.write(f"- {p}")
    st.caption(
        "루트에 올릴 파일: `capa_engine.py`(계산), `capa_page.py`(화면), "
        "`pages/6_QA그룹_CAPA_관리.py`(진입점). 두 py 파일 내용을 바꾸지 마세요."
    )
    st.stop()

try:
    for _name in ("drill_engine", "sim_engine", "capa_engine", "capa_page"):
        _load_local(_name)
    from auth import render_auth_gate  # noqa: E402
    from capa_page import render  # noqa: E402
except Exception as e:
    st.error("QA그룹 CAPA 관리 모듈을 불러오지 못했습니다.")
    st.code(f"{type(e).__name__}: {e}")
    st.code(traceback.format_exc())
    st.caption(
        "가장 흔한 원인: GitHub의 capa_engine.py 에 capa_page.py 내용이 들어감. "
        "로컬 `capa_engine.py` / `capa_page.py` 를 파일명 그대로 다시 업로드하세요."
    )
    st.stop()

if not render_auth_gate():
    st.stop()

render()
