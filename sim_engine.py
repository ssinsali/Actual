"""설비·제품 기준정보와 1440분 운영 시뮬레이션."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from stats_engine import AREAS

DAY_MINUTES = 1440

EQUIP_COLUMNS = ("캠퍼스", "공정", "설비코드", "설비명", "대수", "가동여부", "비고")
PRODUCT_COLUMNS = (
    "제품코드",
    "제품명",
    "공정",
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
    rows = []
    samples = [
        ("천안", "종합측정실", "CMM-01", "3차원측정기", 1),
        ("천안", "치수", "DIM-01", "2.5D 치수기", 2),
        ("천안", "Hole", "HOLE-01", "홀검사기", 1),
        ("천안", "외관", "AOI-01", "외관검사기", 2),
        ("아산", "종합측정실", "CMM-A1", "3차원측정기", 1),
        ("아산", "치수", "DIM-A1", "2.5D 치수기", 1),
        ("아산", "Hole", "HOLE-A1", "홀검사기", 1),
        ("아산", "외관", "AOI-A1", "외관검사기", 1),
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


def product_template() -> pd.DataFrame:
    specs = [
        ("P-A", "제품A", {"종합측정실": 4.0, "치수": 0.9, "Hole": 2.4, "외관": 1.6}),
        ("P-B", "제품B", {"종합측정실": 5.2, "치수": 1.1, "Hole": 3.0, "외관": 1.8}),
        ("P-C", "제품C", {"종합측정실": 3.5, "치수": 0.7, "Hole": 2.0, "외관": 1.3}),
    ]
    equip = {
        "종합측정실": "CMM-01",
        "치수": "DIM-01",
        "Hole": "HOLE-01",
        "외관": "AOI-01",
    }
    rows = []
    for code, name, times in specs:
        for area in AREAS:
            t = times[area]
            rows.append(
                {
                    "제품코드": code,
                    "제품명": name,
                    "공정": area,
                    "설비코드": equip[area],
                    "매당_설비분": t,
                    "매당_인시분": t,
                    "필요인원": 1,
                    "비고": "예시 — 자사 택트로 수정",
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
        return pd.DataFrame(columns=list(EQUIP_COLUMNS))
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


def normalize_products(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=list(PRODUCT_COLUMNS))
    work = _rename_by_alias(
        df.dropna(how="all").copy(),
        {
            "제품코드": ("제품코드", "품번", "item"),
            "제품명": ("제품명", "품명"),
            "공정": ("공정", "영역"),
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
    work["설비코드"] = work["설비코드"].map(_norm)
    work["매당_설비분"] = work["매당_설비분"].map(lambda v: _num(v, 0))
    work["매당_인시분"] = work["매당_인시분"].map(lambda v: _num(v, 0))
    work["필요인원"] = work["필요인원"].map(lambda v: _num(v, 1) or 1)
    work.loc[work["매당_인시분"] <= 0, "매당_인시분"] = work["매당_설비분"]
    work = work[(work["제품코드"] != "") & (work["공정"] != "") & (work["매당_설비분"] > 0)]
    return work.reset_index(drop=True)


def running_qty(equip: pd.DataFrame, *, campus: str | None, area: str, equip_code: str = "") -> float:
    if equip.empty:
        return 0.0
    work = equip[equip["가동"]].copy()
    if campus:
        work = work[(work["캠퍼스"] == campus) | (work["캠퍼스"] == "")]
    work = work[work["공정"] == area]
    if equip_code:
        hit = work[work["설비코드"] == equip_code]
        if not hit.empty:
            work = hit
    return float(work["대수"].sum()) if not work.empty else 0.0


def daily_capacity(
    products: pd.DataFrame,
    equip: pd.DataFrame,
    *,
    campus: str | None = None,
    day_minutes: float = DAY_MINUTES,
) -> pd.DataFrame:
    """제품×공정 일 1440분 기준 가능 매수."""
    if products.empty:
        return pd.DataFrame()
    rows = []
    for _, r in products.iterrows():
        qty = running_qty(equip, campus=campus, area=str(r["공정"]), equip_code=str(r.get("설비코드") or ""))
        tact = float(r["매당_설비분"])
        sheets = round(qty * day_minutes / tact, 1) if tact > 0 else 0.0
        people = qty * float(r["필요인원"])
        rows.append(
            {
                "제품코드": r["제품코드"],
                "제품명": r["제품명"],
                "공정": r["공정"],
                "설비코드": r.get("설비코드") or "",
                "가동대수": qty,
                "매당_설비분": tact,
                "매당_인시분": float(r["매당_인시분"]),
                "필요인원": round(people, 1),
                "일가능매수": sheets,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    bottleneck = (
        out.groupby("제품코드", as_index=False)["일가능매수"]
        .min()
        .rename(columns={"일가능매수": "병목가능매수"})
    )
    out = out.merge(bottleneck, on="제품코드", how="left")
    bn_proc = (
        out.sort_values("일가능매수")
        .groupby("제품코드", as_index=False)
        .first()[["제품코드", "공정"]]
        .rename(columns={"공정": "병목공정"})
    )
    return out.merge(bn_proc, on="제품코드", how="left")


def mix_simulation(
    products: pd.DataFrame,
    equip: pd.DataFrame,
    mix: pd.DataFrame,
    *,
    campus: str | None = None,
    day_minutes: float = DAY_MINUTES,
) -> pd.DataFrame:
    """제품 비중(합=100)으로 설비 시간을 나눠 일 가능 매수를 계산."""
    if products.empty or mix is None or mix.empty:
        return pd.DataFrame()
    work = mix.copy()
    if "제품코드" not in work.columns:
        return pd.DataFrame()
    share_col = "비중" if "비중" in work.columns else None
    if share_col is None:
        return pd.DataFrame()
    work["비중"] = pd.to_numeric(work["비중"], errors="coerce").fillna(0)
    total = float(work["비중"].sum())
    if total <= 0:
        return pd.DataFrame()
    work["비중"] = work["비중"] / total
    rows = []
    for area in AREAS:
        qty = running_qty(equip, campus=campus, area=area)
        minutes_total = qty * day_minutes
        for _, m in work.iterrows():
            code = _norm(m["제품코드"])
            spec = products[(products["제품코드"] == code) & (products["공정"] == area)]
            if spec.empty:
                continue
            tact = float(spec.iloc[0]["매당_설비분"])
            mins = minutes_total * float(m["비중"])
            sheets = round(mins / tact, 1) if tact > 0 else 0.0
            rows.append(
                {
                    "제품코드": code,
                    "제품명": spec.iloc[0]["제품명"],
                    "공정": area,
                    "배분분": round(mins, 1),
                    "매당_설비분": tact,
                    "일가능매수": sheets,
                    "가동대수": qty,
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
    if actuals.empty or standards.empty or "영역" not in actuals.columns:
        return pd.DataFrame()
    work = actuals.copy()
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


def newest_matching(folder: Path, prefix: str) -> Path | None:
    files = (
        list(folder.glob(f"{prefix}*.csv"))
        + list(folder.glob(f"{prefix}*.xlsx"))
        + list(folder.glob(f"{prefix}*.xls"))
    )
    files = [p for p in files if not p.name.startswith("~$")]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None
