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
    compare_month: str | None = None,
    hold_pct: float = 3.0,
) -> tuple[pd.DataFrame, pd.DataFrame, str | None, str | None]:
    """조×공정 월 일평균과 기준 월 대비 비교 월 판정."""
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
    if compare_month not in months or compare_month == current_month:
        prev_candidates = [m for m in months if m < current_month]
        compare_month = prev_candidates[-1] if prev_candidates else None

    cur = series[series["년월"] == current_month].copy()
    cur = cur.rename(
        columns={
            "일평균_실적": "기준월_일평균",
            "작업일수": "기준월_작업일수",
            "인당실적": "기준월_인당실적",
        }
    )
    status_cols = [
        "조",
        "영역",
        "비교월",
        "년월",
        "비교월_일평균",
        "기준월_일평균",
        "차이",
        "기준월대비%",
        "판정",
        "기준월_작업일수",
        "기준월_인당실적",
    ]
    if compare_month is None:
        cur["비교월"] = None
        cur["비교월_일평균"] = None
        cur["비교월_작업일수"] = None
        cur["차이"] = None
        cur["기준월대비%"] = None
        cur["판정"] = "비교불가"
        status = cur[status_cols].rename(columns={"년월": "기준월", "영역": "공정"})
        return series, status.reset_index(drop=True), current_month, None

    prev = series[series["년월"] == compare_month][["조", "영역", "일평균_실적", "작업일수"]].rename(
        columns={"일평균_실적": "비교월_일평균", "작업일수": "비교월_작업일수"}
    )
    status = cur.merge(prev, on=["조", "영역"], how="left")
    status["비교월"] = compare_month
    status["차이"] = (status["비교월_일평균"] - status["기준월_일평균"]).round(1)
    status["기준월대비%"] = status.apply(
        lambda r: round((float(r["비교월_일평균"]) / float(r["기준월_일평균"]) - 1) * 100, 1)
        if pd.notna(r["기준월_일평균"]) and r["기준월_일평균"]
        else None,
        axis=1,
    )
    status["판정"] = status["기준월대비%"].map(lambda p: _classify_mom(p, hold_pct))
    status["_ord"] = status["영역"].map(lambda x: order.get(x, 99))
    status = status.sort_values(["_ord", "조"]).drop(columns="_ord")
    status = status[status_cols].rename(columns={"년월": "기준월", "영역": "공정"})
    return series, status.reset_index(drop=True), current_month, compare_month


def _status_color(val: str) -> str:
    colors = {
        "상승": "color: #7dcea0",
        "유지": "color: #f7dc6f",
        "하락": "color: #f1948a",
        "비교불가": "color: #aab7b8",
    }
    return colors.get(str(val), "")


def _team_avg_gap(status: pd.DataFrame, teams_all: list[str]) -> pd.DataFrame:
    """조별 공정 일평균의 산술평균과, 기준월·전체 조 평균 대비 차이."""
    if status.empty:
        return pd.DataFrame()
    g = status.groupby("조", as_index=False).agg(
        비교월_일평균=("비교월_일평균", "mean"),
        기준월_일평균=("기준월_일평균", "mean"),
        공정수=("공정", "nunique"),
    )
    g["비교월_일평균"] = g["비교월_일평균"].round(1)
    g["기준월_일평균"] = g["기준월_일평균"].round(1)
    g["기준월대비_차이"] = (g["비교월_일평균"] - g["기준월_일평균"]).round(1)
    g["기준월대비%"] = g.apply(
        lambda r: round((float(r["비교월_일평균"]) / float(r["기준월_일평균"]) - 1) * 100, 1)
        if pd.notna(r["기준월_일평균"]) and r["기준월_일평균"]
        else None,
        axis=1,
    )
    overall = g["기준월_일평균"].mean()
    g["조평균대비_차이"] = (g["기준월_일평균"] - overall).round(1)
    g["조평균대비%"] = g.apply(
        lambda r: round((float(r["기준월_일평균"]) / float(overall) - 1) * 100, 1)
        if overall
        else None,
        axis=1,
    )
    g["_ord"] = g["조"].map(lambda x: teams_all.index(x) if x in teams_all else 99)
    return g.sort_values("_ord").drop(columns="_ord").reset_index(drop=True)


def _status_base_view(status: pd.DataFrame, cur_m: str | None) -> pd.DataFrame:
    """기준월 막대용. 툴팁에 쓸 컬럼만 남긴다."""
    return pd.DataFrame(
        {
            "조": status["조"],
            "공정": status["공정"],
            "기준월": cur_m,
            "일평균": status["기준월_일평균"],
            "작업일수": status["기준월_작업일수"],
            "인당실적": status["기준월_인당실적"],
        }
    )


