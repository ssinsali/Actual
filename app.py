"""
Streamlit Cloud 진입점 (= 실적분석통계.py 와 동일).
로컬 권장: python 실적분석통계.py
"""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).resolve().parent / "실적분석통계.py"), run_name="__streamlit_home__")
