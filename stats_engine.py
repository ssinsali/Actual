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


def _as_datetime(series: pd.Series) -> pd.Series:
    """일자 컬럼을 datetime64로. 문자열·캐시 복원·엑셀 일련번호·M-D를 허용."""
    if not isinstance(series, pd.Series):
        series = pd.Series(series)
    if series.empty:
        return pd.to_datetime(series, errors="coerce")

    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")

    parsed = pd.to_datetime(series, errors="coerce")
    try:
        mixed = pd.to_datetime(series, errors="coerce", format="mixed")
        better = mixed.notna() & parsed.isna()
        if better.any():
            parsed = parsed.mask(better, mixed)
    except (TypeError, ValueError):
        pass

    still = parsed.isna() & series.notna()
    if still.any():
        nums = pd.to_numeric(series, errors="coerce")
        excel_ok = still & nums.notna() & (nums >= 20000) & (nums <= 80000)
        if excel_ok.any():
            excel_dates = pd.to_datetime(
                nums, unit="D", origin="1899-12-30", errors="coerce"
            )
            parsed = parsed.mask(excel_ok, excel_dates)

    still = parsed.isna() & series.notna()
    if still.any():
        md = series[still].astype(str).str.extract(r"^(\d{1,2})-(\d{1,2})$")
        if not md.empty:
            year = pd.Timestamp.today().year
            trial = pd.to_datetime(
                {
                    "year": year,
                    "month": pd.to_numeric(md[0], errors="coerce"),
                    "day": pd.to_numeric(md[1], errors="coerce"),
                },
                errors="coerce",
            )
            trial.index = md.index
            hit = trial.dropna()
            if not hit.empty:
                parsed.loc[hit.index] = hit

    result = pd.to_datetime(parsed, errors="coerce")
    if pd.api.types.is_datetime64_any_dtype(result):
        return result
    converted: list[pd.Timestamp] = []
    for v in series.tolist():
        try:
            converted.append(pd.NaT if v is None or v == "" else pd.Timestamp(v))
        except (ValueError, TypeError, OverflowError):
            converted.append(pd.NaT)
    return pd.to_datetime(converted, errors="coerce")