def _team_mean_overlay(
    df: pd.DataFrame,
    x: str,
    y: str,
    *,
    team_col: str = "조",
    color: str | None = None,
    x_sort=None,
    color_sort=None,
) -> alt.Chart | None:
    """선택한 조들의 평균을 선·숫자로 겹친다."""
    if df.empty or team_col not in df.columns or y not in df.columns or x not in df.columns:
        return None
    n_teams = int(df[team_col].nunique())
    if n_teams < 2:
        return None
    mean_title = f"{n_teams}개조 평균"
    group_cols = [c for c in (x, color) if c and c != team_col and c in df.columns]
    if not group_cols:
        group_cols = [x]
    means = df.groupby(group_cols, as_index=False)[y].mean()
    means[y] = means[y].round(1)
    means["평균라벨"] = means[y].map(lambda v: f"{float(v):.1f}")

    if x != team_col:
        line = (
            alt.Chart(means)
            .mark_line(point=True, color="#f7dc6f", strokeWidth=2)
            .encode(
                x=alt.X(f"{x}:N", sort=x_sort),
                y=alt.Y(f"{y}:Q"),
                tooltip=[x, alt.Tooltip(f"{y}:Q", title=mean_title)],
            )
        )
        text = (
            alt.Chart(means)
            .mark_text(dy=-14, fontWeight="bold", color="#f7dc6f", fontSize=12)
            .encode(
                x=alt.X(f"{x}:N", sort=x_sort),
                y=alt.Y(f"{y}:Q"),
                text="평균라벨:N",
            )
        )
        return line + text

    teams = [t for t in (x_sort or []) if t in set(df[team_col].astype(str))]
    if not teams:
        teams = sorted(str(t) for t in df[team_col].dropna().unique().tolist())
    rows: list[dict] = []
    for _, r in means.iterrows():
        for t in teams:
            rec = {team_col: t, y: r[y], "평균라벨": r["평균라벨"], "_평균구분": mean_title}
            if color and color in means.columns:
                rec[color] = r[color]
            rows.append(rec)
    long = pd.DataFrame(rows)
    if long.empty:
        return None
    line_enc = {
        "x": alt.X(f"{x}:N", sort=x_sort),
        "y": alt.Y(f"{y}:Q"),
        "tooltip": [c for c in (color, y) if c] + [alt.Tooltip("_평균구분:N", title="구분")],
    }
    if color and color in long.columns:
        line_enc["color"] = alt.Color(
            f"{color}:N",
            sort=color_sort,
            legend=None,
            scale=alt.Scale(domain=color_sort) if color_sort else alt.Undefined,
        )
    line = alt.Chart(long).mark_line(strokeDash=[6, 3], strokeWidth=2, point=True).encode(**line_enc)
    last = long[long[team_col] == teams[-1]] if teams else long
    text_enc = {
        "x": alt.X(f"{x}:N", sort=x_sort),
        "y": alt.Y(f"{y}:Q"),
        "text": "평균라벨:N",
    }
    if color and color in last.columns:
        text_enc["color"] = alt.Color(f"{color}:N", sort=color_sort, legend=None)
    text = alt.Chart(last).mark_text(dx=10, align="left", fontWeight="bold", fontSize=11).encode(**text_enc)
    return line + text


def _bar(
    df: pd.DataFrame,
    x: str,
    y: str,
    *,
    color: str | None,
    title: str,
    x_sort,
    color_sort=None,
    tooltip=None,
    y_title: str | None = None,
    team_mean: bool = False,
) -> None:
    if df.empty or y not in df.columns:
        st.caption("표시할 데이터가 없습니다.")
        return
    tips = tooltip
    if tips is None:
        tips = [c for c in (x, color, y) if c]
    enc = {
        "x": alt.X(f"{x}:N", title=x, sort=x_sort),
        "y": alt.Y(f"{y}:Q", title=y_title or y),
        "tooltip": tips,
    }
    if color and color in df.columns:
        enc["color"] = alt.Color(
            f"{color}:N",
            title=color,
            sort=color_sort,
            scale=alt.Scale(domain=color_sort) if color_sort else alt.Undefined,
        )
        enc["xOffset"] = alt.XOffset(f"{color}:N", sort=color_sort) if color_sort else f"{color}:N"
    bars = alt.Chart(df).mark_bar().encode(**enc)
    overlay = (
        _team_mean_overlay(
            df,
            x,
            y,
            team_col="조",
            color=color,
            x_sort=x_sort,
            color_sort=color_sort,
        )
        if team_mean
        else None
    )
    chart = alt.layer(bars, overlay).resolve_scale(color="independent") if overlay is not None else bars
    chart = chart.properties(height=360, title=title)
    st.altair_chart(chart, use_container_width=True)


