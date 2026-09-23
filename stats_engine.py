"""설비·제품 기준정보와 1440분 운영 시뮬레이션."""
from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

from stats_engine import AREAS

DAY_MINUTES = 1440
# 3조 2교대: 기준정보의 인원은 전 조 합계 → 하루 근무인원 = 총인원 × (근무조/총조)
DEFAULT_SHIFT_TEAMS = 3
DEFAULT_WORKING_TEAMS = 2
# 1인 1교대 권장 가용분 (12시간 기준). 설비 24시간 가동과는 별개.
DEFAULT_SHIFT_MINUTES = 720
MASTER_STEMS = ("설비_기준정보", "인력_기준정보", "제품_기준정보", "제품별_실적")
MASTER_GH_FOLDERS = ("templates", "data/master", "data")

EQUIP_COLUMNS = ("캠퍼스", "공정", "설비코드", "설비명", "대수", "가동여부", "비고")
MANPOWER_COLUMNS = ("캠퍼스", "공정", "인원", "가용분", "가동여부", "비고")
PRODUCT_COLUMNS = (
    "제품코드",
    "제품명",
    "제품군",
    "공정",
    "제약유형",
    "설비코드",
    "매당_설비분",
    "매당_인시분",
    "필요인원",
    "비고",
)
PRODUCT_ACTUAL_COLUMNS = ("일자", "캠퍼스", "조", "주야", "제품코드", "공정", "인력", "실적")
DEFAULT_MONTHLY_TARGETS = (("CEL", 700.0), ("Ring", 15000.0), ("Wafer", 3000.0))
PLAN_PRODUCT_FAMILIES = tuple(k for k, _ in DEFAULT_MONTHLY_TARGETS)
DEFAULT_WORK_DAYS = 20
MONTHLY_PLAN_COLUMNS = ("제품코드", "월목표매수")

_YES = {"y", "yes", "1", "true", "가동", "사용", "o", "ㅇ", "예"}


def _norm(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


_BLANK_CODES = {
    "",
    "-",
    "--",
    "—",
    "–",
    ".",
    "/",
    "x",
    "없음",
    "무",
    "n/a",
    "na",
    "none",
    "null",
}


def _code_or_blank(v: Any) -> str:
    """설비코드 '-', 없음 등은 빈 값으로 취급."""
    t = _norm(v)
    if t.lower().replace(" ", "") in _BLANK_CODES:
        return ""
    return t


def effective_daily_headcount(
    total_people: float,
    *,
    shift_teams: int = DEFAULT_SHIFT_TEAMS,
    working_teams: int = DEFAULT_WORKING_TEAMS,
) -> float:
    """총인원(전 조 합) → 하루 실제 근무 가능 인원.

    3조 2교대: 하루 2개조 근무·1개조 휴무 → 총인원 × 2/3.
    """
    people = float(total_people or 0)
    teams = int(shift_teams or 0)
    working = int(working_teams or 0)
    if people <= 0:
        return 0.0
    if teams <= 0 or working <= 0:
        return people
    if working >= teams:
        return people
    return people * working / teams


def headcount_factor(
    *,
    shift_teams: int = DEFAULT_SHIFT_TEAMS,
    working_teams: int = DEFAULT_WORKING_TEAMS,
) -> float:
    teams = int(shift_teams or 0)
    working = int(working_teams or 0)
    if teams <= 0 or working <= 0:
        return 1.0
    if working >= teams:
        return 1.0
    return working / teams


def _is_running(v: Any) -> bool:
    t = _norm(v).lower().replace(" ", "")
    if not t:
        return True
    return t in _YES


def _num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
            return default
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def equipment_template() -> pd.DataFrame:
    """설비 공정만 예시. 외관처럼 사람만 하는 공정은 인력_기준정보에 넣습니다."""
    rows = []
    samples = [
        ("천안", "종합측정실", "CMM-01", "3차원측정기", 1),
        ("천안", "치수", "DIM-01", "2.5D 치수기", 2),
        ("천안", "Hole", "HOLE-01", "홀검사기", 1),
        ("아산", "종합측정실", "CMM-A1", "3차원측정기", 1),
        ("아산", "치수", "DIM-A1", "2.5D 치수기", 1),
        ("아산", "Hole", "HOLE-A1", "홀검사기", 1),
    ]
    for campus, area, code, name, qty in samples:
        rows.append(
            {
                "캠퍼스": campus,
                "공정": area,
                "설비코드": code,
                "설비명": name,
                "대수": qty,
                "가동여부": "Y",
                "비고": "",
            }
        )
    return pd.DataFrame(rows, columns=list(EQUIP_COLUMNS))


def manpower_template() -> pd.DataFrame:
    """인력 기준 — 전 공정. 인원=3개조 합계, 계산 시 ×(2/3), 가용분=1인 1교대 분."""
    rows = []
    samples = {
        "천안": {"종합측정실": 3, "치수": 6, "Hole": 4, "외관": 4},
        "아산": {"종합측정실": 2, "치수": 3, "Hole": 2, "외관": 2},
    }
    for campus, areas in samples.items():
        for area, people in areas.items():
            rows.append(
                {
                    "캠퍼스": campus,
                    "공정": area,
                    "인원": people,
                    "가용분": DEFAULT_SHIFT_MINUTES,
                    "가동여부": "Y",
                    "비고": "인원=전조합계 (3조2교대 → 근무인원 ×2/3)",
                }
            )
    return pd.DataFrame(rows, columns=list(MANPOWER_COLUMNS))


def product_template() -> pd.DataFrame:
    specs = [
        ("P-CEL", "CEL", "CEL", {"종합측정실": 4.0, "치수": 0.9, "Hole": 2.4, "외관": 1.6}),
        ("P-RING", "Ring", "Ring", {"종합측정실": 5.2, "치수": 1.1, "Hole": 3.0, "외관": 1.8}),
        ("P-WAFER", "Wafer", "Wafer", {"종합측정실": 3.5, "치수": 0.7, "Hole": 2.0, "외관": 1.3}),
    ]
    equip = {
        "종합측정실": ("설비", "CMM-01"),
        "치수": ("설비", "DIM-01"),
        "Hole": ("설비", "HOLE-01"),
        "외관": ("인력", ""),
    }
    rows = []
    for code, name, family, times in specs:
        for area in AREAS:
            t = times[area]
            kind, eq = equip[area]
            rows.append(
                {
                    "제품코드": code,
                    "제품명": name,
                    "제품군": family,
                    "공정": area,
                    "제약유형": kind,
                    "설비코드": eq,
                    "매당_설비분": t if kind == "설비" else 0,
                    "매당_인시분": t,
                    "필요인원": 1,
                    "비고": "예시 - 자사 택트로 수정" if kind == "설비" else "외관: 인력 기준",
                }
            )
    return pd.DataFrame(rows, columns=list(PRODUCT_COLUMNS))


def product_actual_template() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "일자": "2026-04-01",
                "캠퍼스": "천안",
                "조": "A",
                "주야": "주",
                "제품코드": "P-A",
                "공정": "치수",
                "인력": 2,
                "실적": 625,
            }
        ],
        columns=list(PRODUCT_ACTUAL_COLUMNS),
    )


def csv_bytes(df: pd.DataFrame) -> bytes:
    """엑셀이 한글을 읽도록 UTF-8 BOM을 붙인다."""
    return df.to_csv(index=False).encode("utf-8-sig")


def empty_csv_bytes(columns: tuple[str, ...]) -> bytes:
    return pd.DataFrame(columns=list(columns)).to_csv(index=False).encode("utf-8-sig")


def xlsx_bytes(df: pd.DataFrame, sheet: str = "기준정보") -> bytes:
    """엑셀에서 한글이 깨지지 않는 양식."""
    from io import BytesIO

    buf = BytesIO()
    work = df.copy()
    if work.empty and list(work.columns):
        work = pd.DataFrame(columns=list(work.columns))
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        work.to_excel(writer, index=False, sheet_name=sheet[:31] or "기준정보")
    return buf.getvalue()


def empty_xlsx_bytes(columns: tuple[str, ...], sheet: str = "기준정보") -> bytes:
    return xlsx_bytes(pd.DataFrame(columns=list(columns)), sheet=sheet)


def _rename_by_alias(df: pd.DataFrame, aliases: dict[str, tuple[str, ...]]) -> pd.DataFrame:
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for col in df.columns:
        key = str(col).strip().replace(" ", "").replace("_", "").lower()
        for dest, opts in aliases.items():
            if dest in used:
                continue
            for opt in opts:
                if key == opt.replace(" ", "").replace("_", "").lower():
                    mapping[col] = dest
                    used.add(dest)
                    break
    return df.rename(columns=mapping)


def normalize_equipment(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=list(EQUIP_COLUMNS) + ["가동"])
    work = _rename_by_alias(
        df.dropna(how="all").copy(),
        {
            "캠퍼스": ("캠퍼스", "campus", "공장"),
            "공정": ("공정", "영역", "공정명"),
            "설비코드": ("설비코드", "설비id", "코드"),
            "설비명": ("설비명", "설비이름", "설비"),
            "대수": ("대수", "수량", "보유대수"),
            "가동여부": ("가동여부", "상태", "사용"),
            "비고": ("비고", "메모"),
        },
    )
    for c in EQUIP_COLUMNS:
        if c not in work.columns:
            work[c] = "" if c != "대수" else 0
    work["캠퍼스"] = work["캠퍼스"].map(_norm)
    work["공정"] = work["공정"].map(_norm)
    work["설비코드"] = work["설비코드"].map(_norm)
    work["설비명"] = work["설비명"].map(_norm)
    work["대수"] = work["대수"].map(lambda v: _num(v, 0))
    work["가동"] = work["가동여부"].map(_is_running)
    work = work[work["공정"] != ""]
    work = work[work["대수"] > 0]
    return work.reset_index(drop=True)