def _parse_dates(series: pd.Series) -> pd.Series:
    """YYYY-MM-DD 및 M-D(연도 추정) 지원."""
    return _as_datetime(series)


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

    if info.get("layout") == "long" or (
        info.get("process_col") and (info.get("manpower_col") or info.get("output_col"))
    ):
        work = df.copy()
        if date_col:
            work["_date"] = _parse_dates(work[date_col])
        else:
            work["_date"] = pd.NaT
        work["_team"] = work[team_col].astype(str).str.strip() if team_col else "(미지정)"
        work["_team"] = work["_team"].where(
            work["_team"].notna() & (work["_team"].str.lower() != "nan"),
            "(미지정)",
        )
        work["_area"] = work[info["process_col"]].map(_map_area_label)
        work = work[work["_area"].notna()].copy()
        work["_man"] = _to_number(work[info["manpower_col"]]) if info.get("manpower_col") else 0.0
        work["_out"] = _to_number(work[info["output_col"]]) if info.get("output_col") else 0.0
        work["_man"] = pd.to_numeric(work["_man"], errors="coerce").fillna(0.0)
        work["_out"] = pd.to_numeric(work["_out"], errors="coerce").fillna(0.0)
        if campus_col and campus_col in work.columns:
            work["_campus"] = work[campus_col].map(_map_campus_label)
        else:
            work["_campus"] = "(미지정)"
        if shift_col and shift_col in work.columns:
            work["_shift"] = work[shift_col].map(_map_shift_label)
        else:
            work["_shift"] = "(미지정)"
        out = pd.DataFrame(
            {
                "일자": work["_date"].values,
                "조": work["_team"].values,
                "캠퍼스": work["_campus"].values,
                "주야": work["_shift"].values,
                "영역": work["_area"].values,
                "인력": work["_man"].values,
                "실적": work["_out"].values,
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
        work["_team"] = work["_team"].where(
            work["_team"].notna() & (work["_team"].str.lower() != "nan"),
            "(미지정)",
        )
        if campus_col and campus_col in work.columns:
            work["_campus"] = work[campus_col].map(_map_campus_label)
        else:
            work["_campus"] = "(미지정)"
        if shift_col and shift_col in work.columns:
            work["_shift"] = work[shift_col].map(_map_shift_label)
        else:
            work["_shift"] = "(미지정)"

        wide_map = info.get("wide_map") or {}
        parts: list[pd.DataFrame] = []
        for area in AREAS:
            m = wide_map.get(area) or {}
            man_c, out_c = m.get("인력"), m.get("실적")
            if not man_c and not out_c:
                continue
            piece = pd.DataFrame(
                {
                    "일자": work["_date"].values,
                    "조": work["_team"].values,
                    "캠퍼스": work["_campus"].values,
                    "주야": work["_shift"].values,
                    "영역": area,
                    "인력": _to_number(work[man_c]).fillna(0).values if man_c else 0.0,
                    "실적": _to_number(work[out_c]).fillna(0).values if out_c else 0.0,
                    "source": source,
                }
            )
            piece = piece[(piece["인력"] != 0) | (piece["실적"] != 0)]
            if not piece.empty:
                parts.append(piece)
        out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=empty_cols)

    if out.empty:
        return pd.DataFrame(columns=empty_cols)
    out["일자"] = _as_datetime(out["일자"])
    out["인력"] = pd.to_numeric(out["인력"], errors="coerce").fillna(0)
    out["실적"] = pd.to_numeric(out["실적"], errors="coerce").fillna(0)
    if "캠퍼스" not in out.columns:
        out["캠퍼스"] = "(미지정)"
    if "주야" not in out.columns:
        out["주야"] = "(미지정)"
    man = out["인력"].astype(float)
    out["인당실적"] = (out["실적"].astype(float) / man).where(man > 0)
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
    if "일자" in all_df.columns:
        all_df["일자"] = _as_datetime(all_df["일자"])
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
    work = df.copy()
    work["일자"] = _as_datetime(work["일자"])
    work = work.dropna(subset=["일자"])
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
    work["일자"] = _as_datetime(work["일자"]).dt.normalize()
    work = work.dropna(subset=["일자"])
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
    """일자에서 년·월·분기를 만든다. Series.dt 는 Cloud pandas에서 깨질 수 있어 쓰지 않는다."""
    if df.empty or "일자" not in df.columns:
        return df
    out = df.copy()
    stamps: list[pd.Timestamp] = []
    years: list[int | None] = []
    months: list[int | None] = []
    quarters: list[int | None] = []
    yms: list[str | None] = []
    yqs: list[str | None] = []
    for v in out["일자"].tolist():
        try:
            t = pd.NaT if v is None or v == "" else pd.Timestamp(v)
        except (ValueError, TypeError, OverflowError):
            t = pd.NaT
        if pd.isna(t):
            stamps.append(pd.NaT)
            years.append(None)
            months.append(None)
            quarters.append(None)
            yms.append(None)
            yqs.append(None)
            continue
        stamps.append(t)
        years.append(int(t.year))
        months.append(int(t.month))
        quarters.append(int(t.quarter))
        yms.append(f"{t.year:04d}-{t.month:02d}")
        yqs.append(f"{t.year}Q{t.quarter}")
    out["일자"] = pd.to_datetime(stamps, errors="coerce")
    out["년"] = pd.array(years, dtype="Int64")
    out["월"] = pd.array(months, dtype="Int64")
    out["분기"] = pd.array(quarters, dtype="Int64")
    out["년월"] = yms
    out["년분기"] = yqs
    return out


def period_daily_average(
    df: pd.DataFrame,
    period_col: str = "년월",
    extra_keys: list[str] | None = None,
) -> pd.DataFrame:
    """기간×공정 일평균 실적.

    같은 날의 조·주야·캠퍼스 행은 하루로 합친 뒤,
    일평균_실적 = 기간 합계 실적 ÷ 작업일 수(일자 중복 제거).
    월마다 근무일 수가 달라도 공정·월끼리 비교할 수 있습니다.
    """
    extras = list(extra_keys or [])
    empty_cols = [
        period_col,
        *extras,
        "영역",
        "작업일수",
        "합계_인력",
        "합계_실적",
        "일평균_인력",
        "일평균_실적",
        "인당실적",
        "전기대비%",
    ]
    if df.empty or "일자" not in df.columns or "영역" not in df.columns:
        return pd.DataFrame(columns=empty_cols)

    work = add_calendar_parts(df.dropna(subset=["일자"]).copy())
    work["일자"] = _normalize_dates(work["일자"])
    work = work.dropna(subset=["일자"])
    extras = [k for k in extras if k in work.columns]
    if period_col not in work.columns or work.empty:
        return pd.DataFrame(columns=empty_cols)

    work[period_col] = work[period_col].astype(str)
    daily_keys = ["일자", period_col, *extras, "영역"]
    daily = work.groupby(daily_keys, as_index=False).agg(
        인력=("인력", "sum"),
        실적=("실적", "sum"),
    )
    group_keys = [period_col, *extras, "영역"]
    g = daily.groupby(group_keys, as_index=False).agg(
        작업일수=("일자", "nunique"),
        합계_인력=("인력", "sum"),
        합계_실적=("실적", "sum"),
    )
    g["일평균_인력"] = (g["합계_인력"] / g["작업일수"]).round(2)
    g["일평균_실적"] = (g["합계_실적"] / g["작업일수"]).round(1)
    g["인당실적"] = g.apply(
        lambda r: round(float(r["합계_실적"]) / float(r["합계_인력"]), 2)
        if r["합계_인력"]
        else None,
        axis=1,
    )
    g = g.sort_values([*extras, "영역", period_col])
    g["전기대비%"] = (
        g.groupby([*extras, "영역"], dropna=False)["일평균_실적"].pct_change() * 100
    ).round(1)
    order = {a: i for i, a in enumerate(AREAS)}
    g["_ord"] = g["영역"].map(lambda x: order.get(x, 99))
    g = g.sort_values([period_col, *extras, "_ord"]).drop(columns="_ord")
    return g.reset_index(drop=True)


def _normalize_dates(series: pd.Series) -> pd.Series:
    """일자에서 시분초를 제거. Series.dt 를 쓰지 않는다."""
    out: list[pd.Timestamp] = []
    for v in series.tolist():
        try:
            t = pd.NaT if v is None or v == "" else pd.Timestamp(v)
            out.append(pd.NaT if pd.isna(t) else t.normalize())
        except (ValueError, TypeError, OverflowError):
            out.append(pd.NaT)
    return pd.to_datetime(out, errors="coerce")


def classify_mom(pct: float | None, hold_pct: float = 3.0) -> str:
    """전월 대비 % → 상승/유지/하락."""
    if pct is None or pd.isna(pct):
        return "비교불가"
    if abs(float(pct)) <= float(hold_pct):
        return "유지"
    return "상승" if float(pct) > 0 else "하락"


def monthly_team_process_status(
    df: pd.DataFrame,
    *,
    current_month: str | None = None,
    hold_pct: float = 3.0,
) -> tuple[pd.DataFrame, pd.DataFrame, str | None, str | None]:
    """조×공정 월 일평균과, 기준 월 vs 직전 월 판정.

    일평균_실적 = 그달 실적 합계 ÷ 작업일 수.
    반환: (월별 시계열, 당월 대비표, 당월, 전월)
    """
    empty = pd.DataFrame()
    series = period_daily_average(df, "년월", extra_keys=["조"])
    if series.empty or "년월" not in series.columns:
        return empty, empty, None, None

    months = sorted(str(m) for m in series["년월"].dropna().unique().tolist())
    if not months:
        return empty, empty, None, None
    if current_month not in months:
        current_month = months[-1]
    prev_candidates = [m for m in months if m < current_month]
    prev_month = prev_candidates[-1] if prev_candidates else None

    cur = series[series["년월"].astype(str) == current_month].copy()
    cur = cur.rename(
        columns={
            "일평균_실적": "당월_일평균",
            "작업일수": "당월_작업일수",
            "인당실적": "당월_인당실적",
        }
    )
    if prev_month is None:
        cur["전월"] = None
        cur["전월_일평균"] = None
        cur["전월_작업일수"] = None
        cur["차이"] = None
        cur["전월대비%"] = None
        cur["판정"] = "비교불가"
        status = cur[
            [
                "조",
                "영역",
                "전월",
                "년월",
                "전월_일평균",
                "당월_일평균",
                "차이",
                "전월대비%",
                "판정",
                "당월_작업일수",
                "당월_인당실적",
            ]
        ].rename(columns={"년월": "당월", "영역": "공정"})
        return series, status.reset_index(drop=True), current_month, None

    prev = series[series["년월"].astype(str) == prev_month][
        ["조", "영역", "일평균_실적", "작업일수"]
    ].rename(columns={"일평균_실적": "전월_일평균", "작업일수": "전월_작업일수"})
    status = cur.merge(prev, on=["조", "영역"], how="left")
    status["전월"] = prev_month
    status["차이"] = (status["당월_일평균"] - status["전월_일평균"]).round(1)
    status["전월대비%"] = status.apply(
        lambda r: round((float(r["당월_일평균"]) / float(r["전월_일평균"]) - 1) * 100, 1)
        if pd.notna(r["전월_일평균"]) and r["전월_일평균"]
        else None,
        axis=1,
    )
    status["판정"] = status["전월대비%"].map(lambda p: classify_mom(p, hold_pct))
    order = {a: i for i, a in enumerate(AREAS)}
    status["_ord"] = status["영역"].map(lambda x: order.get(x, 99))
    status = status.sort_values(["_ord", "조"]).drop(columns="_ord")
    cols = [
        "조",
        "영역",
        "전월",
        "년월",
        "전월_일평균",
        "당월_일평균",
        "차이",
        "전월대비%",
        "판정",
        "당월_작업일수",
        "당월_인당실적",
    ]
    status = status[cols].rename(columns={"년월": "당월", "영역": "공정"})
    return series, status.reset_index(drop=True), current_month, prev_month
