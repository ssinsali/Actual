"""QA그룹 CAPA 관리 — 월별 치수·홀 필요대수와 가동율."""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from app_common import data_dir, render_exit_ui
from auth import github_file_get, github_file_put, github_store_enabled, render_logout_controls
from capa_engine import (
    PLAN_COLUMNS,
    PRODUCT_STEM,
    QA_PLAN_STEM,
    QA_STEMS,
    _LEGACY_TIME_STEM,
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
    master_github_paths,
    newest_matching,
    normalize_equipment,
    product_template,
    read_csv_table,
    running_qty,
    xlsx_bytes,
)

DEFAULT_DAY_HOURS = 24.0
DEFAULT_UTILIZATION_PCT = 100.0

SETTINGS_STEM = "QA_가동조건"
SETTINGS_FILE = f"{SETTINGS_STEM}.json"
SETTINGS_KEYS = (
    "capa_work_days",
    "capa_day_hours",
    "capa_util",
    "capa_owned_dim",
    "capa_owned_hole",
)


def master_dir() -> Path:
    folder = data_dir() / "master"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _settings_path() -> Path:
    return master_dir() / SETTINGS_FILE


def _default_settings(*, dim: int = 0, hole: int = 0) -> dict:
    return {
        "capa_work_days": float(DEFAULT_WORK_DAYS),
        "capa_day_hours": float(DEFAULT_DAY_HOURS),
        "capa_util": float(DEFAULT_UTILIZATION_PCT),
        "capa_owned_dim": int(dim),
        "capa_owned_hole": int(hole),
    }


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


def _save_settings(settings: dict) -> str:
    path = _settings_path()
    payload = {k: settings.get(k) for k in SETTINGS_KEYS}
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(raw)
    return _push_github(SETTINGS_FILE, raw)


def _read_settings_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict = {}
    for key in SETTINGS_KEYS:
        if key not in data:
            continue
        try:
            if key in ("capa_owned_dim", "capa_owned_hole"):
                out[key] = int(float(data[key]))
            else:
                out[key] = float(data[key])
        except (TypeError, ValueError):
            continue
    return out


def _load_settings_local() -> dict:
    path = _settings_path()
    if not path.is_file():
        return {}
    return _read_settings_file(path)


def _sync_settings_from_github(*, force: bool = False) -> str:
    if not github_store_enabled():
        return ""
    local = _settings_path()
    if local.is_file() and not force:
        return "가동조건: 로컬 유지"
    for rel in (f"templates/{SETTINGS_FILE}", f"data/master/{SETTINGS_FILE}", SETTINGS_FILE):
        try:
            raw, _sha = github_file_get(rel)
        except Exception as e:
            if "404" in str(e):
                continue
            return f"가동조건 GitHub 오류: {e}"
        if raw:
            local.write_bytes(raw)
            return f"가동조건 GitHub에서 가져옴: {rel}"
    return "가동조건: 저장소에 없음"


def _apply_settings_to_session(settings: dict) -> None:
    for key, val in settings.items():
        if key not in st.session_state:
            st.session_state[key] = val


def _current_settings_from_session() -> dict:
    base = _default_settings()
    out = {}
    for key in SETTINGS_KEYS:
        out[key] = st.session_state[key] if key in st.session_state else base[key]
    return out


def _normalize_settings(settings: dict) -> dict:
    return {
        "capa_work_days": float(settings.get("capa_work_days", DEFAULT_WORK_DAYS)),
        "capa_day_hours": float(settings.get("capa_day_hours", DEFAULT_DAY_HOURS)),
        "capa_util": float(settings.get("capa_util", DEFAULT_UTILIZATION_PCT)),
        "capa_owned_dim": int(float(settings.get("capa_owned_dim", 0) or 0)),
        "capa_owned_hole": int(float(settings.get("capa_owned_hole", 0) or 0)),
    }


def _persist_settings_if_changed() -> None:
    now = _normalize_settings(_current_settings_from_session())
    prev = st.session_state.get("capa_settings_saved")
    if isinstance(prev, dict):
        prev = _normalize_settings(prev)
    if prev == now:
        return
    gh = _save_settings(now)
    st.session_state["capa_settings_saved"] = dict(now)
    if gh and "실패" not in gh:
        st.session_state["capa_settings_note"] = gh


