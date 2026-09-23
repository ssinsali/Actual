"""QA그룹 CAPA 관리 — 월별 치수·홀 필요대수와 가동율."""
from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from app_common import data_dir, render_exit_ui
from auth import render_logout_controls
from capa_engine import (
    PLAN_COLUMNS,
    QA_PLAN_STEM,
    QA_STEMS,
    QA_TIME_STEM,
    calc_qa_capa,
    plan_template,
)
from sim_engine import (
    DAY_MINUTES,
    DEFAULT_WORK_DAYS,
    canonical_master_name,
    csv_bytes,
    empty_xlsx_bytes,
    PRODUCT_COLUMNS,
    newest_matching,
    normalize_equipment,
    product_template,
    read_csv_table,
    running_qty,
    xlsx_bytes,
)


def master_dir() -> Path:
    folder = data_dir() / "master"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _list_paths(stem: str | None = None) -> list[Path]:
    folder = master_dir()
    stems = (stem,) if stem else QA_STEMS
    files: list[Path] = []
    for s in stems:
        files.extend(folder.glob(f"{s}*.csv"))
        files.extend(folder.glob(f"{s}*.xlsx"))
        files.extend(folder.glob(f"{s}*.xls"))
    return [p for p in files if not p.name.startswith("~$")]


def _clear_files(stem: str | None = None) -> list[str]:
    deleted: list[str] = []
    for path in _list_paths(stem):
        try:
            path.unlink()
            deleted.append(path.name)
        except OSError:
            continue
    return deleted


def _save_upload(uploaded, prefix: str) -> Path:
    """올린 파일만 이 페이지 계산에 쓴다. GitHub templates 로는 보내지 않는다."""
    name = canonical_master_name(uploaded.name, prefix)
    _clear_files(prefix)
    dest = master_dir() / name
    dest.write_bytes(uploaded.getvalue())
    return dest


def _owned_from_equipment() -> tuple[int, int, str]:
    """설비_기준정보의 가동 대수. 치수·Hole 합계."""
    path = newest_matching(master_dir(), "설비_기준정보")
    if path is None:
        return 0, 0, ""
    try:
        equip = normalize_equipment(read_csv_table(path))
    except Exception:
        return 0, 0, path.name
    dim = int(round(running_qty(equip, campus=None, area="치수", equip_code="")))
    hole = int(
        round(
            running_qty(equip, campus=None, area="Hole", equip_code="")
            + running_qty(equip, campus=None, area="홀", equip_code="")
        )
    )
    return dim, hole, path.name


def _active_files() -> list[dict[str, str]]:
    folder = master_dir()
    rows: list[dict[str, str]] = []
    for label, stem in (("월별 생산계획", QA_PLAN_STEM), ("제품_기준정보", QA_TIME_STEM)):
        path = newest_matching(folder, stem)
        if path is None:
            rows.append({"구분": label, "파일": "(없음)", "상태": "미등록"})
            continue
        try:
            mtime = pd.Timestamp(path.stat().st_mtime, unit="s").strftime("%Y-%m-%d %H:%M")
        except Exception:
            mtime = "-"
        rows.append({"구분": label, "파일": path.name, "상태": f"운영중 · {mtime}"})
    return rows


def _load_saved() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    folder = master_dir()
    notes: list[str] = []
    plan_path = newest_matching(folder, QA_PLAN_STEM)
    time_path = newest_matching(folder, QA_TIME_STEM)
    plan = pd.DataFrame()
    times = pd.DataFrame()
    if plan_path:
        plan = read_csv_table(plan_path)
        notes.append(f"월별 생산계획: {plan_path.name} ({len(plan)}행)")
    if time_path:
        times = read_csv_table(time_path)
        notes.append(f"제품_기준정보: {time_path.name} ({len(times)}행)")
    return plan, times, notes


