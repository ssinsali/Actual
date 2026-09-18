"""드릴 설비 필요 대수 — 월별 수량 × 제품 가공시간."""
from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

from sim_engine import (
    DAY_MINUTES,
    DEFAULT_WORK_DAYS,
    _norm,
    _num,
    _rename_by_alias,
)

DRILL_QTY_STEM = "드릴_월별필요수량"
DRILL_TIME_STEM = "드릴_제품가공시간"
DRILL_STEMS = (DRILL_QTY_STEM, DRILL_TIME_STEM)

QTY_ID_COLUMNS = ("제품코드", "제품명")
MONTH_COLUMNS = tuple(f"{m}월" for m in range(1, 13))
QTY_WIDE_COLUMNS = (*QTY_ID_COLUMNS, *MONTH_COLUMNS)
QTY_LONG_COLUMNS = ("년도", "월", "제품코드", "제품명", "필요수량")
TIME_COLUMNS = ("제품코드", "제품명", "매당가공시간_분", "비고")

DEFAULT_DAY_HOURS = 24.0
DEFAULT_UTILIZATION_PCT = 100.0

_CODE_ALIASES = (
    "제품코드",
    "코드구분",
    "제품코드구분",
    "품번",
    "품목코드",
    "자재코드",
    "품목",
    "item",
    "itemcode",
    "code",
    "product",
    "productcode",
)

_MONTH_HEADER_RE = re.compile(
    r"^(?:(?P<year>20\d{2})\s*[-./년]?\s*)?(?P<month>1[0-2]|0?[1-9])\s*월?$"
)
_YM_COMPACT_RE = re.compile(r"^(?P<year>20\d{2})(?P<month>1[0-2]|0[1-9])$")


def _code_key(v: Any) -> str:
    """제품코드 비교용 — 공백·특수하이픈을 맞춘다."""
    t = _norm(v).replace("\ufeff", "").replace("\u00a0", " ")
    for ch in ("－", "–", "—", "−", "﹣"):
        t = t.replace(ch, "-")
    return re.sub(r"\s+", "", t).upper()


def _clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = df.dropna(how="all").copy()
    work.columns = [_norm(c) for c in work.columns]
    drop = [
        c
        for c in work.columns
        if c == ""
        or str(c).startswith("Unnamed")
        or work[c].map(lambda v: _norm(v) == "").all()
    ]
    if drop:
        work = work.drop(columns=drop, errors="ignore")
    return work


def _ensure_product_code(work: pd.DataFrame) -> pd.DataFrame:
    if "제품코드" in work.columns:
        return work
    for col in list(work.columns):
        key = str(col).replace(" ", "").replace("_", "").lower()
        for opt in _CODE_ALIASES:
            if key == opt.replace(" ", "").replace("_", "").lower():
                return work.rename(columns={col: "제품코드"})
    for col in list(work.columns):
        key = str(col).replace(" ", "")
        if "코드" in key and "설비" not in key and "공정" not in key:
            return work.rename(columns={col: "제품코드"})
    return work


def _ceil_machines(value: float) -> int:
    v = float(value or 0)
    if v <= 1e-9:
        return 0
    return int(math.ceil(v - 1e-9))


def machine_month_minutes(
    *,
    work_days: float,
    day_hours: float,
    utilization_pct: float,
) -> float:
    days = max(float(work_days or 0), 0.0)
    hours = max(float(day_hours or 0), 0.0)
    util = max(min(float(utilization_pct or 0), 100.0), 0.0) / 100.0
    return days * hours * 60.0 * util