def _list_paths(stem: str | None = None) -> list[Path]:
    folder = master_dir()
    stems = (stem,) if stem else (*QA_STEMS, _LEGACY_TIME_STEM)
    files: list[Path] = []
    for s in stems:
        files.extend(folder.glob(f"{s}*.csv"))
        files.extend(folder.glob(f"{s}*.xlsx"))
        files.extend(folder.glob(f"{s}*.xls"))
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in files:
        if p.name.startswith("~$") or str(p) in seen:
            continue
        seen.add(str(p))
        uniq.append(p)
    return uniq


def _clear_files(stem: str | None = None) -> list[str]:
    deleted: list[str] = []
    for path in _list_paths(stem):
        try:
            path.unlink()
            deleted.append(path.name)
        except OSError:
            continue
    return deleted


def _save_upload(uploaded, prefix: str) -> tuple[Path, str]:
    """올린 파일을 data/master 에 저장하고 GitHub templates/ 에도 고정."""
    name = canonical_master_name(uploaded.name, prefix)
    _clear_files(prefix)
    if prefix == PRODUCT_STEM:
        _clear_files(_LEGACY_TIME_STEM)
    dest = master_dir() / name
    data = uploaded.getvalue()
    dest.write_bytes(data)
    gh = _push_github(name, data)
    return dest, gh


def _sync_master_from_github(*, force: bool = False) -> list[str]:
    if not github_store_enabled():
        return ["GitHub Secrets가 없어 로컬 업로드 파일만 사용합니다."]
    if not force and st.session_state.get("capa_gh_ok"):
        return list(st.session_state.get("capa_gh_notes") or [])
    notes: list[str] = []
    folder = master_dir()
    if force:
        cleared = _clear_files()
        if cleared:
            notes.append("로컬 CAPA 파일 초기화: " + ", ".join(cleared))
    for stem in QA_STEMS:
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
            _clear_files(stem)
            dest.write_bytes(found_raw)
            notes.append(f"GitHub에서 가져옴: {found_rel}")
        else:
            notes.append(f"{stem}: 저장소에 없음 (templates/{stem}.csv 또는 .xlsx)")
    note_set = _sync_settings_from_github(force=force)
    if note_set:
        notes.append(note_set)
    st.session_state["capa_gh_ok"] = True
    st.session_state["capa_gh_notes"] = notes
    return notes