def _render_reset_ui() -> None:
    flag = "capa_confirm_reset"
    if flag not in st.session_state:
        st.session_state[flag] = False
    files = _list_paths()
    if not files:
        st.caption("초기화할 업로드 파일이 없습니다.")
        return
    if not st.session_state[flag]:
        if st.button("업로드 파일 초기화", use_container_width=True, key="capa_btn_reset"):
            st.session_state[flag] = True
            st.rerun()
        return
    st.warning("올려 둔 월별 생산계획·제품_기준정보 파일을 삭제합니다.")
    st.caption("삭제 대상: " + ", ".join(p.name for p in files))
    yes, no = st.columns(2)
    with yes:
        if st.button("삭제", type="primary", use_container_width=True, key="capa_reset_yes"):
            deleted = _clear_files()
            st.session_state[flag] = False
            for k in ("capa_plan_sig", "capa_time_sig"):
                st.session_state.pop(k, None)
            st.session_state["capa_flash"] = "초기화 완료: " + (", ".join(deleted) if deleted else "없음")
            st.rerun()
    with no:
        if st.button("취소", use_container_width=True, key="capa_reset_no"):
            st.session_state[flag] = False
            st.rerun()


def _count_chart(monthly: pd.DataFrame, value_col: str, title: str, color: str) -> None:
    chart_df = monthly[["월라벨", value_col]].rename(columns={"월라벨": "월", value_col: "대수"})
    chart_df["표시"] = chart_df["대수"].map(lambda v: f"{int(v)}대")
    order = list(monthly["월라벨"])
    y_max = max(float(chart_df["대수"].max()), 1.0) * 1.28
    bars = (
        alt.Chart(chart_df)
        .mark_bar(color=color)
        .encode(
            x=alt.X("월:N", sort=order, title="월"),
            y=alt.Y("대수:Q", title="필요 대수", scale=alt.Scale(domain=[0, y_max])),
            tooltip=["월", "대수"],
        )
    )
    labels = (
        alt.Chart(chart_df)
        .mark_text(dy=-12, fontSize=16, fontWeight="bold")
        .encode(
            x=alt.X("월:N", sort=order),
            y=alt.Y("대수:Q"),
            text=alt.Text("표시:N"),
            color=alt.value("#ffffff"),
        )
    )
    st.altair_chart((bars + labels).properties(height=320, title=title), use_container_width=True)


def _util_chart(monthly: pd.DataFrame) -> None:
    long = monthly.melt(
        id_vars=["월라벨"],
        value_vars=["치수_가동율", "홀_가동율"],
        var_name="구분",
        value_name="가동율",
    )
    long["구분"] = long["구분"].map({"치수_가동율": "치수", "홀_가동율": "홀"})
    long = long.rename(columns={"월라벨": "월"}).dropna(subset=["가동율"])
    if long.empty:
        st.info("보유대수를 입력하면 월별 가동율을 계산합니다.")
        return
    long["표시"] = long["가동율"].map(lambda v: f"{float(v):.1f}%")
    order = list(monthly["월라벨"])
    y_max = max(float(long["가동율"].max()), 100.0) * 1.18
    bars = (
        alt.Chart(long)
        .mark_bar()
        .encode(
            x=alt.X("월:N", sort=order, title="월"),
            xOffset="구분:N",
            y=alt.Y("가동율:Q", title="가동율 (%)", scale=alt.Scale(domain=[0, y_max])),
            color=alt.Color(
                "구분:N",
                title="공정",
                scale=alt.Scale(domain=["치수", "홀"], range=["#60a5fa", "#fbbf24"]),
                sort=["치수", "홀"],
            ),
            tooltip=["월", "구분", "가동율"],
        )
    )
    labels = (
        alt.Chart(long)
        .mark_text(dy=-10, fontSize=12, fontWeight="bold")
        .encode(
            x=alt.X("월:N", sort=order),
            xOffset="구분:N",
            y=alt.Y("가동율:Q"),
            text=alt.Text("표시:N"),
            color=alt.value("#ffffff"),
        )
    )
    rule = (
        alt.Chart(pd.DataFrame({"y": [100]}))
        .mark_rule(strokeDash=[6, 4], color="#f87171")
        .encode(y="y:Q")
    )
    st.altair_chart(
        (bars + labels + rule).properties(height=340, title="월별 가동율 (빨간 점선 = 100%)"),
        use_container_width=True,
    )