def normalize_manpower(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=list(MANPOWER_COLUMNS) + ["가동"])
    work = _rename_by_alias(
        df.dropna(how="all").copy(),
        {
            "캠퍼스": ("캠퍼스", "campus", "공장"),
            "공정": ("공정", "영역", "공정명"),
            "인원": ("인원", "인력", "보유인원", "명수"),
            "가용분": ("가용분", "분", "가용시간분", "근무분"),
            "가동여부": ("가동여부", "상태", "사용"),
            "비고": ("비고", "메모"),
        },
    )
    for c in MANPOWER_COLUMNS:
        if c not in work.columns:
            work[c] = DEFAULT_SHIFT_MINUTES if c == "가용분" else ("" if c not in ("인원",) else 0)
    work["캠퍼스"] = work["캠퍼스"].map(_norm)
    work["공정"] = work["공정"].map(_norm)
    work["인원"] = work["인원"].map(lambda v: _num(v, 0))
    work["가용분"] = work["가용분"].map(lambda v: _num(v, DEFAULT_SHIFT_MINUTES) or DEFAULT_SHIFT_MINUTES)
    work["가동"] = work["가동여부"].map(_is_running)
    work = work[(work["공정"] != "") & (work["인원"] > 0)]
    return work.reset_index(drop=True)


def _infer_product_family(name: Any) -> str:
    """제품명/제품군에서 CEL·Ring·Wafer 등을 정규화."""
    t = _norm(name)
    if not t:
        return ""
    u = t.upper().replace(" ", "")
    if "WAFER" in u or "웨이퍼" in t:
        return "Wafer"
    if "RING" in u or "링" == t:
        return "Ring"
    if "CEL" in u:
        return "CEL"
    return t


def normalize_products(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=list(PRODUCT_COLUMNS))
    work = _rename_by_alias(
        df.dropna(how="all").copy(),
        {
            "제품코드": ("제품코드", "품번", "item"),
            "제품명": ("제품명", "품명"),
            "제품군": ("제품군", "제품유형", "품종", "family", "type"),
            "공정": ("공정", "영역"),
            "제약유형": ("제약유형", "유형", "기준유형", "타입"),
            "설비코드": ("설비코드", "설비id"),
            "매당_설비분": ("매당설비분", "설비택트", "ct", "분매", "cycle"),
            "매당_인시분": ("매당인시분", "인시택트", "공수", "인당분"),
            "필요인원": ("필요인원", "인원"),
            "비고": ("비고", "메모"),
        },
    )
    for c in PRODUCT_COLUMNS:
        if c not in work.columns:
            work[c] = "" if c not in ("매당_설비분", "매당_인시분", "필요인원") else 0
    work["제품코드"] = work["제품코드"].map(_norm)
    work["제품명"] = work["제품명"].map(_norm)
    work["제품군"] = work["제품군"].map(_norm)
    work.loc[work["제품군"] == "", "제품군"] = work["제품명"]
    work["제품군"] = work["제품군"].map(_infer_product_family)
    work["공정"] = work["공정"].map(_norm)
    work["설비코드"] = work["설비코드"].map(_code_or_blank)
    work["제약유형"] = work["제약유형"].map(_norm)
    work["매당_설비분"] = work["매당_설비분"].map(lambda v: _num(v, 0))
    work["매당_인시분"] = work["매당_인시분"].map(lambda v: _num(v, 0))
    work["필요인원"] = work["필요인원"].map(lambda v: _num(v, 1) or 1)
    work.loc[work["매당_인시분"] <= 0, "매당_인시분"] = work["매당_설비분"]
    # 제약유형 비어 있으면 자동 판별
    # (외관처럼 설비코드='-'·설비분 공란·인시분만 있는 행은 인력)
    empty_kind = work["제약유형"] == ""
    man_like = (work["매당_설비분"] <= 0) & (work["매당_인시분"] > 0)
    eq_like = (work["매당_설비분"] > 0) | (work["설비코드"] != "")
    work.loc[empty_kind & work["공정"].str.contains("외관", na=False), "제약유형"] = "인력"
    work.loc[empty_kind & (work["제약유형"] == "") & man_like, "제약유형"] = "인력"
    work.loc[empty_kind & (work["제약유형"] == "") & eq_like, "제약유형"] = "설비"
    work.loc[empty_kind & (work["제약유형"] == ""), "제약유형"] = "인력"
    work["제약유형"] = work["제약유형"].map(
        lambda x: "인력" if ("인력" in str(x) or "사람" in str(x) or "수작업" in str(x)) else "설비"
    )
    # 설비 공정은 설비분, 인력 공정은 인시분 필수
    ok_eq = (work["제약유형"] == "설비") & (work["매당_설비분"] > 0)
    ok_man = (work["제약유형"] == "인력") & (work["매당_인시분"] > 0)
    work = work[(work["제품코드"] != "") & (work["공정"] != "") & (ok_eq | ok_man)]
    return work.reset_index(drop=True)


def _equip_slice(
    equip: pd.DataFrame,
    *,
    campus: str | None,
    area: str,
    equip_code: str = "",
) -> pd.DataFrame:
    if equip is None or equip.empty:
        return pd.DataFrame()
    work = equip[equip["가동"]].copy()
    if campus:
        work = work[(work["캠퍼스"] == campus) | (work["캠퍼스"] == "")]
    work = work[work["공정"] == area]
    if equip_code:
        hit = work[work["설비코드"] == equip_code]
        if not hit.empty:
            return hit
    return work


def running_qty(equip: pd.DataFrame, *, campus: str | None, area: str, equip_code: str = "") -> float:
    """가동 대수. 설비코드가 있으면 우선 매칭, 없으면(또는 미스) 해당 공정 전체 합."""
    work = _equip_slice(equip, campus=campus, area=area, equip_code=equip_code)
    if work.empty:
        return 0.0
    # 코드 지정인데 매칭 실패 시 _equip_slice가 공정 전체로 떨어진 경우도 합산
    if equip_code:
        exact = work[work["설비코드"] == equip_code]
        if not exact.empty:
            work = exact
    return float(work["대수"].sum()) if not work.empty else 0.0


def running_manpower(
    manpower: pd.DataFrame,
    *,
    campus: str | None,
    area: str,
) -> tuple[float, float]:
    """(인원 합, 인원가중 평균 가용분). 인력_기준정보 기준 — 전 공정 공통."""
    if manpower is None or manpower.empty:
        return 0.0, float(DEFAULT_SHIFT_MINUTES)
    work = manpower[manpower["가동"]].copy()
    if campus:
        work = work[(work["캠퍼스"] == campus) | (work["캠퍼스"] == "")]
    work = work[work["공정"] == area]
    if work.empty:
        return 0.0, float(DEFAULT_SHIFT_MINUTES)
    people = float(work["인원"].sum())
    avail = float((work["인원"] * work["가용분"]).sum() / people) if people else float(DEFAULT_SHIFT_MINUTES)
    return people, avail


def _spec_tact(specs: pd.DataFrame, equip_code: str) -> tuple[float, float]:
    """제품 기준에서 설비코드 택트. 없으면 공정 평균."""
    if specs is None or specs.empty:
        return 0.0, 0.0
    code = _norm(equip_code)
    if code:
        hit = specs[specs["설비코드"].map(_norm) == code]
        if not hit.empty:
            r = hit.iloc[0]
            eq_t = float(r["매당_설비분"] or 0)
            man_t = float(r["매당_인시분"] or 0) or eq_t
            return eq_t, man_t
    eq_t = float(pd.to_numeric(specs["매당_설비분"], errors="coerce").replace(0, pd.NA).mean() or 0)
    man_t = float(pd.to_numeric(specs["매당_인시분"], errors="coerce").replace(0, pd.NA).mean() or 0) or eq_t
    if eq_t <= 0:
        eq_t = man_t
    return eq_t, man_t


def daily_capacity(
    products: pd.DataFrame,
    equip: pd.DataFrame,
    *,
    campus: str | None = None,
    day_minutes: float = DAY_MINUTES,
    manpower: pd.DataFrame | None = None,
    shift_teams: int = DEFAULT_SHIFT_TEAMS,
    working_teams: int = DEFAULT_WORKING_TEAMS,
) -> pd.DataFrame:
    """제품×공정 일 능력.

    - 총인원/근무인원: 인력_기준정보의 **캠퍼스+공정** 단위 (설비코드별 배분 없음)
      같은 공정의 설비 여러 대여도 인원은 공정 공유 → 표에서는 첫 설비 행에만 표시
    - 설비: 설비_기준정보의 해당 공정 가동 설비를 캠퍼스별로 펼침 (일가능매수는 설비별)
    - 인력 공정: 근무인원 × 가용분 ÷ 매당_인시분
    """
    if products.empty:
        return pd.DataFrame()
    man = manpower if manpower is not None else pd.DataFrame()
    eq = equip if equip is not None else pd.DataFrame()
    factor = headcount_factor(shift_teams=shift_teams, working_teams=working_teams)
    rows: list[dict[str, Any]] = []

    for code in products["제품코드"].map(_norm).unique():
        if not code:
            continue
        psub = products[products["제품코드"].map(_norm) == code]
        pname = _norm(psub["제품명"].iloc[0]) if "제품명" in psub.columns else code
        for area in psub["공정"].map(_norm).unique():
            if not area:
                continue
            specs = psub[psub["공정"].map(_norm) == area]
            kind0 = _norm(specs["제약유형"].iloc[0]) if "제약유형" in specs.columns else "설비"
            eq_work = _equip_slice(eq, campus=campus, area=area, equip_code="")
            man_probe, _ = running_manpower(man, campus=campus, area=area)
            use_man = kind0 == "인력" or (eq_work.empty and man_probe > 0)

            if use_man:
                _, man_tact = _spec_tact(specs, "")
                if man_tact <= 0:
                    man_tact = float(specs["매당_인시분"].iloc[0] or 0)
                # 캠퍼스별 인력 행으로 펼침 (Total일 때 합산 한 줄로 뭉개지 않음)
                if campus:
                    man_campuses: list[str | None] = [campus]
                elif not man.empty and "캠퍼스" in man.columns:
                    hit = man[man["가동"] & (man["공정"].map(_norm) == area)] if "가동" in man.columns else man[man["공정"].map(_norm) == area]
                    man_campuses = sorted({_norm(c) for c in hit["캠퍼스"].tolist() if _norm(c)})
                    if not man_campuses:
                        man_campuses = [None]
                else:
                    man_campuses = [None]
                for mc in man_campuses:
                    man_total, man_avail = running_manpower(man, campus=mc, area=area)
                    man_qty = effective_daily_headcount(
                        man_total, shift_teams=shift_teams, working_teams=working_teams
                    )
                    if man_qty <= 0 and man_total <= 0:
                        continue
                    minutes = man_avail if man_avail else DEFAULT_SHIFT_MINUTES
                    sheets = round(man_qty * minutes / man_tact, 1) if man_tact > 0 else 0.0
                    rows.append(
                        {
                            "제품코드": code,
                            "제품명": pname,
                            "공정": area,
                            "캠퍼스": mc or "합산",
                            "제약유형": "인력",
                            "설비코드": "",
                            "가동대수": 0.0,
                            "총인원": round(man_total, 1),
                            "근무인원": round(man_qty, 1),
                            "조보정": round(factor, 4),
                            "가용분": round(minutes, 1),
                            "매당_설비분": float(specs["매당_설비분"].iloc[0] or 0),
                            "매당_인시분": man_tact,
                            "필요인원": round(man_qty, 1),
                            "일가능매수": sheets,
                        }
                    )
                continue

            default_eq, default_man = _spec_tact(specs, "")
            # 공정 인력은 설비와 무관하게 1회만 조회
            seen_man_keys: set[tuple[str, str]] = set()
            for _, eqr in eq_work.iterrows():
                eq_code = _norm(eqr.get("설비코드"))
                eq_tact, man_tact = _spec_tact(specs, eq_code)
                if eq_tact <= 0:
                    eq_tact = default_eq
                if man_tact <= 0:
                    man_tact = default_man or eq_tact
                qty = float(eqr.get("대수") or 0)
                row_campus = _norm(eqr.get("캠퍼스")) or campus
                man_key = (row_campus or "", area)
                show_man = man_key not in seen_man_keys
                if show_man:
                    seen_man_keys.add(man_key)
                    man_total, _man_avail = running_manpower(
                        man, campus=row_campus if row_campus else None, area=area
                    )
                    man_qty = effective_daily_headcount(
                        man_total, shift_teams=shift_teams, working_teams=working_teams
                    )
                else:
                    man_total, man_qty = float("nan"), float("nan")
                sheets = round(qty * day_minutes / eq_tact, 1) if eq_tact > 0 else 0.0
                need = round(qty * float(specs["필요인원"].iloc[0] or 1), 1)
                rows.append(
                    {
                        "제품코드": code,
                        "제품명": pname,
                        "공정": area,
                        "캠퍼스": row_campus or (campus or ""),
                        "제약유형": "설비",
                        "설비코드": eq_code,
                        "가동대수": qty,
                        "총인원": round(man_total, 1) if show_man else pd.NA,
                        "근무인원": round(man_qty, 1) if show_man else pd.NA,
                        "조보정": round(factor, 4) if show_man else pd.NA,
                        "가용분": round(day_minutes, 1),
                        "매당_설비분": eq_tact,
                        "매당_인시분": man_tact,
                        "필요인원": need,
                        "일가능매수": sheets,
                    }
                )

    out = pd.DataFrame(rows)
    return out