def _signed_bar(df: pd.DataFrame, x: str, y: str, *, title: str, x_sort) -> None:
    if df.empty or y not in df.columns:
        st.caption("표시할 데이터가 없습니다.")
        return
    work = df.dropna(subset=[y]).copy()
    if work.empty:
        st.caption("표시할 데이터가 없습니다.")
        return
    work["_양수"] = work[y].fillna(0) >= 0
    chart = (
        alt.Chart(work)
        .mark_bar()
        .encode(
            x=alt.X(f"{x}:N", title=x, sort=x_sort),
            y=alt.Y(f"{y}:Q", title=y),
            color=alt.Color(
                "_양수:N",
                scale=alt.Scale(domain=[True, False], range=["#7dcea0", "#f1948a"]),
                legend=None,
            ),
            tooltip=["조", x, y] if x != "조" else ["조", y],
        )
        .properties(height=300, title=title)
    )
    st.altair_chart(chart, use_container_width=True)


def render() -> None:
    st.title("월평균 추이")
    st.caption(
        "월평균(일평균 실적) = 그달 실적 합계 ÷ 작업일 수. "
        "비교 월을 기준 월 대비로 봐서 조·공정별로 상승 / 유지 / 하락을 봅니다. "
        "비교월이 기준월보다 크면 +, 작으면 −."
    )

    records, notes, _chosen = load_records()

    campus_sel: list[str] = []
    shift_sel: list[str] = []
    area_sel = list(AREAS)
    team_sel: list[str] = []
    hold_pct = 3.0
    current_month = ""
    compare_month = ""

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
            compare_opts = [m for m in months if m != current_month]
            if not compare_opts:
                compare_opts = list(months)
            default_cmp = None
            earlier = [m for m in months if m < current_month]
            if earlier:
                default_cmp = earlier[-1]
            elif compare_opts:
                default_cmp = compare_opts[0]
            compare_month = render_single_slicer(
                "비교 월",
                compare_opts,
                key="trend_compare_month",
                default=default_cmp,
            )
            hold_pct = st.slider(
                "유지 범위 (±%)",
                min_value=1,
                max_value=10,
                value=3,
                help="비교 월이 기준 월 대비 이 범위 안이면 유지로 봅니다.",
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
        st.warning("기준 월을 선택해 주세요.")
        st.stop()
    if not compare_month:
        st.warning("비교 월을 선택해 주세요.")
        st.stop()
    if compare_month == current_month:
        st.warning("기준 월과 비교 월을 서로 다르게 선택해 주세요.")
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
        compare_month=compare_month,
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
        (
            f"**비교 월 {prev_m}**  vs  기준 월 **{cur_m}**"
            if prev_m
            else f"**기준 월 {cur_m}**  ·  비교 월이 없습니다."
        )
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
    team_gap = _team_avg_gap(status, teams_all)

    st.subheader("조별 비교 (막대)")
    st.caption(
        "기준월 일평균 실적. 같은 공정에서 조끼리, 같은 조에서 비교월·기준월을 비교합니다. "
        "노란 선·숫자는 조회에서 켠 조들의 평균입니다."
    )
    base_view = _status_base_view(status, cur_m)
    base_tip = ["조", "공정", "기준월", "일평균", "작업일수", "인당실적"]
    _bar(
        base_view,
        "공정",
        "일평균",
        color="조",
        title=f"기준월 {cur_m} · 공정별 조 비교 (일평균 실적)",
        x_sort=areas_all,
        color_sort=teams_all,
        tooltip=base_tip,
        y_title="일평균 실적",
        team_mean=True,
    )
    cmp_label = f"비교월 {prev_m}" if prev_m else "비교월"
    cur_label = f"기준월 {cur_m}" if cur_m else "기준월"
    cmp_rows = []
    for _, r in status.iterrows():
        if pd.notna(r.get("기준월_일평균")):
            cmp_rows.append({"조": r["조"], "공정": r["공정"], "구분": cur_label, "일평균": r["기준월_일평균"]})
        if pd.notna(r.get("비교월_일평균")):
            cmp_rows.append({"조": r["조"], "공정": r["공정"], "구분": cmp_label, "일평균": r["비교월_일평균"]})
    cmp_df = pd.DataFrame(cmp_rows)
    if not cmp_df.empty:
        st.markdown("##### 공정별 · 기준월 vs 비교월")
        n_teams = int(cmp_df["조"].nunique())
        mean_title = f"{n_teams}개조 평균"
        bars = (
            alt.Chart(cmp_df)
            .mark_bar()
            .encode(
                x=alt.X("조:N", title="조", sort=teams_all),
                y=alt.Y("일평균:Q", title="일평균 실적"),
                color=alt.Color(
                    "구분:N",
                    title="월",
                    sort=[cur_label, cmp_label],
                    scale=alt.Scale(domain=[cur_label, cmp_label]),
                ),
                xOffset=alt.XOffset("구분:N", sort=[cur_label, cmp_label]),
                tooltip=["조", "공정", "구분", "일평균"],
            )
        )
        layers: list[alt.Chart] = [bars]
        if n_teams >= 2:
            avg = cmp_df.groupby(["공정", "구분"], as_index=False)["일평균"].mean()
            avg["일평균"] = avg["일평균"].round(1)
            avg["평균라벨"] = avg["일평균"].map(lambda v: f"{float(v):.1f}")
            avg["조"] = teams_all[-1] if teams_all else ""
            layers.append(
                alt.Chart(avg)
                .mark_rule(strokeDash=[6, 4], strokeWidth=2)
                .encode(
                    y="일평균:Q",
                    color=alt.Color(
                        "구분:N",
                        title="월",
                        sort=[cur_label, cmp_label],
                        scale=alt.Scale(domain=[cur_label, cmp_label]),
                        legend=None,
                    ),
                    tooltip=["공정", "구분", alt.Tooltip("일평균:Q", title=mean_title)],
                )
            )
            layers.append(
                alt.Chart(avg)
                .mark_text(dx=14, dy=-8, fontWeight="bold", fontSize=11)
                .encode(
                    x=alt.X("조:N", sort=teams_all),
                    y="일평균:Q",
                    text="평균라벨:N",
                    color=alt.Color(
                        "구분:N",
                        sort=[cur_label, cmp_label],
                        scale=alt.Scale(domain=[cur_label, cmp_label]),
                        legend=None,
                    ),
                )
            )
        facet_chart = (
            alt.layer(*layers)
            .resolve_scale(color="independent")
            .properties(height=380, width=520)
            .facet(facet=alt.Facet("공정:N", title="공정", sort=list(AREAS)), columns=2)
            .resolve_scale(y="independent")
        )
        st.altair_chart(facet_chart, use_container_width=True)

    _bar(
        base_view,
        "조",
        "일평균",
        color="공정",
        title=f"기준월 {cur_m} · 조별 공정 비교 (일평균 실적)",
        x_sort=teams_all,
        color_sort=areas_all,
        tooltip=base_tip,
        y_title="일평균 실적",
        team_mean=True,
    )

    st.subheader("조별 평균 차이")
    st.caption(
        f"조별 평균 = 그 조의 공정 일평균을 산술평균. "
        f"비교월={prev_m or '-'} / 기준월={cur_m or '-'}. "
        "기준월대비 차이 = 비교월 조평균 − 기준월 조평균 (비교월이 작으면 −). "
        "조평균대비 차이 = 기준월 조평균 − 전체 조 평균(양수면 전체보다 높음)."
    )
    if team_gap.empty:
        st.caption("조별 평균을 계산할 데이터가 없습니다.")
    else:
        show_gap = team_gap.copy()
        if prev_m:
            show_gap.insert(1, "비교월", prev_m)
        if cur_m:
            show_gap.insert(2 if prev_m else 1, "기준월", cur_m)
        st.dataframe(show_gap, use_container_width=True)
        g1, g2 = st.columns(2)
        with g1:
            _signed_bar(
                team_gap,
                "조",
                "기준월대비_차이",
                title="조별 기준월 대비 평균 차이 (비교월 − 기준월)",
                x_sort=teams_all,
            )
        with g2:
            _signed_bar(
                team_gap,
                "조",
                "조평균대비_차이",
                title="조별 전체평균 대비 차이 (기준월 − 전체 조 평균)",
                x_sort=teams_all,
            )
        team_long = []
        for _, r in team_gap.iterrows():
            if pd.notna(r.get("기준월_일평균")):
                team_long.append({"조": r["조"], "구분": cur_label, "조평균": r["기준월_일평균"]})
            if pd.notna(r.get("비교월_일평균")):
                team_long.append({"조": r["조"], "구분": cmp_label, "조평균": r["비교월_일평균"]})
        _bar(
            pd.DataFrame(team_long),
            "조",
            "조평균",
            color="구분",
            title="조별 평균 — 기준월 vs 비교월",
            x_sort=teams_all,
            color_sort=[cur_label, cmp_label],
        )

    with st.expander("판정표 · 상세 숫자", expanded=False):
        try:
            styled = status.style.map(_status_color, subset=["판정"])
            st.dataframe(styled, use_container_width=True)
        except Exception:
            st.dataframe(status, use_container_width=True)
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
        .properties(height=360, width=520)
        .facet(facet=alt.Facet("공정:N", title="공정", sort=list(AREAS)), columns=2)
        .resolve_scale(y="independent")
    )
    st.altair_chart(chart, use_container_width=True)

    st.download_button(
        "조·공정 월평균 판정 CSV",
        data=status.to_csv(index=False).encode("utf-8-sig"),
        file_name="월평균_조공정_판정.csv",
        mime="text/csv",
        key="trend_dl_status",
    )
