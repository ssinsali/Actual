"""관리자 — 아이디별 메뉴 표시."""
from __future__ import annotations

import streamlit as st

from auth import list_accounts, render_logout_controls, update_user_pages
from page_access import CONTENT_PAGES, PRESETS, effective_page_ids


def _perm_key(username: str, page_id: str) -> str:
    return f"perm_{username}_{page_id}"


def _ensure_checks(username: str, selected: set[str]) -> None:
    for page in CONTENT_PAGES:
        key = _perm_key(username, page["id"])
        if key not in st.session_state:
            st.session_state[key] = page["id"] in selected


def _apply_preset(username: str, page_ids: tuple[str, ...]) -> None:
    wanted = set(page_ids)
    for page in CONTENT_PAGES:
        st.session_state[_perm_key(username, page["id"])] = page["id"] in wanted


def _clear_perm_widgets() -> None:
    for key in list(st.session_state.keys()):
        if str(key).startswith("perm_"):
            st.session_state.pop(key, None)


def render() -> None:
    with st.sidebar:
        st.header("계정")
        render_logout_controls()

    st.title("메뉴 권한")
    st.caption(
        "아이디마다 사이드바에 나올 메뉴를 고릅니다. "
        "관리자는 항상 모든 메뉴를 봅니다. "
        "새로 가입한 계정은 캠퍼스·종합·월평균만 열려 있고, "
        "드릴·CAPA·시뮬레이션은 여기서 켜야 보입니다."
    )
    if st.button("계정 다시 불러오기"):
        _clear_perm_widgets()
        st.session_state.pop("users_db_cache_at", None)
        st.rerun()

    accounts = list_accounts()
    if not accounts:
        st.info("등록된 계정이 없습니다.")
        return

    ordered = sorted(
        accounts.items(),
        key=lambda item: (item[1].get("role") != "admin", item[0]),
    )
    for username, user in ordered:
        if not isinstance(user, dict):
            continue
        role = user.get("role") or "user"
        name = user.get("display_name") or username
        role_label = "관리자" if role == "admin" else "일반"
        saved = effective_page_ids(user) if role != "admin" else [p["id"] for p in CONTENT_PAGES]
        saved_titles = [p["title"] for p in CONTENT_PAGES if p["id"] in set(saved)]
        with st.expander(f"{name}  ·  {username}  ·  {role_label}", expanded=role != "admin"):
            if role == "admin":
                st.caption("관리자는 모든 메뉴를 봅니다. 이 계정은 제한하지 않습니다.")
                continue

            explicit = isinstance(user.get("pages"), list)
            if not explicit:
                st.caption(
                    "아직 권한을 저장하지 않았습니다. "
                    "지금은 캠퍼스·종합·월평균만 보입니다. "
                    "저장하면 체크한 메뉴만 남습니다."
                )
            elif saved_titles:
                st.caption("저장됨: " + ", ".join(saved_titles))
            else:
                st.caption("저장됨: 보이는 메뉴 없음")

            _ensure_checks(username, set(saved))
            preset_cols = st.columns(3)
            for i, (label, ids) in enumerate(PRESETS):
                with preset_cols[i % 3]:
                    st.button(
                        label,
                        key=f"preset_{username}_{label}",
                        use_container_width=True,
                        on_click=_apply_preset,
                        args=(username, ids),
                    )

            chosen: list[str] = []
            section = ""
            for page in CONTENT_PAGES:
                if page["section"] != section:
                    section = page["section"]
                    st.markdown(f"**{section}**")
                if st.checkbox(page["title"], key=_perm_key(username, page["id"])):
                    chosen.append(page["id"])
            st.caption("체크를 모두 끄면 이 아이디는 로그인 후 메뉴가 없습니다.")
            if st.button("저장", key=f"save_{username}", type="primary"):
                ok, msg = update_user_pages(username, chosen)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)