def mix_simulation(
    products: pd.DataFrame,
    equip: pd.DataFrame,
    mix: pd.DataFrame,
    *,
    campus: str | None = None,
    day_minutes: float = DAY_MINUTES,
    manpower: pd.DataFrame | None = None,
    shift_teams: int = DEFAULT_SHIFT_TEAMS,
    working_teams: int = DEFAULT_WORKING_TEAMS,
) -> pd.DataFrame:
    """제품 비중으로 설비·인력 가용분을 나눠 일 가능 매수를 계산."""
    if products.empty or mix is None or mix.empty:
        return pd.DataFrame()
    work = mix.copy()
    if "제품코드" not in work.columns or "비중" not in work.columns:
        return pd.DataFrame()
    man = manpower if manpower is not None else pd.DataFrame()
    work["비중"] = pd.to_numeric(work["비중"], errors="coerce").fillna(0)
    total = float(work["비중"].sum())
    if total <= 0:
        return pd.DataFrame()
    work["비중"] = work["비중"] / total
    rows = []
    for area in AREAS:
        eq_qty = running_qty(equip, campus=campus, area=area, equip_code="")
        man_total, man_avail = running_manpower(man, campus=campus, area=area)
        man_qty = effective_daily_headcount(
            man_total, shift_teams=shift_teams, working_teams=working_teams
        )
        for _, m in work.iterrows():
            code = _norm(m["제품코드"])
            spec = products[(products["제품코드"] == code) & (products["공정"] == area)]
            if spec.empty:
                continue
            row = spec.iloc[0]
            kind = str(row.get("제약유형") or "설비")
            eq_tact = float(row["매당_설비분"])
            man_tact = float(row["매당_인시분"]) or eq_tact
            use_man = kind == "인력" or (eq_qty <= 0 and man_qty > 0 and man_tact > 0)
            if use_man:
                minutes_total = man_qty * (man_avail or day_minutes)
                tact = man_tact
                mode = "인력"
                resource = man_qty
            else:
                minutes_total = eq_qty * day_minutes
                tact = eq_tact if eq_tact > 0 else man_tact
                mode = "설비"
                resource = eq_qty
            mins = minutes_total * float(m["비중"])
            sheets = round(mins / tact, 1) if tact > 0 else 0.0
            rows.append(
                {
                    "제품코드": code,
                    "제품명": row["제품명"],
                    "공정": area,
                    "제약유형": mode,
                    "배분분": round(mins, 1),
                    "매당분": tact,
                    "일가능매수": sheets,
                    "자원수": resource,
                    "총인원": round(man_total, 1),
                    "근무인원": round(man_qty, 1),
                }
            )
    return pd.DataFrame(rows)


def default_monthly_targets(products: pd.DataFrame | None = None) -> pd.DataFrame:
    """월 목표 기본: CEL 700 / Ring 15000 / Wafer 3000."""
    rows = [{"제품군": k, "월목표매수": float(v)} for k, v in DEFAULT_MONTHLY_TARGETS]
    if products is not None and not products.empty:
        col = "제품군" if "제품군" in products.columns else "제품명"
        found = {_infer_product_family(x) for x in products[col].tolist()}
        for fam in sorted(found):
            if fam and fam not in {r["제품군"] for r in rows}:
                rows.append({"제품군": fam, "월목표매수": 0.0})
    return pd.DataFrame(rows)


def _family_process_spec(products: pd.DataFrame, family: str, area: str) -> dict[str, Any] | None:
    """제품군×공정의 대표 택트(평균)."""
    if products.empty:
        return None
    fam_col = "제품군" if "제품군" in products.columns else "제품명"
    fam_key = _infer_product_family(family)
    sub = products[
        (products[fam_col].map(_infer_product_family) == fam_key)
        & (products["공정"].map(_norm) == area)
    ]
    if sub.empty:
        return None
    kind = "인력" if (sub["제약유형"].map(_norm) == "인력").mean() >= 0.5 else "설비"
    eq_tact = float(pd.to_numeric(sub["매당_설비분"], errors="coerce").replace(0, pd.NA).mean() or 0)
    man_tact = float(pd.to_numeric(sub["매당_인시분"], errors="coerce").replace(0, pd.NA).mean() or 0)
    if man_tact <= 0:
        man_tact = eq_tact
    if eq_tact <= 0:
        eq_tact = man_tact
    return {
        "제품군": _norm(family),
        "공정": area,
        "제약유형": kind,
        "매당_설비분": eq_tact,
        "매당_인시분": man_tact,
        "품목수": int(sub["제품코드"].nunique()),
    }