def qty_template() -> pd.DataFrame:
    """월별 제품코드 필요수량 예시 (1월~12월 가로형)."""
    return pd.DataFrame(
        [
            {
                "제품코드": "A3E00T-SM",
                "제품명": "예시 CEL",
                "1월": 700,
                "2월": 650,
                "3월": 800,
                "4월": 820,
                "5월": 780,
                "6월": 720,
                "7월": 700,
                "8월": 760,
                "9월": 800,
                "10월": 780,
                "11월": 740,
                "12월": 680,
            },
            {
                "제품코드": "C3E01S-SH",
                "제품명": "예시 CEL",
                "1월": 1200,
                "2월": 1100,
                "3월": 1400,
                "4월": 1350,
                "5월": 1300,
                "6월": 1250,
                "7월": 1200,
                "8월": 1280,
                "9월": 1380,
                "10월": 1320,
                "11월": 1260,
                "12월": 1180,
            },
            {
                "제품코드": "P-RING",
                "제품명": "예시 Ring",
                "1월": 15000,
                "2월": 14000,
                "3월": 16000,
                "4월": 15800,
                "5월": 15200,
                "6월": 14800,
                "7월": 14500,
                "8월": 15000,
                "9월": 15500,
                "10월": 15200,
                "11월": 14800,
                "12월": 14200,
            },
        ],
        columns=list(QTY_WIDE_COLUMNS),
    )


def time_template() -> pd.DataFrame:
    """제품별 드릴 가공시간 예시 (1매당 분)."""
    return pd.DataFrame(
        [
            {
                "제품코드": "A3E00T-SM",
                "제품명": "예시 CEL",
                "매당가공시간_분": 18.0,
                "비고": "1매 드릴 가공시간",
            },
            {
                "제품코드": "C3E01S-SH",
                "제품명": "예시 CEL",
                "매당가공시간_분": 24.0,
                "비고": "1매 드릴 가공시간",
            },
            {
                "제품코드": "P-RING",
                "제품명": "예시 Ring",
                "매당가공시간_분": 8.0,
                "비고": "1매 드릴 가공시간",
            },
        ],
        columns=list(TIME_COLUMNS),
    )


def _parse_month_header(col: Any) -> tuple[str, int] | None:
    text = _norm(col).replace(" ", "")
    if not text:
        return None
    compact = _YM_COMPACT_RE.match(text)
    if compact:
        return compact.group("year"), int(compact.group("month"))
    matched = _MONTH_HEADER_RE.match(text)
    if not matched:
        return None
    month = int(matched.group("month"))
    year = matched.group("year") or ""
    return year, month


def _month_label(year: str, month: int) -> str:
    if year:
        return f"{year}-{int(month):02d}"
    return f"{int(month)}월"


def _is_qty_wide(df: pd.DataFrame) -> bool:
    return any(_parse_month_header(c) for c in df.columns)


