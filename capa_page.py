"""QA그룹 CAPA — 월별 생산계획 × 제품 측정시간 → 치수·홀 필요대수·가동율.

설비 운영 시뮬레이션과 같은 규칙:
- 치수: CEL·Ring·Wafer 등 측정시간이 있는 전 제품
- 홀(Hole): CEL만
- 1대 월 가용(분) = 작업일수 × 1일 가동시간 × 60  (설비 24시간이면 작업일 × 1440)
- 필요대수 = ceil(그 달 필요시간 합 ÷ 1대 월 가용)
- 가동율(%) = 필요시간 ÷ (보유대수 × 1대 월 가용) × 100
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

from drill_engine import _code_key, _month_label, _parse_month_header, machine_month_minutes, normalize_qty
from sim_engine import _infer_product_family, _norm, _rename_by_alias, normalize_products

QA_PLAN_STEM = "QA_월별생산계획"
# 설비 운영 시뮬레이션과 동일한 제품 기준정보 파일명
PRODUCT_STEM = "제품_기준정보"
QA_STEMS = (QA_PLAN_STEM, PRODUCT_STEM)
# 예전 CAPA 전용 파일명 (있으면 제품_기준정보 없을 때 fallback)
_LEGACY_TIME_STEM = "QA_제품측정시간"

PLAN_COLUMNS = ("제품코드", "제품명", *(f"{m}월" for m in range(1, 13)))
TIME_COLUMNS = ("제품코드", "제품명", "제품군", "치수_측정분", "홀_측정분", "비고")


def _ceil_machines(value: float) -> int:
    v = float(value or 0)
    if v <= 1e-9:
        return 0
    return int(math.ceil(v - 1e-9))


def plan_template() -> pd.DataFrame:
    """월별 생산계획 예시 (1월~12월 가로형)."""
    return pd.DataFrame(
        [
            {
                "제품코드": "P-CEL",
                "제품명": "CEL",
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
                "제품코드": "P-RING",
                "제품명": "Ring",
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
            {
                "제품코드": "P-WAFER",
                "제품명": "Wafer",
                "1월": 3000,
                "2월": 2800,
                "3월": 3200,
                "4월": 3100,
                "5월": 3000,
                "6월": 2900,
                "7월": 2800,
                "8월": 3000,
                "9월": 3150,
                "10월": 3050,
                "11월": 2950,
                "12월": 2700,
            },
        ],
        columns=list(PLAN_COLUMNS),
    )


def _clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = df.dropna(how="all").copy()
    work.columns = [_norm(c) for c in work.columns]
    return work


def _positive_mean(series: pd.Series) -> float:
    vals = pd.to_numeric(series, errors="coerce")
    vals = vals[vals > 0]
    if vals.empty:
        return 0.0
    return float(vals.mean())


def _area_name(v: Any) -> str:
    name = _norm(v).replace(" ", "")
    upper = name.upper()
    if "홀" in name or upper == "HOLE" or "HOLE" in upper:
        return "홀"
    if "치수" in name:
        return "치수"
    return ""


def _family_of(row: pd.Series) -> str:
    fam = _infer_product_family(row.get("제품군", ""))
    if fam in ("CEL", "Ring", "Wafer"):
        return fam
    fam = _infer_product_family(row.get("제품명", ""))
    if fam in ("CEL", "Ring", "Wafer"):
        return fam
    return _infer_product_family(row.get("제품코드", ""))


_WIDE_TIME_KEYS = {
    "치수측정분",
    "치수매당분",
    "치수측정시간",
    "매당치수분",
    "홀측정분",
    "hole매당분",
    "홀매당분",
    "홀측정시간",
    "hole측정시간",
    "매당홀분",
}


def _has_wide_time_columns(df: pd.DataFrame) -> bool:
    keys = {_norm(c).replace(" ", "").replace("_", "").lower() for c in df.columns}
    return bool(keys & _WIDE_TIME_KEYS)


def _finish_measure(out: pd.DataFrame) -> pd.DataFrame:
    empty = pd.DataFrame(columns=list(TIME_COLUMNS))
    if out is None or out.empty:
        return empty
    work = out.copy()
    for col in TIME_COLUMNS:
        if col not in work.columns:
            work[col] = "" if col not in ("치수_측정분", "홀_측정분") else 0
    work["제품코드"] = work["제품코드"].map(_code_key)
    work["제품명"] = work["제품명"].map(_norm)
    work["제품군"] = work["제품군"].map(_norm)
    work["비고"] = work["비고"].map(_norm)
    work["치수_측정분"] = pd.to_numeric(work["치수_측정분"], errors="coerce").fillna(0)
    work["홀_측정분"] = pd.to_numeric(work["홀_측정분"], errors="coerce").fillna(0)
    work = work[work["제품코드"] != ""]
    if work.empty:
        return empty
    work = (
        work.groupby("제품코드", as_index=False)
        .agg(
            제품명=("제품명", "last"),
            제품군=("제품군", "last"),
            치수_측정분=("치수_측정분", "max"),
            홀_측정분=("홀_측정분", "max"),
            비고=("비고", "last"),
        )
    )
    work["제품군"] = work.apply(_family_of, axis=1)
    work = work[(work["치수_측정분"] > 0) | (work["홀_측정분"] > 0)]
    if work.empty:
        return empty
    return work[list(TIME_COLUMNS)].reset_index(drop=True)


def normalize_measure_times(df: pd.DataFrame) -> pd.DataFrame:
    """제품_기준정보 → 제품코드별 치수·홀 측정분.

    설비 운영 시뮬레이션과 같은 `normalize_products`로 읽은 뒤
    공정=치수 / Hole 행의 매당_설비분을 사용한다.
    """
    empty = pd.DataFrame(columns=list(TIME_COLUMNS))
    if df is None or df.empty:
        return empty

    products = normalize_products(df)
    if not products.empty and "공정" in products.columns:
        work = products.copy()
        work["공정키"] = work["공정"].map(_area_name)
        work = work[work["공정키"].isin(["치수", "홀"])]
        if not work.empty:
            work["_tact"] = pd.to_numeric(work["매당_설비분"], errors="coerce").fillna(0)
            man = pd.to_numeric(work["매당_인시분"], errors="coerce").fillna(0)
            work.loc[work["_tact"] <= 0, "_tact"] = man
            rows: list[dict[str, Any]] = []
            for code, sub in work.groupby(work["제품코드"].map(_code_key), sort=False):
                if not code:
                    continue
                dim = sub.loc[sub["공정키"] == "치수", "_tact"]
                hole = sub.loc[sub["공정키"] == "홀", "_tact"]
                name = next((_norm(x) for x in sub["제품명"].tolist() if _norm(x)), "")
                fam = next((_norm(x) for x in sub["제품군"].tolist() if _norm(x)), "")
                note = next((_norm(x) for x in sub["비고"].tolist() if _norm(x)), "") if "비고" in sub.columns else ""
                rows.append(
                    {
                        "제품코드": code,
                        "제품명": name,
                        "제품군": fam,
                        "치수_측정분": _positive_mean(dim),
                        "홀_측정분": _positive_mean(hole),
                        "비고": note,
                    }
                )
            out = _finish_measure(pd.DataFrame(rows))
            if not out.empty:
                return out

    # 구형 가로형(치수_측정분/홀_측정분)만 있을 때
    work = _rename_by_alias(
        _clean_frame(df),
        {
            "제품코드": ("제품코드", "코드구분", "품번", "품목코드", "item", "code"),
            "제품명": ("제품명", "품명", "itemname", "name"),
            "제품군": ("제품군", "제품유형", "품종", "family", "type"),
            "치수_측정분": (
                "치수_측정분",
                "치수측정분",
                "치수_매당분",
                "치수매당분",
                "치수측정시간",
                "치수_측정시간",
                "매당_치수분",
            ),
            "홀_측정분": (
                "홀_측정분",
                "홀측정분",
                "Hole_매당분",
                "홀_매당분",
                "홀매당분",
                "홀측정시간",
                "Hole측정시간",
                "매당_홀분",
            ),
            "비고": ("비고", "메모", "remark", "note"),
        },
    )
    if "제품코드" not in work.columns or not _has_wide_time_columns(df):
        return empty
    return _finish_measure(work)


def _declared_months(plan: pd.DataFrame) -> pd.DataFrame:
    """가로형 생산계획에 적힌 월. 수량이 0이어도 차트 축에 남긴다."""
    cols = ["년도", "월", "월라벨"]
    empty = pd.DataFrame(columns=cols)
    if plan is None or plan.empty:
        return empty
    rows: list[dict[str, Any]] = []
    for col in plan.columns:
        parsed = _parse_month_header(_norm(col))
        if not parsed:
            continue
        year, month = parsed
        rows.append(
            {
                "년도": year or "",
                "월": int(month),
                "월라벨": _month_label(year or "", int(month)),
            }
        )
    if not rows:
        return empty
    return pd.DataFrame(rows).drop_duplicates().sort_values(["년도", "월"]).reset_index(drop=True)


def calc_qa_capa(
    plan: pd.DataFrame,
    times: pd.DataFrame,
    *,
    work_days: float = 20,
    day_hours: float = 24.0,
    utilization_pct: float = 100.0,
    owned_dim: float = 0,
    owned_hole: float = 0,
) -> dict[str, Any]:
    """월별 치수·홀 필요대수와 가동율."""
    qty = normalize_qty(plan) if plan is not None else pd.DataFrame()
    meas = normalize_measure_times(times)
    avail = machine_month_minutes(
        work_days=work_days,
        day_hours=day_hours,
        utilization_pct=utilization_pct,
    )
    empty_monthly = pd.DataFrame(
        columns=[
            "년도",
            "월",
            "월라벨",
            "치수_생산수량",
            "치수_필요시간_분",
            "치수_이론필요대수",
            "치수_필요대수",
            "치수_가동율",
            "홀_생산수량",
            "홀_필요시간_분",
            "홀_이론필요대수",
            "홀_필요대수",
            "홀_가동율",
        ]
    )
    result: dict[str, Any] = {
        "qty": qty,
        "times": meas,
        "detail": pd.DataFrame(),
        "monthly": empty_monthly,
        "unmatched": [],
        "unused_times": [],
        "hole_skipped": [],
        "plan_columns": list(plan.columns) if plan is not None else [],
        "time_columns": list(times.columns) if times is not None else [],
        "work_days": float(work_days),
        "day_hours": float(day_hours),
        "utilization_pct": float(utilization_pct),
        "machine_month_min": avail,
        "owned_dim": float(owned_dim or 0),
        "owned_hole": float(owned_hole or 0),
        "peak_dim_label": "",
        "peak_hole_label": "",
        "peak_dim_required": 0,
        "peak_hole_required": 0,
    }
    if qty.empty or meas.empty or avail <= 0:
        return result

    meas = meas.copy()
    meas["제품코드"] = meas["제품코드"].map(_code_key)
    time_codes = set(meas["제품코드"])
    qty_codes = set(qty["제품코드"].map(_code_key))
    result["unmatched"] = sorted(qty_codes - time_codes)
    result["unused_times"] = sorted(time_codes - qty_codes)

    merged = qty.merge(
        meas[["제품코드", "제품명", "제품군", "치수_측정분", "홀_측정분"]],
        on="제품코드",
        how="inner",
        suffixes=("", "_기준"),
    )
    if merged.empty:
        return result
    if "제품명_기준" in merged.columns:
        merged["제품명"] = merged["제품명"].where(merged["제품명"].astype(str).str.strip() != "", merged["제품명_기준"])
        merged = merged.drop(columns=["제품명_기준"])

    merged["치수_필요시간_분"] = merged["필요수량"] * merged["치수_측정분"]
    is_cel = merged["제품군"] == "CEL"
    merged["홀_적용"] = is_cel & (merged["홀_측정분"] > 0)
    merged["홀_필요시간_분"] = 0.0
    merged.loc[merged["홀_적용"], "홀_필요시간_분"] = (
        merged.loc[merged["홀_적용"], "필요수량"] * merged.loc[merged["홀_적용"], "홀_측정분"]
    )
    skipped = sorted(
        {
            c
            for c, fam, hole_t in zip(merged["제품코드"], merged["제품군"], merged["홀_측정분"])
            if fam != "CEL" and float(hole_t or 0) > 0
        }
    )
    result["hole_skipped"] = skipped
    result["detail"] = merged.sort_values(["년도", "월", "제품코드"]).reset_index(drop=True)

    def _util(minutes: float, owned: float) -> float | None:
        if owned <= 0 or avail <= 0:
            return None
        return round(float(minutes) / (owned * avail) * 100, 1)

    rows: list[dict[str, Any]] = []
    for (year, month, label), sub in result["detail"].groupby(["년도", "월", "월라벨"], sort=False):
        dim_min = float(sub["치수_필요시간_분"].sum())
        hole_min = float(sub["홀_필요시간_분"].sum())
        dim_qty = float(sub.loc[sub["치수_측정분"] > 0, "필요수량"].sum())
        hole_qty = float(sub.loc[sub["홀_적용"], "필요수량"].sum())
        dim_theo = dim_min / avail
        hole_theo = hole_min / avail
        rows.append(
            {
                "년도": year,
                "월": int(month),
                "월라벨": label,
                "치수_생산수량": dim_qty,
                "치수_필요시간_분": round(dim_min, 1),
                "치수_이론필요대수": round(dim_theo, 4),
                "치수_필요대수": _ceil_machines(dim_theo),
                "치수_가동율": _util(dim_min, float(owned_dim or 0)),
                "홀_생산수량": hole_qty,
                "홀_필요시간_분": round(hole_min, 1),
                "홀_이론필요대수": round(hole_theo, 4),
                "홀_필요대수": _ceil_machines(hole_theo),
                "홀_가동율": _util(hole_min, float(owned_hole or 0)),
            }
        )
    monthly = pd.DataFrame(rows)
    if monthly.empty:
        return result
    declared = _declared_months(plan)
    if not declared.empty:
        monthly = declared.merge(monthly, on=["년도", "월", "월라벨"], how="left")
        for col in (
            "치수_생산수량",
            "치수_필요시간_분",
            "치수_이론필요대수",
            "치수_필요대수",
            "홀_생산수량",
            "홀_필요시간_분",
            "홀_이론필요대수",
            "홀_필요대수",
        ):
            monthly[col] = monthly[col].fillna(0)
        if float(owned_dim or 0) > 0:
            monthly["치수_가동율"] = monthly["치수_가동율"].fillna(0)
        if float(owned_hole or 0) > 0:
            monthly["홀_가동율"] = monthly["홀_가동율"].fillna(0)
        monthly["치수_필요대수"] = monthly["치수_필요대수"].astype(int)
        monthly["홀_필요대수"] = monthly["홀_필요대수"].astype(int)
    monthly = monthly.sort_values(["년도", "월"]).reset_index(drop=True)
    result["monthly"] = monthly
    dim_idx = monthly["치수_이론필요대수"].idxmax()
    hole_idx = monthly["홀_이론필요대수"].idxmax()
    result["peak_dim_label"] = str(monthly.loc[dim_idx, "월라벨"])
    result["peak_hole_label"] = str(monthly.loc[hole_idx, "월라벨"])
    result["peak_dim_required"] = int(monthly["치수_필요대수"].max())
    result["peak_hole_required"] = int(monthly["홀_필요대수"].max())
    return result
