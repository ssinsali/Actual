"""홀 틀어짐 분석 — 로컬 폴더 일괄 분석 UI."""
from __future__ import annotations

import os
from pathlib import Path

import altair as alt
import cv2
import numpy as np
import pandas as pd
import streamlit as st

from auth import render_logout_controls
from hole_offset_engine import (
    DEFAULT_OCCLUSION_PCT,
    DIRECTION_LABELS_8,
    analyze_folder,
    analyze_image_path,
    draw_overlay,
    list_image_files,
    summarize_results,
    top_rows,
)


def _is_cloud_runtime() -> bool:
    """Streamlit Cloud 등 원격 런타임 추정 — 로컬 디스크 경로 분석 불가."""
    if os.environ.get("STREAMLIT_CLOUD"):
        return True
    if Path("/mount/src").exists():
        return True
    home = Path.home().as_posix().lower()
    if "appuser" in home or home.startswith("/home/adminuser"):
        return True
    return False


def _fmt(v: float, digits: int = 3) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "-"
    if not np.isfinite(x):
        return "-"
    return f"{x:.{digits}f}"


def _stats_table(block: dict, unit: str = "") -> pd.DataFrame:
    rows = [
        ("평균", block.get("mean")),
        ("중앙값", block.get("median")),
        ("표준편차", block.get("std")),
        ("최소", block.get("min")),
        ("최대", block.get("max")),
        ("P90", block.get("p90")),
        ("P95", block.get("p95")),
        ("P99", block.get("p99")),
    ]
    suffix = f" ({unit})" if unit else ""
    return pd.DataFrame(
        {"지표": [r[0] + suffix for r in rows], "값": [_fmt(r[1], 4) for r in rows]}
    )


