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
    period_daily_average,
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


def newest_data_names() -> list[str]:
    """수정 시각이 가장 늦은 실적 파일 하나."""
    files = default_files()
    if not files:
        return []
    newest = max(files, key=lambda p: (p.stat().st_mtime, p.name))
    return [newest.name]


def select_analysis_files(names: list[str]) -> None:
    """분석 대상을 이 파일들로만 맞춘다."""
    st.session_state.selected_files = list(names)
    for key in list(st.session_state.keys()):
        if "file_select" in str(key):
            st.session_state.pop(key, None)


_PROTECTED_DATA_NAMES = {"users.json", "README.txt"}


def _upload_nonce() -> int:
    return int(st.session_state.get("upload_widget_nonce") or 0)


def list_resettable_data_files() -> list[Path]:
    """로그인·안내 파일을 제외한 실적 엑셀/CSV."""
    return [p for p in default_files() if p.name not in _PROTECTED_DATA_NAMES]


def clear_performance_data() -> list[str]:
    """업로드된 실적 파일을 삭제한다. users.json 은 유지."""
    deleted: list[str] = []
    for path in list_resettable_data_files():
        try:
            path.unlink()
            deleted.append(path.name)
        except OSError:
            continue
    st.session_state.selected_files = []
    st.session_state["upload_widget_nonce"] = _upload_nonce() + 1
    for key in list(st.session_state.keys()):
        name = str(key)
        if name.endswith("last_upload_sig") or name.endswith("confirm_reset_data"):
            st.session_state.pop(key, None)
        elif "file_select" in name:
            st.session_state.pop(key, None)
    st.cache_data.clear()
    return deleted


def render_data_reset_ui(*, key_prefix: str = "") -> None:
    """잘못 올린 실적 파일을 확인 후 삭제."""
    files = list_resettable_data_files()
    flag = f"{key_prefix}confirm_reset_data"
    if flag not in st.session_state:
        st.session_state[flag] = False

    if not files:
        st.caption("초기화할 실적 파일이 없습니다. 위에서 다시 업로드하세요.")
        return

    if not st.session_state[flag]:
        if st.button(
            "실적 데이터 초기화",
            use_container_width=True,
            key=f"{key_prefix}btn_reset_data",
        ):
            st.session_state[flag] = True
            st.rerun()
        return

    st.warning("업로드한 엑셀/CSV를 모두 삭제합니다. 로그인 계정은 그대로입니다.")
    st.caption("삭제: " + ", ".join(path.name for path in files))
    yes, no = st.columns(2)
    with yes:
        if st.button("삭제", type="primary", use_container_width=True, key=f"{key_prefix}reset_yes"):
            clear_performance_data()
            st.session_state[flag] = False
            st.rerun()
    with no:
        if st.button("취소", use_container_width=True, key=f"{key_prefix}reset_no"):
            st.session_state[flag] = False
            st.rerun()


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
        st.session_state.selected_files = newest_data_names()
    path_map = {p.name: p for p in files}
    chosen_names = [n for n in st.session_state.selected_files if n in path_map]
    if not chosen_names and files:
        chosen_names = newest_data_names()
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
        "새로 올리면 **그 파일만** 분석합니다. 이전 파일은 목록에만 남습니다."
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
        key=f"{key_prefix}uploader_{_upload_nonce()}",
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
        select_analysis_files(names)
        st.cache_data.clear()
        st.rerun()

    files = default_files()
    if not files:
        st.warning("data 폴더에 파일이 없습니다.")
        render_data_reset_ui(key_prefix=key_prefix)
        render_exit_ui(key_prefix=key_prefix)
        st.stop()

    file_names = [p.name for p in files]
    if "selected_files" not in st.session_state:
        st.session_state.selected_files = newest_data_names()
    st.session_state.selected_files = [n for n in st.session_state.selected_files if n in file_names]
    if not st.session_state.selected_files:
        st.session_state.selected_files = newest_data_names() or file_names[:1]

    selected = st.multiselect(
        "분석할 파일 (기본: 마지막 업로드)",
        options=file_names,
        default=st.session_state.selected_files,
        key=f"{key_prefix}file_select",
    )
    # widget 값과 session 동기화 (불필요한 연속 rerun 방지)
    if selected != st.session_state.selected_files:
        st.session_state.selected_files = selected
    if not selected:
        render_data_reset_ui(key_prefix=key_prefix)
        render_exit_ui(key_prefix=key_prefix)
        st.stop()

    if st.button("데이터 새로고침", use_container_width=True, key=f"{key_prefix}refresh"):
        st.cache_data.clear()
        st.rerun()

    render_data_reset_ui(key_prefix=key_prefix)
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


def render_process_daily_avg(
    df: pd.DataFrame,
    *,
    period_col: str = "년월",
    extra_keys: list[str] | None = None,
    period_label: str = "월",
    split_campus: bool = False,
) -> pd.DataFrame:
    """기간×단위공정 일평균 실적 비교표·차트."""
    from ui_charts import bar_chart

    st.subheader(f"{period_label}별 · 단위공정 일평균 실적")
    st.caption(
        "일평균 실적 = 해당 기간·공정의 실적 합계 ÷ 작업일 수. "
        "월마다 근무일 수가 달라도 공정끼리, 월끼리 비교할 수 있습니다. "
        "전기대비%는 같은 공정의 직전 기간 일평균 대비입니다."
    )
    keys = list(extra_keys or [])
    if split_campus and "캠퍼스" not in keys:
        keys = ["캠퍼스", *keys]
    g = period_daily_average(df, period_col, extra_keys=keys or None)
    if g.empty:
        st.caption("표시할 데이터가 없습니다.")
        return g

    show_cols = [
        c
        for c in [
            period_col,
            *keys,
            "영역",
            "작업일수",
            "합계_실적",
            "일평균_실적",
            "전기대비%",
            "일평균_인력",
            "인당실적",
        ]
        if c in g.columns
    ]
    st.dataframe(g[show_cols].rename(columns={"영역": "공정"}), use_container_width=True)

    index_cols: list[str] = []
    for c in [*keys, period_col]:
        if c in g.columns and c not in index_cols:
            index_cols.append(c)
    piv = g.pivot_table(
        index=index_cols,
        columns="영역",
        values="일평균_실적",
        aggfunc="first",
    )
    piv = piv.reindex(columns=[a for a in AREAS if a in piv.columns])
    st.markdown("##### 일평균 실적 비교표 (행: 기간, 열: 공정)")
    st.dataframe(piv, use_container_width=True)

    if split_campus and "캠퍼스" in g.columns:
        campuses = [c for c in CAMPUSES if c in set(g["캠퍼스"])] + [
            c for c in sorted(g["캠퍼스"].unique()) if c not in CAMPUSES
        ]
        cols = st.columns(max(len(campuses), 1))
        for col, campus in zip(cols, campuses):
            with col:
                sub = g[g["캠퍼스"] == campus]
                bar_chart(
                    sub,
                    period_col,
                    "일평균_실적",
                    color="영역",
                    title=f"{campus} · {period_label}별 공정 일평균 실적",
                )
    else:
        bar_chart(
            g,
            period_col,
            "일평균_실적",
            color="영역",
            title=f"{period_label}별 · 공정 일평균 실적",
        )
    return g