def render() -> None:
    st.title("QA그룹 CAPA 관리")
    st.caption(
        "월별 생산계획과 제품_기준정보로 치수·홀 설비 필요대수와 가동율을 계산합니다. "
        "측정시간은 설비 운영 시뮬레이션과 같은 제품_기준정보(공정, 매당_설비분)를 씁니다. 홀은 CEL만 봅니다."
    )

    flash = st.session_state.pop("capa_flash", None)
    if flash:
        st.success(flash)

    dim_default, hole_default, eq_name = _owned_from_equipment()
    if "capa_owned_dim" not in st.session_state:
        st.session_state["capa_owned_dim"] = dim_default
    if "capa_owned_hole" not in st.session_state:
        st.session_state["capa_owned_hole"] = hole_default

    work_days = float(DEFAULT_WORK_DAYS)
    day_hours = 24.0

    with st.sidebar:
        st.header("계정")
        render_logout_controls()
        st.divider()
        st.header("가동 조건")
        work_days = float(
            st.number_input(
                "월 작업일수",
                min_value=1.0,
                max_value=31.0,
                value=float(DEFAULT_WORK_DAYS),
                step=1.0,
                help="한 달 조업일. 모든 월에 동일하게 적용합니다.",
                key="capa_work_days",
            )
        )
        day_hours = float(
            st.number_input(
                "1일 가동시간 (시간)",
                min_value=1.0,
                max_value=24.0,
                value=24.0,
                step=1.0,
                help="설비 이론능력은 24시간(1440분)입니다.",
                key="capa_day_hours",
            )
        )
        owned_dim = int(
            st.number_input(
                "치수 보유대수",
                min_value=0,
                max_value=999,
                step=1,
                help="가동율 분모. 설비_기준정보 치수 가동 대수가 있으면 그 값으로 시작합니다.",
                key="capa_owned_dim",
            )
        )
        owned_hole = int(
            st.number_input(
                "홀 보유대수",
                min_value=0,
                max_value=999,
                step=1,
                help="가동율 분모. 설비_기준정보 Hole 가동 대수가 있으면 그 값으로 시작합니다.",
                key="capa_owned_hole",
            )
        )
        avail = work_days * day_hours * 60.0
        st.caption(
            f"1대 월 가용 = {work_days:g}일 × {day_hours:g}시간 × 60 = **{avail:,.0f}분**. "
            f"참고: 24시간 = {DAY_MINUTES}분/일."
        )
        if eq_name:
            st.caption(f"보유대수 초기값: `{eq_name}` 치수 {dim_default}대 · 홀 {hole_default}대")

        st.divider()
        st.header("파일 업로드")
        st.caption(
            "월별 생산계획과 제품_기준정보를 직접 올리세요. "
            "제품_기준정보는 설비 운영 시뮬레이션과 같은 양식입니다. "
            "치수·Hole 행의 매당_설비분을 1매 측정시간으로 사용합니다."
        )
        st.dataframe(pd.DataFrame(_active_files()), use_container_width=True, hide_index=True)
        _render_reset_ui()

        plan_up = st.file_uploader("① 월별 생산계획", type=["csv", "xlsx"], key="capa_up_plan")
        time_up = st.file_uploader("② 제품_기준정보", type=["csv", "xlsx"], key="capa_up_time")
        plan_sig = (plan_up.name, int(getattr(plan_up, "size", 0) or 0)) if plan_up else None
        time_sig = (time_up.name, int(getattr(time_up, "size", 0) or 0)) if time_up else None
        if plan_up is not None and plan_sig != st.session_state.get("capa_plan_sig"):
            path = _save_upload(plan_up, QA_PLAN_STEM)
            st.session_state["capa_plan_sig"] = plan_sig
            st.session_state["capa_use_sample"] = False
            st.session_state["capa_flash"] = f"생산계획 업로드: {path.name}"
            st.rerun()
        if time_up is not None and time_sig != st.session_state.get("capa_time_sig"):
            path = _save_upload(time_up, QA_TIME_STEM)
            st.session_state["capa_time_sig"] = time_sig
            st.session_state["capa_use_sample"] = False
            st.session_state["capa_flash"] = f"제품_기준정보 업로드: {path.name}"
            st.rerun()

        st.subheader("양식 받기")
        st.download_button(
            "월별 생산계획 엑셀 (예시)",
            data=xlsx_bytes(plan_template(), "생산계획"),
            file_name="QA_월별생산계획.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="capa_dl_plan_xlsx",
        )
        st.download_button(
            "제품_기준정보 엑셀 (예시)",
            data=xlsx_bytes(product_template(), "제품"),
            file_name="제품_기준정보.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="capa_dl_time_xlsx",
        )
        with st.expander("빈 양식 · CSV"):
            st.download_button(
                "월별 생산계획 빈 엑셀",
                data=empty_xlsx_bytes(PLAN_COLUMNS, "생산계획"),
                file_name="QA_월별생산계획_빈양식.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="capa_dl_plan_empty",
            )
            st.download_button(
                "제품_기준정보 빈 엑셀",
                data=empty_xlsx_bytes(PRODUCT_COLUMNS, "제품"),
                file_name="제품_기준정보_빈양식.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="capa_dl_time_empty",
            )
            st.download_button(
                "월별 생산계획 CSV (예시)",
                data=csv_bytes(plan_template()),
                file_name="QA_월별생산계획.csv",
                mime="text/csv",
                use_container_width=True,
                key="capa_dl_plan_csv",
            )
            st.download_button(
                "제품_기준정보 CSV (예시)",
                data=csv_bytes(product_template()),
                file_name="제품_기준정보.csv",
                mime="text/csv",
                use_container_width=True,
                key="capa_dl_time_csv",
            )
        if st.button("예시 데이터로 미리보기", use_container_width=True, key="capa_preview"):
            st.session_state["capa_use_sample"] = True
            st.rerun()
        render_exit_ui(key_prefix="capa_")

    saved_plan, saved_times, notes = _load_saved()
    use_sample = bool(st.session_state.get("capa_use_sample"))
    if use_sample:
        plan_raw, time_raw = plan_template(), product_template()
        st.info("예시 양식으로 미리보기 중입니다. 실제 계획이면 사이드바에서 업로드하세요.")
    else:
        plan_raw, time_raw = saved_plan, saved_times

    result = calc_qa_capa(
        plan_raw,
        time_raw,
        work_days=work_days,
        day_hours=day_hours,
        owned_dim=owned_dim,
        owned_hole=owned_hole,
    )

    if plan_raw.empty or time_raw.empty:
        missing = []
        if plan_raw.empty:
            missing.append("월별 생산계획")
        if time_raw.empty:
            missing.append("제품_기준정보")
        st.info(
            "사이드바에서 **월별 생산계획**과 **제품_기준정보** 양식을 받아 올린 뒤 차트를 봅니다. "
            "바로 보려면 **예시 데이터로 미리보기**를 누르세요. "
            f"지금 없는 파일: {' · '.join(missing)}."
        )
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("##### 월별 생산계획")
            st.dataframe(plan_template(), use_container_width=True, hide_index=True)
            st.caption("가로형: 제품코드 + 1월~12월. 세로형(년도, 월, 제품코드, 필요수량)도 가능합니다.")
        with c2:
            st.markdown("##### 제품_기준정보")
            st.dataframe(product_template(), use_container_width=True, hide_index=True)
            st.caption("설비 운영 시뮬레이션과 같은 양식입니다. 치수·Hole의 매당_설비분이 1매 측정시간입니다. 홀은 CEL만 계산합니다.")
        return

    if result["monthly"].empty:
        st.warning(
            "생산계획과 측정시간의 제품코드가 맞지 않거나, 1월~12월 수량을 읽지 못했습니다. "
            f"생산계획 열: {', '.join(str(c) for c in result.get('plan_columns') or []) or '(없음)'}"
        )
        if result["unmatched"]:
            st.caption("측정시간이 없는 제품코드: " + ", ".join(result["unmatched"][:30]))
        with st.expander("올린 파일 미리보기", expanded=True):
            st.dataframe(plan_raw, use_container_width=True, hide_index=True)
            st.dataframe(time_raw, use_container_width=True, hide_index=True)
        return

    monthly = result["monthly"]
    avail_min = float(result["machine_month_min"])

    st.subheader("월별 치수 설비 필요대수")
    st.caption(
        f"필요대수 = ceil(치수 측정시간 합 ÷ 1대 월 가용 {avail_min:,.0f}분). "
        f"피크 {result['peak_dim_label']} · {result['peak_dim_required']}대. "
        "치수는 측정시간이 있는 전 제품입니다."
    )
    _count_chart(monthly, "치수_필요대수", "월별 치수 설비 필요대수", "#60a5fa")

    st.subheader("월별 홀 설비 필요대수")
    st.caption(
        f"필요대수 = ceil(홀 측정시간 합 ÷ 1대 월 가용 {avail_min:,.0f}분). "
        f"피크 {result['peak_hole_label']} · {result['peak_hole_required']}대. "
        "홀은 CEL만 포함합니다."
    )
    _count_chart(monthly, "홀_필요대수", "월별 홀 설비 필요대수", "#fbbf24")

    st.subheader("월별 가동율")
    st.caption(
        f"가동율 = 필요시간 ÷ (보유대수 × {avail_min:,.0f}분) × 100. "
        f"치수 보유 {owned_dim}대 · 홀 보유 {owned_hole}대. 100%를 넘으면 보유 설비가 부족합니다."
    )
    _util_chart(monthly)

    if result["unmatched"]:
        st.warning("측정시간이 없어 빠진 제품코드: " + ", ".join(result["unmatched"]))
    if result["hole_skipped"]:
        st.caption("홀 계산에서 제외(CEL 아님): " + ", ".join(result["hole_skipped"]))
    if result["unused_times"]:
        st.caption("생산계획이 없는 측정시간 코드: " + ", ".join(result["unused_times"]))

    show = monthly.copy()
    for col in ("치수_생산수량", "홀_생산수량"):
        show[col] = show[col].map(lambda v: f"{float(v):,.0f}")
    for col in ("치수_필요시간_분", "홀_필요시간_분"):
        show[col] = show[col].map(lambda v: f"{float(v):,.1f}")
    for col in ("치수_이론필요대수", "홀_이론필요대수"):
        show[col] = show[col].map(lambda v: f"{float(v):,.2f}")
    for col in ("치수_가동율", "홀_가동율"):
        show[col] = show[col].map(lambda v: "-" if v is None or (isinstance(v, float) and pd.isna(v)) else f"{float(v):,.1f}")

    with st.expander("월별 수치", expanded=False):
        st.dataframe(
            show[
                [
                    "월라벨",
                    "치수_생산수량",
                    "치수_필요시간_분",
                    "치수_이론필요대수",
                    "치수_필요대수",
                    "치수_가동율",
                    "홀_생산수량",
                    "홀_필요시간_분",
                    "홀_이론필요대수",
                    "홀_필요대수",
                    "홀_가동율",
                ]
            ].rename(
                columns={
                    "월라벨": "월",
                    "치수_필요대수": "치수 필요대수",
                    "홀_필요대수": "홀 필요대수",
                    "치수_가동율": "치수 가동율(%)",
                    "홀_가동율": "홀 가동율(%)",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
        st.download_button(
            "월별 결과 CSV",
            data=monthly.to_csv(index=False).encode("utf-8-sig"),
            file_name="QA_CAPA_월별.csv",
            mime="text/csv",
            key="capa_dl_monthly",
        )

    with st.expander("계산식 · 올린 파일"):
        st.markdown(
            f"""
- 치수 필요시간(분) = Σ (월 생산수량 × 치수 공정 매당_설비분) — 전 제품
- 홀 필요시간(분) = Σ (CEL 월 생산수량 × Hole 공정 매당_설비분)
- 1대 월 가용 = {work_days:g} × {day_hours:g} × 60 = **{avail_min:,.0f}분**
- 필요대수 = ceil(필요시간 ÷ 1대 월 가용)
- 가동율(%) = 필요시간 ÷ (보유대수 × 1대 월 가용) × 100
            """
        )
        for n in notes:
            st.write("- ", n)
        st.markdown("**월별 생산계획**")
        st.dataframe(plan_raw, use_container_width=True, hide_index=True)
        st.markdown("**제품_기준정보**")
        st.dataframe(time_raw, use_container_width=True, hide_index=True)