def _product_path() -> Path | None:
    folder = master_dir()
    return newest_matching(folder, PRODUCT_STEM) or newest_matching(folder, _LEGACY_TIME_STEM)


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
    for label, stem in (("월별 생산계획", QA_PLAN_STEM), ("제품_기준정보", PRODUCT_STEM)):
        path = newest_matching(folder, stem)
        if path is None and stem == PRODUCT_STEM:
            path = newest_matching(folder, _LEGACY_TIME_STEM)
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
    time_path = _product_path()
    plan = pd.DataFrame()
    times = pd.DataFrame()
    if plan_path:
        plan = read_csv_table(plan_path)
        notes.append(f"월별 생산계획: {plan_path.name} ({len(plan)}행)")
    if time_path:
        times = read_csv_table(time_path)
        shared = " · 설비 시뮬레이션과 공유" if time_path.name.startswith(PRODUCT_STEM) else " · 예전 CAPA 파일"
        notes.append(f"제품_기준정보: {time_path.name} ({len(times)}행){shared}")
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
    st.warning(
        "올려 둔 월별 생산계획을 삭제합니다. "
        "제품_기준정보는 설비 운영 시뮬레이션과 같은 파일이라, 여기서 지우면 시뮬레이션에도 없어집니다."
    )
    st.caption("삭제 대상: " + ", ".join(p.name for p in files))
    yes, no = st.columns(2)
    with yes:
        if st.button("삭제", type="primary", use_container_width=True, key="capa_reset_yes"):
            deleted = _clear_files()
            st.session_state[flag] = False
            st.session_state["capa_gh_ok"] = False
            st.session_state.pop("capa_gh_notes", None)
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
        "가동 조건·업로드 파일은 로컬에 고정 저장되고, GitHub Secrets가 있으면 Cloud 재시작 후에도 유지됩니다. "
        "제품_기준정보는 설비 운영 시뮬레이션과 같은 파일입니다. 홀은 CEL만 봅니다."
    )

    force_gh = bool(st.session_state.pop("capa_gh_force_refresh", False))
    if force_gh:
        _sync_master_from_github(force=True)
        st.session_state["capa_flash"] = "GitHub에서 CAPA 데이터 다시 가져오기 완료"
    else:
        _sync_master_from_github()

    flash = st.session_state.pop("capa_flash", None)
    if flash:
        st.success(flash)

    dim_default, hole_default, eq_name = _owned_from_equipment()
    saved = _load_settings_local()
    if not saved:
        saved = _default_settings(dim=dim_default, hole=hole_default)
    else:
        # 보유대수가 설정에 없고 설비 기준이 있으면 그 값으로 시작
        if "capa_owned_dim" not in saved and dim_default:
            saved["capa_owned_dim"] = dim_default
        if "capa_owned_hole" not in saved and hole_default:
            saved["capa_owned_hole"] = hole_default
    _apply_settings_to_session(saved)
    if "capa_settings_saved" not in st.session_state:
        st.session_state["capa_settings_saved"] = dict(_current_settings_from_session())

    with st.sidebar:
        st.header("계정")
        render_logout_controls()
        st.divider()
        st.header("가동 조건")
        st.caption("값을 바꾸면 자동으로 저장됩니다. Cloud에서는 GitHub에도 반영됩니다.")
        work_days = float(
            st.number_input(
                "월 작업일수",
                min_value=1.0,
                max_value=31.0,
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
                step=0.5,
                help="설비 이론능력은 24시간(1440분)입니다.",
                key="capa_day_hours",
            )
        )
        util_pct = float(
            st.number_input(
                "가동률 (%)",
                min_value=1.0,
                max_value=100.0,
                step=1.0,
                help="셋업·비가동·인력 제약을 반영. 상단 「가동률 기준 필요대수」와 1대 월 가용에 그대로 적용됩니다.",
                key="capa_util",
            )
        )
        owned_dim = int(
            st.number_input(
                "치수 보유대수",
                min_value=0,
                max_value=999,
                step=1,
                help="가동율 분모. 저장해 두면 다음에도 같은 값으로 시작합니다.",
                key="capa_owned_dim",
            )
        )
        owned_hole = int(
            st.number_input(
                "홀 보유대수",
                min_value=0,
                max_value=999,
                step=1,
                help="가동율 분모. 저장해 두면 다음에도 같은 값으로 시작합니다.",
                key="capa_owned_hole",
            )
        )
        _persist_settings_if_changed()
        avail = work_days * day_hours * 60.0 * (util_pct / 100.0)
        st.caption(
            f"1대 월 가용 = {work_days:g}일 × {day_hours:g}시간 × 60 × {util_pct:g}% "
            f"= **{avail:,.0f}분**. 참고: 24시간 = {DAY_MINUTES}분/일."
        )
        if eq_name:
            st.caption(f"설비_기준정보 참고: `{eq_name}` 치수 {dim_default}대 · 홀 {hole_default}대")
        note = st.session_state.pop("capa_settings_note", None)
        if note:
            st.caption(note)
        if github_store_enabled():
            if st.button("GitHub에서 다시 가져오기", use_container_width=True, key="capa_gh_refresh"):
                st.session_state["capa_gh_force_refresh"] = True
                st.session_state["capa_gh_ok"] = False
                for k in SETTINGS_KEYS:
                    st.session_state.pop(k, None)
                st.session_state.pop("capa_settings_saved", None)
                st.rerun()
        else:
            st.caption("GitHub Secrets가 없으면 이 서버의 로컬 파일만 유지됩니다.")

        st.divider()
        st.header("파일 업로드")
        st.caption(
            "올린 파일은 저장되어 다음에도 그대로 사용합니다. "
            "제품_기준정보는 설비 운영 시뮬레이션과 공유됩니다. "
            "치수·Hole 행의 매당_설비분이 1매 측정시간입니다."
        )
        st.dataframe(pd.DataFrame(_active_files()), use_container_width=True, hide_index=True)
        _render_reset_ui()

        plan_up = st.file_uploader("① 월별 생산계획", type=["csv", "xlsx"], key="capa_up_plan")
        time_up = st.file_uploader("② 제품_기준정보", type=["csv", "xlsx"], key="capa_up_time")
        plan_sig = (plan_up.name, int(getattr(plan_up, "size", 0) or 0)) if plan_up else None
        time_sig = (time_up.name, int(getattr(time_up, "size", 0) or 0)) if time_up else None
        if plan_up is not None and plan_sig != st.session_state.get("capa_plan_sig"):
            path, gh = _save_upload(plan_up, QA_PLAN_STEM)
            st.session_state["capa_plan_sig"] = plan_sig
            st.session_state["capa_use_sample"] = False
            st.session_state["capa_gh_ok"] = True
            st.session_state["capa_flash"] = f"생산계획 저장: {path.name}" + (f" · {gh}" if gh else "")
            st.rerun()
        if time_up is not None and time_sig != st.session_state.get("capa_time_sig"):
            path, gh = _save_upload(time_up, PRODUCT_STEM)
            st.session_state["capa_time_sig"] = time_sig
            st.session_state["capa_use_sample"] = False
            st.session_state["capa_gh_ok"] = True
            st.session_state["capa_flash"] = (
                f"제품_기준정보 저장: {path.name} (설비 시뮬레이션과 공유)"
                + (f" · {gh}" if gh else "")
            )
            st.rerun()

        st.subheader("양식 받기")
        st.caption("제품_기준정보 양식은 설비 운영 시뮬레이션과 동일합니다.")
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
        utilization_pct=util_pct,
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
    peak_dim = int(result["peak_dim_required"])
    peak_hole = int(result["peak_hole_required"])
    short_dim = max(peak_dim - owned_dim, 0)
    short_hole = max(peak_hole - owned_hole, 0)

    st.subheader(f"가동률 {util_pct:g}% 기준 필요대수")
    st.caption(
        f"사이드바 **가동 조건 → 가동률**({util_pct:g}%)을 반영한 값입니다. "
        f"1대 월 가용 = {work_days:g}일 × {day_hours:g}시간 × 60 × {util_pct:g}% = **{avail_min:,.0f}분**. "
        "필요대수 = ceil(월 측정시간 합 ÷ 1대 월 가용). 인력 제약이 있으면 가동률을 낮춰 보세요."
    )
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.metric("치수 피크 필요", f"{peak_dim}대", help=f"피크월 {result['peak_dim_label']}")
    with k2:
        st.metric("치수 부족", f"{short_dim}대", help=f"피크 필요 {peak_dim} − 보유 {owned_dim}")
    with k3:
        st.metric("홀 피크 필요", f"{peak_hole}대", help=f"피크월 {result['peak_hole_label']}")
    with k4:
        st.metric("홀 부족", f"{short_hole}대", help=f"피크 필요 {peak_hole} − 보유 {owned_hole}")

    st.markdown("##### 월별 치수 필요대수")
    st.caption(
        f"치수 = 측정시간이 있는 전 제품. 피크 {result['peak_dim_label']} · {peak_dim}대 "
        f"(보유 {owned_dim}대 → 부족 {short_dim}대)."
    )
    _count_chart(
        monthly,
        "치수_필요대수",
        f"가동률 {util_pct:g}% 기준 · 월별 치수 필요대수",
        "#60a5fa",
    )

    st.markdown("##### 월별 홀 필요대수")
    st.caption(
        f"홀 = CEL만. 피크 {result['peak_hole_label']} · {peak_hole}대 "
        f"(보유 {owned_hole}대 → 부족 {short_hole}대)."
    )
    _count_chart(
        monthly,
        "홀_필요대수",
        f"가동률 {util_pct:g}% 기준 · 월별 홀 필요대수",
        "#fbbf24",
    )

    st.divider()
    st.subheader("월별 가동율")
    st.caption(
        f"가동율 = 필요시간 ÷ (보유대수 × {avail_min:,.0f}분) × 100. "
        f"분모의 1대 가용에도 가동률 {util_pct:g}%가 들어가 있습니다. "
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
- 1대 월 가용 = {work_days:g} × {day_hours:g} × 60 × {util_pct:g}% = **{avail_min:,.0f}분**
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
