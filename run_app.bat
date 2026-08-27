@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt -q
python 실적분석통계.py
