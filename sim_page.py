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
from pathlib import Path

from io import BytesIO

from auth import github_file_get, github_file_put, github_store_enabled, render_logout_controls
from stats_engine import AREAS, SHIFTS, add_calendar_parts
from sim_engine import (
    DEFAULT_SHIFT_MINUTES,
    DEFAULT_SHIFT_TEAMS,
    DEFAULT_WORK_DAYS,
    DEFAULT_WORKING_TEAMS,
    EQUIP_COLUMNS,
    MANPOWER_COLUMNS,
    MASTER_STEMS,
    MONTHLY_PLAN_COLUMNS,
    PRODUCT_ACTUAL_COLUMNS,
    PRODUCT_COLUMNS,
    canonical_master_name,
    csv_bytes,
    daily_operation_plan,
    empty_csv_bytes,
    empty_xlsx_bytes,
    equipment_template,
    manpower_template,
    master_github_paths,
    monthly_plan_feasibility,
    monthly_plan_template,
    newest_matching,
    normalize_equipment,
    normalize_manpower,
    normalize_monthly_plan,
    normalize_product_actuals,
    normalize_products,
    process_standard_times,
    product_actual_template,
    product_template,
    read_csv_table,
    xlsx_bytes,
    utilization_from_actuals,
)


def _read_plan_csv(raw: bytes) -> pd.DataFrame:
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return pd.read_csv(BytesIO(raw), encoding=enc).dropna(how="all")
        except UnicodeDecodeError:
            continue
    return pd.DataFrame()


def master_dir():
    folder = data_dir() / "master"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _list_master_paths(stem: str | None = None) -> list[Path]:
    folder = master_dir()
    stems = (stem,) if stem else MASTER_STEMS
    files: list[Path] = []
    for s in stems:
        files.extend(folder.glob(f"{s}*.csv"))
        files.extend(folder.glob(f"{s}*.xlsx"))
        files.extend(folder.glob(f"{s}*.xls"))
    return [p for p in files if not p.name.startswith("~$")]


def _clear_master_files(stem: str | None = None) -> list[str]:
    """운영 중 기준정보 파일을 지운다. stem 없으면 전부."""
    deleted: list[str] = []
    for path in _list_master_paths(stem):
        try:
            path.unlink()
            deleted.append(path.name)
        except OSError:
            continue
    return deleted


def _push_master_github(filename: str, content: bytes) -> str:
    if not github_store_enabled():
        return ""
    rel = f"templates/{filename}"
    try:
        _, sha = github_file_get(rel)
        github_file_put(rel, content, f"chore: update {filename}", sha)
        return f"GitHub 반영: {rel}"
    except Exception as e:
        return f"GitHub 저장 실패: {e}"


def _sync_master_from_github(*, force: bool = False) -> list[str]:
    """GitHub templates → data/master.

    - force=False: 로컬에 이미 있는 종류는 유지(업로드분 덮어쓰지 않음). 없는 종류만 가져옴.
    - force=True: 로컬을 지우고 저장소에서 다시 받음.
    """
    if not github_store_enabled():
        return ["GitHub Secrets([github] token/repo)가 없어 로컬·업로드 파일만 사용합니다."]
    if not force and st.session_state.get("sim_gh_master_ok"):
        return list(st.session_state.get("sim_gh_master_notes") or [])
    notes: list[str] = []
    folder = master_dir()
    if force:
        cleared = _clear_master_files()
        if cleared:
            notes.append("로컬 기준정보 초기화: " + ", ".join(cleared))
    for stem in MASTER_STEMS:
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
            _clear_master_files(stem)
            dest.write_bytes(found_raw)
            notes.append(f"GitHub에서 가져옴: {found_rel}")
        else:
            notes.append(f"{stem}: 저장소에 없음 (templates/{stem}.csv 또는 .xlsx)")
    st.session_state["sim_gh_master_ok"] = True
    st.session_state["sim_gh_master_notes"] = notes
    return notes


def _save_upload(uploaded, prefix: str):
    """같은 종류 옛 파일을 지우고 새 파일만 운영한다."""
    name = canonical_master_name(uploaded.name, prefix)
    _clear_master_files(prefix)
    dest = master_dir() / name
    data = uploaded.getvalue()
    dest.write_bytes(data)
    # 업로드분을 GitHub 재동기화가 덮어쓰지 않도록
    st.session_state["sim_gh_master_ok"] = True
    st.session_state.pop("sim_gh_master_notes", None)
    gh = _push_master_github(name, data)
    return dest, gh


