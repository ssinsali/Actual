"""
실적 분석 통계 — 메인: 캠퍼스 · 조별 분석

로컬 실행:
  python 실적분석통계.py

Streamlit Cloud:
  Main file path = 실적분석통계.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))


def _launched_by_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None
    except Exception:
        return False


def _run_streamlit() -> None:
    import subprocess

    script = Path(__file__).resolve()
    env = os.environ.copy()
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in result.stdout.splitlines():
                if ":8502" in line and "LISTENING" in line:
                    pid = line.split()[-1]
                    if pid.isdigit():
                        subprocess.run(
                            ["taskkill", "/PID", pid, "/F"],
                            capture_output=True,
                            check=False,
                        )
        except OSError:
            pass
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(script),
            "--server.headless",
            "false",
            "--server.port",
            "8502",
        ],
        check=False,
        env=env,
        cwd=str(_APP_DIR),
    )


if __name__ == "__main__" and not _launched_by_streamlit():
    _run_streamlit()
    raise SystemExit(0)

st.set_page_config(page_title="캠퍼스·조별 실적", page_icon="📊", layout="wide")

from auth import render_auth_gate  # noqa: E402

if not render_auth_gate():
    st.stop()

from campus_page import render  # noqa: E402

render()
