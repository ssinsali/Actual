"""드릴 설비 필요 분석 — 월별 수량 × 제품 가공시간 → 필요대수."""
from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from app_common import data_dir, render_exit_ui
from auth import github_file_get, github_file_put, github_store_enabled, render_logout_controls
from drill_engine import (
    DEFAULT_DAY_HOURS,
    DEFAULT_UTILIZATION_PCT,
    DEDUCT_COLUMNS,
    DRILL_QTY_STEM,
    DRILL_STEMS,
    DRILL_TIME_STEM,
    QTY_WIDE_COLUMNS,
    TIME_COLUMNS,
    calc_drill_requirement,
    qty_template,
    time_template,
)
from sim_engine import (
    DAY_MINUTES,
    DEFAULT_WORK_DAYS,
    canonical_master_name,
    csv_bytes,
    empty_xlsx_bytes,
    master_github_paths,
    newest_matching,
    read_csv_table,
    xlsx_bytes,
)


def master_dir() -> Path:
    folder = data_dir() / "master"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _list_drill_paths(stem: str | None = None) -> list[Path]:
    folder = master_dir()
    stems = (stem,) if stem else DRILL_STEMS
    files: list[Path] = []
    for s in stems:
        files.extend(folder.glob(f"{s}*.csv"))
        files.extend(folder.glob(f"{s}*.xlsx"))
        files.extend(folder.glob(f"{s}*.xls"))
    return [p for p in files if not p.name.startswith("~$")]


def _clear_drill_files(stem: str | None = None) -> list[str]:
    deleted: list[str] = []
    for path in _list_drill_paths(stem):
        try:
            path.unlink()
            deleted.append(path.name)
        except OSError:
            continue
    return deleted


def _push_github(filename: str, content: bytes) -> str:
    if not github_store_enabled():
        return ""
    rel = f"templates/{filename}"
    try:
        _, sha = github_file_get(rel)
        github_file_put(rel, content, f"chore: update {filename}", sha)
        return f"GitHub 반영: {rel}"
    except Exception as e:
        return f"GitHub 저장 실패: {e}"


def _sync_from_github(*, force: bool = False) -> list[str]:
    """GitHub templates/드릴_* → data/master. Cloud 재시작 후에도 계획을 유지한다."""
    if not github_store_enabled():
        return ["GitHub Secrets([github] token/repo)가 없어 로컬·업로드 파일만 사용합니다."]
    if not force and st.session_state.get("drill_gh_ok"):
        return list(st.session_state.get("drill_gh_notes") or [])
    notes: list[str] = []
    folder = master_dir()
    if force:
        cleared = _clear_drill_files()
        if cleared:
            notes.append("로컬 드릴 파일 초기화: " + ", ".join(cleared))
    for stem in DRILL_STEMS:
        local = newest_matching(folder, stem)
        if local is not None and not force:
            notes.append(f"{stem}: 로컬 유지 ({local.name})")
            continue
        found_rel = None
        found_raw = None
        for rel in master_github_paths(stem):
            try:
                raw, _sha = github_file_get(rel)
            except Exception as e:
                if "404" in str(e):
                    continue
                notes.append(f"{stem}: GitHub 오류 ({e})")
                found_rel = "__error__"
                break
            if raw:
                found_rel, found_raw = rel, raw
                break
        if found_rel == "__error__":
            continue
        if found_rel and found_raw:
            dest = folder / Path(found_rel).name
            if not dest.name.startswith(stem):
                dest = folder / f"{stem}{Path(found_rel).suffix}"
            _clear_drill_files(stem)
            dest.write_bytes(found_raw)
            notes.append(f"GitHub에서 가져옴: {found_rel}")
        else:
            notes.append(f"{stem}: 저장소에 없음 (templates/{stem}.csv 또는 .xlsx)")
    st.session_state["drill_gh_ok"] = True
    st.session_state["drill_gh_notes"] = notes
    return notes


def _save_upload(uploaded, prefix: str):
    name = canonical_master_name(uploaded.name, prefix)
    _clear_drill_files(prefix)
    dest = master_dir() / name
    data = uploaded.getvalue()
    dest.write_bytes(data)
    st.session_state["drill_gh_ok"] = True
    st.session_state.pop("drill_gh_notes", None)
    gh = _push_github(name, data)
    return dest, gh