def _render_master_reset_ui() -> None:
    flag = "sim_confirm_reset_master"
    if flag not in st.session_state:
        st.session_state[flag] = False
    files = _list_master_paths()
    if not files:
        st.caption("초기화할 운영 기준정보가 없습니다.")
        return
    if not st.session_state[flag]:
        if st.button("운영 기준정보 초기화", use_container_width=True, key="sim_btn_reset_master"):
            st.session_state[flag] = True
            st.rerun()
        return
    st.warning("지금 운영 중인 기준정보 파일을 모두 삭제합니다. 그다음 새로 업로드하면 됩니다.")
    st.caption("삭제 대상: " + ", ".join(p.name for p in files))
    yes, no = st.columns(2)
    with yes:
        if st.button("삭제", type="primary", use_container_width=True, key="sim_reset_master_yes"):
            deleted = _clear_master_files()
            st.session_state[flag] = False
            st.session_state["sim_gh_master_ok"] = False
            st.session_state.pop("sim_gh_master_notes", None)
            for k in ("sim_eq_sig", "sim_man_sig", "sim_pr_sig", "sim_act_sig"):
                st.session_state.pop(k, None)
            st.session_state["sim_flash"] = "기준정보 초기화 완료: " + (", ".join(deleted) if deleted else "없음")
            st.rerun()
    with no:
        if st.button("취소", use_container_width=True, key="sim_reset_master_no"):
            st.session_state[flag] = False
            st.rerun()


def _active_master_files() -> list[dict[str, str]]:
    """지금 운영에 쓰는 기준정보 파일 목록."""
    folder = master_dir()
    rows: list[dict[str, str]] = []
    for label, stem in (
        ("설비", "설비_기준정보"),
        ("인력", "인력_기준정보"),
        ("제품", "제품_기준정보"),
        ("제품별 실적", "제품별_실적"),
    ):
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


def _load_master() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    folder = master_dir()
    notes: list[str] = []
    eq_path = newest_matching(folder, "설비_기준정보")
    man_path = newest_matching(folder, "인력_기준정보")
    pr_path = newest_matching(folder, "제품_기준정보")
    act_path = newest_matching(folder, "제품별_실적")
    equip = pd.DataFrame()
    manpower = pd.DataFrame()
    products = pd.DataFrame()
    actuals = pd.DataFrame()
    if eq_path:
        equip = normalize_equipment(read_csv_table(eq_path))
        notes.append(f"설비: {eq_path.name} ({len(equip)}행)")
    else:
        notes.append("설비 기준정보가 없습니다. (설비 공정용)")
    if man_path:
        manpower = normalize_manpower(read_csv_table(man_path))
        notes.append(f"인력: {man_path.name} ({len(manpower)}행)")
    else:
        notes.append("인력 기준정보가 없습니다. (외관 등 수작업 공정용)")
    if pr_path:
        products = normalize_products(read_csv_table(pr_path))
        notes.append(f"제품: {pr_path.name} ({len(products)}행)")
    else:
        notes.append("제품 기준정보가 없습니다. GitHub templates/ 또는 업로드하세요.")
    if act_path:
        actuals = normalize_product_actuals(read_csv_table(act_path))
        notes.append(f"제품별 실적: {act_path.name} ({len(actuals)}행)")
    return equip, manpower, products, actuals, notes


