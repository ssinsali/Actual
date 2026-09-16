"""설비·제품 기준정보와 1440분 운영 시뮬레이션."""
from __future__ import annotations

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
    "공정",
    "제약유형",
    "설비코드",
    "매당_설비분",
    "매당_인시분",
    "필요인원",
    "비고",
)
PRODUCT_ACTUAL_COLUMNS = ("일자", "캠퍼스", "조", "주야", "제품코드", "공정", "인력", "실적")

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
        ("P-A", "제품A", {"종합측정실": 4.0, "치수": 0.9, "Hole": 2.4, "외관": 1.6}),
        ("P-B", "제품B", {"종합측정실": 5.2, "치수": 1.1, "Hole": 3.0, "외관": 1.8}),
        ("P-C", "제품C", {"종합측정실": 3.5, "치수": 0.7, "Hole": 2.0, "외관": 1.3}),
    ]
    equip = {
        "종합측정실": ("설비", "CMM-01"),
        "치수": ("설비", "DIM-01"),
        "Hole": ("설비", "HOLE-01"),
        "외관": ("인력", ""),
    }
    rows = []
    for code, name, times in specs:
        for area in AREAS:
            t = times[area]
            kind, eq = equip[area]
            rows.append(
                {
                    "제품코드": code,
                    "제품명": name,
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


def normalize_products(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=list(PRODUCT_COLUMNS))
    work = _rename_by_alias(
        df.dropna(how="all").copy(),
        {
            "제품코드": ("제품코드", "품번", "item"),
            "제품명": ("제품명", "품명"),
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

    - 총인원/근무인원: 항상 인력_기준정보 (전 공정, 3조2교대 → ×근무조/총조)
    - 설비: 설비_기준정보의 해당 공정 가동 설비를 캠퍼스 합산해 행으로 펼침
      (제품 설비코드는 택트 매칭용. 코드가 달라도 공정이 같으면 대수에 포함)
    - 인력: 근무인원 × 가용분 ÷ 매당_인시분
    - 공정은 개별 능력(병목 없음)
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
            man_total, man_avail = running_manpower(man, campus=campus, area=area)
            man_qty = effective_daily_headcount(
                man_total, shift_teams=shift_teams, working_teams=working_teams
            )
            eq_work = _equip_slice(eq, campus=campus, area=area, equip_code="")
            use_man = kind0 == "인력" or (eq_work.empty and man_qty > 0)

            if use_man:
                _, man_tact = _spec_tact(specs, "")
                if man_tact <= 0:
                    man_tact = float(specs["매당_인시분"].iloc[0] or 0)
                minutes = man_avail if man_avail else DEFAULT_SHIFT_MINUTES
                sheets = round(man_qty * minutes / man_tact, 1) if man_tact > 0 else 0.0
                rows.append(
                    {
                        "제품코드": code,
                        "제품명": pname,
                        "공정": area,
                        "캠퍼스": campus or "합산",
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
            for _, eqr in eq_work.iterrows():
                eq_code = _norm(eqr.get("설비코드"))
                eq_tact, man_tact = _spec_tact(specs, eq_code)
                if eq_tact <= 0:
                    eq_tact = default_eq
                if man_tact <= 0:
                    man_tact = default_man or eq_tact
                qty = float(eqr.get("대수") or 0)
                sheets = round(qty * day_minutes / eq_tact, 1) if eq_tact > 0 else 0.0
                need = round(qty * float(specs["필요인원"].iloc[0] or 1), 1)
                rows.append(
                    {
                        "제품코드": code,
                        "제품명": pname,
                        "공정": area,
                        "캠퍼스": _norm(eqr.get("캠퍼스")) or (campus or ""),
                        "제약유형": "설비",
                        "설비코드": eq_code,
                        "가동대수": qty,
                        "총인원": round(man_total, 1),
                        "근무인원": round(man_qty, 1),
                        "조보정": round(factor, 4),
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
