"""공통 Altair 차트."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from stats_engine import AREAS, SHIFTS


def bar_chart(df: pd.DataFrame, x: str, y: str, color: str | None = None, title: str = "") -> None:
    if df.empty:
        st.caption("표시할 데이터가 없습니다.")
        return
    enc = {
        "x": alt.X(f"{x}:N", sort=None, title=x),
        "y": alt.Y(f"{y}:Q", title=y),
        "tooltip": list(df.columns),
    }
    if color and color in df.columns:
        if color == "주야":
            enc["color"] = alt.Color(
                f"{color}:N",
                title=color,
                sort=list(SHIFTS),
                scale=alt.Scale(domain=list(SHIFTS)),
            )
            enc["xOffset"] = alt.XOffset(f"{color}:N", sort=list(SHIFTS))
        else:
            enc["color"] = alt.Color(f"{color}:N", title=color)
            enc["xOffset"] = f"{color}:N"
    chart = alt.Chart(df).mark_bar().encode(**enc).properties(height=320, title=title or None)
    st.altair_chart(chart, use_container_width=True)


def grouped_by_area_chart(
    df: pd.DataFrame,
    y: str,
    title: str,
    *,
    color: str = "조",
) -> None:
    if df.empty or y not in df.columns or color not in df.columns:
        st.caption("표시할 데이터가 없습니다.")
        return
    color_sort = list(SHIFTS) if color == "주야" else None
    if color == "주야":
        x_off: alt.XOffset | str = alt.XOffset(f"{color}:N", sort=list(SHIFTS))
    else:
        x_off = f"{color}:N"
    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("영역:N", sort=list(AREAS), title="공정"),
            y=alt.Y(f"{y}:Q", title=y),
            color=alt.Color(
                f"{color}:N",
                title=color,
                sort=color_sort,
                scale=alt.Scale(domain=color_sort) if color_sort else alt.Undefined,
            ),
            xOffset=x_off,
            tooltip=[color, "영역", y],
        )
        .properties(height=340, title=title)
    )
    st.altair_chart(chart, use_container_width=True)
