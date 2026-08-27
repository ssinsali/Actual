"""실적 분석 통계 — 페이지 공통 (경로·로드·데이터 사이드바)."""
from __future__ import annotations

import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import pandas as pd
import streamlit as st

from stats_engine import (
    AREAS,
    CAMPUSES,
    SHIFTS,
    add_calendar_parts,
    empty_template_csv_bytes,
    filter_period,
    load_many,
    template_csv_bytes,
    template_dataframe,
)

_DATA_DIR = _APP_DIR / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

TEAM_STACK_ORDER = ("A조", "B조", "C조")


def render_slicer(
    label: str,
    options: list[str],
    *,
    key: str,
    default_on: bool = True,
) -> list[str]:
    """피벗 슬라이서형 필터 — 항목을 모두 보여 주고 ON/OFF로 선택."""
    st.markdown(f"**{label}**")
    if not options:
        st.caption("선택 가능한 항목이 없습니다.")
        return []

    keys = [f"{key}__{i}" for i, _ in enumerate(options)]
    # 최초 기본값
    for ck in keys:
        if ck not in st.session_state:
            st.session_state[ck] = default_on

    a1, a2 = st.columns(2)
    with a1:
        if st.button("전체", key=f"{key}_btn_all", use_container_width=True):
            for ck in keys:
                st.session_state[ck] = True
            st.rerun()
    with a2:
        if st.button("해제", key=f"{key}_btn_none", use_container_width=True):
            for ck in keys:
                st.session_state[ck] = False
            st.rerun()

    ncols = min(len(options), 4)
    cols = st.columns(ncols)
    selected: list[str] = []
    for i, opt in enumerate(options):
        with cols[i % ncols]:
            if st.checkbox(str(opt), key=keys[i]):
                selected.append(opt)
    return selected


def render_single_slicer(
    label: str,
    options: list[str],
    *,
    key: str,
    default: str | None = None,
) -> str:
    """피벗 슬라이서형 단일 선택 — 항목을 모두 보여 주고 하나만 선택."""
    st.markdown(f"**{label}**")
    if not options:
        st.caption("선택 가능한 항목이 없습니다.")
        return ""

    state_key = f"{key}_value"
    if state_key not in st.session_state or st.session_state[state_key] not in options:
        st.session_state[state_key] = default if default in options else options[0]

    ncols = min(len(options), 4)
    cols = st.columns(ncols)
    for i, opt in enumerate(options):
        with cols[i % ncols]:
            is_on = st.session_state[state_key] == opt
            if st.button(
                str(opt),
                key=f"{key}_pick_{i}",
                type="primary" if is_on else "secondary",
                use_container_width=True,
            ):
                st.session_state[state_key] = opt
                st.rerun()
    return str(st.session_state[state_key])


def app_dir() -> Path:
    return _APP_DIR


def data_dir() -> Path:
    return _DATA_DIR


def default_files() -> list[Path]:
    files = (
        sorted(_DATA_DIR.glob("*.xlsx"))
        + sorted(_DATA_DIR.glob("*.xls"))
        + sorted(_DATA_DIR.glob("*.csv"))
    )
    return [p for p in files if not p.name.startswith("~$")]


def save_upload(uploaded) -> Path:
    dest = _DATA_DIR / uploaded.name
    dest.write_bytes(uploaded.getvalue())
    return dest


@st.cache_data(show_spinner=False)
def load_cached(path_mtimes: tuple[tuple[str, float], ...]) -> tuple[pd.DataFrame, list[str]]:
    paths = [Path(p) for p, _ in path_mtimes]
    return load_many(paths)