def render() -> None:
    st.title("설비 운영 시뮬레이션")
    st.caption(
        "보유 설비·인력과 제품 택트로 하루 능력을 보고, 실적 대비 인당 시간 활용률을 계산합니다. "
        "인력 기준정보의 인원은 **전 공정·3개조 합계**로 두고, 하루 능력은 근무조(기본 2/3)만 반영합니다. "
        "설비 대수는 설비_기준정보를 캠퍼스·공정으로 합산합니다. "
        "외관처럼 설비 없이 사람이 하는 공정은 `인력_기준정보`에 넣습니다. "
        "GitHub `templates/`에 설비_기준정보 / 인력_기준정보 / 제품_기준정보 / 제품별_실적을 올리면 자동으로 가져옵니다."
    )

    records, rec_notes, _chosen = load_records()

    # GitHub 다시 가져오기 / 초기화 직후 메시지
    force_gh = bool(st.session_state.pop("sim_gh_force_refresh", False))
    if force_gh:
        _sync_master_from_github(force=True)
        st.session_state["sim_flash"] = "GitHub 기준정보 다시 가져오기 완료"
    else:
        _sync_master_from_github()

    equip, manpower, products, product_actuals, _master_notes = _load_master()

    flash = st.session_state.pop("sim_flash", None)
    st.session_state.pop("sim_flash_detail", None)
    if flash:
        st.success(flash)

    campus_sel: list[str] = []
    shift_sel: list[str] = []
    area_sel = list(AREAS)
    team_sel: list[str] = []
    product_name_sel: list[str] = []
    available_min = float(DEFAULT_SHIFT_MINUTES)
    shift_teams = DEFAULT_SHIFT_TEAMS
    working_teams = DEFAULT_WORKING_TEAMS

    with st.sidebar:
        st.header("계정")
        render_logout_controls()
        st.divider()
        st.header("조회 조건")
        campus_opts = []
        if not equip.empty:
            campus_opts = sorted(equip["캠퍼스"].dropna().unique().tolist())
        if not manpower.empty and "캠퍼스" in manpower.columns:
            campus_opts = sorted(set(campus_opts) | set(manpower["캠퍼스"].dropna().unique().tolist()))
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
        names = sorted(products["제품명"].dropna().unique().tolist()) if not products.empty and "제품명" in products.columns else []
        product_name_sel = (
            render_slicer("제품명", names, key="sim_product_name", default_on=True) if names else []
        )
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
        st.markdown("**교대·인원 환산 (능력 계산)**")
        shift_teams = int(
            st.number_input(
                "총 조 수",
                min_value=1,
                max_value=6,
                value=DEFAULT_SHIFT_TEAMS,
                step=1,
                help="인력 기준정보의 인원에 포함된 조 수. 3조 2교대면 3.",
                key="sim_shift_teams",
            )
        )
        working_teams = int(
            st.number_input(
                "하루 근무 조 수",
                min_value=1,
                max_value=shift_teams,
                value=min(DEFAULT_WORKING_TEAMS, shift_teams),
                step=1,
                help="하루 실제로 근무하는 조 수. 3조 2교대면 2 (주·야), 1조는 휴무.",
                key="sim_working_teams",
            )
        )
        st.caption(
            f"근무인원 = 총인원 × ({working_teams}/{shift_teams}) = 총인원 × {working_teams / shift_teams:.4g}. "
            "설비 능력(대수×1440)에는 적용하지 않습니다."
        )
        available_min = float(
            st.number_input(
                "인당 가용 분 (활용률 분모)",
                min_value=60,
                max_value=1440,
                value=DEFAULT_SHIFT_MINUTES,
                step=60,
                help="실적 활용률 분모. 1인 1교대 기준이면 보통 720(12시간). 설비 이론능력은 대수×1440.",
            )
        )
        if github_store_enabled():
            if st.button("GitHub에서 기준정보 다시 가져오기", use_container_width=True, key="sim_gh_refresh"):
                st.session_state["sim_gh_force_refresh"] = True
                st.session_state["sim_gh_master_ok"] = False
                st.rerun()
        else:
            st.caption("GitHub Secrets([github] token/repo)가 없으면 다시 가져오기를 쓸 수 없습니다.")

        st.divider()
        st.header("기준정보 등록")
        st.caption(
            "파일명: 설비_기준정보 / 인력_기준정보 / 제품_기준정보 / 제품별_실적 (.csv 또는 .xlsx). "
            "외관 등 수작업은 인력_기준정보에 인원을 넣으세요. "
            "치수·Hole 등 설비 공정도 인력_기준정보에 공정별 인원을 넣으면 총인원/근무인원에 반영됩니다. "
            "새로 올리면 같은 종류의 이전 운영 파일은 자동으로 교체됩니다."
        )
        st.markdown("**지금 운영 중**")
        active_df = pd.DataFrame(_active_master_files())
        st.dataframe(active_df, use_container_width=True, hide_index=True)
        _render_master_reset_ui()
        eq_up = st.file_uploader("① 설비_기준정보", type=["csv", "xlsx"], key="sim_up_eq")
        man_up = st.file_uploader("② 인력_기준정보 (외관 등)", type=["csv", "xlsx"], key="sim_up_man")
        pr_up = st.file_uploader("③ 제품_기준정보", type=["csv", "xlsx"], key="sim_up_pr")
        act_up = st.file_uploader("④ 제품별_실적", type=["csv", "xlsx"], key="sim_up_act")
        eq_sig = (eq_up.name, int(getattr(eq_up, "size", 0) or 0)) if eq_up else None
        man_sig = (man_up.name, int(getattr(man_up, "size", 0) or 0)) if man_up else None
        pr_sig = (pr_up.name, int(getattr(pr_up, "size", 0) or 0)) if pr_up else None
        act_sig = (act_up.name, int(getattr(act_up, "size", 0) or 0)) if act_up else None
        if eq_up is not None and eq_sig != st.session_state.get("sim_eq_sig"):
            path, gh = _save_upload(eq_up, "설비_기준정보")
            st.session_state["sim_eq_sig"] = eq_sig
            st.session_state["sim_flash"] = f"설비 교체 완료: {path.name}" + (f" · {gh}" if gh else "")
            st.rerun()
        if man_up is not None and man_sig != st.session_state.get("sim_man_sig"):
            path, gh = _save_upload(man_up, "인력_기준정보")
            st.session_state["sim_man_sig"] = man_sig
            st.session_state["sim_flash"] = f"인력 교체 완료: {path.name}" + (f" · {gh}" if gh else "")
            st.rerun()
        if pr_up is not None and pr_sig != st.session_state.get("sim_pr_sig"):
            path, gh = _save_upload(pr_up, "제품_기준정보")
            st.session_state["sim_pr_sig"] = pr_sig
            st.session_state["sim_flash"] = f"제품 교체 완료: {path.name}" + (f" · {gh}" if gh else "")
            st.rerun()
        if act_up is not None and act_sig != st.session_state.get("sim_act_sig"):
            path, gh = _save_upload(act_up, "제품별_실적")
            st.session_state["sim_act_sig"] = act_sig
            st.session_state["sim_flash"] = f"제품별 실적 교체 완료: {path.name}" + (f" · {gh}" if gh else "")
            st.rerun()
        st.subheader("양식 받기")
        st.caption("엑셀에서 한글이 깨지면 xlsx를 받으세요.")
        st.download_button(
            "인력 기준정보 엑셀 (외관 등)",
            data=xlsx_bytes(manpower_template(), "인력"),
            file_name="인력_기준정보.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="sim_dl_man_xlsx",
        )
        st.download_button(
            "제품 기준정보 엑셀",
            data=xlsx_bytes(product_template(), "제품"),
            file_name="제품_기준정보.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="sim_dl_pr_xlsx",
        )
        st.download_button(
            "설비 기준정보 엑셀",
            data=xlsx_bytes(equipment_template(), "설비"),
            file_name="설비_기준정보.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="sim_dl_eq_xlsx",
        )
        st.download_button(
            "제품별_실적 엑셀",
            data=xlsx_bytes(product_actual_template(), "제품실적"),
            file_name="제품별_실적.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="sim_dl_act_xlsx",
        )
        with st.expander("빈 양식 · CSV"):
            st.download_button(
                "인력 기준정보 빈 엑셀",
                data=empty_xlsx_bytes(MANPOWER_COLUMNS, "인력"),
                file_name="인력_기준정보_빈양식.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="sim_dl_man_xlsx_empty",
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
                "설비 기준정보 빈 엑셀",
                data=empty_xlsx_bytes(EQUIP_COLUMNS, "설비"),
                file_name="설비_기준정보_빈양식.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="sim_dl_eq_xlsx_empty",
            )
            st.download_button(
                "제품별_실적 빈 엑셀",
                data=empty_xlsx_bytes(PRODUCT_ACTUAL_COLUMNS, "제품실적"),
                file_name="제품별_실적_빈양식.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="sim_dl_act_xlsx_empty",
            )
            st.download_button(
                "인력 기준정보 CSV",
                data=csv_bytes(manpower_template()),
                file_name="인력_기준정보.csv",
                mime="text/csv",
                use_container_width=True,
                key="sim_dl_man_ex",
            )
            st.download_button(
                "설비 기준정보 CSV",
                data=csv_bytes(equipment_template()),
                file_name="설비_기준정보.csv",
                mime="text/csv",
                use_container_width=True,
                key="sim_dl_eq_ex",
            )
            st.download_button(
                "제품 기준정보 CSV",
                data=csv_bytes(product_template()),
                file_name="제품_기준정보.csv",
                mime="text/csv",
                use_container_width=True,
                key="sim_dl_pr_ex",
            )
            st.download_button(
                "제품별_실적 CSV",
                data=csv_bytes(product_actual_template()),
                file_name="제품별_실적.csv",
                mime="text/csv",
                use_container_width=True,
                key="sim_dl_act",
            )

    eq_view = equip.copy()
    man_view = manpower.copy()
    pr_view = products.copy()
    if campus_sel and not eq_view.empty:
        eq_view = eq_view[eq_view["캠퍼스"].isin(campus_sel) | (eq_view["캠퍼스"] == "")]
    if campus_sel and not man_view.empty:
        man_view = man_view[man_view["캠퍼스"].isin(campus_sel) | (man_view["캠퍼스"] == "")]
    if area_sel and not eq_view.empty:
        eq_view = eq_view[eq_view["공정"].isin(area_sel)]
    if area_sel and not man_view.empty:
        man_view = man_view[man_view["공정"].isin(area_sel)]
    if area_sel and not pr_view.empty:
        pr_view = pr_view[pr_view["공정"].isin(area_sel)]
    if product_name_sel and not pr_view.empty and "제품명" in pr_view.columns:
        pr_view = pr_view[pr_view["제품명"].isin(product_name_sel)]

    tab_sim, tab_master, tab_util = st.tabs(["운영 시뮬레이션", "기준정보", "실적 시간 활용"])

    with tab_master:
        st.subheader("현재 적용 중인 기준")
        st.markdown("**설비** — 가동여부가 Y/가동/1 이면 시뮬레이션에 포함합니다.")
        if eq_view.empty:
            st.info("설비 기준정보를 업로드하세요. (종합측정실·치수·Hole 등)")
        else:
            st.dataframe(eq_view.drop(columns=["가동"], errors="ignore"), use_container_width=True)
            by = eq_view[eq_view["가동"]].groupby(["캠퍼스", "공정"], as_index=False)["대수"].sum()
            st.caption("가동 대수 합계")
            st.dataframe(by, use_container_width=True)
        st.markdown(
            "**인력** — `인력_기준정보`는 **캠퍼스+공정** 단위로 둡니다. "
            "치수처럼 설비가 2종이어도 인원을 설비별로 나누지 않습니다. "
            "`인원`은 3개조 합계, `가용분`은 1인 1교대 분(권장 720). "
            f"인력 능력 = 총인원×({working_teams}/{shift_teams}) × 가용분 ÷ 매당_인시분."
        )
        if man_view.empty:
            st.info("인력 기준정보를 업로드하세요. (전 공정 인원)")
        else:
            st.dataframe(man_view.drop(columns=["가동"], errors="ignore"), use_container_width=True)
        st.markdown(
            "**제품** — `제약유형`이 설비가면 매당_설비분, 인력이면 매당_인시분을 씁니다. "
            "외관은 제약유형=인력, 설비코드는 비워 두면 됩니다."
        )
        if pr_view.empty:
            st.info("제품 기준정보를 업로드하세요.")
        else:
            st.dataframe(pr_view, use_container_width=True)
        st.markdown("**제품별 실적** — 있으면 활용률을 제품 택트 기준으로 계산합니다.")
        if product_actuals.empty:
            st.caption("없으면 기존 공정 실적 파일로 계산합니다.")
        else:
            st.dataframe(product_actuals, use_container_width=True)

    with tab_sim:
        st.subheader("월 생산 계획")
        st.caption(
            "**제품코드 + 월목표매수** CSV를 업로드하면 일목표·공정별 시간 배분·하루 운영안·달성 여부를 계산합니다. "
            f"근무인원 = 총인원 × ({working_teams}/{shift_teams})."
        )

        campus_scopes: list[tuple[str, str | None]] = [("Total", None)]
        for c in CAMPUSES:
            if campus_sel and c not in campus_sel:
                continue
            campus_scopes.append((c, c))
        extra = []
        if not eq_view.empty and "캠퍼스" in eq_view.columns:
            extra.extend(eq_view["캠퍼스"].dropna().unique().tolist())
        if not man_view.empty and "캠퍼스" in man_view.columns:
            extra.extend(man_view["캠퍼스"].dropna().unique().tolist())
        for c in sorted({str(x) for x in extra if str(x).strip()}):
            if c and c not in {n for n, _ in campus_scopes}:
                if campus_sel and c not in campus_sel:
                    continue
                campus_scopes.append((c, c))

        if pr_view.empty or (eq_view.empty and man_view.empty):
            st.warning("제품·설비·인력 기준정보를 먼저 올려 주세요.")
        else:
            work_days = int(
                st.number_input(
                    "월 작업일수",
                    min_value=1,
                    max_value=31,
                    value=DEFAULT_WORK_DAYS,
                    step=1,
                    key="sim_work_days",
                    help="일목표 = 월목표 ÷ 작업일수",
                )
            )
            plan_dl, plan_up = st.columns(2)
            with plan_dl:
                st.download_button(
                    "월 생산계획 양식 CSV",
                    data=csv_bytes(monthly_plan_template()),
                    file_name="월_생산계획.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key="sim_dl_plan_csv",
                )
            with plan_up:
                plan_file = st.file_uploader(
                    "월 생산계획 CSV 업로드",
                    type=["csv"],
                    key="sim_plan_upload",
                    help="열: 제품코드, 월목표매수",
                )
            if plan_file is not None:
                sig = (plan_file.name, int(getattr(plan_file, "size", 0) or 0))
                if sig != st.session_state.get("sim_plan_sig"):
                    try:
                        uploaded = _read_plan_csv(plan_file.getvalue())
                    except Exception:
                        uploaded = pd.DataFrame()
                    if uploaded.empty:
                        st.error("CSV를 읽지 못했습니다. 인코딩·열 이름을 확인하세요.")
                    else:
                        st.session_state["sim_plan_upload_df"] = uploaded
                        st.session_state["sim_plan_sig"] = sig
                        st.session_state["sim_plan_fname"] = plan_file.name
                        st.rerun()

            plan_raw = st.session_state.get("sim_plan_upload_df")
            plan_for_calc = normalize_monthly_plan(plan_raw) if plan_raw is not None else pd.DataFrame()

            if plan_raw is None:
                st.info("월 생산계획 CSV를 업로드하세요. (제품코드, 월목표매수)")
            elif plan_for_calc.empty:
                st.warning("유효한 행이 없습니다. 제품코드와 월목표매수(>0)를 확인하세요.")
            else:
                fname = st.session_state.get("sim_plan_fname", "업로드 파일")
                st.caption(f"적용 중: **{fname}** · {len(plan_for_calc)}종")
                st.dataframe(plan_for_calc, use_container_width=True, hide_index=True)
                for label, camp in campus_scopes:
                    detail, summary, missing = monthly_plan_feasibility(
                        pr_view,
                        eq_view,
                        plan_for_calc,
                        campus=camp,
                        work_days=work_days,
                        manpower=man_view,
                        shift_teams=shift_teams,
                        working_teams=working_teams,
                    )
                    st.markdown(f"**생산 계획 · {label}**")
                    if missing:
                        st.warning(
                            "제품 기준정보에 없는 코드: "
                            + ", ".join(missing[:20])
                            + (" …" if len(missing) > 20 else "")
                        )
                    if summary.empty:
                        st.caption("계획에 유효한 제품코드가 없습니다. 기준정보와 코드를 맞춰 주세요.")
                        continue
                    ok_n = int((summary["달성"] == "OK").sum())
                    ng_n = int((summary["달성"] != "OK").sum())
                    c1, c2, c3, c4 = st.columns(4)
                    with c1:
                        st.metric("계획 품목", f"{len(summary)}종")
                    with c2:
                        st.metric("달성 OK", f"{ok_n}")
                    with c3:
                        st.metric("부족", f"{ng_n}")
                    with c4:
                        st.metric("작업일", f"{work_days}일")
                    st.markdown("**월·일 목표 vs 가능**")
                    show_sum = summary[
                        [
                            c
                            for c in (
                                "제품코드",
                                "제품명",
                                "월목표매수",
                                "일목표매수",
                                "월가능매수",
                                "일가능매수",
                                "병목공정",
                                "달성",
                                "부족매수",
                            )
                            if c in summary.columns
                        ]
                    ]
                    st.dataframe(show_sum, use_container_width=True, hide_index=True)
                    daily = daily_operation_plan(detail, summary)
                    st.markdown("**하루 운영안 (공정별 시간·매수 배분)**")
                    st.dataframe(daily, use_container_width=True, hide_index=True)
                    with st.expander(f"{label} · 공정별 상세", expanded=False):
                        st.dataframe(detail, use_container_width=True, hide_index=True)
                        chart_df = summary.melt(
                            id_vars=["제품코드"],
                            value_vars=["월목표매수", "월가능매수"],
                            var_name="구분",
                            value_name="매수",
                        )
                        chart_df["구분"] = chart_df["구분"].map(
                            {"월목표매수": "월목표", "월가능매수": "월가능"}
                        )
                        chart_df["라벨"] = chart_df["매수"].map(lambda v: f"{v:,.0f}")
                        y_max = float(chart_df["매수"].max() or 0) * 1.15 or 1.0
                        bars = (
                            alt.Chart(chart_df)
                            .mark_bar()
                            .encode(
                                x=alt.X("제품코드:N", title="제품코드"),
                                xOffset=alt.XOffset("구분:N", sort=["월목표", "월가능"]),
                                y=alt.Y("매수:Q", title="매수/월", scale=alt.Scale(domain=[0, y_max])),
                                color=alt.Color("구분:N", sort=["월목표", "월가능"]),
                                tooltip=["제품코드", "구분", "매수"],
                            )
                        )
                        texts = (
                            alt.Chart(chart_df)
                            .mark_text(dy=-8, fontSize=10)
                            .encode(
                                x=alt.X("제품코드:N"),
                                xOffset=alt.XOffset("구분:N", sort=["월목표", "월가능"]),
                                y=alt.Y("매수:Q", scale=alt.Scale(domain=[0, y_max])),
                                text=alt.Text("라벨:N"),
                            )
                        )
                        st.altair_chart(
                            (bars + texts).properties(height=280, title=f"{label} — 월목표 vs 월가능"),
                            use_container_width=True,
                        )

    with tab_util:
        st.subheader("실적 기준 인당 시간 활용")
        st.caption(
            f"인당시간활용률(%) = (실적 × 매당_인시분) ÷ (인력 × {available_min:g}분) × 100. "
            "여기서 인력은 실적에 적힌 당일·당조 인원입니다(전 조 합계에 2/3를 또 적용하지 않음). "
            "100%면 기준 택트만큼 시간을 다 쓴 것이고, 낮으면 여유·대기·다른 일이 있는 쪽으로 봅니다."
        )
        util = pd.DataFrame()
        pa = product_actuals.copy()
        if not pa.empty:
            if campus_sel and "캠퍼스" in pa.columns:
                pa = pa[pa["캠퍼스"].isin(campus_sel) | (pa["캠퍼스"].fillna("") == "")]
            if area_sel and "공정" in pa.columns:
                pa = pa[pa["공정"].isin(area_sel)]
            if team_sel and "조" in pa.columns:
                pa = pa[pa["조"].isin(team_sel)]
            if shift_sel and "주야" in pa.columns:
                pa = pa[pa["주야"].isin(shift_sel)]
            if product_name_sel:
                if "제품명" in pa.columns:
                    pa = pa[pa["제품명"].isin(product_name_sel)]
                elif "제품코드" in pa.columns and not products.empty and "제품명" in products.columns:
                    codes = products.loc[products["제품명"].isin(product_name_sel), "제품코드"]
                    pa = pa[pa["제품코드"].isin(codes)]
        if not pa.empty and not pr_view.empty:
            tact = pr_view[["제품코드", "공정", "매당_인시분"]].drop_duplicates()
            merged = pa.merge(tact, on=["제품코드", "공정"], how="left")
            util = utilization_from_actuals(merged, pd.DataFrame(), available_min=available_min)
            st.caption("제품별_실적 파일과 제품 택트로 계산합니다.")
        elif records.empty:
            util = pd.DataFrame()
            st.info("제품별_실적 또는 홈 화면 실적 파일이 있어야 활용률을 봅니다.")
        elif pr_view.empty:
            util = pd.DataFrame()
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
                util = pd.DataFrame()
                st.warning("선택 조건에 해당하는 실적이 없습니다.")
            else:
                std = process_standard_times(
                    pr_view,
                    pr_view["제품코드"].dropna().unique().tolist() if not pr_view.empty else None,
                )
                util = utilization_from_actuals(filtered, std, available_min=available_min)
                st.caption("공정 실적 파일과 제품 평균 택트로 계산합니다.")
        if not pa.empty and not pr_view.empty and util.empty:
            st.warning("제품별 실적과 기준정보의 제품코드·공정이 맞지 않습니다.")
        elif not util.empty:
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
                by_team = util.groupby("조", as_index=False)["인당시간활용률"].mean().round(1)
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