def render() -> None:
    with st.sidebar:
        st.header("계정")
        render_logout_controls()
        st.divider()
        st.caption(
            "대량 이미지는 **로컬 PC**에서 폴더 경로로 분석하세요. "
            "Streamlit Cloud에서는 사용자 PC 폴더에 접근할 수 없습니다."
        )

    st.title("홀 틀어짐 분석")
    st.caption(
        "0.75(겉) · 0.45(안) 2단 관통 홀 — 편심 거리·가림률·방향(8방위)을 일괄 집계합니다. "
        "제품 1매 폴더(100~5,000장)를 지정해 분석합니다."
    )

    if _is_cloud_runtime():
        st.warning(
            "현재 **Cloud 환경**으로 보입니다. 로컬 경로 분석은 사용할 수 없습니다. "
            "PC에서 `python 실적분석통계.py` 로 실행한 뒤 폴더 경로를 입력하세요."
        )
        st.stop()

    with st.expander("분석 기준", expanded=False):
        st.markdown(
            """
- **겉 홀**: 외곽 흰 링의 안쪽 경계 (Ø0.75)
- **안 홀**: 가운데 밝은 원 (Ø0.45)
- **틀어짐**: 두 중심 거리 (px / mm, 큰홀 직경으로 환산)
- **방향**: 겉 홀 중심 → 안 홀 중심, 화면 위=북 기준 8방위
- **가림률**: 안 홀 원 면적 중 겉 홀 원 **밖**에 있는 비율(%)
- **합격(홀)**: 가림률 ≤ 임계값 **그리고** 여유간격(clearance) > 0
            """
        )

    c1, c2, c3 = st.columns([3, 1, 1])
    with c1:
        folder = st.text_input(
            "이미지 폴더 경로",
            value=st.session_state.get("hole_offset_folder", ""),
            placeholder=r"예: D:\검사\제품A\홀이미지",
            key="hole_offset_folder_input",
        )
    with c2:
        occ_limit = st.number_input(
            "가림 판정 임계(%)",
            min_value=0.0,
            max_value=50.0,
            value=float(st.session_state.get("hole_offset_occ_limit", DEFAULT_OCCLUSION_PCT)),
            step=0.5,
            help="이 값을 넘으면 가려진 홀(불합격)로 집계",
        )
    with c3:
        recursive = st.checkbox("하위 폴더 포함", value=True)

    path = Path(folder.strip()) if folder.strip() else None
    n_files = 0
    if path is not None and path.is_dir():
        n_files = len(list_image_files(path, recursive=recursive))
        st.info(f"이미지 {n_files:,}장 발견 — `{path}`")
    elif folder.strip():
        st.error("폴더를 찾을 수 없습니다. 로컬 경로를 확인하세요.")

    run = st.button("분석 시작", type="primary", disabled=not (path and path.is_dir() and n_files > 0))

    if run and path is not None:
        st.session_state["hole_offset_folder"] = str(path)
        st.session_state["hole_offset_occ_limit"] = float(occ_limit)
        prog = st.progress(0.0, text="분석 준비 중…")
        status = st.empty()

        def _cb(done: int, total: int, cur: str) -> None:
            prog.progress(done / max(total, 1), text=f"{done:,} / {total:,}")
            status.caption(Path(cur).name)

        with st.spinner("홀 검출·집계 중…"):
            df = analyze_folder(
                path,
                occlusion_limit_pct=float(occ_limit),
                recursive=recursive,
                max_workers=1,
                progress_cb=_cb,
            )
        prog.progress(1.0, text="완료")
        status.empty()
        summary = summarize_results(df, occlusion_limit_pct=float(occ_limit))
        st.session_state["hole_offset_df"] = df
        st.session_state["hole_offset_summary"] = summary
        st.session_state["hole_offset_root"] = str(path)

    df: pd.DataFrame | None = st.session_state.get("hole_offset_df")
    summary: dict | None = st.session_state.get("hole_offset_summary")
    if df is None or summary is None:
        st.info("폴더를 지정한 뒤 **분석 시작**을 누르세요.")
        return

    # —— KPI ——
    st.subheader("제품 요약")
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("전체 홀", f"{summary['total']:,}")
    k2.metric("가려진 홀", f"{summary['occluded_count']:,}", f"{summary['occluded_ratio_pct']:.1f}%")
    occ = summary.get("occlusion") or {}
    k3.metric("평균 가림률", f"{_fmt(occ.get('mean'), 2)}%")
    off = summary.get("offset_mm") or {}
    k4.metric("평균 틀어짐", f"{_fmt(off.get('mean'), 4)} mm")
    verdict = "합격" if summary.get("product_pass") else "불합격"
    k5.metric("제품 판정", verdict)

    st.caption(
        f"검출 성공 {summary['detected']:,} · 검출 실패 {summary['failed_detect']:,} · "
        f"홀 합격 {summary['pass_count']:,} / 불합격 {summary['fail_count']:,} · "
        f"가림 임계 {summary['occlusion_limit_pct']}% · "
        f"주 방향 **{summary.get('direction_dominant') or '-'}**"
    )

    # —— 통계 블록 ——
    t1, t2, t3 = st.tabs(["가림·틀어짐 통계", "방향 분포", "상세·다운로드"])

    with t1:
        c_a, c_b = st.columns(2)
        with c_a:
            st.markdown("**가림률 (%)**")
            st.dataframe(_stats_table(summary.get("occlusion") or {}, "%"), hide_index=True, use_container_width=True)
            st.markdown("**틀어짐 거리 (mm)**")
            st.dataframe(_stats_table(summary.get("offset_mm") or {}, "mm"), hide_index=True, use_container_width=True)
        with c_b:
            st.markdown("**틀어짐 거리 (px)**")
            st.dataframe(_stats_table(summary.get("offset_px") or {}, "px"), hide_index=True, use_container_width=True)
            st.markdown("**정규화 편심 (d / R_겉)**")
            st.dataframe(_stats_table(summary.get("offset_norm") or {}), hide_index=True, use_container_width=True)
            st.markdown("**여유간격 clearance (px)**")
            st.dataframe(_stats_table(summary.get("clearance_px") or {}, "px"), hide_index=True, use_container_width=True)
            st.caption(f"clearance ≤ 0 인 홀: {summary.get('negative_clearance_count', 0):,}개")

        valid = df[df["ok"] == True]  # noqa: E712
        if not valid.empty:
            hist_occ = (
                alt.Chart(valid)
                .mark_bar()
                .encode(
                    x=alt.X("occlusion_pct:Q", bin=alt.Bin(maxbins=30), title="가림률(%)"),
                    y=alt.Y("count()", title="홀 수"),
                    tooltip=["count()"],
                )
                .properties(height=220, title="가림률 분포")
            )
            hist_off = (
                alt.Chart(valid)
                .mark_bar()
                .encode(
                    x=alt.X("offset_mm:Q", bin=alt.Bin(maxbins=30), title="틀어짐(mm)"),
                    y=alt.Y("count()", title="홀 수"),
                    tooltip=["count()"],
                )
                .properties(height=220, title="틀어짐 분포")
            )
            st.altair_chart(hist_occ, use_container_width=True)
            st.altair_chart(hist_off, use_container_width=True)

    with t2:
        counts = summary.get("direction_counts") or {}
        dir_df = pd.DataFrame(
            {
                "방향": list(DIRECTION_LABELS_8),
                "홀수": [int(counts.get(d, 0)) for d in DIRECTION_LABELS_8],
            }
        )
        total_dir = max(int(dir_df["홀수"].sum()), 1)
        dir_df["비율(%)"] = (dir_df["홀수"] / total_dir * 100.0).round(1)
        chart = (
            alt.Chart(dir_df)
            .mark_bar()
            .encode(
                x=alt.X("방향:N", sort=list(DIRECTION_LABELS_8), title="방향(겉→안)"),
                y=alt.Y("홀수:Q", title="홀 수"),
                tooltip=["방향", "홀수", "비율(%)"],
                color=alt.value("#5dade2"),
            )
            .properties(height=280, title="안 홀 방향 분포 (화면 위=북)")
        )
        st.altair_chart(chart, use_container_width=True)
        st.dataframe(dir_df, hide_index=True, use_container_width=True)

    with t3:
        show_cols = [
            "file_name",
            "ok",
            "passed",
            "occluded",
            "occlusion_pct",
            "offset_mm",
            "offset_px",
            "direction",
            "angle_deg",
            "clearance_px",
            "large_r_px",
            "small_r_px",
            "error",
        ]
        view = df[[c for c in show_cols if c in df.columns]].copy()
        st.dataframe(view, hide_index=True, use_container_width=True, height=360)

        csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "홀별 상세 CSV 다운로드",
            data=csv_bytes,
            file_name="hole_offset_detail.csv",
            mime="text/csv",
        )

        st.markdown("**가림률 Top 10**")
        st.dataframe(top_rows(df, "occlusion_pct", 10)[show_cols[:8]], hide_index=True, use_container_width=True)
        st.markdown("**틀어짐 Top 10**")
        st.dataframe(top_rows(df, "offset_mm", 10)[show_cols[:8]], hide_index=True, use_container_width=True)

        fail_detect = df[df["ok"] == False]  # noqa: E712
        if not fail_detect.empty:
            st.markdown("**검출 실패 목록**")
            st.dataframe(fail_detect[["file_name", "file_path", "error"]], hide_index=True, use_container_width=True)

    # —— 미리보기 ——
    st.subheader("오버레이 미리보기")
    valid_files = df.loc[df["ok"] == True, "file_path"].tolist()  # noqa: E712
    if not valid_files:
        st.caption("검출 성공 이미지가 없습니다.")
        return

    pick = st.selectbox("이미지 선택", valid_files, format_func=lambda p: Path(p).name)
    if pick:
        row = df.loc[df["file_path"] == pick].iloc[0]
        from hole_offset_engine import HoleResult

        result = HoleResult(
            file_name=str(row["file_name"]),
            file_path=str(row["file_path"]),
            ok=bool(row["ok"]),
            error=str(row.get("error") or ""),
            large_cx=float(row["large_cx"]),
            large_cy=float(row["large_cy"]),
            large_r_px=float(row["large_r_px"]),
            small_cx=float(row["small_cx"]),
            small_cy=float(row["small_cy"]),
            small_r_px=float(row["small_r_px"]),
            offset_px=float(row["offset_px"]),
            offset_mm=float(row["offset_mm"]),
            offset_norm=float(row["offset_norm"]),
            clearance_px=float(row["clearance_px"]),
            angle_deg=float(row["angle_deg"]),
            direction=str(row["direction"]),
            occlusion_pct=float(row["occlusion_pct"]),
            occluded=bool(row["occluded"]),
            passed=bool(row["passed"]),
            px_per_mm=float(row["px_per_mm"]),
        )
        img = cv2.imread(pick, cv2.IMREAD_GRAYSCALE)
        if img is None:
            # 재분석
            result = analyze_image_path(pick, occlusion_limit_pct=float(summary["occlusion_limit_pct"]))
            img = cv2.imread(pick, cv2.IMREAD_GRAYSCALE)
        if img is not None:
            overlay = draw_overlay(img, result)
            rgb = cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB)
            st.image(rgb, caption=Path(pick).name, use_container_width=True)
            st.caption(
                f"방향 {result.direction} ({_fmt(result.angle_deg, 1)}°) · "
                f"틀어짐 {_fmt(result.offset_mm, 4)} mm · "
                f"가림 {_fmt(result.occlusion_pct, 2)}% · "
                f"{'합격' if result.passed else '불합격'}"
            )