def monthly_mix_feasibility(
    products: pd.DataFrame,
    equip: pd.DataFrame,
    targets: pd.DataFrame,
    *,
    campus: str | None = None,
    work_days: float = DEFAULT_WORK_DAYS,
    day_minutes: float = DAY_MINUTES,
    manpower: pd.DataFrame | None = None,
    shift_teams: int = DEFAULT_SHIFT_TEAMS,
    working_teams: int = DEFAULT_WORKING_TEAMS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """제품군 월 목표 믹스가 현재 설비·인력으로 가능한지 계산.

    반환: (공정별 상세, 제품군 요약)
    - 일목표 = 월목표 ÷ 작업일수
    - 필요분 = 일목표 × 택트 (제품군 평균)
    - 가용분을 필요분 비중으로 나눠 일가능매수 산출
    - 월가능매수 = 일가능매수 × 작업일수
    """
    empty_detail = pd.DataFrame()
    empty_sum = pd.DataFrame()
    if products.empty or targets is None or targets.empty:
        return empty_detail, empty_sum
    work = targets.copy()
    if "제품군" not in work.columns:
        return empty_detail, empty_sum
    qty_col = "월목표매수" if "월목표매수" in work.columns else ("목표" if "목표" in work.columns else "")
    if not qty_col:
        return empty_detail, empty_sum
    days = float(work_days or DEFAULT_WORK_DAYS) or DEFAULT_WORK_DAYS
    work["제품군"] = work["제품군"].map(_norm)
    work["월목표매수"] = pd.to_numeric(work[qty_col], errors="coerce").fillna(0)
    work = work[work["제품군"] != ""]
    work = work[work["월목표매수"] > 0]
    if work.empty:
        return empty_detail, empty_sum
    work["일목표매수"] = (work["월목표매수"] / days).round(2)
    man = manpower if manpower is not None else pd.DataFrame()

    detail_rows: list[dict[str, Any]] = []
    for area in AREAS:
        eq_qty = running_qty(equip, campus=campus, area=area, equip_code="")
        man_total, man_avail = running_manpower(man, campus=campus, area=area)
        man_qty = effective_daily_headcount(
            man_total, shift_teams=shift_teams, working_teams=working_teams
        )
        needs: list[dict[str, Any]] = []
        for _, t in work.iterrows():
            fam = str(t["제품군"])
            spec = _family_process_spec(products, fam, area)
            if spec is None:
                continue
            kind = spec["제약유형"]
            use_man = kind == "인력" or (eq_qty <= 0 and man_qty > 0 and spec["매당_인시분"] > 0)
            tact = float(spec["매당_인시분"] if use_man else spec["매당_설비분"]) or float(spec["매당_인시분"])
            if tact <= 0:
                continue
            daily = float(t["일목표매수"])
            need_min = daily * tact
            needs.append(
                {
                    "제품군": fam,
                    "공정": area,
                    "제약유형": "인력" if use_man else "설비",
                    "품목수": spec["품목수"],
                    "월목표매수": float(t["월목표매수"]),
                    "일목표매수": daily,
                    "매당분": round(tact, 4),
                    "필요분": round(need_min, 1),
                    "use_man": use_man,
                }
            )
        if not needs:
            continue
        use_man_area = all(n["use_man"] for n in needs)
        if use_man_area:
            avail = man_qty * (man_avail or day_minutes)
            resource = man_qty
            mode = "인력"
        else:
            # 설비 공정: 설비 시간 기준 (혼합이면 설비 우선)
            if any(not n["use_man"] for n in needs):
                avail = eq_qty * day_minutes
                resource = eq_qty
                mode = "설비"
                needs = [n for n in needs if not n["use_man"]] or needs
            else:
                avail = man_qty * (man_avail or day_minutes)
                resource = man_qty
                mode = "인력"
        need_sum = sum(n["필요분"] for n in needs) or 1.0
        proc_load = round(need_sum / avail * 100, 1) if avail > 0 else None
        for n in needs:
            share = n["필요분"] / need_sum
            alloc = avail * share
            daily_cap = round(alloc / n["매당분"], 1) if n["매당분"] > 0 else 0.0
            month_cap = round(daily_cap * days, 1)
            meet = month_cap + 1e-6 >= n["월목표매수"]
            detail_rows.append(
                {
                    "제품군": n["제품군"],
                    "공정": area,
                    "제약유형": "인력" if n["use_man"] else "설비",
                    "품목수": n["품목수"],
                    "월목표매수": n["월목표매수"],
                    "일목표매수": n["일목표매수"],
                    "매당분": n["매당분"],
                    "필요분": n["필요분"],
                    "가용분": round(avail, 1),
                    "배분분": round(alloc, 1),
                    "자원수": resource,
                    "공정부하율%": proc_load,
                    "일가능매수": daily_cap,
                    "월가능매수": month_cap,
                    "달성": "OK" if meet else "부족",
                }
            )

    detail = pd.DataFrame(detail_rows)
    if detail.empty:
        return detail, empty_sum

    # 전체 공정 합산 부하로 달성 재판정: 공정별로 필요합≤가용이면 그 공정 OK
    # 제품군 요약: 전 공정 월가능의 최소(병목)가 월 출하 가능량
    summary = (
        detail.groupby("제품군", as_index=False)
        .agg(
            월목표매수=("월목표매수", "first"),
            일목표매수=("일목표매수", "first"),
            품목수=("품목수", "max"),
            월가능매수=("월가능매수", "min"),
            일가능매수=("일가능매수", "min"),
            최대부하율=("공정부하율%", "max"),
        )
    )
    summary["월가능매수"] = summary["월가능매수"].round(1)
    summary["일가능매수"] = summary["일가능매수"].round(1)
    summary["달성"] = summary.apply(
        lambda r: "OK" if float(r["월가능매수"]) + 1e-6 >= float(r["월목표매수"]) else "부족",
        axis=1,
    )
    summary["부족매수"] = (summary["월목표매수"] - summary["월가능매수"]).clip(lower=0).round(1)
    # 병목 공정
    bn = (
        detail.sort_values("월가능매수")
        .groupby("제품군", as_index=False)
        .first()[["제품군", "공정"]]
        .rename(columns={"공정": "병목공정"})
    )
    summary = summary.merge(bn, on="제품군", how="left")
    return detail, summary


def monthly_plan_template(products: pd.DataFrame | None = None) -> pd.DataFrame:
    """월 생산계획 빈 양식 — 제품코드별 목표."""
    if products is None or products.empty or "제품코드" not in products.columns:
        return pd.DataFrame(columns=list(MONTHLY_PLAN_COLUMNS))
    codes = products[["제품코드"]].drop_duplicates()
    if "제품명" in products.columns:
        codes = products[["제품코드", "제품명"]].drop_duplicates("제품코드")
    rows = []
    for _, r in codes.iterrows():
        rows.append({"제품코드": _norm(r["제품코드"]), "월목표매수": 0.0})
    return pd.DataFrame(rows, columns=list(MONTHLY_PLAN_COLUMNS))


def normalize_monthly_plan(df: pd.DataFrame) -> pd.DataFrame:
    """업로드/편집 월 계획 — 제품코드 + 월목표매수."""
    if df is None or df.empty:
        return pd.DataFrame(columns=list(MONTHLY_PLAN_COLUMNS))
    work = _rename_by_alias(
        df.dropna(how="all").copy(),
        {
            "제품코드": ("제품코드", "품번", "item", "code"),
            "월목표매수": ("월목표매수", "월목표", "목표", "목표수량", "수량", "qty"),
        },
    )
    for c in MONTHLY_PLAN_COLUMNS:
        if c not in work.columns:
            work[c] = "" if c == "제품코드" else 0
    work["제품코드"] = work["제품코드"].map(_norm)
    work["월목표매수"] = pd.to_numeric(work["월목표매수"], errors="coerce").fillna(0)
    work = work[(work["제품코드"] != "") & (work["월목표매수"] > 0)]
    return work.drop_duplicates("제품코드", keep="last").reset_index(drop=True)


def monthly_plan_family_stats(
    plan: pd.DataFrame,
    products: pd.DataFrame,
) -> pd.DataFrame:
    """업로드 월 계획 — 합계·CEL·Ring·Wafer별 품목 수·월목표 합계."""
    empty = pd.DataFrame(columns=["구분", "계획품목수", "월목표합계"])
    work = normalize_monthly_plan(plan)
    if work.empty:
        return empty

    fam_map: dict[str, str] = {}
    if not products.empty and "제품코드" in products.columns:
        pc = products[["제품코드", "제품군"]].drop_duplicates("제품코드")
        fam_map = {
            _norm(c): _infer_product_family(g)
            for c, g in zip(pc["제품코드"], pc["제품군"])
            if _norm(c)
        }

    tagged = work.copy()
    tagged["제품군"] = tagged["제품코드"].map(
        lambda c: fam_map.get(_norm(c), _infer_product_family(c))
    )

    def _row(label: str, sub: pd.DataFrame) -> dict[str, Any]:
        return {
            "구분": label,
            "계획품목수": int(len(sub)),
            "월목표합계": float(sub["월목표매수"].sum()) if not sub.empty else 0.0,
        }

    rows = [_row("합계", tagged)]
    for fam in PLAN_PRODUCT_FAMILIES:
        rows.append(_row(fam, tagged[tagged["제품군"] == fam]))
    other = tagged[~tagged["제품군"].isin(PLAN_PRODUCT_FAMILIES)]
    if not other.empty:
        rows.append(_row("기타", other))
    return pd.DataFrame(rows)


def _tagged_monthly_plan(plan: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    """월 계획에 제품군을 붙인 표."""
    work = normalize_monthly_plan(plan)
    if work.empty:
        return work
    fam_map: dict[str, str] = {}
    if not products.empty and "제품코드" in products.columns and "제품군" in products.columns:
        pc = products[["제품코드", "제품군"]].drop_duplicates("제품코드")
        fam_map = {
            _norm(c): _infer_product_family(g)
            for c, g in zip(pc["제품코드"], pc["제품군"])
            if _norm(c)
        }
    out = work.copy()
    out["제품군"] = out["제품코드"].map(
        lambda c: fam_map.get(_norm(c), _infer_product_family(c))
    )
    return out


def _campus_resource_share(
    *,
    area: str,
    campus: str,
    equip: pd.DataFrame | None = None,
    manpower: pd.DataFrame | None = None,
    shift_teams: int = DEFAULT_SHIFT_TEAMS,
    working_teams: int = DEFAULT_WORKING_TEAMS,
) -> float:
    """캠퍼스가 해당 공정에서 차지하는 자원 비중 (0~1)."""
    eq = equip if equip is not None else pd.DataFrame()
    man = manpower if manpower is not None else pd.DataFrame()
    if area == "외관":
        total_h, _ = running_manpower(man, campus=None, area=area)
        camp_h, _ = running_manpower(man, campus=campus, area=area)
        total_n = effective_daily_headcount(
            total_h, shift_teams=shift_teams, working_teams=working_teams
        )
        camp_n = effective_daily_headcount(
            camp_h, shift_teams=shift_teams, working_teams=working_teams
        )
        if total_n <= 0:
            return 0.0
        return float(camp_n) / float(total_n)
    total_q = running_qty(eq, campus=None, area=area, equip_code="")
    camp_q = running_qty(eq, campus=campus, area=area, equip_code="")
    if total_q <= 0:
        # 설비 없으면 인력 비중으로
        total_h, _ = running_manpower(man, campus=None, area=area)
        camp_h, _ = running_manpower(man, campus=campus, area=area)
        total_n = effective_daily_headcount(
            total_h, shift_teams=shift_teams, working_teams=working_teams
        )
        camp_n = effective_daily_headcount(
            camp_h, shift_teams=shift_teams, working_teams=working_teams
        )
        if total_n <= 0:
            return 0.0
        return float(camp_n) / float(total_n)
    return float(camp_q) / float(total_q)


def monthly_plan_daily_avg(
    plan: pd.DataFrame,
    products: pd.DataFrame,
    *,
    work_days: float = DEFAULT_WORK_DAYS,
    campus: str | None = None,
    equip: pd.DataFrame | None = None,
    manpower: pd.DataFrame | None = None,
    shift_teams: int = DEFAULT_SHIFT_TEAMS,
    working_teams: int = DEFAULT_WORKING_TEAMS,
) -> dict[str, float]:
    """일평균 매수 — 치수 CEL/Ring/Wafer · Hole CEL · 외관.

    campus가 있으면 공정 자원 비중(설비/인력)으로 Total 일평균을 배분.
    """
    days = float(work_days or DEFAULT_WORK_DAYS) or DEFAULT_WORK_DAYS
    tagged = _tagged_monthly_plan(plan, products)
    zero = {
        "치수_CEL": 0.0,
        "치수_Ring": 0.0,
        "치수_Wafer": 0.0,
        "Hole_CEL": 0.0,
        "외관": 0.0,
    }
    if tagged.empty:
        return zero

    cel = float(tagged.loc[tagged["제품군"] == "CEL", "월목표매수"].sum())
    ring = float(tagged.loc[tagged["제품군"] == "Ring", "월목표매수"].sum())
    wafer = float(tagged.loc[tagged["제품군"] == "Wafer", "월목표매수"].sum())
    total = float(tagged["월목표매수"].sum())
    out = {
        "치수_CEL": round(cel / days, 1),
        "치수_Ring": round(ring / days, 1),
        "치수_Wafer": round(wafer / days, 1),
        "Hole_CEL": round(cel / days, 1),  # Hole은 CEL만
        "외관": round(total / days, 1),
    }
    if not campus:
        return out

    dim_share = _campus_resource_share(
        area="치수",
        campus=campus,
        equip=equip,
        manpower=manpower,
        shift_teams=shift_teams,
        working_teams=working_teams,
    )
    hole_share = _campus_resource_share(
        area="Hole",
        campus=campus,
        equip=equip,
        manpower=manpower,
        shift_teams=shift_teams,
        working_teams=working_teams,
    )
    app_share = _campus_resource_share(
        area="외관",
        campus=campus,
        equip=equip,
        manpower=manpower,
        shift_teams=shift_teams,
        working_teams=working_teams,
    )
    return {
        "치수_CEL": round(out["치수_CEL"] * dim_share, 1),
        "치수_Ring": round(out["치수_Ring"] * dim_share, 1),
        "치수_Wafer": round(out["치수_Wafer"] * dim_share, 1),
        "Hole_CEL": round(out["Hole_CEL"] * hole_share, 1),
        "외관": round(out["외관"] * app_share, 1),
    }


def _product_process_spec(products: pd.DataFrame, code: str, area: str) -> dict[str, Any] | None:
    """제품코드×공정 택트 (동일 공정 여러 설비코드면 평균)."""
    if products.empty:
        return None
    sub = products[
        (products["제품코드"].map(_norm) == _norm(code))
        & (products["공정"].map(_norm) == area)
    ]
    if sub.empty:
        return None
    kind = "인력" if (sub["제약유형"].map(_norm) == "인력").mean() >= 0.5 else "설비"
    eq_tact = float(pd.to_numeric(sub["매당_설비분"], errors="coerce").replace(0, pd.NA).mean() or 0)
    man_tact = float(pd.to_numeric(sub["매당_인시분"], errors="coerce").replace(0, pd.NA).mean() or 0)
    if man_tact <= 0:
        man_tact = eq_tact
    if eq_tact <= 0:
        eq_tact = man_tact
    pname = _norm(sub["제품명"].iloc[0]) if "제품명" in sub.columns else _norm(code)
    return {
        "제품코드": _norm(code),
        "제품명": pname,
        "공정": area,
        "제약유형": kind,
        "매당_설비분": eq_tact,
        "매당_인시분": man_tact,
    }


def _monthly_capacity_core(
    products: pd.DataFrame,
    equip: pd.DataFrame,
    work: pd.DataFrame,
    *,
    key_col: str,
    spec_fn,
    campus: str | None = None,
    work_days: float = DEFAULT_WORK_DAYS,
    day_minutes: float = DAY_MINUTES,
    manpower: pd.DataFrame | None = None,
    shift_teams: int = DEFAULT_SHIFT_TEAMS,
    working_teams: int = DEFAULT_WORKING_TEAMS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """공통: 월/일 목표 → 공정별 배분 → 달성."""
    empty = pd.DataFrame()
    if work.empty:
        return empty, empty
    days = float(work_days or DEFAULT_WORK_DAYS) or DEFAULT_WORK_DAYS
    man = manpower if manpower is not None else pd.DataFrame()
    detail_rows: list[dict[str, Any]] = []

    for area in AREAS:
        eq_qty = running_qty(equip, campus=campus, area=area, equip_code="")
        man_total, man_avail = running_manpower(man, campus=campus, area=area)
        man_qty = effective_daily_headcount(
            man_total, shift_teams=shift_teams, working_teams=working_teams
        )
        needs: list[dict[str, Any]] = []
        for _, t in work.iterrows():
            key = str(t[key_col])
            spec = spec_fn(products, key, area)
            if spec is None:
                continue
            kind = spec["제약유형"]
            use_man = kind == "인력" or (eq_qty <= 0 and man_qty > 0 and spec["매당_인시분"] > 0)
            tact = float(spec["매당_인시분"] if use_man else spec["매당_설비분"]) or float(spec["매당_인시분"])
            if tact <= 0:
                continue
            daily = float(t["일목표매수"])
            row: dict[str, Any] = {
                key_col: key,
                "공정": area,
                "제약유형": "인력" if use_man else "설비",
                "월목표매수": float(t["월목표매수"]),
                "일목표매수": daily,
                "매당분": round(tact, 4),
                "필요분": round(daily * tact, 1),
                "use_man": use_man,
            }
            if key_col == "제품코드":
                row["제품명"] = spec.get("제품명", key)
            elif "품목수" in spec:
                row["품목수"] = spec["품목수"]
            needs.append(row)
        if not needs:
            continue
        if all(n["use_man"] for n in needs):
            avail = man_qty * (man_avail or day_minutes)
            resource = man_qty
        else:
            if any(not n["use_man"] for n in needs):
                avail = eq_qty * day_minutes
                resource = eq_qty
                needs = [n for n in needs if not n["use_man"]] or needs
            else:
                avail = man_qty * (man_avail or day_minutes)
                resource = man_qty
        need_sum = sum(n["필요분"] for n in needs) or 1.0
        proc_load = round(need_sum / avail * 100, 1) if avail > 0 else None
        for n in needs:
            share = n["필요분"] / need_sum
            alloc = avail * share
            daily_cap = round(alloc / n["매당분"], 1) if n["매당분"] > 0 else 0.0
            month_cap = round(daily_cap * days, 1)
            meet = month_cap + 1e-6 >= n["월목표매수"]
            detail_rows.append(
                {
                    **{key_col: n[key_col]},
                    "제품명": n.get("제품명", ""),
                    "공정": area,
                    "제약유형": "인력" if n["use_man"] else "설비",
                    "품목수": n.get("품목수", 1),
                    "월목표매수": n["월목표매수"],
                    "일목표매수": n["일목표매수"],
                    "매당분": n["매당분"],
                    "필요분": n["필요분"],
                    "가용분": round(avail, 1),
                    "배분분": round(alloc, 1),
                    "시간배분%": round(share * 100, 1),
                    "자원수": resource,
                    "공정부하율%": proc_load,
                    "일가능매수": daily_cap,
                    "월가능매수": month_cap,
                    "달성": "OK" if meet else "부족",
                }
            )

    detail = pd.DataFrame(detail_rows)
    if detail.empty:
        return detail, empty

    agg_cols = {
        "월목표매수": ("월목표매수", "first"),
        "일목표매수": ("일목표매수", "first"),
        "월가능매수": ("월가능매수", "min"),
        "일가능매수": ("일가능매수", "min"),
        "최대부하율": ("공정부하율%", "max"),
    }
    if "제품명" in detail.columns:
        agg_cols["제품명"] = ("제품명", "first")
    if "품목수" in detail.columns:
        agg_cols["품목수"] = ("품목수", "max")

    summary = detail.groupby(key_col, as_index=False).agg(**agg_cols)
    summary["월가능매수"] = summary["월가능매수"].round(1)
    summary["일가능매수"] = summary["일가능매수"].round(1)
    summary["달성"] = summary.apply(
        lambda r: "OK" if float(r["월가능매수"]) + 1e-6 >= float(r["월목표매수"]) else "부족",
        axis=1,
    )
    summary["부족매수"] = (summary["월목표매수"] - summary["월가능매수"]).clip(lower=0).round(1)
    bn = (
        detail.sort_values("월가능매수")
        .groupby(key_col, as_index=False)
        .first()[[key_col, "공정"]]
        .rename(columns={"공정": "병목공정"})
    )
    summary = summary.merge(bn, on=key_col, how="left")
    return detail, summary


def monthly_plan_feasibility(
    products: pd.DataFrame,
    equip: pd.DataFrame,
    plan: pd.DataFrame,
    *,
    campus: str | None = None,
    work_days: float = DEFAULT_WORK_DAYS,
    day_minutes: float = DAY_MINUTES,
    manpower: pd.DataFrame | None = None,
    shift_teams: int = DEFAULT_SHIFT_TEAMS,
    working_teams: int = DEFAULT_WORKING_TEAMS,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """제품코드 월 목표 → 생산 계획 (공정별 상세 + 제품별 요약).

    반환: (공정별 상세, 제품 요약, 기준정보에 없는 제품코드 목록)
    """
    empty = pd.DataFrame()
    if products.empty:
        return empty, empty, []
    work = normalize_monthly_plan(plan)
    if work.empty:
        return empty, empty, []
    known = set(products["제품코드"].map(_norm).tolist())
    missing = sorted({c for c in work["제품코드"].tolist() if c not in known})
    work = work[~work["제품코드"].isin(missing)]
    if work.empty:
        return empty, empty, missing
    days = float(work_days or DEFAULT_WORK_DAYS) or DEFAULT_WORK_DAYS
    work["일목표매수"] = (work["월목표매수"] / days).round(2)
    detail, summary = _monthly_capacity_core(
        products,
        equip,
        work,
        key_col="제품코드",
        spec_fn=_product_process_spec,
        campus=campus,
        work_days=days,
        day_minutes=day_minutes,
        manpower=manpower,
        shift_teams=shift_teams,
        working_teams=working_teams,
    )
    return detail, summary, missing


def daily_operation_plan(detail: pd.DataFrame, summary: pd.DataFrame) -> pd.DataFrame:
    """하루 운영안 — 공정별 제품 시간 배분 + 권장 일 매수."""
    if detail is None or detail.empty:
        return pd.DataFrame()
    cols = [
        c
        for c in (
            "제품코드",
            "제품명",
            "공정",
            "제약유형",
            "일목표매수",
            "일가능매수",
            "필요분",
            "배분분",
            "시간배분%",
            "공정부하율%",
            "매당분",
            "달성",
        )
        if c in detail.columns
    ]
    return detail[cols].sort_values(["공정", "제품코드"]).reset_index(drop=True)


def floor_manager_daily_raw(
    products: pd.DataFrame,
    plan: pd.DataFrame,
    *,
    work_days: float = DEFAULT_WORK_DAYS,
    campuses: tuple[str, ...] | list[str] = ("천안", "아산"),
    equip: pd.DataFrame | None = None,
    manpower: pd.DataFrame | None = None,
    shift_teams: int = DEFAULT_SHIFT_TEAMS,
    working_teams: int = DEFAULT_WORKING_TEAMS,
) -> pd.DataFrame:
    """현장 관리자용 일별 처리 Raw — 캠퍼스·공정·제품별 권장 매수.

    규칙:
    - 치수: CEL·Ring·Wafer
    - Hole: CEL만
    - 외관·종합측정실: 계획 전체
    - 캠퍼스 배분: 공정 자원 비중(치수·Hole=설비, 외관=인력)
    """
    empty_cols = [
        "캠퍼스",
        "공정",
        "처리순서",
        "제품코드",
        "제품명",
        "제품군",
        "일목표_전체",
        "캠퍼스배분매수",
        "예상소요분",
        "매당분",
        "제약유형",
        "캠퍼스비중%",
        "비고",
    ]
    tagged = _tagged_monthly_plan(plan, products)
    if tagged.empty or products.empty:
        return pd.DataFrame(columns=empty_cols)

    days = float(work_days or DEFAULT_WORK_DAYS) or DEFAULT_WORK_DAYS
    tagged = tagged.copy()
    tagged["일목표_전체"] = (tagged["월목표매수"] / days).round(2)

    # 제품명 맵
    name_map: dict[str, str] = {}
    if "제품명" in products.columns:
        for _, r in products.drop_duplicates("제품코드").iterrows():
            name_map[_norm(r["제품코드"])] = _norm(r["제품명"])

    eq = equip if equip is not None else pd.DataFrame()
    man = manpower if manpower is not None else pd.DataFrame()
    camp_list = [c for c in campuses if c]

    def _share(area: str, campus: str) -> float:
        return _campus_resource_share(
            area=area,
            campus=campus,
            equip=eq,
            manpower=man,
            shift_teams=shift_teams,
            working_teams=working_teams,
        )

    shares: dict[tuple[str, str], float] = {}
    for area in AREAS:
        raw = {c: _share(area, c) for c in camp_list}
        s = sum(raw.values())
        if s <= 0 and camp_list:
            raw = {c: 1.0 / len(camp_list) for c in camp_list}
        elif s > 0:
            raw = {c: v / s for c, v in raw.items()}
        for c, v in raw.items():
            shares[(c, area)] = v

    rows: list[dict[str, Any]] = []
    for _, t in tagged.iterrows():
        code = _norm(t["제품코드"])
        fam = _norm(t["제품군"])
        daily_all = float(t["일목표_전체"])
        pname = name_map.get(code, code)
        for area in AREAS:
            # 공정별 대상 제품군 필터
            if area == "Hole" and fam != "CEL":
                continue
            if area == "치수" and fam not in PLAN_PRODUCT_FAMILIES:
                continue
            spec = _product_process_spec(products, code, area)
            if spec is None:
                continue
            tact = float(spec["매당_인시분"] if spec["제약유형"] == "인력" else spec["매당_설비분"])
            if tact <= 0:
                tact = float(spec["매당_인시분"] or spec["매당_설비분"] or 0)
            note = ""
            if area == "Hole":
                note = "Hole은 CEL만 측정"
            elif area == "치수":
                note = "치수=CEL·Ring·Wafer"
            for camp in camp_list:
                share = shares.get((camp, area), 0.0)
                qty = round(daily_all * share, 2)
                if qty <= 0:
                    continue
                rows.append(
                    {
                        "캠퍼스": camp,
                        "공정": area,
                        "처리순서": 0,
                        "제품코드": code,
                        "제품명": pname,
                        "제품군": fam,
                        "일목표_전체": daily_all,
                        "캠퍼스배분매수": qty,
                        "예상소요분": round(qty * tact, 1),
                        "매당분": round(tact, 4),
                        "제약유형": spec["제약유형"],
                        "캠퍼스비중%": round(share * 100, 1),
                        "비고": note,
                    }
                )

    if not rows:
        return pd.DataFrame(columns=empty_cols)

    out = pd.DataFrame(rows)
    # 공정 내: 제품군(CEL→Ring→Wafer) · 배분매수 큰 순 → 처리순서
    fam_ord = {f: i for i, f in enumerate(PLAN_PRODUCT_FAMILIES)}
    out["_fam"] = out["제품군"].map(lambda x: fam_ord.get(x, 99))
    out["_area"] = out["공정"].map(lambda x: list(AREAS).index(x) if x in AREAS else 99)
    out = out.sort_values(
        ["캠퍼스", "_area", "_fam", "캠퍼스배분매수", "제품코드"],
        ascending=[True, True, True, False, True],
    )
    out["처리순서"] = out.groupby(["캠퍼스", "공정"]).cumcount() + 1
    return out.drop(columns=["_fam", "_area"]).reset_index(drop=True)


# ----- 공정 재공 + 출하(긴급품) → 일별 최적 처리 -----

WIP_COLUMNS = ("사업장", "공정코드", "공정명", "제품코드", "제품군", "검사영역")
SHIP_COLUMNS = ("우선순위", "제품코드", "재공_출하표", "완제품", "부족분", "출하예정일", "출하예정수량")


def _map_wip_inspect_area(process_name: str) -> str:
    """재공 공정명 → 검사 영역.

    - 종합측정실: 공정명에 '종합측정실' 포함 (예: 종합측정실 (3D))
    - 치수: 저항측정 · 3D측정 (예: 저항측정 (Si), SiC 3D측정)
    - Hole / 외관: 기존과 동일
    """
    name = _norm(process_name)
    if not name:
        return "기타"
    compact = name.replace(" ", "").upper()

    # 종합측정실이 들어가면 종합측정실 (3D 포함이어도 종합 우선)
    if "종합측정실" in name.replace(" ", "") or "종합측정실" in name:
        return "종합측정실"

    if "외관" in name:
        return "외관"

    if (
        "HOLE" in compact
        or "홀측정" in name.replace(" ", "")
        or "홀 측정" in name
        or compact.endswith("홀")
    ):
        return "Hole"

    # 치수: 저항측정 / 3D측정 만
    if "저항" in name and "측정" in name:
        return "치수"
    if "3D측정" in compact or "3D 측정" in name:
        return "치수"

    return "기타"


def process_name_matches_area(process_name: str, area: str) -> bool:
    """공정명 기준으로 표시 탭(치수/Hole/외관/종합측정실) 소속 여부."""
    return _map_wip_inspect_area(process_name) == area


# 공정코드가 커질수록 뒤 공정. 이름 규칙에 없는 재공에만 쓴다.
# 재공에 Hole/외관 공정명이 있으면 그 코드로 경계를 바꾸고, 없으면 이 값.
DEFAULT_HOLE_CODE_FROM = 79000
DEFAULT_APPEARANCE_CODE_FROM = 85000


def process_code_number(code: Any) -> float | None:
    """공정코드 → 숫자. 없으면 None."""
    s = _norm(code).replace(",", "")
    if s.endswith(".0"):
        s = s[:-2]
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        matched = re.search(r"\d+", s)
        return float(matched.group()) if matched else None


def area_by_process_code(
    code: Any,
    *,
    hole_from: float | None = None,
    appearance_from: float | None = None,
) -> str:
    """코드가 작으면 치수, 커지면 Hole, 더 커지면 외관."""
    number = process_code_number(code)
    if number is None:
        return "기타"
    hole = float(DEFAULT_HOLE_CODE_FROM if hole_from is None else hole_from)
    appearance = float(
        DEFAULT_APPEARANCE_CODE_FROM if appearance_from is None else appearance_from
    )
    if appearance < hole:
        appearance = hole
    if number >= appearance:
        return "외관"
    if number >= hole:
        return "Hole"
    return "치수"


def route_code_bounds(df: pd.DataFrame) -> tuple[float, float]:
    """이름 규칙으로 잡힌 Hole·외관 공정코드로 경계.

    외관은 Hole 코드 이상인 것만 본다. 수입검사-외관처럼 앞 공정 코드는 빼기 위해서다.
    """
    hole_from = float(DEFAULT_HOLE_CODE_FROM)
    appearance_from = float(DEFAULT_APPEARANCE_CODE_FROM)
    if df is None or df.empty or "공정명" not in df.columns:
        return hole_from, appearance_from

    def _nums(area: str) -> list[float]:
        if "공정코드" not in df.columns:
            return []
        mask = df["공정명"].map(lambda n: _map_wip_inspect_area(n) == area)
        out: list[float] = []
        for raw in df.loc[mask, "공정코드"]:
            number = process_code_number(raw)
            if number is not None:
                out.append(number)
        return out

    hole_nums = _nums("Hole")
    if hole_nums:
        hole_from = min(hole_nums)
    late_appearance = [n for n in _nums("외관") if n >= hole_from]
    if late_appearance:
        appearance_from = min(late_appearance)
    if appearance_from < hole_from:
        appearance_from = hole_from
    return hole_from, appearance_from


def _priority_rank(label: Any) -> int:
    t = _norm(label)
    if not t:
        return 99
    if "특" in t and "1" in t:
        return 0
    if "1순위" in t or t == "1":
        return 1
    if "2순위" in t or t == "2":
        return 2
    if "3순위" in t or t == "3":
        return 3
    # 숫자 추출
    for i, ch in enumerate(t):
        if ch.isdigit():
            try:
                return int("".join(c for c in t[i:] if c.isdigit())[:2] or "50")
            except ValueError:
                break
    return 50


def normalize_wip(df: pd.DataFrame) -> pd.DataFrame:
    """공정 재공 리스트 정규화. 행 1개 = 재공 1매. Sub Total 제외."""
    empty = pd.DataFrame(columns=list(WIP_COLUMNS))
    if df is None or df.empty:
        return empty
    work = _rename_by_alias(
        df.dropna(how="all").copy(),
        {
            "사업장": ("사업장", "캠퍼스", "공장", "campus"),
            "공정코드": ("공정코드", "공정", "공정번호"),
            "공정명": ("공정명", "설명", "공정이름"),
            "제품코드": ("제품코드", "제품", "품목코드", "품번"),
            "제품군": ("제품군", "제품구분", "세부형상", "유형"),
        },
    )
    for c in ("사업장", "공정코드", "공정명", "제품코드", "제품군"):
        if c not in work.columns:
            work[c] = ""
    work["사업장"] = work["사업장"].map(_norm)
    work["공정명"] = work["공정명"].map(_norm)
    work["제품코드"] = work["제품코드"].map(_norm)
    work["제품군"] = work["제품군"].map(lambda v: _infer_product_family(v) or _norm(v))
    work["공정코드"] = work["공정코드"].map(lambda v: _norm(v).replace(".0", "") if _norm(v).endswith(".0") else _norm(v))
    # Sub Total / 합계 행 제거
    bad = work["제품코드"].str.contains(r"sub\s*total|합계|total", case=False, na=False)
    work = work[(work["제품코드"] != "") & ~bad]
    # 사업장 앞으로 채우기(병합 셀)
    work["사업장"] = work["사업장"].replace("", pd.NA).ffill().fillna("")
    work["검사영역"] = work["공정명"].map(_map_wip_inspect_area)
    return work[list(WIP_COLUMNS)].reset_index(drop=True)


def aggregate_wip(wip: pd.DataFrame) -> pd.DataFrame:
    """사업장·공정·제품별 재공 매수."""
    if wip is None or wip.empty:
        return pd.DataFrame(columns=[*WIP_COLUMNS, "재공매수"])
    work = wip if "검사영역" in wip.columns and "제품코드" in wip.columns else normalize_wip(wip)
    if work.empty:
        return pd.DataFrame(columns=[*WIP_COLUMNS, "재공매수"])
    # 공정명 규칙 변경 반영(세션에 남은 옛 매핑 보정)
    if "공정명" in work.columns:
        work = work.copy()
        work["검사영역"] = work["공정명"].map(_map_wip_inspect_area)
    if "재공매수" in work.columns:
        return work
    return (
        work.groupby(["사업장", "공정코드", "공정명", "제품코드", "제품군", "검사영역"], as_index=False)
        .size()
        .rename(columns={"size": "재공매수"})
    )

def _shipping_date_columns(df: pd.DataFrame) -> list[str]:
    """긴급품 시트의 일자 열만 추출 (우선순위·품목·재공·완제품·부족분 제외)."""
    skip = {
        "우선순위",
        "품목코드",
        "제품코드",
        "재공",
        "재공_출하표",
        "완제품",
        "부족분",
        "순위",
        "priority",
    }
    cols = []
    for c in df.columns:
        s = str(c).replace("\n", " ").strip()
        if s in skip or s.startswith("Unnamed"):
            continue
        ts = pd.to_datetime(s, errors="coerce")
        if pd.notna(ts):
            cols.append(c)
            continue
        # 9/17, 09-17, 2026.9.17 등
        if re.search(r"\d{1,4}[-/.]\d{1,2}([-/.]\d{1,4})?", s):
            ts2 = pd.to_datetime(s, errors="coerce")
            if pd.notna(ts2):
                cols.append(c)
    def _key(c):
        t = pd.to_datetime(str(c), errors="coerce")
        return t if pd.notna(t) else pd.Timestamp.max

    return sorted(cols, key=_key)


def _col_to_date_label(c: Any) -> str:
    ts = pd.to_datetime(str(c), errors="coerce")
    if pd.notna(ts):
        return str(ts.date())
    return str(c).strip()[:10]


def normalize_shipping_urgent(df: pd.DataFrame, ship_date: str | None = None) -> pd.DataFrame:
    """긴급품 시트 → 일자별 출하 예정 (제품×일자 행).

    ship_date:
      - None / '' / '전체' → 수량이 있는 모든 일자 펼침
      - 'YYYY-MM-DD' → 해당 일자만
    """
    empty = pd.DataFrame(columns=list(SHIP_COLUMNS))
    if df is None or df.empty:
        return empty
    work = df.dropna(how="all").copy()
    work.columns = [str(c).replace("\n", " ").strip() for c in work.columns]
    work = _rename_by_alias(
        work,
        {
            "우선순위": ("우선순위", "순위", "priority"),
            "제품코드": ("제품코드", "품목코드", "품번", "item"),
            "재공_출하표": ("재공",),
            "완제품": ("완제품",),
            "부족분": ("부족분",),
        },
    )
    for c in ("우선순위", "제품코드", "재공_출하표", "완제품", "부족분"):
        if c not in work.columns:
            work[c] = "" if c in ("우선순위", "제품코드") else 0
    work["제품코드"] = work["제품코드"].map(_norm)
    work = work[work["제품코드"] != ""]
    date_cols = _shipping_date_columns(work)
    if not date_cols:
        return empty

    want_all = ship_date is None or str(ship_date).strip() in ("", "전체", "all", "ALL")
    use_cols = date_cols
    if not want_all:
        matched = [c for c in date_cols if str(ship_date)[:10] in str(c) or _col_to_date_label(c) == str(ship_date)[:10]]
        use_cols = matched or date_cols[:1]

    rows: list[dict[str, Any]] = []
    for _, r in work.iterrows():
        base = {
            "우선순위": _norm(r.get("우선순위", "")),
            "제품코드": _norm(r["제품코드"]),
            "재공_출하표": pd.to_numeric(r.get("재공_출하표", 0), errors="coerce") or 0,
            "완제품": pd.to_numeric(r.get("완제품", 0), errors="coerce") or 0,
            "부족분": pd.to_numeric(r.get("부족분", 0), errors="coerce") or 0,
        }
        for dc in use_cols:
            qty = pd.to_numeric(r.get(dc), errors="coerce")
            if pd.isna(qty) or float(qty) <= 0:
                continue
            rows.append(
                {
                    **base,
                    "출하예정일": _col_to_date_label(dc),
                    "출하예정수량": float(qty),
                }
            )

    if not rows:
        return empty
    out = pd.DataFrame(rows)
    out["우선순위점수"] = out["우선순위"].map(_priority_rank)
    out = out.sort_values(["출하예정일", "우선순위점수", "제품코드"]).drop(columns=["우선순위점수"])
    return out.reset_index(drop=True)


def shipping_date_options(df: pd.DataFrame) -> list[str]:
    """긴급품 raw에서 선택 가능한 출하일 목록. 맨 앞에 '전체'."""
    if df is None or df.empty:
        return []
    work = df.copy()
    work.columns = [str(c).replace("\n", " ").strip() for c in work.columns]
    date_cols = _shipping_date_columns(work)
    if not date_cols:
        return []
    opts = ["전체"]
    for c in date_cols:
        opts.append(_col_to_date_label(c))
    # 중복 제거 (순서 유지)
    seen: set[str] = set()
    uniq = []
    for o in opts:
        if o not in seen:
            seen.add(o)
            uniq.append(o)
    return uniq


def read_wip_excel(data: bytes | Path) -> pd.DataFrame:
    """재공 xlsx/csv → 정규화."""
    if isinstance(data, Path):
        raw = data.read_bytes()
    else:
        raw = data
    try:
        df = pd.read_excel(BytesIO(raw), sheet_name=0)
    except Exception:
        df = pd.DataFrame()
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                df = pd.read_csv(BytesIO(raw), encoding=enc)
                break
            except Exception:
                continue
    return normalize_wip(df)


def read_shipping_excel(data: bytes | Path, ship_date: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """출하 xlsx → (긴급품 raw, 선택일 정규화).

    시트 우선: 긴급품 → 출하계획 → 첫 시트.
    """
    if isinstance(data, Path):
        path_or_buf: Any = data
        raw = data.read_bytes()
    else:
        raw = data
        path_or_buf = BytesIO(raw)
    try:
        xl = pd.ExcelFile(path_or_buf)
        sheet = "긴급품" if "긴급품" in xl.sheet_names else (
            "출하계획" if "출하계획" in xl.sheet_names else xl.sheet_names[0]
        )
        urgent = pd.read_excel(xl, sheet_name=sheet)
    except Exception:
        urgent = pd.DataFrame()
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                urgent = pd.read_csv(BytesIO(raw), encoding=enc)
                break
            except Exception:
                continue
    return urgent, normalize_shipping_urgent(urgent, ship_date=ship_date)


def daily_optimal_from_wip_shipping(
    wip: pd.DataFrame,
    shipping: pd.DataFrame,
    *,
    products: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """출하 예정(긴급품) ∩ 공정 재공 → 현장용 일별 최적 처리 Raw.

    규칙:
      1) 제품별 완제품을 출하예정일 빠른 날부터 차감 → 남는 순필요만 현장 처리
      2) 공정 재공은 외관→Hole→치수 순, 제품·일자 간 재고를 중복 배분하지 않음
      3) Hole은 CEL만
    """
    cols = [
        "처리순서",
        "우선순위",
        "제품코드",
        "제품군",
        "출하예정일",
        "출하예정수량",
        "완제품사용",
        "순필요매수",
        "사업장",
        "공정코드",
        "공정명",
        "검사영역",
        "재공매수",
        "권장처리매수",
        "상태",
        "비고",
    ]
    if shipping is None or shipping.empty:
        return pd.DataFrame(columns=cols)
    ship = shipping.copy()
    if "출하예정수량" not in ship.columns:
        ship = normalize_shipping_urgent(ship)
    if ship.empty:
        return pd.DataFrame(columns=cols)

    wip_agg = aggregate_wip(wip)
    fam_map: dict[str, str] = {}
    if products is not None and not products.empty and "제품코드" in products.columns:
        pc = products[["제품코드", "제품군"]].drop_duplicates("제품코드")
        fam_map = {_norm(a): _infer_product_family(b) for a, b in zip(pc["제품코드"], pc["제품군"])}

    rows: list[dict[str, Any]] = []
    area_ord = {"외관": 0, "Hole": 1, "치수": 2, "종합측정실": 3}
    status_ord = {
        "처리가능": 0,
        "재공부족": 1,
        "재공없음": 2,
        "대기(재고배분완료)": 3,
        "완제품충당": 9,
    }

    ship = ship.copy()
    ship["제품코드"] = ship["제품코드"].map(_norm)
    ship["_pri"] = ship["우선순위"].map(_priority_rank) if "우선순위" in ship.columns else 99
    if "출하예정일" not in ship.columns:
        ship["출하예정일"] = ""
    if "완제품" not in ship.columns:
        ship["완제품"] = 0
    ship["완제품"] = pd.to_numeric(ship["완제품"], errors="coerce").fillna(0).clip(lower=0)
    ship["출하예정수량"] = pd.to_numeric(ship["출하예정수량"], errors="coerce").fillna(0)
    # 일자 빠른 순 → 완제품·재공 모두 앞에서부터 소진
    ship = ship.sort_values(["제품코드", "출하예정일", "_pri"])

    # 제품별 완제품 잔량 (긴급품 시트 값, 일자 공통)
    fg_left: dict[str, float] = {}
    for code, g in ship.groupby("제품코드", sort=False):
        fg_left[str(code)] = float(g["완제품"].max())

    # 공정 재공 잔량 (배분 시 차감)
    wip_pool = wip_agg.copy()
    if wip_pool.empty:
        wip_pool["_left"] = pd.Series(dtype=float)
    else:
        wip_pool["_left"] = pd.to_numeric(wip_pool["재공매수"], errors="coerce").fillna(0)

    for _, s in ship.iterrows():
        code = _norm(s["제품코드"])
        gross = float(s["출하예정수량"])
        if gross <= 0:
            continue
        day = _norm(s.get("출하예정일", ""))
        pri = _norm(s.get("우선순위", ""))
        fam = fam_map.get(code, "")

        use_fg = min(fg_left.get(code, 0.0), gross)
        fg_left[code] = fg_left.get(code, 0.0) - use_fg
        need = gross - use_fg

        if need <= 0.5:
            rows.append(
                {
                    "처리순서": 0,
                    "우선순위": pri,
                    "제품코드": code,
                    "제품군": fam,
                    "출하예정일": day,
                    "출하예정수량": gross,
                    "완제품사용": round(use_fg, 1),
                    "순필요매수": 0.0,
                    "사업장": "",
                    "공정코드": "",
                    "공정명": "",
                    "검사영역": "",
                    "재공매수": 0,
                    "권장처리매수": 0,
                    "상태": "완제품충당",
                    "비고": f"완제품 {use_fg:g}매로 출하 충당(현장 처리 불필요)",
                }
            )
            continue

        hit = (
            wip_pool[wip_pool["제품코드"] == code].copy()
            if not wip_pool.empty
            else pd.DataFrame()
        )
        if not hit.empty:
            hit["_ord"] = hit["검사영역"].map(lambda a: area_ord.get(a, 9))
            if fam and fam != "CEL":
                hit = hit[hit["검사영역"] != "Hole"]
            hit = hit[hit["_left"] > 0.5]

        if hit.empty:
            note = (
                f"완제품 {use_fg:g}매 차감 후 순필요 {need:g}매, 공정 재공 없음"
                if use_fg > 0
                else "출하 대상이나 공정 재공에 없음"
            )
            rows.append(
                {
                    "처리순서": 0,
                    "우선순위": pri,
                    "제품코드": code,
                    "제품군": fam,
                    "출하예정일": day,
                    "출하예정수량": gross,
                    "완제품사용": round(use_fg, 1),
                    "순필요매수": round(need, 1),
                    "사업장": "",
                    "공정코드": "",
                    "공정명": "",
                    "검사영역": "",
                    "재공매수": 0,
                    "권장처리매수": round(need, 1),
                    "상태": "재공없음",
                    "비고": note,
                }
            )
            continue

        hit = hit.sort_values(["_ord", "사업장", "공정명"])
        remain = need
        fg_note_used = use_fg
        for idx, w in hit.iterrows():
            left = float(wip_pool.at[idx, "_left"])
            stock = float(w["재공매수"])
            take = min(remain, left) if remain > 0 else 0.0
            note_bits = []
            if fg_note_used > 0:
                note_bits.append(f"완제품 {fg_note_used:g}매 차감")
                fg_note_used = 0.0
            if w["검사영역"] == "Hole" and fam == "CEL":
                note_bits.append("Hole=CEL만")
            rows.append(
                {
                    "처리순서": 0,
                    "우선순위": pri,
                    "제품코드": code,
                    "제품군": fam or _norm(w.get("제품군", "")),
                    "출하예정일": day,
                    "출하예정수량": gross,
                    "완제품사용": round(use_fg, 1),
                    "순필요매수": round(need, 1),
                    "사업장": _norm(w["사업장"]),
                    "공정코드": _norm(w["공정코드"]),
                    "공정명": _norm(w["공정명"]),
                    "검사영역": _norm(w["검사영역"]),
                    "재공매수": stock,
                    "권장처리매수": round(take, 1),
                    "상태": "처리가능" if take > 0 else "대기(재고배분완료)",
                    "비고": " · ".join(note_bits),
                }
            )
            if take > 0:
                wip_pool.at[idx, "_left"] = left - take
                remain -= take
        if remain > 0.5:
            rows.append(
                {
                    "처리순서": 0,
                    "우선순위": pri,
                    "제품코드": code,
                    "제품군": fam,
                    "출하예정일": day,
                    "출하예정수량": gross,
                    "완제품사용": round(use_fg, 1),
                    "순필요매수": round(need, 1),
                    "사업장": "",
                    "공정코드": "",
                    "공정명": "",
                    "검사영역": "",
                    "재공매수": 0,
                    "권장처리매수": round(remain, 1),
                    "상태": "재공부족",
                    "비고": f"순필요 {need:g}매 중 재공 부족 {remain:g}매",
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=cols)

    out["_pri"] = out["우선순위"].map(_priority_rank)
    out["_st"] = out["상태"].map(lambda x: status_ord.get(x, 5))
    # 현장 처리 필요 건을 위에, 완제품충당은 아래
    out = out.sort_values(["_st", "출하예정일", "_pri", "제품코드", "사업장"])
    out["처리순서"] = range(1, len(out) + 1)
    return out.drop(columns=["_pri", "_st"]).reset_index(drop=True)


def process_standard_times(products: pd.DataFrame, product_codes: list[str] | None = None) -> pd.DataFrame:
    """공정별 평균 매당 인시분·설비분."""
    if products.empty:
        return pd.DataFrame(columns=["공정", "매당_인시분", "매당_설비분"])
    work = products
    if product_codes:
        work = work[work["제품코드"].isin(product_codes)]
    if work.empty:
        work = products
    g = work.groupby("공정", as_index=False).agg(
        매당_인시분=("매당_인시분", "mean"),
        매당_설비분=("매당_설비분", "mean"),
    )
    g["매당_인시분"] = g["매당_인시분"].round(2)
    g["매당_설비분"] = g["매당_설비분"].round(2)
    return g


def utilization_from_actuals(
    actuals: pd.DataFrame,
    standards: pd.DataFrame,
    *,
    available_min: float = DAY_MINUTES,
) -> pd.DataFrame:
    """실적 × 매당인시분 / (인력 × 가용분) × 100."""
    if actuals.empty:
        return pd.DataFrame()
    work = actuals.copy()
    if "영역" not in work.columns and "공정" in work.columns:
        work = work.rename(columns={"공정": "영역"})
    if "영역" not in work.columns:
        return pd.DataFrame()
    if "매당_인시분" not in work.columns:
        if standards is None or standards.empty:
            return pd.DataFrame()
        std = standards.rename(columns={"공정": "영역"})
        work = work.merge(std[["영역", "매당_인시분"]], on="영역", how="left")
    work = work[work["매당_인시분"].notna() & (work["매당_인시분"] > 0)]
    if work.empty:
        return pd.DataFrame()
    man = pd.to_numeric(work["인력"], errors="coerce").fillna(0)
    qty = pd.to_numeric(work["실적"], errors="coerce").fillna(0)
    work["투입인시분"] = (man * float(available_min)).round(1)
    work["실적인시분"] = (qty * work["매당_인시분"]).round(1)
    work["인당시간활용률"] = work.apply(
        lambda r: round(float(r["실적인시분"]) / float(r["투입인시분"]) * 100, 1) if r["투입인시분"] else None,
        axis=1,
    )
    work["이론인당매수"] = work["매당_인시분"].map(
        lambda t: round(float(available_min) / float(t), 1) if t else None
    )
    work["실적인당매수"] = work.apply(
        lambda r: round(float(r["실적"]) / float(r["인력"]), 1) if r["인력"] else None,
        axis=1,
    )
    cols = [
        c
        for c in (
            "일자",
            "캠퍼스",
            "조",
            "주야",
            "제품코드",
            "영역",
            "인력",
            "실적",
            "매당_인시분",
            "투입인시분",
            "실적인시분",
            "인당시간활용률",
            "이론인당매수",
            "실적인당매수",
        )
        if c in work.columns
    ]
    return work[cols].rename(columns={"영역": "공정"}).reset_index(drop=True)


def read_csv_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        df = pd.read_excel(path)
        return df.dropna(how="all").reset_index(drop=True)
    last_err: Exception | None = None
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            df = pd.read_csv(path, encoding=enc)
            return df.dropna(how="all").reset_index(drop=True)
        except UnicodeDecodeError as e:
            last_err = e
    if last_err:
        raise last_err
    return pd.DataFrame()


def master_github_paths(stem: str) -> list[str]:
    """저장소에서 찾을 기준정보 경로. 파일명은 설비_기준정보 / 제품_기준정보 / 제품별_실적."""
    paths: list[str] = []
    for folder in MASTER_GH_FOLDERS:
        for ext in (".xlsx", ".csv", ".xls"):
            paths.append(f"{folder}/{stem}{ext}")
    for ext in (".xlsx", ".csv", ".xls"):
        paths.append(f"{stem}{ext}")
    return paths


def canonical_master_name(filename: str, prefix: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in (".csv", ".xlsx", ".xls"):
        suffix = ".csv"
    return f"{prefix}{suffix}"


def newest_matching(folder: Path, prefix: str) -> Path | None:
    files = (
        list(folder.glob(f"{prefix}*.csv"))
        + list(folder.glob(f"{prefix}*.xlsx"))
        + list(folder.glob(f"{prefix}*.xls"))
    )
    files = [p for p in files if not p.name.startswith("~$")]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def normalize_product_actuals(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=list(PRODUCT_ACTUAL_COLUMNS))
    work = _rename_by_alias(
        df.dropna(how="all").copy(),
        {
            "일자": ("일자", "날짜", "date"),
            "캠퍼스": ("캠퍼스", "campus"),
            "조": ("조", "team"),
            "주야": ("주야", "shift"),
            "제품코드": ("제품코드", "품번"),
            "공정": ("공정", "영역"),
            "인력": ("인력", "인원"),
            "실적": ("실적", "수량", "매수"),
        },
    )
    for c in PRODUCT_ACTUAL_COLUMNS:
        if c not in work.columns:
            work[c] = None
    work["제품코드"] = work["제품코드"].map(_norm)
    work["공정"] = work["공정"].map(_norm)
    work["인력"] = work["인력"].map(lambda v: _num(v, 0))
    work["실적"] = work["실적"].map(lambda v: _num(v, 0))
    return work[(work["제품코드"] != "") & (work["공정"] != "")].reset_index(drop=True)