def normalize_qty(df: pd.DataFrame) -> pd.DataFrame:
    """월별 필요수량을 긴 형태로 맞춘다.

    가로형: 제품코드, (제품명), 1월~12월 또는 2026-01 …
    세로형: 제품코드, 월/년월, 필요수량
    """
    empty = pd.DataFrame(columns=["년도", "월", "월라벨", "제품코드", "제품명", "필요수량"])
    if df is None or df.empty:
        return empty

    work = _clean_frame(df)
    work = _rename_by_alias(
        work,
        {
            "제품코드": _CODE_ALIASES,
            "제품명": ("제품명", "품명", "itemname", "name"),
            "년도": ("년도", "연도", "year"),
            "월": ("월", "month"),
            "년월": ("년월", "연월", "yyyymm", "period"),
            "필요수량": ("필요수량", "수량", "매수", "목표", "월목표", "월목표매수", "qty"),
        },
    )
    work = _ensure_product_code(work)

    if "제품코드" not in work.columns:
        return empty
    work["제품코드"] = work["제품코드"].map(_code_key)
    if "제품명" not in work.columns:
        work["제품명"] = ""
    work["제품명"] = work["제품명"].map(_norm)
    work = work[work["제품코드"] != ""].copy()
    if work.empty:
        return empty

    if _is_qty_wide(work):
        id_cols = [c for c in ("제품코드", "제품명") if c in work.columns]
        month_cols = [c for c in work.columns if _parse_month_header(c)]
        melted = work.melt(
            id_vars=id_cols,
            value_vars=month_cols,
            var_name="_월헤더",
            value_name="필요수량",
        )
        parsed = melted["_월헤더"].map(_parse_month_header)
        melted["년도"] = parsed.map(lambda p: p[0] if p else "")
        melted["월"] = parsed.map(lambda p: int(p[1]) if p else 0)
        if "년도" in work.columns:
            year_by_code = work[["제품코드", "년도"]].copy()
            year_by_code["년도"] = year_by_code["년도"].map(
                lambda v: str(int(_num(v))) if _num(v) else _norm(v)
            )
            year_map = {
                _norm(r["제품코드"]): _norm(r["년도"])
                for _, r in year_by_code.drop_duplicates("제품코드").iterrows()
            }
            melted["년도"] = melted.apply(
                lambda r: r["년도"] or year_map.get(_norm(r["제품코드"]), ""),
                axis=1,
            )
        melted["필요수량"] = pd.to_numeric(melted["필요수량"], errors="coerce").fillna(0)
        melted = melted[melted["월"].between(1, 12) & (melted["필요수량"] > 0)]
        melted["월라벨"] = melted.apply(lambda r: _month_label(str(r["년도"]), int(r["월"])), axis=1)
        return melted[["년도", "월", "월라벨", "제품코드", "제품명", "필요수량"]].reset_index(drop=True)

    # 세로형
    if "년월" in work.columns:
        ym = work["년월"].map(_norm)
        parsed = ym.map(_parse_month_header)
        work["년도"] = parsed.map(lambda p: p[0] if p else "")
        work["월"] = parsed.map(lambda p: int(p[1]) if p else 0)
    else:
        if "년도" in work.columns:
            work["년도"] = work["년도"].map(
                lambda v: str(int(_num(v))) if _num(v) else _norm(v)
            )
        else:
            work["년도"] = ""
        if "월" in work.columns:
            work["월"] = work["월"].map(
                lambda v: int(_parse_month_header(v)[1]) if _parse_month_header(v) else int(_num(v))
            )
        else:
            work["월"] = 0

    if "필요수량" not in work.columns:
        return empty
    work["필요수량"] = pd.to_numeric(work["필요수량"], errors="coerce").fillna(0)
    work = work[(work["월"].between(1, 12)) & (work["필요수량"] > 0)].copy()
    if work.empty:
        return empty
    work["월라벨"] = work.apply(lambda r: _month_label(str(r.get("년도", "")), int(r["월"])), axis=1)
    grouped = (
        work.groupby(["년도", "월", "월라벨", "제품코드"], as_index=False)
        .agg(제품명=("제품명", "last"), 필요수량=("필요수량", "sum"))
    )
    return grouped.reset_index(drop=True)


def normalize_times(df: pd.DataFrame) -> pd.DataFrame:
    empty = pd.DataFrame(columns=list(TIME_COLUMNS))
    if df is None or df.empty:
        return empty
    work = _rename_by_alias(
        _clean_frame(df),
        {
            "제품코드": _CODE_ALIASES,
            "제품명": ("제품명", "품명", "itemname", "name"),
            "매당가공시간_분": (
                "매당가공시간_분",
                "매당가공시간",
                "가공시간",
                "가공시간분",
                "택트",
                "택트분",
                "cycle",
                "cycletime",
                "분",
            ),
            "비고": ("비고", "메모", "remark", "note"),
        },
    )
    work = _ensure_product_code(work)
    for col in TIME_COLUMNS:
        if col not in work.columns:
            work[col] = "" if col != "매당가공시간_분" else 0
    work["제품코드"] = work["제품코드"].map(_code_key)
    work["제품명"] = work["제품명"].map(_norm)
    work["비고"] = work["비고"].map(_norm)
    work["매당가공시간_분"] = pd.to_numeric(work["매당가공시간_분"], errors="coerce").fillna(0)
    work = work[(work["제품코드"] != "") & (work["매당가공시간_분"] > 0)]
    return (
        work.drop_duplicates("제품코드", keep="last")[list(TIME_COLUMNS)]
        .reset_index(drop=True)
    )