def _active_files() -> list[dict[str, str]]:
    folder = master_dir()
    rows: list[dict[str, str]] = []
    for label, stem in (("월별 필요수량", DRILL_QTY_STEM), ("제품 가공시간", DRILL_TIME_STEM)):
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
    qty_path = newest_matching(folder, DRILL_QTY_STEM)
    time_path = newest_matching(folder, DRILL_TIME_STEM)
    qty = pd.DataFrame()
    times = pd.DataFrame()
    if qty_path:
        qty = read_csv_table(qty_path)
        notes.append(f"월별 필요수량: {qty_path.name} ({len(qty)}행)")
    if time_path:
        times = read_csv_table(time_path)
        notes.append(f"제품 가공시간: {time_path.name} ({len(times)}행)")
    return qty, times, notes


def _render_reset_ui() -> None:
    flag = "drill_confirm_reset"
    if flag not in st.session_state:
        st.session_state[flag] = False
    files = _list_drill_paths()
    if not files:
        st.caption("초기화할 업로드 파일이 없습니다.")
        return
    if not st.session_state[flag]:
        if st.button("업로드 파일 초기화", use_container_width=True, key="drill_btn_reset"):
            st.session_state[flag] = True
            st.rerun()
        return
    st.warning("올려 둔 월별 필요수량·가공시간 파일을 삭제합니다.")
    st.caption("삭제 대상: " + ", ".join(p.name for p in files))
    yes, no = st.columns(2)
    with yes:
        if st.button("삭제", type="primary", use_container_width=True, key="drill_reset_yes"):
            deleted = _clear_drill_files()
            st.session_state[flag] = False
            st.session_state["drill_gh_ok"] = False
            st.session_state.pop("drill_gh_notes", None)
            for k in ("drill_qty_sig", "drill_time_sig"):
                st.session_state.pop(k, None)
            st.session_state["drill_flash"] = "초기화 완료: " + (", ".join(deleted) if deleted else "없음")
            st.rerun()
    with no:
        if st.button("취소", use_container_width=True, key="drill_reset_no"):
            st.session_state[flag] = False
            st.rerun()


def _fmt_int(v: float | int) -> str:
    return f"{float(v):,.0f}"


def _fmt_num(v: float, digits: int = 2) -> str:
    return f"{float(v):,.{digits}f}"


