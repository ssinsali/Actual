"""종합 실적 분석 (조·주/야·공정)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from app_common import app_dir, render_exit_ui, render_slicer
from auth import render_logout_controls
from stats_engine import (
    AREAS,
    CAMPUSES,
    SHIFTS,
    add_calendar_parts,
    average_by_process,
    daily_team_area,
    detect_layout,
    empty_template_csv_bytes,
    filter_period,
    format_display_df,
    group_vs_process_gap,
    load_many,
    read_excel_table,
    summary_by,
    template_csv_bytes,
    template_dataframe,
)
from ui_charts import bar_chart, grouped_by_area_chart

_APP_DIR = app_dir()
_DATA_DIR = _APP_DIR / "data"


def _default_files() -> list[Path]:
    files = (
        sorted(_DATA_DIR.glob("*.xlsx"))
        + sorted(_DATA_DIR.glob("*.xls"))
        + sorted(_DATA_DIR.glob("*.csv"))
    )
    return [p for p in files if not p.name.startswith("~$")]


def _save_upload(uploaded) -> Path:
    dest = _DATA_DIR / uploaded.name
    dest.write_bytes(uploaded.getvalue())
    return dest


def _render_group_compare(df: pd.DataFrame, group_key: str, label: str) -> None:
    gap = group_vs_process_gap(df, group_key)
    by_g = summary_by(df, [group_key, "영역"])
    by_only = summary_by(df, [group_key])

    st.markdown(f"##### {label} × 공정 — 실적")
    st.caption(f"같은 공정 안에서 {label}끼리 비교. %는 해당 공정 {label} 평균 대비입니다.")
    if gap.empty:
        st.caption("표시할 데이터가 없습니다.")
        return

    st.dataframe(
        gap[[group_key, "영역", "실적", "인력", "실적_대비공정평균%", "건수"]].rename(
            columns={"영역": "공정", "실적_대비공정평균%": f"{label}평균대비(%)"}
        ),
        use_container_width=True,
    )
    grouped_by_area_chart(by_g, "실적", f"공정별 · {label} 실적", color=group_key)

    st.markdown(f"##### {label} × 공정 — 인당실적")
    st.dataframe(
        gap[
            [group_key, "영역", "인력", "실적", "인당실적", "인당실적_대비공정평균%", "건수"]
        ].rename(columns={"영역": "공정", "인당실적_대비공정평균%": f"{label}평균대비(%)"}),
        use_container_width=True,
    )
    c1, c2 = st.columns(2)
    with c1:
        grouped_by_area_chart(by_g, "인당실적", f"공정별 · {label} 인당실적", color=group_key)
    with c2:
        grouped_by_area_chart(by_g, "인력", f"공정별 · {label} 인력", color=group_key)

    st.markdown(f"##### {label} 합계 (공정 합산)")
    st.dataframe(by_only, use_container_width=True)
    b1, b2 = st.columns(2)
    with b1:
        bar_chart(by_only, group_key, "실적", title=f"{label} 총 실적")
    with b2:
        bar_chart(by_only, group_key, "인당실적", title=f"{label} 인당실적")


@st.cache_data(show_spinner=False)
def _load_cached(path_mtimes: tuple[tuple[str, float], ...]) -> tuple[pd.DataFrame, list[str]]:
    paths = [Path(p) for p, _ in path_mtimes]
    return load_many(paths)


def render() -> None:
    st.title("종합 실적 분석")
    st.caption("조별 · 주/야별 · 공정별 실적·인당실적 비교 (인당실적 = 실적 ÷ 인력)")

    files = _default_files()
    if "selected_files" not in st.session_state:
        st.session_state.selected_files = [p.name for p in files]

    path_map = {p.name: p for p in files}
    chosen_names = [n for n in st.session_state.selected_files if n in path_map]
    if not chosen_names and files:
        chosen_names = [p.name for p in files]
        st.session_state.selected_files = chosen_names
    chosen = [path_map[n] for n in chosen_names]
    mtimes = tuple((str(p), p.stat().st_mtime) for p in chosen) if chosen else tuple()

    records = pd.DataFrame()
    notes: list[str] = []
    if chosen:
        records, notes = _load_cached(mtimes)
        if not records.empty:
            records = add_calendar_parts(records)

    mode = "전체"
    year = quarter = month = None
    day = start = end = None
    area_sel = list(AREAS)
    team_sel: list[str] = []
    campus_sel: list[str] = []
    shift_sel: list[str] = []

    with st.sidebar:
        st.header("계정")
        render_logout_controls()
        st.divider()
        st.header("조회 조건")
        if records.empty:
            st.caption("데이터가 로드되면 기간·캠퍼스·주/야·영역·조를 선택할 수 있습니다.")
        else:
            if "캠퍼스" not in records.columns:
                records = records.copy()
                records["캠퍼스"] = "(미지정)"
            if "주야" not in records.columns:
                records = records.copy()
                records["주야"] = "(미지정)"
            mode = st.radio("기간 단위", ("전체", "년", "분기", "월", "일", "기간"), key="summary_period_mode")
            years = sorted(records["년"].dropna().unique().astype(int).tolist())
            if mode in ("년", "분기", "월") and years:
                year = st.selectbox("년도", years, index=len(years) - 1, key="summary_year")
            if mode == "분기" and year is not None:
                quarter = st.selectbox("분기", [1, 2, 3, 4], format_func=lambda q: f"{q}분기", key="summary_q")
            if mode == "월" and year is not None:
                months = sorted(records.loc[records["년"] == year, "월"].dropna().unique().astype(int).tolist())
                month = st.selectbox("월", months if months else list(range(1, 13)), key="summary_m")
            if mode == "일":
                min_d = records["일자"].min().date()
                max_d = records["일자"].max().date()
                day = st.date_input("일자", value=max_d, min_value=min_d, max_value=max_d, key="summary_day")
            if mode == "기간":
                min_d = records["일자"].min().date()
                max_d = records["일자"].max().date()
                rng = st.date_input("시작~종료", value=(min_d, max_d), min_value=min_d, max_value=max_d, key="summary_rng")
                if isinstance(rng, (list, tuple)) and len(rng) == 2:
                    start, end = pd.Timestamp(rng[0]), pd.Timestamp(rng[1])

            campuses = sorted(records["캠퍼스"].dropna().unique().tolist())
            prefer = [c for c in CAMPUSES if c in campuses]
            campus_opts = prefer + [c for c in campuses if c not in prefer]
            campus_sel = render_slicer(
                "캠퍼스",
                campus_opts,
                key="summary_campus",
                default_on=True,
            )

            shifts = sorted(records["주야"].dropna().unique().tolist())
            prefer_s = [s for s in SHIFTS if s in shifts]
            shift_opts = prefer_s + [s for s in shifts if s not in prefer_s]
            shift_sel = render_slicer(
                "주/야",
                shift_opts,
                key="summary_shift",
                default_on=True,
            )

            area_sel = render_slicer(
                "영역",
                list(AREAS),
                key="summary_area",
                default_on=True,
            )
            pre_filtered = filter_period(
                records,
                mode=mode,
                year=year,
                quarter=quarter,
                month=month,
                day=pd.Timestamp(day) if day else None,
                start=start,
                end=end,
            )
            if campus_sel:
                pre_filtered = pre_filtered[pre_filtered["캠퍼스"].isin(campus_sel)]
            if shift_sel:
                pre_filtered = pre_filtered[pre_filtered["주야"].isin(shift_sel)]
            if area_sel:
                pre_filtered = pre_filtered[pre_filtered["영역"].isin(area_sel)]
            teams = sorted(pre_filtered["조"].dropna().unique().tolist()) if not pre_filtered.empty else []
            team_sel = render_slicer(
                "조",
                teams,
                key="summary_team",
                default_on=True,
            ) if teams else []

        st.divider()
        st.header("데이터")
        st.markdown(f"기본 폴더: `{_DATA_DIR}`")
        st.download_button(
            "기본 CSV 양식 다운로드",
            data=template_csv_bytes(),
            file_name="실적통계_기본양식.csv",
            mime="text/csv",
            use_container_width=True,
            key="summary_dl_tpl",
        )
        st.download_button(
            "빈 CSV 양식 다운로드",
            data=empty_template_csv_bytes(),
            file_name="실적통계_빈양식.csv",
            mime="text/csv",
            use_container_width=True,
            key="summary_dl_empty",
        )
        with st.expander("양식 컬럼 안내"):
            st.dataframe(template_dataframe(), use_container_width=True)

        uploads = st.file_uploader(
            "엑셀/CSV 업로드",
            type=["xlsx", "xls", "csv"],
            accept_multiple_files=True,
            key="summary_upload",
        )
        upload_sig = tuple((u.name, int(getattr(u, "size", 0) or 0)) for u in (uploads or []))
        if uploads and upload_sig and upload_sig != st.session_state.get("summary_last_upload_sig"):
            names: list[str] = []
            for up in uploads:
                _save_upload(up)
                names.append(up.name)
                st.success(f"저장: {up.name}")
            st.session_state["summary_last_upload_sig"] = upload_sig
            cur = list(st.session_state.get("selected_files") or [])
            for n in names:
                if n not in cur:
                    cur.append(n)
            st.session_state.selected_files = cur
            st.cache_data.clear()
            st.rerun()

        files = _default_files()
        if not files:
            st.warning("data 폴더에 파일이 없습니다.")
            render_exit_ui(key_prefix="summary_")
            st.stop()

        file_names = [p.name for p in files]
        if "selected_files" not in st.session_state:
            st.session_state.selected_files = file_names
        st.session_state.selected_files = [n for n in st.session_state.selected_files if n in file_names]
        if not st.session_state.selected_files:
            st.session_state.selected_files = file_names

        selected = st.multiselect(
            "분석할 파일",
            options=file_names,
            default=st.session_state.selected_files,
            key="summary_file_select",
        )
        if selected != st.session_state.selected_files:
            st.session_state.selected_files = selected
        if not selected:
            render_exit_ui(key_prefix="summary_")
            st.stop()

        if st.button("데이터 새로고침", use_container_width=True, key="summary_refresh"):
            st.cache_data.clear()
            st.rerun()

        render_exit_ui(key_prefix="summary_")

    with st.expander("로드 정보 / 컬럼 인식 결과", expanded=False):
        for n in notes:
            st.write("- ", n)
        if not records.empty:
            st.dataframe(format_display_df(records.head(20)), use_container_width=True)

    if records.empty:
        st.error("표준 데이터가 없습니다. 사이드바에서 양식을 받아 업로드하세요.")
        if chosen:
            preview = read_excel_table(chosen[0])
            st.subheader("원본 미리보기")
            st.dataframe(preview.head(30), use_container_width=True)
            st.json(detect_layout(preview))
        st.stop()

    filtered = filter_period(
        records,
        mode=mode,
        year=year,
        quarter=quarter,
        month=month,
        day=pd.Timestamp(day) if day else None,
        start=start,
        end=end,
    )
    if "캠퍼스" not in filtered.columns:
        filtered = filtered.copy()
        filtered["캠퍼스"] = "(미지정)"
    if "주야" not in filtered.columns:
        filtered = filtered.copy()
        filtered["주야"] = "(미지정)"
    if campus_sel:
        filtered = filtered[filtered["캠퍼스"].isin(campus_sel)]
    if shift_sel:
        filtered = filtered[filtered["주야"].isin(shift_sel)]
    if area_sel:
        filtered = filtered[filtered["영역"].isin(area_sel)]
    if team_sel:
        filtered = filtered[filtered["조"].isin(team_sel)]

    if filtered.empty:
        st.warning("선택 조건에 해당하는 데이터가 없습니다.")
        st.stop()

    total_out = float(filtered["실적"].sum())
    total_man = float(filtered["인력"].sum())
    per_person = (total_out / total_man) if total_man else None
    area_out = {a: float(filtered.loc[filtered["영역"] == a, "실적"].sum()) for a in AREAS}

    k1, k2, k3 = st.columns(3)
    with k1:
        st.metric("총 실적", f"{total_out:,.0f}")
        st.caption("Σ 실적 (조회조건)")
    with k2:
        st.metric("총 인력(합)", f"{total_man:,.1f}")
        st.caption("Σ 인력 (조회조건)")
    with k3:
        st.metric("인당 실적", f"{per_person:,.1f}" if per_person is not None else "-")
        st.caption("총 실적 ÷ 총 인력")

    area_cols = st.columns(4)
    area_labels = {
        "종합측정실": "종합측정실 실적합계",
        "치수": "치수 실적합계",
        "Hole": "Hole 실적합계",
        "외관": "외관검사 실적합계",
    }
    for col, area in zip(area_cols, AREAS):
        with col:
            st.metric(area_labels[area], f"{area_out[area]:,.0f}")
            st.caption(f"Σ {area} 실적 (조회조건)")

    gap_team = group_vs_process_gap(filtered, "조")
    gap_shift = group_vs_process_gap(filtered, "주야")
    by_team_area = summary_by(filtered, ["조", "영역"])
    by_shift_area = summary_by(filtered, ["주야", "영역"])
    by_team_shift = summary_by(filtered, ["조", "주야", "영역"])
    avg_area = average_by_process(filtered, ["영역"])

    tab_team, tab_shift, tab_cross, tab_detail, tab_period, tab_raw = st.tabs(
        ["조별", "주/야", "조 × 주/야", "상세(일자)", "월·분기·년", "Raw"]
    )

    with tab_team:
        st.subheader("조별 실적 · 인당실적")
        _render_group_compare(filtered, "조", "조")
        st.dataframe(
            avg_area[["영역", "평균_실적", "합계_실적", "인당실적", "건수"]].rename(columns={"영역": "공정"}),
            use_container_width=True,
        )

    with tab_shift:
        st.subheader("주/야 실적 · 인당실적")
        _render_group_compare(filtered, "주야", "주/야")

    with tab_cross:
        st.subheader("조 × 주/야 × 공정")
        if not by_team_shift.empty:
            st.dataframe(by_team_shift.rename(columns={"영역": "공정"}), use_container_width=True)
            by_ts = summary_by(filtered, ["조", "주야"])
            bar_chart(by_ts, "조", "실적", color="주야", title="조별 · 주/야 실적")
            bar_chart(by_ts, "조", "인당실적", color="주야", title="조별 · 주/야 인당실적")
            grouped_by_area_chart(by_team_area, "실적", "공정별 · 조별 실적", color="조")
            grouped_by_area_chart(by_shift_area, "실적", "공정별 · 주/야 실적", color="주야")

    with tab_detail:
        daily = daily_team_area(filtered)
        st.dataframe(format_display_df(daily), use_container_width=True)
        chart_df = daily.copy()
        chart_df["일자라벨"] = pd.to_datetime(chart_df["일자"]).dt.strftime("%Y-%m-%d")
        bar_chart(chart_df, "일자라벨", "실적", color="주야", title="일자별 · 주/야 실적")
        bar_chart(chart_df, "일자라벨", "실적", color="조", title="일자별 · 조별 실적")

    with tab_period:
        f2 = add_calendar_parts(filtered)
        by_m = summary_by(f2, ["년월", "영역"])
        st.dataframe(by_m, use_container_width=True)
        bar_chart(by_m, "년월", "실적", color="영역", title="월별 실적")
        by_mt = summary_by(f2, ["년월", "조", "영역"])
        bar_chart(by_mt, "년월", "실적", color="조", title="월별 · 조별 실적")

    with tab_raw:
        raw_view = format_display_df(filtered.sort_values("일자"))
        st.download_button(
            "정규화 데이터 CSV",
            data=raw_view.to_csv(index=False).encode("utf-8-sig"),
            file_name="실적_정규화.csv",
            mime="text/csv",
        )
        st.dataframe(raw_view, use_container_width=True)
