"""월평균 추이 — 조 · 공정 상승/유지/하락."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app_common import (
    CAMPUSES,
    apply_basic_filters,
    load_records,
    render_data_sidebar,
    render_single_slicer,
    render_slicer,
    team_stack_order,
)
from auth import render_logout_controls
from stats_engine import AREAS, SHIFTS, add_calendar_parts


def _classify_mom(pct, hold_pct: float = 3.0) -> str:
    if pct is None or pd.isna(pct):
        return "비교불가"
    if abs(float(pct)) <= float(hold_pct):
        return "유지"
    return "상승" if float(pct) > 0 else "하락"


def _monthly_team_process_status(
    df: pd.DataFrame,
    *,
    current_month: str | None = None,
    hold_pct: float = 3.0,
) -> tuple[pd.DataFrame, pd.DataFrame, str | None, str | None]:
    """조×공정 월 일평균과 기준 월 vs 직전 월 판정."""
    empty = pd.DataFrame()
    if df.empty or "일자" not in df.columns or "영역" not in df.columns or "조" not in df.columns:
        return empty, empty, None, None

    work = add_calendar_parts(df.dropna(subset=["일자"]).copy())
    if work.empty or "년월" not in work.columns:
        return empty, empty, None, None

    stamps: list[pd.Timestamp] = []
    for v in work["일자"].tolist():
        try:
            t = pd.NaT if v is None or v == "" else pd.Timestamp(v)
            stamps.append(pd.NaT if pd.isna(t) else t.normalize())
        except (ValueError, TypeError, OverflowError):
            stamps.append(pd.NaT)
    work = work.copy()
    work["일자"] = pd.to_datetime(stamps, errors="coerce")
    work = work.dropna(subset=["일자"])
    work["년월"] = work["년월"].astype(str)
    if work.empty:
        return empty, empty, None, None

    daily = work.groupby(["일자", "년월", "조", "영역"], as_index=False).agg(
        인력=("인력", "sum"),
        실적=("실적", "sum"),
    )
    series = daily.groupby(["년월", "조", "영역"], as_index=False).agg(
        작업일수=("일자", "nunique"),
        합계_인력=("인력", "sum"),
        합계_실적=("실적", "sum"),
    )
    series["일평균_실적"] = (series["합계_실적"] / series["작업일수"]).round(1)
    series["인당실적"] = series.apply(
        lambda r: round(float(r["합계_실적"]) / float(r["합계_인력"]), 2) if r["합계_인력"] else None,
        axis=1,
    )
    order = {a: i for i, a in enumerate(AREAS)}
    series["_ord"] = series["영역"].map(lambda x: order.get(x, 99))
    series = series.sort_values(["년월", "조", "_ord"]).drop(columns="_ord").reset_index(drop=True)

    months = sorted(str(m) for m in series["년월"].dropna().unique().tolist())
    if not months:
        return empty, empty, None, None
    if current_month not in months:
        current_month = months[-1]
    prev_candidates = [m for m in months if m < current_month]
    prev_month = prev_candidates[-1] if prev_candidates else None

    cur = series[series["년월"] == current_month].copy()
    cur = cur.rename(
        columns={
            "일평균_실적": "당월_일평균",
            "작업일수": "당월_작업일수",
            "인당실적": "당월_인당실적",
        }
    )
    status_cols = [
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
    if prev_month is None:
        cur["전월"] = None
        cur["전월_일평균"] = None
        cur["전월_작업일수"] = None
        cur["차이"] = None
        cur["전월대비%"] = None
        cur["판정"] = "비교불가"
        status = cur[status_cols].rename(columns={"년월": "당월", "영역": "공정"})
        return series, status.reset_index(drop=True), current_month, None

    prev = series[series["년월"] == prev_month][["조", "영역", "일평균_실적", "작업일수"]].rename(
        columns={"일평균_실적": "전월_일평균", "작업일수": "전월_작업일수"}
    )
    status = cur.merge(prev, on=["조", "영역"], how="left")
    status["전월"] = prev_month
    status["차이"] = (status["당월_일평균"] - status["전월_일평균"]).round(1)
    status["전월대비%"] = status.apply(
        lambda r: round((float(r["당월_일평균"]) / float(r["전월_일평균"]) - 1) * 100, 1)
        if pd.notna(r["전월_일평균"]) and r["전월_일평균"]
        else None,
        axis=1,
    )
    status["판정"] = status["전월대비%"].map(lambda p: _classify_mom(p, hold_pct))
    status["_ord"] = status["영역"].map(lambda x: order.get(x, 99))
    status = status.sort_values(["_ord", "조"]).drop(columns="_ord")
    status = status[status_cols].rename(columns={"년월": "당월", "영역": "공정"})
    return series, status.reset_index(drop=True), current_month, prev_month


def _status_color(val: str) -> str:
    colors = {
        "상승": "color: #7dcea0",
        "유지": "color: #f7dc6f",
        "하락": "color: #f1948a",
        "비교불가": "color: #aab7b8",
    }
    return colors.get(str(val), "")


def render() -> None:
    st.title("월평균 추이")
    st.caption(
        "월평균(일평균 실적) = 그달 실적 합계 ÷ 작업일 수. "
        "기준 월을 직전 월과 비교해 조·공정별로 상승 / 유지 / 하락을 봅니다."
    )

    records, notes, _chosen = load_records()

    campus_sel: list[str] = []
    shift_sel: list[str] = []
    area_sel = list(AREAS)
    team_sel: list[str] = []
    hold_pct = 3.0
    current_month = ""

    with st.sidebar:
        st.header("계정")
        render_logout_controls()
        st.divider()
        st.header("조회 조건")
        if records.empty:
            st.caption("데이터가 로드되면 캠퍼스·주/야·영역·조를 선택할 수 있습니다.")
        else:
            work = add_calendar_parts(records)
            campuses = sorted(work["캠퍼스"].dropna().unique().tolist())
            prefer = [c for c in CAMPUSES if c in campuses]
            campus_sel = render_slicer(
                "캠퍼스",
                prefer + [c for c in campuses if c not in prefer],
                key="trend_campus",
                default_on=True,
            )
            shifts = sorted(work["주야"].dropna().unique().tolist())
            prefer_s = [s for s in SHIFTS if s in shifts]
            shift_sel = render_slicer(
                "주/야",
                prefer_s + [s for s in shifts if s not in prefer_s],
                key="trend_shift",
                default_on=True,
            )
            area_sel = render_slicer("영역", list(AREAS), key="trend_area", default_on=True)
            teams = sorted(work["조"].dropna().unique().tolist())
            team_sel = render_slicer("조", teams, key="trend_team", default_on=True) if teams else []

            months = sorted(
                str(m) for m in work["년월"].dropna().unique().tolist() if str(m) not in ("None", "<NA>", "nan")
            )
            current_month = render_single_slicer(
                "기준 월",
                months,
                key="trend_month",
                default=months[-1] if months else None,
            )
            hold_pct = st.slider(
                "유지 범위 (±%)",
                min_value=1,
                max_value=10,
                value=3,
                help="전월 대비 이 범위 안이면 유지로 봅니다.",
            )

        render_data_sidebar(key_prefix="trend_")

    if records.empty:
        st.error("표준 데이터가 없습니다. 사이드바에서 양식을 받아 업로드하세요.")
        st.stop()
    if not area_sel:
        st.warning("영역 필터에서 항목을 하나 이상 켜 주세요.")
        st.stop()
    if not shift_sel:
        st.warning("주/야 필터에서 항목을 하나 이상 켜 주세요.")
        st.stop()
    if not campus_sel:
        st.warning("캠퍼스 필터에서 항목을 하나 이상 켜 주세요.")
        st.stop()
    if not team_sel:
        st.warning("조 필터에서 항목을 하나 이상 켜 주세요.")
        st.stop()
    if not current_month:
        st.warning("비교할 월이 없습니다.")
        st.stop()

    with st.expander("로드 정보", expanded=False):
        for n in notes:
            st.write("- ", n)

    filtered = apply_basic_filters(
        records,
        area_sel=area_sel,
        campus_sel=campus_sel,
        shift_sel=shift_sel,
        team_sel=team_sel,
        mode="전체",
    )
    if filtered.empty:
        st.warning("선택 조건에 해당하는 데이터가 없습니다.")
        st.stop()

    series, status, cur_m, prev_m = _monthly_team_process_status(
        filtered,
        current_month=current_month,
        hold_pct=float(hold_pct),
    )
    if status.empty:
        st.warning("월평균으로 집계할 데이터가 없습니다.")
        st.stop()

    n_up = int((status["판정"] == "상승").sum())
    n_hold = int((status["판정"] == "유지").sum())
    n_down = int((status["판정"] == "하락").sum())
    n_na = int((status["판정"] == "비교불가").sum())

    st.markdown(
        f"**기준 월 {cur_m}**"
        + (f"  vs  전월 **{prev_m}**" if prev_m else "  ·  비교할 전월이 없습니다.")
        + f"  ·  유지 범위 ±{hold_pct:g}%"
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("상승", f"{n_up}건")
    with c2:
        st.metric("유지", f"{n_hold}건")
    with c3:
        st.metric("하락", f"{n_down}건")
    with c4:
        st.metric("비교불가", f"{n_na}건")

    teams_all = team_stack_order(sorted(status["조"].dropna().unique().tolist()))
    areas_all = [a for a in AREAS if a in set(status["공정"].tolist())]

    st.subheader("조 × 공정 — 당월 일평균")
    st.caption("숫자는 당월 일평균 실적. 화살표는 전월 대비입니다.")
    for area in areas_all:
        st.markdown(f"##### {area}")
        sub = status[status["공정"] == area]
        cols = st.columns(max(len(teams_all), 1))
        for col, team in zip(cols, teams_all):
            row = sub[sub["조"] == team]
            with col:
                if row.empty:
                    st.caption(f"{team} 없음")
                    continue
                r = row.iloc[0]
                pct = r["전월대비%"]
                judge = str(r["판정"])
                if pd.notna(pct):
                    delta = f"{float(pct):+.1f}% · {judge}"
                else:
                    delta = judge
                delta_color = "off" if judge in ("유지", "비교불가") else "normal"
                st.metric(
                    str(team),
                    f"{float(r['당월_일평균']):,.1f}" if pd.notna(r["당월_일평균"]) else "-",
                    delta=delta,
                    delta_color=delta_color,
                )

    st.subheader("판정표")
    show = status.copy()
    try:
        styled = show.style.map(_status_color, subset=["판정"])
        st.dataframe(styled, use_container_width=True)
    except Exception:
        st.dataframe(show, use_container_width=True)

    piv = status.pivot_table(index="조", columns="공정", values="판정", aggfunc="first")
    piv = piv.reindex(index=[t for t in teams_all if t in piv.index])
    piv = piv.reindex(columns=areas_all)
    st.markdown("##### 한눈에 보기 (행: 조, 열: 공정)")
    st.dataframe(piv, use_container_width=True)

    st.subheader("월별 일평균 추이")
    if series.empty:
        st.caption("표시할 시계열이 없습니다.")
        return
    chart_df = series.rename(columns={"영역": "공정"})
    if "조" in chart_df.columns:
        chart_df["_조순서"] = chart_df["조"].map(lambda x: teams_all.index(x) if x in teams_all else 99)
        chart_df = chart_df.sort_values(["공정", "_조순서", "년월"])
    chart = (
        alt.Chart(chart_df)
        .mark_line(point=True)
        .encode(
            x=alt.X("년월:N", title="월", sort=None),
            y=alt.Y("일평균_실적:Q", title="일평균 실적"),
            color=alt.Color("조:N", title="조", sort=teams_all),
            tooltip=["년월", "조", "공정", "일평균_실적", "작업일수", "인당실적"],
        )
        .properties(height=180)
        .facet(facet=alt.Facet("공정:N", title="공정", sort=list(AREAS)), columns=2)
    )
    st.altair_chart(chart, use_container_width=True)

    st.download_button(
        "조·공정 월평균 판정 CSV",
        data=status.to_csv(index=False).encode("utf-8-sig"),
        file_name="월평균_조공정_판정.csv",
        mime="text/csv",
        key="trend_dl_status",
    )