def render() -> None:
    st.title("드릴설비 필요 분석")
    own_col, own_help = st.columns([1, 3])
    with own_col:
        owned = int(
            st.number_input(
                "현재 보유 대수",
                min_value=0,
                max_value=999,
                value=0,
                step=1,
                help="지금 가동 중인 드릴 설비 대수. 부족대수 = 월 필요대수 − 보유대수.",
                key="drill_owned",
            )
        )
    with own_help:
        st.caption(
            "월별 제품코드 필요수량과 제품별 가공시간(1매당 분)을 올리면 "
            "드릴 설비 **총 필요대수**와 **보유 대비 부족대수**를 계산합니다. "
            "부족대수 = 월 필요대수(올림) − 현재 보유 (0 미만은 0). "
            "GitHub `templates/`에 드릴_월별필요수량 / 드릴_제품가공시간을 올리면 Cloud 재시작 후에도 가져옵니다."
        )

    st.markdown("##### 수동 차감")
    st.caption(
        "올린 계획에서 빼려는 제품코드와 **매월 차감 매수**를 입력하세요. "
        "예: `A3E00T-SM` / `500` → 1~12월 모두 500매씩 차감합니다. "
        "행을 늘려 여러 제품을 넣을 수 있습니다."
    )
    deduct_edit = st.data_editor(
        pd.DataFrame({c: [""] if c == "제품코드" else [0.0] for c in DEDUCT_COLUMNS}),
        column_config={
            "제품코드": st.column_config.TextColumn("제품코드", help="예: A3E00T-SM"),
            "매월차감": st.column_config.NumberColumn(
                "매월 차감매수",
                min_value=0,
                step=1,
                format="%d",
                help="모든 월의 필요수량에서 이 매수만큼 뺍니다.",
            ),
        },
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="drill_deduct_editor",
    )

    force_gh = bool(st.session_state.pop("drill_gh_force_refresh", False))
    if force_gh:
        _sync_from_github(force=True)
        st.session_state["drill_flash"] = "GitHub 드릴 데이터 다시 가져오기 완료"
    else:
        _sync_from_github()

    flash = st.session_state.pop("drill_flash", None)
    if flash:
        st.success(flash)

    work_days = float(DEFAULT_WORK_DAYS)
    day_hours = float(DEFAULT_DAY_HOURS)
    util_pct = float(DEFAULT_UTILIZATION_PCT)

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
                help="한 달 실제 조업일. 모든 월에 동일하게 적용합니다.",
                key="drill_work_days",
            )
        )
        day_hours = float(
            st.number_input(
                "1일 가동시간 (시간)",
                min_value=1.0,
                max_value=24.0,
                value=float(DEFAULT_DAY_HOURS),
                step=0.5,
                help="드릴 설비 하루 가동 시간. 3조 연속이면 24.",
                key="drill_day_hours",
            )
        )
        util_pct = float(
            st.number_input(
                "가동률 (%)",
                min_value=1.0,
                max_value=100.0,
                value=float(DEFAULT_UTILIZATION_PCT),
                step=1.0,
                help="셋업·비가동을 빼려면 100보다 낮게. 1대 가용시간 = 작업일 × 일가동 × 60 × 가동률.",
                key="drill_util",
            )
        )
        avail = work_days * day_hours * 60.0 * (util_pct / 100.0)
        st.caption(
            f"1대 월 가용 = {work_days:g}일 × {day_hours:g}시간 × 60 × {util_pct:g}% "
            f"= **{avail:,.0f}분** ({avail / 60:,.0f}시간). "
            f"참고: 24시간 기준 {DAY_MINUTES}분/일."
        )
        if github_store_enabled():
            if st.button("GitHub에서 다시 가져오기", use_container_width=True, key="drill_gh_refresh"):
                st.session_state["drill_gh_force_refresh"] = True
                st.session_state["drill_gh_ok"] = False
                st.rerun()
        else:
            st.caption("GitHub Secrets([github] token/repo)가 없으면 다시 가져오기를 쓸 수 없습니다.")

        st.divider()
        st.header("데이터 등록")
        st.caption("양식을 받아 작성한 뒤 업로드하세요. 새로 올리면 같은 종류 이전 파일을 교체합니다.")
        st.dataframe(pd.DataFrame(_active_files()), use_container_width=True, hide_index=True)
        _render_reset_ui()

        qty_up = st.file_uploader("① 월별 제품코드 필요수량", type=["csv", "xlsx"], key="drill_up_qty")
        time_up = st.file_uploader("② 제품별 가공시간", type=["csv", "xlsx"], key="drill_up_time")
        qty_sig = (qty_up.name, int(getattr(qty_up, "size", 0) or 0)) if qty_up else None
        time_sig = (time_up.name, int(getattr(time_up, "size", 0) or 0)) if time_up else None
        if qty_up is not None and qty_sig != st.session_state.get("drill_qty_sig"):
            path, gh = _save_upload(qty_up, DRILL_QTY_STEM)
            st.session_state["drill_qty_sig"] = qty_sig
            st.session_state["drill_use_sample"] = False
            st.session_state["drill_flash"] = f"필요수량 저장: {path.name}" + (f" · {gh}" if gh else "")
            st.rerun()
        if time_up is not None and time_sig != st.session_state.get("drill_time_sig"):
            path, gh = _save_upload(time_up, DRILL_TIME_STEM)
            st.session_state["drill_time_sig"] = time_sig
            st.session_state["drill_use_sample"] = False
            st.session_state["drill_flash"] = f"가공시간 저장: {path.name}" + (f" · {gh}" if gh else "")
            st.rerun()

        st.subheader("양식 받기")
        st.caption("엑셀에서 한글이 깨지면 xlsx를 받으세요. 숫자는 예시이므로 자사 계획으로 바꿔 올리세요.")
        st.download_button(
            "월별 필요수량 엑셀 (예시)",
            data=xlsx_bytes(qty_template(), "필요수량"),
            file_name="드릴_월별필요수량.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="drill_dl_qty_xlsx",
        )
        st.download_button(
            "제품 가공시간 엑셀 (예시)",
            data=xlsx_bytes(time_template(), "가공시간"),
            file_name="드릴_제품가공시간.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="drill_dl_time_xlsx",
        )
        with st.expander("빈 양식 · CSV"):
            st.download_button(
                "월별 필요수량 빈 엑셀",
                data=empty_xlsx_bytes(QTY_WIDE_COLUMNS, "필요수량"),
                file_name="드릴_월별필요수량_빈양식.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="drill_dl_qty_empty_xlsx",
            )
            st.download_button(
                "제품 가공시간 빈 엑셀",
                data=empty_xlsx_bytes(TIME_COLUMNS, "가공시간"),
                file_name="드릴_제품가공시간_빈양식.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="drill_dl_time_empty_xlsx",
            )
            st.download_button(
                "월별 필요수량 CSV (예시)",
                data=csv_bytes(qty_template()),
                file_name="드릴_월별필요수량.csv",
                mime="text/csv",
                use_container_width=True,
                key="drill_dl_qty_csv",
            )
            st.download_button(
                "제품 가공시간 CSV (예시)",
                data=csv_bytes(time_template()),
                file_name="드릴_제품가공시간.csv",
                mime="text/csv",
                use_container_width=True,
                key="drill_dl_time_csv",
            )

        if st.button("예시 데이터로 미리보기", use_container_width=True, key="drill_preview"):
            st.session_state["drill_use_sample"] = True
            st.rerun()

        render_exit_ui(key_prefix="drill_")

    saved_qty, saved_times, notes = _load_saved()
    use_sample = bool(st.session_state.get("drill_use_sample"))
    if use_sample:
        qty_raw, time_raw = qty_template(), time_template()
        source_note = "예시 양식으로 미리보기 중입니다. 실제 계획이면 사이드바에서 업로드하세요."
    else:
        qty_raw, time_raw = saved_qty, saved_times
        source_note = ""

    if source_note:
        st.info(source_note)

    result = calc_drill_requirement(
        qty_raw,
        time_raw,
        work_days=work_days,
        day_hours=day_hours,
        utilization_pct=util_pct,
        deduct=deduct_edit,
    )

    if qty_raw.empty or time_raw.empty:
        missing = []
        if qty_raw.empty:
            missing.append("월별 필요수량")
        if time_raw.empty:
            missing.append("제품별 가공시간")
        st.info(
            "사이드바에서 **월별 필요수량**과 **제품별 가공시간** 양식을 받아 작성한 뒤 업로드하세요. "
            "바로 확인하려면 **예시 데이터로 미리보기**를 누르면 됩니다. "
            f"지금 없는 파일: {' · '.join(missing)}."
        )
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("##### 월별 필요수량 양식")
            st.dataframe(qty_template(), use_container_width=True, hide_index=True)
            st.caption("가로형: 제품코드(또는 코드구분) + 1월~12월. 세로형(년도, 월, 제품코드, 필요수량)도 가능합니다.")
        with c2:
            st.markdown("##### 제품별 가공시간 양식")
            st.dataframe(time_template(), use_container_width=True, hide_index=True)
            st.caption("매당가공시간_분 = 해당 제품 1매를 드릴하는 데 걸리는 시간(분).")
        st.markdown(
            """
**계산식**

- 제품·월 필요시간(분) = (원 필요수량 − 수동 차감) × 매당가공시간_분
- 1대 월 가용시간(분) = 월 작업일수 × 1일 가동시간 × 60 × 가동률
- 월 필요대수(이론) = 그 달 필요시간 합 ÷ 1대 월 가용시간
- **총 필요대수** = 월별 필요대수를 올림한 값 중 최대 (가장 바쁜 달을 커버하는 보유 대수)
            """
        )
        return

    if result["detail"].empty:
        if result.get("deduct_notes") and result["qty"].empty:
            st.warning("수동 차감 후 남은 필요수량이 없습니다. 차감 매수를 줄여 보세요.")
        elif result["qty"].empty:
            cols = ", ".join(str(c) for c in result.get("qty_columns") or []) or "(없음)"
            st.warning(
                "월별 필요수량에서 제품코드 열을 읽지 못했습니다. "
                "`제품코드` 또는 `코드구분` 열이 있는지 확인하세요. "
                f"현재 열: {cols}"
            )
        elif result["times"].empty:
            cols = ", ".join(str(c) for c in result.get("time_columns") or []) or "(없음)"
            st.warning(
                "제품 가공시간에서 매당가공시간_분 값을 읽지 못했습니다. "
                f"현재 열: {cols}"
            )
        else:
            st.warning(
                "수량과 가공시간의 제품코드가 겹치지 않습니다. "
                "철자·공백·하이픈을 확인하세요."
            )
        if result.get("deduct_notes"):
            st.info("수동 차감: " + " · ".join(result["deduct_notes"]))
        if result.get("deduct_missing"):
            st.warning(
                "수량 계획에 없어 차감하지 못한 제품코드: " + ", ".join(result["deduct_missing"])
            )
        if result["unmatched"]:
            st.caption("가공시간이 없는 제품코드: " + ", ".join(result["unmatched"][:30]))
        if result["unused_times"]:
            st.caption("수량 계획이 없는 가공시간 코드: " + ", ".join(result["unused_times"][:30]))
        with st.expander("올린 파일 미리보기", expanded=True):
            st.dataframe(qty_raw, use_container_width=True, hide_index=True)
            st.dataframe(time_raw, use_container_width=True, hide_index=True)
        return

    peak_label = result["peak_label"] or "-"
    total_req = int(result["total_required"])
    theo = float(result["peak_theoretical"])
    avail_min = float(result["machine_month_min"])
    short_peak = max(total_req - owned, 0)

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.metric("현재 보유", f"{owned}대")
    with k2:
        st.metric("총 필요대수", f"{total_req}대")
    with k3:
        st.metric("부족대수", f"{short_peak}대")
    with k4:
        st.metric("피크월", peak_label)

    st.caption(
        f"총 필요대수 {total_req}대 = {peak_label} 필요시간 "
        f"{result['peak_hours']:,.1f}시간 ÷ 1대 가용 {avail_min / 60:,.1f}시간 "
        f"→ 이론 {theo:.2f}대를 올림. "
        f"부족대수 = {total_req} − 보유 {owned} = {short_peak}대. "
        f"1대 월 가용 {avail_min:,.0f}분."
    )
    if result["unmatched"]:
        st.warning(
            "가공시간이 없어 계산에서 빠진 제품코드: " + ", ".join(result["unmatched"])
        )
    if result["unused_times"]:
        st.caption("수량 계획이 없는 가공시간 코드: " + ", ".join(result["unused_times"]))
    if result.get("deduct_notes"):
        st.info("수동 차감 적용: " + " · ".join(result["deduct_notes"]))
    if result.get("deduct_missing"):
        st.warning(
            "수량 계획에 없어 차감하지 못한 제품코드: " + ", ".join(result["deduct_missing"])
        )

    monthly = result["monthly"].copy()
    monthly["보유대수"] = owned
    monthly["부족대수"] = (monthly["필요대수"] - owned).clip(lower=0).astype(int)
    if owned > 0:
        monthly["보유대비부하%"] = (monthly["이론필요대수"] / owned * 100).round(1)
    else:
        monthly["보유대비부하%"] = None

    st.subheader("월별 부족 설비")
    st.caption(f"부족대수 = 월 필요대수(올림) − 현재 보유 {owned}대. 여유 달은 0으로 표시합니다.")
    chart_df = monthly[["월라벨", "필요대수", "보유대수", "부족대수"]].rename(columns={"월라벨": "월"})
    bars = (
        alt.Chart(chart_df)
        .mark_bar()
        .encode(
            x=alt.X("월:N", sort=list(monthly["월라벨"]), title="월"),
            y=alt.Y("부족대수:Q", title="부족 대수"),
            tooltip=["월", "필요대수", "보유대수", "부족대수"],
        )
    )
    hold_rule = (
        alt.Chart(pd.DataFrame({"y": [0]}))
        .mark_rule(strokeDash=[4, 4])
        .encode(y="y:Q")
    )
    st.altair_chart(
        (bars + hold_rule).properties(height=320, title=f"월별 부족 설비 (보유 {owned}대 기준)"),
        use_container_width=True,
    )

    show_m = monthly.copy()
    show_m["필요수량합"] = show_m["필요수량합"].map(_fmt_int)
    show_m["필요시간_분"] = show_m["필요시간_분"].map(lambda v: _fmt_num(v, 1))
    show_m["이론필요대수"] = show_m["이론필요대수"].map(lambda v: _fmt_num(v, 2))
    show_m["보유대비부하%"] = show_m["보유대비부하%"].map(
        lambda v: "-" if v is None or (isinstance(v, float) and pd.isna(v)) else _fmt_num(v, 1)
    )
    st.subheader("월별 필요대수")
    st.dataframe(
        show_m[
            [
                "월라벨",
                "필요수량합",
                "필요시간_분",
                "이론필요대수",
                "필요대수",
                "보유대수",
                "부족대수",
                "보유대비부하%",
            ]
        ].rename(columns={"월라벨": "월", "필요대수": "필요대수(올림)"}),
        use_container_width=True,
        hide_index=True,
    )

    peak_detail = result["detail"][result["detail"]["월라벨"] == peak_label].copy()
    if not peak_detail.empty:
        peak_detail = peak_detail.sort_values("필요시간_분", ascending=False)
        peak_sum = float(peak_detail["필요시간_분"].sum()) or 1.0
        peak_detail["비중%"] = (peak_detail["필요시간_분"] / peak_sum * 100).round(1)
        st.subheader(f"피크월({peak_label}) 제품별 부하")
        show_p = peak_detail.copy()
        show_p["필요수량"] = show_p["필요수량"].map(_fmt_int)
        if "차감매수" in show_p.columns:
            show_p["차감매수"] = show_p["차감매수"].map(_fmt_int)
        if "필요수량_원" in show_p.columns:
            show_p["필요수량_원"] = show_p["필요수량_원"].map(_fmt_int)
        show_p["매당가공시간_분"] = show_p["매당가공시간_분"].map(lambda v: _fmt_num(v, 2))
        show_p["필요시간_분"] = show_p["필요시간_분"].map(lambda v: _fmt_num(v, 1))
        show_p["이론필요대수"] = show_p["이론필요대수"].map(lambda v: _fmt_num(v, 3))
        peak_cols = [
            c
            for c in [
                "제품코드",
                "제품명",
                "필요수량_원",
                "차감매수",
                "필요수량",
                "매당가공시간_분",
                "필요시간_분",
                "이론필요대수",
                "비중%",
            ]
            if c in show_p.columns
        ]
        st.dataframe(
            show_p[peak_cols],
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("제품·월 상세"):
        detail = result["detail"].copy()
        detail["필요수량"] = detail["필요수량"].map(_fmt_int)
        if "차감매수" in detail.columns:
            detail["차감매수"] = detail["차감매수"].map(_fmt_int)
        if "필요수량_원" in detail.columns:
            detail["필요수량_원"] = detail["필요수량_원"].map(_fmt_int)
        detail["매당가공시간_분"] = detail["매당가공시간_분"].map(lambda v: _fmt_num(v, 2))
        detail["필요시간_분"] = detail["필요시간_분"].map(lambda v: _fmt_num(v, 1))
        detail["이론필요대수"] = detail["이론필요대수"].map(lambda v: _fmt_num(v, 3))
        detail_cols = [
            c
            for c in [
                "월라벨",
                "제품코드",
                "제품명",
                "필요수량_원",
                "차감매수",
                "필요수량",
                "매당가공시간_분",
                "필요시간_분",
                "이론필요대수",
            ]
            if c in detail.columns
        ]
        st.dataframe(
            detail[detail_cols].rename(columns={"월라벨": "월"}),
            use_container_width=True,
            hide_index=True,
        )
        st.download_button(
            "상세 CSV 다운로드",
            data=result["detail"].to_csv(index=False).encode("utf-8-sig"),
            file_name="드릴설비_필요분석_상세.csv",
            mime="text/csv",
            key="drill_dl_detail",
        )

    with st.expander("계산식 · 올린 파일"):
        st.markdown(
            f"""
- 제품·월 필요시간(분) = (원 필요수량 − 수동 차감) × 매당가공시간_분
- 1대 월 가용 = {work_days:g} × {day_hours:g} × 60 × {util_pct:g}% = **{avail_min:,.0f}분**
- 월 필요대수(올림) = ceil(그 달 필요시간 합 ÷ 1대 월 가용)
- 부족대수 = max(월 필요대수 − 현재 보유 {owned}대, 0)
- 총 필요대수 = 월별 올림 대수 중 최대
- 총 부족대수 = max(총 필요대수 − 보유, 0)
            """
        )
        for n in notes:
            st.write("- ", n)
        st.markdown("**월별 필요수량**")
        st.dataframe(qty_raw, use_container_width=True)
        st.markdown("**제품별 가공시간**")
        st.dataframe(time_raw, use_container_width=True)
