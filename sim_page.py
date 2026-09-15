"""설비 기준 운영 시뮬레이션 · 실적 시간 활용."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app_common import (
    CAMPUSES,
    apply_basic_filters,
    data_dir,
    load_records,
    render_slicer,
    team_stack_order,
)
from auth import render_logout_controls
from stats_engine import AREAS, SHIFTS, add_calendar_parts
from sim_engine import (
    DAY_MINUTES,
    EQUIP_COLUMNS,
    PRODUCT_COLUMNS,
    csv_bytes,
    daily_capacity,
    empty_csv_bytes,
    empty_xlsx_bytes,
    equipment_template,
    mix_simulation,
    newest_matching,
    normalize_equipment,
    normalize_products,
    process_standard_times,
    product_actual_template,
    product_template,
    read_csv_table,
    xlsx_bytes,
    utilization_from_actuals,
)


def master_dir():
    folder = data_dir() / "master"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _save_upload(uploaded, prefix: str):
    name = uploaded.name
    if not str(name).startswith(prefix):
        name = f"{prefix}_{name}"
    dest = master_dir() / name
    dest.write_bytes(uploaded.getvalue())
    return dest


def _load_master() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    folder = master_dir()
    notes: list[str] = []
    eq_path = newest_matching(folder, "설비_기준정보")
    pr_path = newest_matching(folder, "제품_기준정보")
    equip = pd.DataFrame()
    products = pd.DataFrame()
    if eq_path:
        equip = normalize_equipment(read_csv_table(eq_path))
        notes.append(f"설비: {eq_path.name} ({len(equip)}행)")
    else:
        notes.append("설비 기준정보가 없습니다. 양식을 받아 업로드하세요.")
    if pr_path:
        products = normalize_products(read_csv_table(pr_path))
        notes.append(f"제품: {pr_path.name} ({len(products)}행)")
    else:
        notes.append("제품 기준정보가 없습니다. 양식을 받아 업로드하세요.")
    return equip, products, notes


def render() -> None:
    st.title("설비 운영 시뮬레이션")
    st.caption(
        "보유 설비와 제품 기준정보로 하루 1440분 동안 몇 매를 할 수 있는지 보고, "
        "실적과 비교해 인당 시간을 얼마나 썼는지 계산합니다. "
        "기준정보는 CSV로 올리면 바로 반영됩니다."
    )

    records, rec_notes, _chosen = load_records()
    equip, products, master_notes = _load_master()

    campus_sel: list[str] = []
    shift_sel: list[str] = []
    area_sel = list(AREAS)
    team_sel: list[str] = []
    product_sel: list[str] = []
    available_min = float(DAY_MINUTES)

    with st.sidebar:
        st.header("계정")
        render_logout_controls()
        st.divider()
        st.header("조회 조건")
        campus_opts = []
        if not equip.empty:
            campus_opts = sorted(equip["캠퍼스"].dropna().unique().tolist())
        if records is not None and not records.empty and "캠퍼스" in records.columns:
            campus_opts = sorted(set(campus_opts) | set(records["캠퍼스"].dropna().unique().tolist()))
        if not campus_opts:
            campus_opts = list(CAMPUSES)
        prefer = [c for c in CAMPUSES if c in campus_opts]
        campus_sel = render_slicer(
            "캠퍼스",
            prefer + [c for c in campus_opts if c not in prefer],
            key="sim_campus",
            default_on=True,
        )
        area_sel = render_slicer("공정", list(AREAS), key="sim_area", default_on=True)
        codes = sorted(products["제품코드"].dropna().unique().tolist()) if not products.empty else []
        product_sel = render_slicer("제품", codes, key="sim_product", default_on=True) if codes else []
        if not records.empty:
            shifts = sorted(records["주야"].dropna().unique().tolist()) if "주야" in records.columns else list(SHIFTS)
            prefer_s = [s for s in SHIFTS if s in shifts]
            shift_sel = render_slicer(
                "주/야",
                prefer_s + [s for s in shifts if s not in prefer_s],
                key="sim_shift",
                default_on=True,
            )
            teams = sorted(records["조"].dropna().unique().tolist()) if "조" in records.columns else []
            team_sel = render_slicer("조", teams, key="sim_team", default_on=True) if teams else []
        available_min = float(
            st.number_input(
                "인당 가용 분 (활용률 분모)",
                min_value=60,
                max_value=1440,
                value=1440,
                step=60,
                help="이론 능력은 설비×1440분. 활용률은 인력×이 값으로 나눕니다. 24시간 기준이면 1440.",
            )
        )

        st.divider()
        st.header("기준정보 양식")
        st.caption("엑셀에서 한글이 깨지면 **xlsx** 양식을 받으세요. CSV는 UTF-8(BOM)입니다.")
        st.download_button(
            "제품 기준정보 엑셀 양식 (권장)",
            data=xlsx_bytes(product_template(), "제품"),
            file_name="제품_기준정보.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="sim_dl_pr_xlsx",
        )
        st.download_button(
            "제품 기준정보 빈 엑셀",
            data=empty_xlsx_bytes(PRODUCT_COLUMNS, "제품"),
            file_name="제품_기준정보_빈양식.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="sim_dl_pr_xlsx_empty",
        )
        st.download_button(
            "설비 기준정보 엑셀 양식 (권장)",
            data=xlsx_bytes(equipment_template(), "설비"),
            file_name="설비_기준정보.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="sim_dl_eq_xlsx",
        )
        st.download_button(
            "설비 기준정보 빈 엑셀",
            data=empty_xlsx_bytes(EQUIP_COLUMNS, "설비"),
            file_name="설비_기준정보_빈양식.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="sim_dl_eq_xlsx_empty",
        )
        with st.expander("CSV 양식 (UTF-8)"):
            st.download_button(
                "설비 기준정보 CSV (예시)",
                data=csv_bytes(equipment_template()),
                file_name="설비_기준정보.csv",
                mime="text/csv",
                use_container_width=True,
                key="sim_dl_eq_ex",
            )
            st.download_button(
                "설비 기준정보 빈 CSV",
                data=empty_csv_bytes(EQUIP_COLUMNS),
                file_name="설비_기준정보_빈양식.csv",
                mime="text/csv",
                use_container_width=True,
                key="sim_dl_eq_empty",
            )
            st.download_button(
                "제품 기준정보 CSV (예시)",
                data=csv_bytes(product_template()),
                file_name="제품_기준정보.csv",
                mime="text/csv",
                use_container_width=True,
                key="sim_dl_pr_ex",
            )
            st.download_button(
                "제품 기준정보 빈 CSV",
                data=empty_csv_bytes(PRODUCT_COLUMNS),
                file_name="제품_기준정보_빈양식.csv",
                mime="text/csv",
                use_container_width=True,
                key="sim_dl_pr_empty",
            )
            st.download_button(
                "제품별 실적 CSV (선택)",
                data=csv_bytes(product_actual_template()),
                file_name="제품별_실적.csv",
                mime="text/csv",
                use_container_width=True,
                key="sim_dl_act",
            )
        eq_up = st.file_uploader("설비 기준정보 업로드", type=["csv", "xlsx"], key="sim_up_eq")
        pr_up = st.file_uploader("제품 기준정보 업로드", type=["csv", "xlsx"], key="sim_up_pr")
        eq_sig = (eq_up.name, int(getattr(eq_up, "size", 0) or 0)) if eq_up else None
        pr_sig = (pr_up.name, int(getattr(pr_up, "size", 0) or 0)) if pr_up else None
        if eq_up is not None and eq_sig != st.session_state.get("sim_eq_sig"):
            path = _save_upload(eq_up, "설비_기준정보")
            st.session_state["sim_eq_sig"] = eq_sig
            st.success(f"저장: {path.name}")
            st.rerun()
        if pr_up is not None and pr_sig != st.session_state.get("sim_pr_sig"):
            path = _save_upload(pr_up, "제품_기준정보")
            st.session_state["sim_pr_sig"] = pr_sig
            st.success(f"저장: {path.name}")
            st.rerun()

    for n in master_notes:
        st.caption("· " + n)

    eq_view = equip.copy()
    pr_view = products.copy()
    if campus_sel and not eq_view.empty:
        eq_view = eq_view[eq_view["캠퍼스"].isin(campus_sel) | (eq_view["캠퍼스"] == "")]
    if area_sel and not eq_view.empty:
        eq_view = eq_view[eq_view["공정"].isin(area_sel)]
    if area_sel and not pr_view.empty:
        pr_view = pr_view[pr_view["공정"].isin(area_sel)]
    if product_sel and not pr_view.empty:
        pr_view = pr_view[pr_view["제품코드"].isin(product_sel)]

    tab_master, tab_sim, tab_util = st.tabs(["기준정보", "운영 시뮬레이션", "실적 시간 활용"])

    with tab_master:
        st.subheader("현재 적용 중인 기준")
        st.markdown("**설비** — 가동여부가 Y/가동/1 이면 시뮬레이션에 포함합니다.")
        if eq_view.empty:
            st.info("설비 기준정보를 업로드하세요.")
        else:
            st.dataframe(eq_view.drop(columns=["가동"], errors="ignore"), use_container_width=True)
            by = eq_view[eq_view["가동"]].groupby(["캠퍼스", "공정"], as_index=False)["대수"].sum()
            st.caption("가동 대수 합계")
            st.dataframe(by, use_container_width=True)
        st.markdown("**제품** — `매당_설비분`은 설비 1대로 1매 도는 시간(분), `매당_인시분`은 사람 1명이 쓰는 시간입니다.")
        if pr_view.empty:
            st.info("제품 기준정보를 업로드하세요.")
        else:
            st.dataframe(pr_view, use_container_width=True)

    with tab_sim:
        st.subheader("하루 1440분 능력")
        st.caption(
            "일가능매수 = 가동 대수 × 1440 ÷ 매당_설비분. "
            "그 제품만 하루 종일 돌린다고 가정한 이론 값입니다. "
            "제품별 병목은 공정 중 가장 낮은 일가능매수입니다."
        )
        campus_for_cap = campus_sel[0] if len(campus_sel) == 1 else None
        if len(campus_sel) != 1:
            st.caption("캠퍼스를 하나만 켜면 그 캠퍼스 설비만으로 계산합니다. 여러 개면 켠 캠퍼스를 합칩니다.")
        cap_equip = eq_view if len(campus_sel) != 1 else eq_view
        cap = daily_capacity(pr_view, cap_equip, campus=campus_for_cap if len(campus_sel) == 1 else None)
        if cap.empty:
            st.warning("제품·설비 기준정보가 있어야 시뮬레이션할 수 있습니다.")
        else:
            k1, k2, k3 = st.columns(3)
            with k1:
                st.metric("가동 대수", f"{int(cap['가동대수'].sum())}대")
            with k2:
                bn = cap.drop_duplicates("제품코드")
                st.metric("제품 수", f"{len(bn)}종")
            with k3:
                st.metric("병목 합(참고)", f"{bn['병목가능매수'].sum():,.0f}매")
            st.dataframe(cap, use_container_width=True)
            chart_df = cap.copy()
            bar = (
                alt.Chart(chart_df)
                .mark_bar()
                .encode(
                    x=alt.X("공정:N", title="공정", sort=list(AREAS)),
                    y=alt.Y("일가능매수:Q", title="일가능매수 (1440분)"),
                    color=alt.Color("제품코드:N", title="제품"),
                    xOffset="제품코드:N",
                    tooltip=["제품코드", "제품명", "공정", "가동대수", "매당_설비분", "일가능매수", "병목공정"],
                )
                .properties(height=340, title="제품·공정별 일 가능 매수")
            )
            st.altair_chart(bar, use_container_width=True)

            st.markdown("##### 믹스 가동 (설비 시간을 비중으로 나눔)")
            codes = sorted(pr_view["제품코드"].unique().tolist())
            mix_default = pd.DataFrame({"제품코드": codes, "비중": [round(100 / len(codes), 1)] * len(codes)})
            mix_edit = st.data_editor(
                mix_default,
                use_container_width=True,
                hide_index=True,
                key="sim_mix_editor",
                column_config={
                    "제품코드": st.column_config.TextColumn(disabled=True),
                    "비중": st.column_config.NumberColumn(min_value=0, step=1),
                },
            )
            mixed = mix_simulation(pr_view, cap_equip, mix_edit, campus=campus_for_cap if len(campus_sel) == 1 else None)
            if mixed.empty:
                st.caption("비중을 넣으면 공정별로 나눠 돌린 매수가 나옵니다.")
            else:
                st.dataframe(mixed, use_container_width=True)
                st.altair_chart(
                    alt.Chart(mixed)
                    .mark_bar()
                    .encode(
                        x=alt.X("공정:N", sort=list(AREAS), title="공정"),
                        y=alt.Y("일가능매수:Q"),
                        color="제품코드:N",
                        xOffset="제품코드:N",
                        tooltip=list(mixed.columns),
                    )
                    .properties(height=300, title="믹스 기준 일 가능 매수"),
                    use_container_width=True,
                )

    with tab_util:
        st.subheader("실적 기준 인당 시간 활용")
        st.caption(
            f"인당시간활용률(%) = (실적 × 매당_인시분) ÷ (인력 × {available_min:g}분) × 100. "
            "100%면 기준 택트만큼 시간을 다 쓴 것이고, 낮으면 여유·대기·다른 일이 있는 쪽으로 봅니다."
        )
        if records.empty:
            st.info("실적 CSV/엑셀을 홈 화면 데이터에서 올린 뒤 이 탭을 보면 됩니다.")
        elif pr_view.empty:
            st.warning("제품 기준정보의 매당_인시분이 있어야 활용률을 계산합니다.")
        else:
            filtered = apply_basic_filters(
                records,
                area_sel=area_sel,
                campus_sel=campus_sel,
                shift_sel=shift_sel or None,
                team_sel=team_sel or None,
                mode="전체",
            )
            if filtered.empty:
                st.warning("선택 조건에 해당하는 실적이 없습니다.")
            else:
                std = process_standard_times(pr_view, product_sel or None)
                util = utilization_from_actuals(filtered, std, available_min=available_min)
                if util.empty:
                    st.warning("실적 공정과 제품 기준정보의 공정이 맞지 않습니다.")
                else:
                    avg_u = float(pd.to_numeric(util["인당시간활용률"], errors="coerce").mean())
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.metric("평균 인당시간활용률", f"{avg_u:.1f}%")
                    with c2:
                        st.metric("실적 합", f"{pd.to_numeric(util['실적'], errors='coerce').sum():,.0f}매")
                    with c3:
                        st.metric("인력 합(행)", f"{pd.to_numeric(util['인력'], errors='coerce').sum():,.0f}명")
                    st.dataframe(util, use_container_width=True)
                    by_area = (
                        util.groupby("공정", as_index=False)
                        .agg(인당시간활용률=("인당시간활용률", "mean"), 실적=("실적", "sum"), 인력=("인력", "sum"))
                        .round(1)
                    )
                    st.altair_chart(
                        alt.Chart(by_area)
                        .mark_bar()
                        .encode(
                            x=alt.X("공정:N", sort=list(AREAS), title="공정"),
                            y=alt.Y("인당시간활용률:Q", title="평균 활용률 %"),
                            tooltip=list(by_area.columns),
                        )
                        .properties(height=300, title="공정별 평균 인당 시간 활용률"),
                        use_container_width=True,
                    )
                    if "조" in util.columns:
                        teams_all = team_stack_order(sorted(util["조"].dropna().unique().tolist()))
                        by_team = (
                            util.groupby("조", as_index=False)["인당시간활용률"].mean().round(1)
                        )
                        st.altair_chart(
                            alt.Chart(by_team)
                            .mark_bar()
                            .encode(
                                x=alt.X("조:N", sort=teams_all),
                                y=alt.Y("인당시간활용률:Q", title="평균 활용률 %"),
                                tooltip=["조", "인당시간활용률"],
                            )
                            .properties(height=280, title="조별 평균 인당 시간 활용률"),
                            use_container_width=True,
                        )
                    st.download_button(
                        "활용률 계산 CSV",
                        data=util.to_csv(index=False).encode("utf-8-sig"),
                        file_name="인당시간활용률.csv",
                        mime="text/csv",
                        key="sim_dl_util",
                    )

        with st.expander("로드된 실적 파일", expanded=False):
            for n in rec_notes:
                st.write("- ", n)
            if records.empty:
                st.caption("실적이 없습니다.")
            else:
                st.caption(f"실적 행 수: {len(add_calendar_parts(records))}")