def ensure_dims(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if "캠퍼스" not in out.columns:
        out["캠퍼스"] = "(미지정)"
    if "주야" not in out.columns:
        out["주야"] = "(미지정)"
    return out


def load_records() -> tuple[pd.DataFrame, list[str], list[Path]]:
    files = default_files()
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
        records, notes = load_cached(mtimes)
        if not records.empty:
            records = add_calendar_parts(ensure_dims(records))
    return records, notes, chosen


def render_data_sidebar(*, key_prefix: str = "") -> None:
    """사이드바 하단: 양식·업로드·파일선택."""
    st.divider()
    st.header("데이터")
    st.markdown(
        f"기본 폴더: `{_DATA_DIR}`  \n"
        "표준 CSV 양식을 받거나, 엑셀/CSV를 업로드하세요."
    )
    st.download_button(
        "기본 CSV 양식 다운로드 (예시 포함)",
        data=template_csv_bytes(),
        file_name="실적통계_기본양식.csv",
        mime="text/csv",
        use_container_width=True,
        key=f"{key_prefix}dl_tpl_example",
    )
    st.download_button(
        "빈 CSV 양식 다운로드",
        data=empty_template_csv_bytes(),
        file_name="실적통계_빈양식.csv",
        mime="text/csv",
        use_container_width=True,
        key=f"{key_prefix}dl_tpl_empty",
    )
    with st.expander("양식 컬럼 안내"):
        st.dataframe(template_dataframe(), use_container_width=True)
        st.caption(
            "A 일자, B 조, C~J 영역별 인력/실적, K 캠퍼스(천안/아산), L 주야(주/야)"
        )

    uploads = st.file_uploader(
        "엑셀/CSV 추가 업로드",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
        key=f"{key_prefix}uploader",
    )
    # file_uploader는 파일이 남아 있으면 매 실행마다 True → rerun 루프 방지
    upload_sig = tuple((u.name, int(getattr(u, "size", 0) or 0)) for u in (uploads or []))
    last_key = f"{key_prefix}last_upload_sig"
    if uploads and upload_sig and upload_sig != st.session_state.get(last_key):
        names: list[str] = []
        for up in uploads:
            save_upload(up)
            names.append(up.name)
            st.success(f"저장: {up.name}")
        st.session_state[last_key] = upload_sig
        # 방금 올린 파일을 분석 대상에 포함
        cur = list(st.session_state.get("selected_files") or [])
        for n in names:
            if n not in cur:
                cur.append(n)
        st.session_state.selected_files = cur
        st.cache_data.clear()
        st.rerun()

    files = default_files()
    if not files:
        st.warning("data 폴더에 파일이 없습니다.")
        render_exit_ui(key_prefix=key_prefix)
        st.stop()

    file_names = [p.name for p in files]
    if "selected_files" not in st.session_state:
        st.session_state.selected_files = file_names
    # 사라진 파일 정리, 새 파일은 유지된 선택에 맞춤
    st.session_state.selected_files = [n for n in st.session_state.selected_files if n in file_names]
    if not st.session_state.selected_files:
        st.session_state.selected_files = file_names

    selected = st.multiselect(
        "분석할 파일",
        options=file_names,
        default=st.session_state.selected_files,
        key=f"{key_prefix}file_select",
    )
    # widget 값과 session 동기화 (불필요한 연속 rerun 방지)
    if selected != st.session_state.selected_files:
        st.session_state.selected_files = selected
    if not selected:
        render_exit_ui(key_prefix=key_prefix)
        st.stop()

    if st.button("데이터 새로고침", use_container_width=True, key=f"{key_prefix}refresh"):
        st.cache_data.clear()
        st.rerun()

    render_exit_ui(key_prefix=key_prefix)


def shutdown_app() -> None:
    """Streamlit 서버 프로세스 종료 (로컬 실행용)."""
    import os

    os._exit(0)


def render_exit_ui(*, key_prefix: str = "") -> None:
    """사이드바 프로그램 종료 버튼 (확인 후 종료)."""
    st.divider()
    st.header("프로그램")
    flag = f"{key_prefix}confirm_shutdown"
    if flag not in st.session_state:
        st.session_state[flag] = False

    if not st.session_state[flag]:
        if st.button(
            "프로그램 종료",
            use_container_width=True,
            type="primary",
            key=f"{key_prefix}btn_exit",
        ):
            st.session_state[flag] = True
            st.rerun()
    else:
        st.warning("프로그램을 종료할까요?")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("예", key=f"{key_prefix}shutdown_yes", use_container_width=True):
                shutdown_app()
        with c2:
            if st.button("아니오", key=f"{key_prefix}shutdown_no", use_container_width=True):
                st.session_state[flag] = False
                st.rerun()
        st.caption("브라우저 탭은 수동으로 닫아 주세요.")


def apply_basic_filters(
    records: pd.DataFrame,
    *,
    area_sel: list[str] | None = None,
    campus_sel: list[str] | None = None,
    shift_sel: list[str] | None = None,
    team_sel: list[str] | None = None,
    mode: str = "전체",
    year: int | None = None,
    quarter: int | None = None,
    month: int | None = None,
    day=None,
    start=None,
    end=None,
) -> pd.DataFrame:
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
    filtered = ensure_dims(filtered)
    if campus_sel:
        filtered = filtered[filtered["캠퍼스"].isin(campus_sel)]
    if shift_sel:
        filtered = filtered[filtered["주야"].isin(shift_sel)]
    if area_sel:
        filtered = filtered[filtered["영역"].isin(area_sel)]
    if team_sel:
        filtered = filtered[filtered["조"].isin(team_sel)]
    return filtered


def team_stack_order(teams: list[str]) -> list[str]:
    """누적 막대: 아래 A조 → B조 → 위 C조. 나머지는 뒤에."""
    prefer = [t for t in TEAM_STACK_ORDER if t in teams]
    rest = sorted(t for t in teams if t not in prefer)
    return prefer + rest


def timeseries_campus_team(df: pd.DataFrame, grain: str) -> pd.DataFrame:
    """캠퍼스×조 시계열 실적 합계. grain: 일|월|분기|년."""
    if df.empty:
        return pd.DataFrame(columns=["기간", "캠퍼스", "조", "실적", "인력", "인당실적"])
    work = add_calendar_parts(ensure_dims(df))
    if grain == "일":
        work["기간"] = work["일자"].dt.strftime("%Y-%m-%d")
        sort_key = "일자"
    elif grain == "월":
        work["기간"] = work["년월"]
        sort_key = "년월"
    elif grain == "분기":
        work["기간"] = work["년분기"]
        sort_key = "년분기"
    else:
        work["기간"] = work["년"].astype(str)
        sort_key = "년"

    g = work.groupby(["기간", "캠퍼스", "조"], as_index=False).agg(
        실적=("실적", "sum"),
        인력=("인력", "sum"),
        _sort=(sort_key, "min"),
    )
    g["인당실적"] = g.apply(lambda r: r["실적"] / r["인력"] if r["인력"] else None, axis=1)
    g = g.sort_values(["캠퍼스", "_sort", "조"]).drop(columns="_sort")
    return g.reset_index(drop=True)