def calc_drill_requirement(
    qty: pd.DataFrame,
    times: pd.DataFrame,
    *,
    work_days: float = DEFAULT_WORK_DAYS,
    day_hours: float = DEFAULT_DAY_HOURS,
    utilization_pct: float = DEFAULT_UTILIZATION_PCT,
) -> dict[str, Any]:
    """월별 필요시간·필요대수를 계산한다.

    필요시간(분) = 필요수량 × 매당가공시간_분
    1대 월가용(분) = 작업일수 × 일가동시간 × 60 × 가동률
    이론필요대수 = 필요시간 ÷ 1대 월가용
    총 필요대수 = 월별 올림 대수 중 최대 (피크월 커버)
    """
    qty_n = normalize_qty(qty)
    time_n = normalize_times(times)
    avail = machine_month_minutes(
        work_days=work_days,
        day_hours=day_hours,
        utilization_pct=utilization_pct,
    )
    empty_detail = pd.DataFrame(
        columns=[
            "년도",
            "월",
            "월라벨",
            "제품코드",
            "제품명",
            "필요수량",
            "매당가공시간_분",
            "필요시간_분",
            "이론필요대수",
        ]
    )
    empty_monthly = pd.DataFrame(
        columns=[
            "년도",
            "월",
            "월라벨",
            "필요수량합",
            "필요시간_분",
            "1대월가용_분",
            "이론필요대수",
            "필요대수",
            "부하율%",
        ]
    )
    result: dict[str, Any] = {
        "qty": qty_n,
        "times": time_n,
        "detail": empty_detail,
        "monthly": empty_monthly,
        "unmatched": [],
        "unused_times": [],
        "qty_columns": list(qty.columns) if qty is not None else [],
        "time_columns": list(times.columns) if times is not None else [],
        "work_days": float(work_days),
        "day_hours": float(day_hours),
        "utilization_pct": float(utilization_pct),
        "machine_month_min": avail,
        "peak_label": "",
        "peak_hours": 0.0,
        "peak_theoretical": 0.0,
        "total_required": 0,
        "avg_theoretical": 0.0,
    }
    if qty_n.empty or time_n.empty or avail <= 0:
        return result

    time_map = {
        _code_key(r["제품코드"]): float(r["매당가공시간_분"])
        for _, r in time_n.iterrows()
    }
    name_map = {
        _code_key(r["제품코드"]): _norm(r["제품명"])
        for _, r in time_n.iterrows()
        if _norm(r["제품명"])
    }
    qty_codes = set(qty_n["제품코드"].map(_code_key))
    time_codes = set(time_map)
    result["unmatched"] = sorted(qty_codes - time_codes)
    result["unused_times"] = sorted(time_codes - qty_codes)

    detail = qty_n.copy()
    detail["매당가공시간_분"] = detail["제품코드"].map(time_map)
    detail = detail[detail["매당가공시간_분"].notna() & (detail["매당가공시간_분"] > 0)].copy()
    if detail.empty:
        return result
    detail["제품명"] = detail.apply(
        lambda r: r["제품명"] or name_map.get(_code_key(r["제품코드"]), ""),
        axis=1,
    )
    detail["필요시간_분"] = detail["필요수량"] * detail["매당가공시간_분"]
    detail["이론필요대수"] = (detail["필요시간_분"] / avail).round(4)
    detail = detail.sort_values(["년도", "월", "제품코드"]).reset_index(drop=True)
    result["detail"] = detail

    monthly = (
        detail.groupby(["년도", "월", "월라벨"], as_index=False)
        .agg(필요수량합=("필요수량", "sum"), 필요시간_분=("필요시간_분", "sum"))
    )
    monthly["1대월가용_분"] = avail
    monthly["이론필요대수"] = (monthly["필요시간_분"] / avail).round(4)
    monthly["필요대수"] = monthly["이론필요대수"].map(_ceil_machines)
    monthly["부하율%"] = (monthly["이론필요대수"] * 100).round(1)
    monthly = monthly.sort_values(["년도", "월"]).reset_index(drop=True)
    result["monthly"] = monthly

    if monthly.empty:
        return result
    peak_idx = monthly["이론필요대수"].idxmax()
    peak = monthly.loc[peak_idx]
    result["peak_label"] = str(peak["월라벨"])
    result["peak_hours"] = float(peak["필요시간_분"]) / 60.0
    result["peak_theoretical"] = float(peak["이론필요대수"])
    result["total_required"] = int(monthly["필요대수"].max())
    result["avg_theoretical"] = float(monthly["이론필요대수"].mean())
    return result
