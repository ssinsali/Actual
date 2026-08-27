"""캠퍼스 · 조별 실적 분석 (메인 화면)."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app_common import (
    CAMPUSES,
    apply_basic_filters,
    load_records,
    render_data_sidebar,
    team_stack_order,
    timeseries_campus_team,
)
from auth import render_logout_controls
from stats_engine import AREAS, SHIFTS, add_calendar_parts, summary_by


def _grain_period_widgets(records: pd.DataFrame, grain: str) -> dict:
    """시계열 단위별 기간 설정 → filter_period 인자."""
    out = {
        "mode": "전체",
        "year": None,
        "quarter": None,
        "month": None,
        "day": None,
        "start": None,
        "end": None,
        "months": None,
        "quarters": None,
        "years": None,
    }
    if records.empty or "일자" not in records.columns:
        return out

    work = add_calendar_parts(records)
    years = sorted(work["년"].dropna().unique().astype(int).tolist())
    min_d = work["일자"].min().date()
    max_d = work["일자"].max().date()

    st.caption("기간 설정")
    if grain == "일":
        rng = st.date_input(
            "일자 범위",
            value=(min_d, max_d),
            min_value=min_d,
            max_value=max_d,
            key="campus_rng_day",
        )
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            out["start"] = pd.Timestamp(rng[0])
            out["end"] = pd.Timestamp(rng[1])
            out["mode"] = "기간"
    elif grain == "월":
        year = st.selectbox("년도", years, index=len(years) - 1, key="campus_rng_year_m")
        out["year"] = int(year)
        out["mode"] = "년"
        months_avail = sorted(
            work.loc[work["년"] == year, "월"].dropna().unique().astype(int).tolist()
        )
        month_sel = st.multiselect(
            "월",
            months_avail if months_avail else list(range(1, 13)),
            default=months_avail if months_avail else list(range(1, 13)),
            key="campus_rng_months",
        )
        out["months"] = month_sel
    elif grain == "분기":
        year = st.selectbox("년도", years, index=len(years) - 1, key="campus_rng_year_q")
        out["year"] = int(year)
        out["mode"] = "년"
        q_avail = sorted(
            work.loc[work["년"] == year, "분기"].dropna().unique().astype(int).tolist()
        )
        quarter_sel = st.multiselect(
            "분기",
            q_avail if q_avail else [1, 2, 3, 4],
            default=q_avail if q_avail else [1, 2, 3, 4],
            format_func=lambda q: f"{q}분기",
            key="campus_rng_quarters",
        )
        out["quarters"] = quarter_sel
    elif grain == "년":
        year_sel = st.multiselect("년도", years, default=years, key="campus_rng_years")
        out["years"] = year_sel
    return out


def render() -> None:
    st.title("캠퍼스 · 조별 실적 분석")
    st.caption(
        "캠퍼스별,조별,주야별 분석. "
        "누적 막대: 아래 A조 · 중간 B조 · 위 C조."
    )

    records, notes, _chosen = load_records()

    period_args = {
        "mode": "전체",
        "year": None,
        "quarter": None,
        "month": None,
        "day": None,
        "start": None,
        "end": None,
    }
    month_filter: list[int] | None = None
    quarter_filter: list[int] | None = None
    year_filter: list[int] | None = None

    with st.sidebar:
        st.header("계정")
        render_logout_controls()
        st.divider()
        st.header("조회 조건")
        grain = st.radio("시계열 단위", ("일", "월", "분기", "년"), index=0, key="campus_grain")
        if not records.empty:
            scope = _grain_period_widgets(records, grain)
            period_args = {
                "mode": scope["mode"],
                "year": scope["year"],
                "quarter": scope["quarter"],
                "month": scope["month"],
                "day": scope["day"],
                "start": scope["start"],
                "end": scope["end"],
            }
            month_filter = scope.get("months")
            quarter_filter = scope.get("quarters")
            year_filter = scope.get("years")
        area_sel = st.multiselect(
            "영역 (기본=전체 합계)",
            list(AREAS),
            default=list(AREAS),
            key="campus_area",
        )
        shift_sel: list[str] = []
        if not records.empty:
            shifts = sorted(records["주야"].dropna().unique().tolist())
            prefer_s = [s for s in SHIFTS if s in shifts]
            shift_opts = prefer_s + [s for s in shifts if s not in prefer_s]
            shift_sel = st.multiselect("주/야 필터", shift_opts, default=shift_opts, key="campus_shift")
        else:
            st.caption("데이터 로드 후 기간·주/야 필터를 사용할 수 있습니다.")

        render_data_sidebar(key_prefix="campus_")

    if records.empty:
        st.error("표준 데이터가 없습니다. 사이드바에서 양식을 받아 업로드하세요.")
        st.stop()

    with st.expander("로드 정보", expanded=False):
        for n in notes:
            st.write("- ", n)

    filtered = apply_basic_filters(
        records,
        area_sel=area_sel or list(AREAS),
        shift_sel=shift_sel or None,
        mode=period_args["mode"],
        year=period_args["year"],
        quarter=period_args["quarter"],
        month=period_args["month"],
        day=period_args["day"],
        start=period_args["start"],
        end=period_args["end"],
    )
    if not filtered.empty:
        f2 = add_calendar_parts(filtered)
        if grain == "월" and month_filter:
            f2 = f2[f2["월"].isin(month_filter)]
        if grain == "분기" and quarter_filter:
            f2 = f2[f2["분기"].isin(quarter_filter)]
        if grain == "년" and year_filter:
            f2 = f2[f2["년"].isin(year_filter)]
        filtered = f2
    if filtered.empty:
        st.warning("선택 조건에 해당하는 데이터가 없습니다.")
        st.stop()

    ts = timeseries_campus_team(filtered, grain)
    if ts.empty:
        st.warning("시계열로 집계할 데이터가 없습니다.")
        st.stop()

    teams_all = team_stack_order(sorted(ts["조"].dropna().unique().tolist()))
    ord_map = {t: i for i, t in enumerate(teams_all)}
    ts = ts.copy()
    ts["조순서"] = ts["조"].map(lambda x: ord_map.get(x, 99))

    def _stacked_campus_chart(campus: str) -> None:
        sub = ts[ts["캠퍼스"] == campus]
        st.subheader(f"{campus} 캠퍼스")
        if sub.empty:
            st.caption(f"{campus} 데이터가 없습니다. (양식 K열 캠퍼스를 확인하세요)")
            return

        rank = sub.groupby("조", as_index=False).agg(실적합계=("실적", "sum"), 인력합계=("인력", "sum"))
        rank["인당실적"] = rank.apply(
            lambda r: r["실적합계"] / r["인력합계"] if r["인력합계"] else None, axis=1
        )
        rank = rank.sort_values("실적합계", ascending=False)
        r1, r2, r3 = st.columns(3)
        if len(rank):
            top = rank.iloc[0]
            bot = rank.iloc[-1]
            diff_out = float(top["실적합계"]) - float(bot["실적합계"])
            with r1:
                st.metric("실적 상위 조", f"{top['조']}")
                st.caption(f"실적 {top['실적합계']:,.0f}")
            with r2:
                st.metric("실적 차이", f"{diff_out:,.0f}")
                st.caption(f"{top['조']} − {bot['조']}")
            with r3:
                st.metric("실적 하위 조", f"{bot['조']}")
                st.caption(f"실적 {bot['실적합계']:,.0f}")

            pp_rank = rank.dropna(subset=["인당실적"]).sort_values("인당실적", ascending=False)
            if not pp_rank.empty:
                pp_top = pp_rank.iloc[0]
                pp_bot = pp_rank.iloc[-1]
                diff_pp = float(pp_top["인당실적"]) - float(pp_bot["인당실적"])
                p1, p2, p3 = st.columns(3)
                with p1:
                    st.metric("인당실적 상위 조", f"{pp_top['조']}")
                    st.caption(f"인당실적 {pp_top['인당실적']:,.1f}")
                with p2:
                    st.metric("인당실적 차이", f"{diff_pp:,.1f}")
                    st.caption(f"{pp_top['조']} − {pp_bot['조']}")
                with p3:
                    st.metric("인당실적 하위 조", f"{pp_bot['조']}")
                    st.caption(f"인당실적 {pp_bot['인당실적']:,.1f}")

        chart = (
            alt.Chart(sub)
            .mark_bar()
            .encode(
                x=alt.X("기간:N", sort=None, title=f"기간 ({grain})"),
                y=alt.Y("실적:Q", title="실적 (합계)", stack="zero"),
                color=alt.Color("조:N", title="조", sort=teams_all, scale=alt.Scale(domain=teams_all)),
                order=alt.Order("조순서:Q", sort="ascending"),
                tooltip=["기간", "캠퍼스", "조", "실적", "인력", "인당실적"],
            )
            .properties(height=360, title=f"{campus} · {grain}별 조 누적 실적 (아래 A→B→위 C)")
        )
        st.altair_chart(chart, use_container_width=True)
        st.dataframe(
            sub.pivot_table(index="기간", columns="조", values="실적", aggfunc="sum", fill_value=0)
            .reindex(columns=[c for c in teams_all if c in sub["조"].unique()]),
            use_container_width=True,
        )

    c_left, c_right = st.columns(2)
    with c_left:
        _stacked_campus_chart("천안")
    with c_right:
        _stacked_campus_chart("아산")

    other = [c for c in sorted(ts["캠퍼스"].unique()) if c not in CAMPUSES]
    if other:
        st.markdown("##### 기타 캠퍼스")
        for oc in other:
            _stacked_campus_chart(oc)

    st.divider()
    st.subheader("조별 주/야 차이")
    st.caption("같은 조에서 주간·야간 실적·인당실적 차이를 봅니다.")

    by_cts = summary_by(filtered, ["캠퍼스", "조", "주야"])
    if by_cts.empty:
        st.caption("표시할 데이터가 없습니다.")
        return

    st.dataframe(by_cts, use_container_width=True)
    piv = by_cts.pivot_table(
        index=["캠퍼스", "조"],
        columns="주야",
        values=["실적", "인당실적"],
        aggfunc="sum",
    )
    if isinstance(piv.columns, pd.MultiIndex):
        piv.columns = [f"{a}_{b}" for a, b in piv.columns]
    piv = piv.reset_index()
    if "인당실적_주" in piv.columns and "인당실적_야" in piv.columns:
        piv["인당실적_주야차이"] = piv["인당실적_주"] - piv["인당실적_야"]
    if "실적_주" in piv.columns and "실적_야" in piv.columns:
        piv["실적_주야차이"] = piv["실적_주"] - piv["실적_야"]
    st.markdown("##### 주 − 야 차이 (양수면 주간이 큼)")
    st.dataframe(piv, use_container_width=True)

    for campus in [c for c in CAMPUSES if c in by_cts["캠퍼스"].unique()]:
        sub = by_cts[by_cts["캠퍼스"] == campus]
        chart = (
            alt.Chart(sub)
            .mark_bar()
            .encode(
                x=alt.X("조:N", sort=teams_all, title="조"),
                y=alt.Y("실적:Q", title="실적"),
                color=alt.Color(
                    "주야:N",
                    sort=list(SHIFTS),
                    scale=alt.Scale(domain=list(SHIFTS)),
                    title="주/야",
                ),
                xOffset=alt.XOffset("주야:N", sort=list(SHIFTS)),
                tooltip=["캠퍼스", "조", "주야", "실적", "인당실적"],
            )
            .properties(height=300, title=f"{campus} · 조별 주/야 실적")
        )
        st.altair_chart(chart, use_container_width=True)
        chart2 = (
            alt.Chart(sub)
            .mark_bar()
            .encode(
                x=alt.X("조:N", sort=teams_all, title="조"),
                y=alt.Y("인당실적:Q", title="인당실적"),
                color=alt.Color(
                    "주야:N",
                    sort=list(SHIFTS),
                    scale=alt.Scale(domain=list(SHIFTS)),
                    title="주/야",
                ),
                xOffset=alt.XOffset("주야:N", sort=list(SHIFTS)),
                tooltip=["캠퍼스", "조", "주야", "인력", "실적", "인당실적"],
            )
            .properties(height=300, title=f"{campus} · 조별 주/야 인당실적")
        )
        st.altair_chart(chart2, use_container_width=True)
