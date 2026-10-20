"""캠퍼스 · 조별 실적 분석 (메인 화면)."""
from __future__ import annotations

import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import altair as alt
import pandas as pd
import streamlit as st

from app_common import (
    CAMPUSES,
    apply_basic_filters,
    load_records,
    render_data_sidebar,
    render_process_daily_avg,
    render_single_slicer,
    render_slicer,
    team_stack_order,
    timeseries_campus_team,
)
from auth import render_logout_controls
from stats_engine import AREAS, SHIFTS, add_calendar_parts, summary_by

_GRAIN_OPTS = ("일", "월", "분기", "년")


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
        year_labels = [str(y) for y in years]
        year_pick = render_single_slicer(
            "년도",
            year_labels,
            key="campus_rng_year_m",
            default=year_labels[-1] if year_labels else None,
        )
        year = int(year_pick) if year_pick else (years[-1] if years else None)
        out["year"] = year
        out["mode"] = "년"
        months_avail = sorted(
            work.loc[work["년"] == year, "월"].dropna().unique().astype(int).tolist()
        ) if year is not None else list(range(1, 13))
        if not months_avail:
            months_avail = list(range(1, 13))
        month_labels = [f"{m}월" for m in months_avail]
        month_sel_labels = render_slicer(
            "월",
            month_labels,
            key="campus_rng_months",
            default_on=True,
        )
        out["months"] = [int(x.replace("월", "")) for x in month_sel_labels]
    elif grain == "분기":
        year_labels = [str(y) for y in years]
        year_pick = render_single_slicer(
            "년도",
            year_labels,
            key="campus_rng_year_q",
            default=year_labels[-1] if year_labels else None,
        )
        year = int(year_pick) if year_pick else (years[-1] if years else None)
        out["year"] = year
        out["mode"] = "년"
        q_avail = sorted(
            work.loc[work["년"] == year, "분기"].dropna().unique().astype(int).tolist()
        ) if year is not None else [1, 2, 3, 4]
        if not q_avail:
            q_avail = [1, 2, 3, 4]
        q_labels = [f"{q}분기" for q in q_avail]
        q_sel_labels = render_slicer(
            "분기",
            q_labels,
            key="campus_rng_quarters",
            default_on=True,
        )
        out["quarters"] = [int(x.replace("분기", "")) for x in q_sel_labels]
    elif grain == "년":
        year_labels = [str(y) for y in years]
        year_sel_labels = render_slicer(
            "년도",
            year_labels,
            key="campus_rng_years",
            default_on=True,
        )
        out["years"] = [int(x) for x in year_sel_labels]
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
        grain = render_single_slicer(
            "시계열 단위",
            list(_GRAIN_OPTS),
            key="campus_grain",
            default="일",
        )
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
        area_sel = render_slicer(
            "영역",
            list(AREAS),
            key="campus_area",
            default_on=True,
        )
        shift_sel: list[str] = []
        if not records.empty:
            shifts = sorted(records["주야"].dropna().unique().tolist())
            prefer_s = [s for s in SHIFTS if s in shifts]
            shift_opts = prefer_s + [s for s in shifts if s not in prefer_s]
            shift_sel = render_slicer(
                "주/야",
                shift_opts,
                key="campus_shift",
                default_on=True,
            )
        else:
            st.caption("데이터 로드 후 기간·주/야 필터를 사용할 수 있습니다.")

        render_data_sidebar(key_prefix="campus_")

    if records.empty:
        st.error("표준 데이터가 없습니다. 사이드바에서 양식을 받아 업로드하세요.")
        st.stop()

    if not area_sel:
        st.warning("영역 필터에서 항목을 하나 이상 켜 주세요.")
        st.stop()
    if not shift_sel:
        st.warning("주/야 필터에서 항목을 하나 이상 켜 주세요.")
        st.stop()
    if grain == "월" and not (month_filter or []):
        st.warning("월 필터에서 항목을 하나 이상 켜 주세요.")
        st.stop()
    if grain == "분기" and not (quarter_filter or []):
        st.warning("분기 필터에서 항목을 하나 이상 켜 주세요.")
        st.stop()
    if grain == "년" and not (year_filter or []):
        st.warning("년도 필터에서 항목을 하나 이상 켜 주세요.")
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
        by_month = pd.DataFrame(columns=["년월", "조", "실적", "인력"])
        if "년월" in filtered.columns:
            src = filtered[filtered["캠퍼스"] == campus]
            if not src.empty:
                by_month = src.groupby(["년월", "조"], as_index=False).agg(
                    실적=("실적", "sum"),
                    인력=("인력", "sum"),
                )
        n_months = int(by_month["년월"].nunique()) if not by_month.empty else 0
        if n_months:
            month_avg = by_month.groupby("조", as_index=False).agg(실적=("실적", "sum"), 인력=("인력", "sum"))
            month_avg["월평균실적"] = month_avg["실적"] / n_months
            month_avg["월평균인력"] = month_avg["인력"] / n_months
            rank = rank.merge(month_avg[["조", "월평균실적", "월평균인력"]], on="조", how="left")
        else:
            rank["월평균실적"] = None
            rank["월평균인력"] = None
        rank = rank.sort_values("실적합계", ascending=False)

        def _avg(row: pd.Series, col: str) -> float | None:
            if col not in row.index or pd.isna(row[col]):
                return None
            return float(row[col])

        def _month_pp_gap(high: str, low: str) -> float | None:
            if by_month.empty:
                return None
            wide = by_month.pivot_table(index="년월", columns="조", values=["실적", "인력"], aggfunc="sum")
            gaps: list[float] = []
            for period in wide.index:
                try:
                    out_h = float(wide.loc[period, ("실적", high)])
                    man_h = float(wide.loc[period, ("인력", high)])
                    out_l = float(wide.loc[period, ("실적", low)])
                    man_l = float(wide.loc[period, ("인력", low)])
                except KeyError:
                    continue
                if pd.isna(man_h) or pd.isna(man_l) or man_h <= 0 or man_l <= 0:
                    continue
                gaps.append(out_h / man_h - out_l / man_l)
            if not gaps:
                return None
            return float(sum(gaps) / len(gaps))

        r1, r2, r3 = st.columns(3)
        if len(rank):
            top = rank.iloc[0]
            bot = rank.iloc[-1]
            diff_out = float(top["실적합계"]) - float(bot["실적합계"])
            top_m = _avg(top, "월평균실적")
            bot_m = _avg(bot, "월평균실적")
            with r1:
                st.metric("실적 상위 조", f"{top['조']}")
                st.caption(f"실적 {top['실적합계']:,.0f}")
                if top_m is not None:
                    st.caption(f"월평균 실적 {top_m:,.1f}")
            with r2:
                st.metric("실적 차이", f"{diff_out:,.0f}")
                st.caption(f"{top['조']} − {bot['조']}")
                if top_m is not None and bot_m is not None:
                    st.caption(f"월평균 실적 차이 {top_m - bot_m:,.1f}")
            with r3:
                st.metric("실적 하위 조", f"{bot['조']}")
                st.caption(f"실적 {bot['실적합계']:,.0f}")
                if bot_m is not None:
                    st.caption(f"월평균 실적 {bot_m:,.1f}")

            pp_rank = rank.dropna(subset=["인당실적"]).sort_values("인당실적", ascending=False)
            if not pp_rank.empty:
                pp_top = pp_rank.iloc[0]
                pp_bot = pp_rank.iloc[-1]
                diff_pp = float(pp_top["인당실적"]) - float(pp_bot["인당실적"])
                pp_top_out = _avg(pp_top, "월평균실적")
                pp_bot_out = _avg(pp_bot, "월평균실적")
                pp_top_man = _avg(pp_top, "월평균인력")
                pp_bot_man = _avg(pp_bot, "월평균인력")
                pp_month_gap = _month_pp_gap(str(pp_top["조"]), str(pp_bot["조"]))
                p1, p2, p3 = st.columns(3)
                with p1:
                    st.metric("인당실적 상위 조", f"{pp_top['조']}")
                    st.caption(f"인당실적 {pp_top['인당실적']:,.1f}")
                    if pp_top_out is not None:
                        st.caption(f"월평균 실적 {pp_top_out:,.1f}")
                    if pp_top_man is not None:
                        st.caption(f"월평균 인력 {pp_top_man:,.1f}")
                with p2:
                    st.metric("인당실적 차이", f"{diff_pp:,.1f}")
                    st.caption(f"{pp_top['조']} − {pp_bot['조']}")
                    if pp_month_gap is not None:
                        st.caption(f"월평균 인당실적 차이 {pp_month_gap:,.1f}")
                    if pp_top_out is not None and pp_bot_out is not None:
                        st.caption(f"월평균 실적 차이 {pp_top_out - pp_bot_out:,.1f}")
                    if pp_top_man is not None and pp_bot_man is not None:
                        st.caption(f"월평균 인력 차이 {pp_top_man - pp_bot_man:,.1f}")
                with p3:
                    st.metric("인당실적 하위 조", f"{pp_bot['조']}")
                    st.caption(f"인당실적 {pp_bot['인당실적']:,.1f}")
                    if pp_bot_out is not None:
                        st.caption(f"월평균 실적 {pp_bot_out:,.1f}")
                    if pp_bot_man is not None:
                        st.caption(f"월평균 인력 {pp_bot_man:,.1f}")
            if n_months:
                st.caption(f"월평균 = 선택한 기간 합계 ÷ {n_months}개월. 월평균 인당실적 차이는 달마다 인당실적 차이를 낸 뒤 그 평균입니다.")

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
    render_process_daily_avg(
        filtered,
        period_col="년월",
        period_label="월",
        split_campus=True,
    )

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
