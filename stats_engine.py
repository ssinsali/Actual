"""실적 분석 통계 — 데이터 로드·정규화·집계."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

AREAS = ("종합측정실", "치수", "Hole", "외관")
AREA_ALIASES: dict[str, tuple[str, ...]] = {
    "종합측정실": ("종합측정실", "종합측정", "종합", "측정실", "cmm", "종합검사실"),
    "치수": ("치수", "치수검사", "치수검사기", "dimension"),
    "Hole": ("hole", "홀", "hole검사", "홀검사"),
    "외관": ("외관", "외관검사", "visual", "육안"),
}
DATE_ALIASES = ("일자", "날짜", "date", "작업일", "근무일", "기준일", "일자_")
TEAM_ALIASES = ("조", "조별", "근무조", "team", "반")
CAMPUS_ALIASES = ("캠퍼스", "campus", "사업장", "공장", "사이트", "site", "위치")
CAMPUSES = ("천안", "아산")
SHIFT_ALIASES = ("주야", "주/야", "주야간", "주간야간", "교대", "근무대", "daynight", "dn", "shift")
SHIFTS = ("주", "야")
MANPOWER_ALIASES = ("인력", "인원", "인원수", "인력수", "명", "headcount", "manpower")
OUTPUT_ALIASES = ("실적", "처리", "처리량", "수량", "건수", "qty", "output", "제품수", "판넬", "panel")

# 통계 입력용 표준 CSV 컬럼 (가로형) — K=캠퍼스, L=주야
TEMPLATE_COLUMNS = (
    "일자",
    "조",
    "종합측정실_인력",
    "종합측정실_실적",
    "치수_인력",
    "치수_실적",
    "Hole_인력",
    "Hole_실적",
    "외관_인력",
    "외관_실적",
    "캠퍼스",
    "주야",
)


def template_dataframe() -> pd.DataFrame:
    """통계 프로그램용 기본 CSV 예시 2행."""
    return pd.DataFrame(
        [
            {
                "일자": "2026-01-21",
                "조": "A조",
                "종합측정실_인력": 2,
                "종합측정실_실적": 120,
                "치수_인력": 3,
                "치수_실적": 450,
                "Hole_인력": 2,
                "Hole_실적": 300,
                "외관_인력": 4,
                "외관_실적": 520,
                "캠퍼스": "천안",
                "주야": "주",
            },
            {
                "일자": "2026-01-21",
                "조": "B조",
                "종합측정실_인력": 1,
                "종합측정실_실적": 80,
                "치수_인력": 2,
                "치수_실적": 380,
                "Hole_인력": 2,
                "Hole_실적": 280,
                "외관_인력": 3,
                "외관_실적": 490,
                "캠퍼스": "아산",
                "주야": "야",
            },
        ],
        columns=list(TEMPLATE_COLUMNS),
    )


def template_csv_bytes() -> bytes:
    return template_dataframe().to_csv(index=False).encode("utf-8-sig")


def empty_template_csv_bytes() -> bytes:
    return pd.DataFrame(columns=list(TEMPLATE_COLUMNS)).to_csv(index=False).encode("utf-8-sig")


def _norm(s: Any) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    t = str(s).strip().lower().replace(" ", "").replace("_", "")
    return t


def _find_header_row(raw: pd.DataFrame, max_scan: int = 15) -> int:
    best_i, best_score = 0, -1
    keywords = DATE_ALIASES + TEAM_ALIASES + MANPOWER_ALIASES + OUTPUT_ALIASES
    for alias in AREA_ALIASES.values():
        keywords += alias
    for i in range(min(max_scan, len(raw))):
        row = [_norm(v) for v in raw.iloc[i].tolist()]
        score = 0
        for cell in row:
            if not cell:
                continue
            for kw in keywords:
                if _norm(kw) in cell or cell in _norm(kw):
                    score += 1
                    break
        if score > best_score:
            best_score, best_i = score, i
    return best_i


def read_excel_table(path: Path, sheet: str | int | None = None) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding="cp949")
        return df.dropna(how="all").reset_index(drop=True)

    raw = pd.read_excel(path, sheet_name=sheet if sheet is not None else 0, header=None)
    if isinstance(raw, dict):
        raw = next(iter(raw.values()))
    hdr = _find_header_row(raw)
    cols = []
    seen: dict[str, int] = {}
    for j, v in enumerate(raw.iloc[hdr].tolist()):
        name = str(v).strip() if pd.notna(v) and str(v).strip() else f"컬럼{j+1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        cols.append(name)
    df = raw.iloc[hdr + 1 :].copy()
    df.columns = cols
    df = df.dropna(how="all").reset_index(drop=True)
    return df


def list_excel_sheets(path: Path) -> list[str]:
    if path.suffix.lower() == ".csv":
        return ["csv"]
    xl = pd.ExcelFile(path)
    return list(xl.sheet_names)


def _match_col(columns: list[str], aliases: tuple[str, ...]) -> str | None:
    norms = {_norm(c): c for c in columns}
    for a in aliases:
        an = _norm(a)
        if an in norms:
            return norms[an]
    for a in aliases:
        an = _norm(a)
        for cn, c in norms.items():
            if an and (an in cn or cn in an):
                return c
    return None


def _map_campus_label(value: Any) -> str:
    n = _norm(value)
    if not n:
        return "(미지정)"
    if "천안" in n or n in ("cheonan", "cheon-an"):
        return "천안"
    if "아산" in n or n in ("asan",):
        return "아산"
    raw = str(value).strip()
    return raw if raw and raw.lower() != "nan" else "(미지정)"


def _map_shift_label(value: Any) -> str:
    n = _norm(value)
    if not n:
        return "(미지정)"
    if n in ("주", "주간", "주간조", "day", "d") or n.startswith("주"):
        return "주"
    if n in ("야", "야간", "야간조", "night", "n") or n.startswith("야"):
        return "야"
    raw = str(value).strip()
    return raw if raw and raw.lower() != "nan" else "(미지정)"


def detect_layout(df: pd.DataFrame) -> dict[str, Any]:
    cols = list(df.columns.astype(str))
    date_col = _match_col(cols, DATE_ALIASES)
    campus_col = _match_col(cols, CAMPUS_ALIASES)
    shift_col = _match_col(cols, SHIFT_ALIASES)
    team_col = _match_col(cols, TEAM_ALIASES)
    if team_col and team_col in {campus_col, shift_col}:
        team_col = None

    # 긴 형식: 공정/영역 컬럼 + 인력 + 실적
    process_col = None
    for aliases in (("공정", "영역", "검사항목", "부서", "라인", "항목"),):
        process_col = _match_col(cols, aliases)
        if process_col:
            break
    man_col = _match_col(cols, MANPOWER_ALIASES)
    out_col = _match_col(cols, OUTPUT_ALIASES)

    wide_map: dict[str, dict[str, str | None]] = {}
    for area, aliases in AREA_ALIASES.items():
        man_c = None
        out_c = None
        for c in cols:
            cn = _norm(c)
            if not any(_norm(a) in cn for a in aliases):
                continue
            if any(_norm(a) in cn for a in MANPOWER_ALIASES) or cn.endswith("인원") or "인력" in cn:
                man_c = c
            elif any(_norm(a) in cn for a in OUTPUT_ALIASES) or "실적" in cn or "처리" in cn:
                out_c = c
            elif man_c is None and out_c is None:
                # 영역명만 있는 단일 컬럼은 실적으로 간주
                out_c = c
        # 인접 컬럼 휴리스틱: "종합측정실" 다음에 인원/실적
        for i, c in enumerate(cols):
            cn = _norm(c)
            if cn in {_norm(a) for a in aliases} or any(_norm(a) == cn for a in aliases):
                # 같은 영역 접두 컬럼 탐색
                for k in range(i, min(i + 4, len(cols))):
                    ck = cols[k]
                    ckn = _norm(ck)
                    if any(_norm(a) in ckn for a in MANPOWER_ALIASES):
                        man_c = man_c or ck
                    if any(_norm(a) in ckn for a in OUTPUT_ALIASES):
                        out_c = out_c or ck
        wide_map[area] = {"인력": man_c, "실적": out_c}

    # 템플릿형: 종합측정실_인력 / 종합측정실_실적 …
    if not any(v["인력"] or v["실적"] for v in wide_map.values()):
        for area in AREAS:
            man_name = f"{area}_인력"
            out_name = f"{area}_실적"
            man_c = next((c for c in cols if _norm(c) == _norm(man_name)), None)
            out_c = next((c for c in cols if _norm(c) == _norm(out_name)), None)
            if man_c or out_c:
                wide_map[area] = {"인력": man_c, "실적": out_c}

    # Y26Q1형: 일자/조 헤더 없고 인력·실적 쌍이 4개 연속
    if not any(v["인력"] or v["실적"] for v in wide_map.values()):
        pairs: list[tuple[str, str]] = []
        i = 0
        while i < len(cols) - 1:
            a, b = cols[i], cols[i + 1]
            an, bn = _norm(a), _norm(b)
            if ("인력" in an or "인원" in an) and ("실적" in bn or "처리" in bn):
                pairs.append((a, b))
                i += 2
            else:
                i += 1
        if len(pairs) >= 4:
            for area, (mc, oc) in zip(AREAS, pairs[:4]):
                wide_map[area] = {"인력": mc, "실적": oc}
        elif len(pairs) > 0:
            for area, (mc, oc) in zip(AREAS, pairs):
                wide_map[area] = {"인력": mc, "실적": oc}

    if date_col is None:
        for c in cols:
            sample = df[c].dropna().astype(str).head(8)
            if sample.empty:
                continue
            if sample.str.match(r"^\d{1,2}-\d{1,2}$").mean() > 0.5:
                date_col = c
                break
            if sample.str.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}").mean() > 0.5:
                date_col = c
                break
    if team_col is None:
        reserved = {date_col, campus_col, shift_col}
        for c in cols:
            if c in reserved:
                continue
            sample = df[c].dropna().astype(str).head(8)
            if sample.empty:
                continue
            if sample.str.match(r"^[A-Za-z가-힣]+-?\d*$").mean() > 0.5 and sample.str.len().mean() <= 8:
                # 숫자만인 컬럼 제외
                if sample.str.match(r"^\d+(\.0)?$").mean() > 0.5:
                    continue
                vals = {_norm(v) for v in sample.tolist()}
                # 캠퍼스·주야 값만 있는 컬럼은 조로 쓰지 않음
                if vals <= {_norm(x) for x in CAMPUSES}:
                    continue
                if vals <= {_norm(x) for x in SHIFTS} | {_norm("주간"), _norm("야간")}:
                    continue
                team_col = c
                break

    long_ok = process_col is not None and (man_col is not None or out_col is not None)
    wide_ok = any(v["인력"] or v["실적"] for v in wide_map.values())

    return {
        "date_col": date_col,
        "team_col": team_col,
        "campus_col": campus_col,
        "shift_col": shift_col,
        "process_col": process_col,
        "manpower_col": man_col,
        "output_col": out_col,
        "wide_map": wide_map,
        "layout": "long" if long_ok and not wide_ok else ("wide" if wide_ok else "unknown"),
        "columns": cols,
    }


def _to_number(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False).str.replace("명", "", regex=False),
        errors="coerce",
    )


def _map_area_label(value: Any) -> str | None:
    n = _norm(value)
    if not n:
        return None
    for area, aliases in AREA_ALIASES.items():
        for a in aliases:
            if _norm(a) in n or n in _norm(a):
                return area
    return None


def _parse_dates(series: pd.Series) -> pd.Series:
    """YYYY-MM-DD 및 M-D(연도 추정) 지원."""
    s = series.copy()
    parsed = pd.to_datetime(s, errors="coerce")
    mask = parsed.isna() & s.notna()
    if mask.any():
        md = s[mask].astype(str).str.extract(r"^(\d{1,2})-(\d{1,2})$")
        if not md.empty:
            year = pd.Timestamp.today().year
            trial = pd.to_datetime(
                dict(year=year, month=pd.to_numeric(md[0], errors="coerce"), day=pd.to_numeric(md[1], errors="coerce")),
                errors="coerce",
            )
            parsed.loc[mask] = trial.values
    return parsed


def normalize_records(
    df: pd.DataFrame,
    layout: dict[str, Any] | None = None,
    *,
    source: str = "",
) -> pd.DataFrame:
    """표준 스키마: 일자, 조, 캠퍼스, 주야, 영역, 인력, 실적, source."""
    empty_cols = ["일자", "조", "캠퍼스", "주야", "영역", "인력", "실적", "source"]
    if df.empty:
        return pd.DataFrame(columns=empty_cols)
    info = layout or detect_layout(df)
    date_col = info.get("date_col")
    team_col = info.get("team_col")
    campus_col = info.get("campus_col")
    shift_col = info.get("shift_col")
    rows: list[dict] = []

    def _row_campus(r: pd.Series) -> str:
        if campus_col and campus_col in r.index:
            return _map_campus_label(r[campus_col])
        return "(미지정)"

    def _row_shift(r: pd.Series) -> str:
        if shift_col and shift_col in r.index:
            return _map_shift_label(r[shift_col])
        return "(미지정)"

    if info.get("layout") == "long" or (
        info.get("process_col") and (info.get("manpower_col") or info.get("output_col"))
    ):
        work = df.copy()
        if date_col:
            work["_date"] = _parse_dates(work[date_col])
        else:
            work["_date"] = pd.NaT
        work["_team"] = work[team_col].astype(str).str.strip() if team_col else "(미지정)"
        work["_area"] = work[info["process_col"]].map(_map_area_label)
        work = work[work["_area"].notna()]
        work["_man"] = _to_number(work[info["manpower_col"]]) if info.get("manpower_col") else 0
        work["_out"] = _to_number(work[info["output_col"]]) if info.get("output_col") else 0
        for _, r in work.iterrows():
            rows.append(
                {
                    "일자": r["_date"],
                    "조": r["_team"] if r["_team"] and r["_team"].lower() != "nan" else "(미지정)",
                    "캠퍼스": _row_campus(r),
                    "주야": _row_shift(r),
                    "영역": r["_area"],
                    "인력": float(r["_man"]) if pd.notna(r["_man"]) else 0.0,
                    "실적": float(r["_out"]) if pd.notna(r["_out"]) else 0.0,
                    "source": source,
                }
            )
    else:
        work = df.copy()
        if date_col:
            work["_date"] = _parse_dates(work[date_col])
        else:
            work["_date"] = pd.NaT
        work["_team"] = work[team_col].astype(str).str.strip() if team_col else "(미지정)"
        wide_map = info.get("wide_map") or {}
        for _, r in work.iterrows():
            team = r["_team"] if r["_team"] and str(r["_team"]).lower() != "nan" else "(미지정)"
            campus = _row_campus(r)
            shift = _row_shift(r)
            for area in AREAS:
                m = wide_map.get(area) or {}
                man_c, out_c = m.get("인력"), m.get("실적")
                man = float(_to_number(pd.Series([r[man_c]])).iloc[0] or 0) if man_c else 0.0
                out = float(_to_number(pd.Series([r[out_c]])).iloc[0] or 0) if out_c else 0.0
                if man == 0 and out == 0:
                    continue
                rows.append(
                    {
                        "일자": r["_date"],
                        "조": team,
                        "캠퍼스": campus,
                        "주야": shift,
                        "영역": area,
                        "인력": man,
                        "실적": out,
                        "source": source,
                    }
                )

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=empty_cols)
    out["일자"] = pd.to_datetime(out["일자"], errors="coerce")
    out["인력"] = pd.to_numeric(out["인력"], errors="coerce").fillna(0)
    out["실적"] = pd.to_numeric(out["실적"], errors="coerce").fillna(0)
    if "캠퍼스" not in out.columns:
        out["캠퍼스"] = "(미지정)"
    if "주야" not in out.columns:
        out["주야"] = "(미지정)"
    out["인당실적"] = out.apply(
        lambda r: (r["실적"] / r["인력"]) if r["인력"] else None,
        axis=1,
    )
    return out


def load_many(paths: list[Path], sheet_by_file: dict[str, str] | None = None) -> tuple[pd.DataFrame, list[str]]:
    sheet_by_file = sheet_by_file or {}
    frames: list[pd.DataFrame] = []
    notes: list[str] = []
    empty = pd.DataFrame(
        columns=["일자", "조", "캠퍼스", "주야", "영역", "인력", "실적", "인당실적", "source"]
    )
    for p in paths:
        try:
            if p.suffix.lower() == ".csv":
                df = read_excel_table(p)
                sheet = "csv"
            else:
                sheets = list_excel_sheets(p)
                sheet = sheet_by_file.get(p.name)
                if sheet is None:
                    sheet = sheets[0]
                df = read_excel_table(p, sheet)
            info = detect_layout(df)
            notes.append(
                f"{p.name} / sheet={sheet} / layout={info['layout']} / "
                f"일자={info['date_col']} / 조={info['team_col']} / "
                f"캠퍼스={info.get('campus_col')} / 주야={info.get('shift_col')}"
            )
            frames.append(normalize_records(df, info, source=p.name))
        except Exception as e:
            notes.append(f"{p.name}: 오류 — {e}")
    if not frames:
        return empty, notes
    all_df = pd.concat(frames, ignore_index=True)
    if "캠퍼스" not in all_df.columns:
        all_df["캠퍼스"] = "(미지정)"
    if "주야" not in all_df.columns:
        all_df["주야"] = "(미지정)"
    return all_df, notes


def filter_period(
    df: pd.DataFrame,
    *,
    mode: str,
    year: int | None = None,
    quarter: int | None = None,
    month: int | None = None,
    day: pd.Timestamp | None = None,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    if df.empty or "일자" not in df.columns:
        return df
    work = df.dropna(subset=["일자"]).copy()
    if mode == "전체":
        return work
    if mode == "기간" and start is not None and end is not None:
        return work[(work["일자"] >= start) & (work["일자"] <= end)]
    if mode == "년" and year is not None:
        return work[work["일자"].dt.year == year]
    if mode == "분기" and year is not None and quarter is not None:
        return work[(work["일자"].dt.year == year) & (work["일자"].dt.quarter == quarter)]
    if mode == "월" and year is not None and month is not None:
        return work[(work["일자"].dt.year == year) & (work["일자"].dt.month == month)]
    if mode == "일" and day is not None:
        d = pd.Timestamp(day).normalize()
        return work[work["일자"].dt.normalize() == d]
    return work


def daily_team_area(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["일자", "캠퍼스", "주야", "조", "영역", "인력", "실적", "인당실적"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    work = df.dropna(subset=["일자"]).copy()
    work["일자"] = work["일자"].dt.normalize()
    if "캠퍼스" not in work.columns:
        work["캠퍼스"] = "(미지정)"
    if "주야" not in work.columns:
        work["주야"] = "(미지정)"
    g = work.groupby(["일자", "캠퍼스", "주야", "조", "영역"], as_index=False).agg(
        인력=("인력", "sum"),
        실적=("실적", "sum"),
    )
    g["인당실적"] = g.apply(lambda r: r["실적"] / r["인력"] if r["인력"] else None, axis=1)
    return g.sort_values(["일자", "캠퍼스", "주야", "조", "영역"])


def summary_by(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    g = df.groupby(keys, as_index=False).agg(인력=("인력", "sum"), 실적=("실적", "sum"), 건수=("실적", "size"))
    g["인당실적"] = g.apply(lambda r: r["실적"] / r["인력"] if r["인력"] else None, axis=1)
    return g


def average_by_process(df: pd.DataFrame, keys: list[str] | None = None) -> pd.DataFrame:
    """공정(영역)별 평균 인력·평균 실적·평균 인당실적."""
    if df.empty:
        return pd.DataFrame()
    group_keys = keys or ["영역"]
    g = (
        df.groupby(group_keys, as_index=False)
        .agg(
            평균_인력=("인력", "mean"),
            평균_실적=("실적", "mean"),
            합계_인력=("인력", "sum"),
            합계_실적=("실적", "sum"),
            건수=("실적", "size"),
        )
    )
    g["평균_인력"] = g["평균_인력"].round(2)
    g["평균_실적"] = g["평균_실적"].round(2)
    g["인당실적"] = g.apply(
        lambda r: round(r["합계_실적"] / r["합계_인력"], 2) if r["합계_인력"] else None,
        axis=1,
    )
    if "영역" in g.columns:
        order = {a: i for i, a in enumerate(AREAS)}
        g["_ord"] = g["영역"].map(lambda x: order.get(x, 99))
        g = g.sort_values(["_ord"] + [k for k in group_keys if k != "영역"]).drop(columns="_ord")
    return g.reset_index(drop=True)


def group_vs_process_gap(df: pd.DataFrame, group_key: str) -> pd.DataFrame:
    """group_key×공정 실적·인당실적과, 같은 공정 내 group 평균 대비 차이(%)."""
    if df.empty or group_key not in df.columns:
        return pd.DataFrame()
    by_g = summary_by(df, [group_key, "영역"])
    area_mean = by_g.groupby("영역", as_index=False).agg(
        공정_그룹평균_실적=("실적", "mean"),
        공정_그룹평균_인당실적=("인당실적", "mean"),
    )
    out = by_g.merge(area_mean, on="영역", how="left")
    out["실적_대비공정평균%"] = out.apply(
        lambda r: round((r["실적"] / r["공정_그룹평균_실적"] - 1) * 100, 1)
        if r["공정_그룹평균_실적"]
        else None,
        axis=1,
    )
    out["인당실적_대비공정평균%"] = out.apply(
        lambda r: round((r["인당실적"] / r["공정_그룹평균_인당실적"] - 1) * 100, 1)
        if r["공정_그룹평균_인당실적"] and pd.notna(r["인당실적"])
        else None,
        axis=1,
    )
    order = {a: i for i, a in enumerate(AREAS)}
    out["_ord"] = out["영역"].map(lambda x: order.get(x, 99))
    out = out.sort_values(["_ord", group_key]).drop(columns="_ord")
    return out.reset_index(drop=True)


def team_vs_process_gap(df: pd.DataFrame) -> pd.DataFrame:
    """조×공정 대비 차이(%)."""
    return group_vs_process_gap(df, "조")


def format_display_df(df: pd.DataFrame) -> pd.DataFrame:
    """화면/CSV용 — 일자에서 시분초 제거."""
    if df.empty:
        return df
    out = df.copy()
    if "일자" in out.columns:
        out["일자"] = pd.to_datetime(out["일자"], errors="coerce").dt.strftime("%Y-%m-%d")
    return out


def add_calendar_parts(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["년"] = out["일자"].dt.year
    out["월"] = out["일자"].dt.month
    out["분기"] = out["일자"].dt.quarter
    out["년월"] = out["일자"].dt.strftime("%Y-%m")
    out["년분기"] = out["년"].astype(str) + "Q" + out["분기"].astype(str)
    return out
