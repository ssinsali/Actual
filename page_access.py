"""로그인 아이디별 사이드바 메뉴.

계정 `pages` 값
- 없음: 실적 3개(캠퍼스·종합·월평균)만 보여 준다.
- 리스트: 그 아이디에 허용한 메뉴만 보여 준다.
- role 이 admin: 목록과 관계없이 모든 메뉴 + 메뉴 권한 화면.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from auth import (
    current_user,
    is_authenticated,
    list_accounts,
    render_auth_gate,
    render_logout_controls,
)

_APP_DIR = Path(__file__).resolve().parent

# id 는 users.json 과 URL 에 저장한다. 화면 이름은 title.
CONTENT_PAGES: tuple[dict[str, str], ...] = (
    {
        "id": "campus",
        "title": "캠퍼스·조별 실적",
        "icon": "📊",
        "section": "실적 분석",
        "path": "screens/campus.py",
    },
    {
        "id": "summary",
        "title": "종합 실적 분석",
        "icon": "📈",
        "section": "실적 분석",
        "path": "screens/summary.py",
    },
    {
        "id": "trend",
        "title": "월평균 추이",
        "icon": "📉",
        "section": "실적 분석",
        "path": "screens/trend.py",
    },
    {
        "id": "sim",
        "title": "설비 운영 시뮬레이션",
        "icon": "🏭",
        "section": "설비·CAPA",
        "path": "screens/sim.py",
    },
    {
        "id": "drill",
        "title": "드릴설비 필요 분석",
        "icon": "🔧",
        "section": "설비·CAPA",
        "path": "screens/drill.py",
    },
    {
        "id": "capa",
        "title": "QA그룹 CAPA 관리",
        "icon": "📐",
        "section": "설비·CAPA",
        "path": "screens/capa.py",
    },
)

DEFAULT_PAGE_IDS: tuple[str, ...] = ("campus", "summary", "trend")
CONTENT_PAGE_IDS: tuple[str, ...] = tuple(page["id"] for page in CONTENT_PAGES)

PRESETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("실적만", DEFAULT_PAGE_IDS),
    ("드릴만", ("drill",)),
    ("CAPA만", ("capa",)),
    ("시뮬레이션만", ("sim",)),
    ("전체", CONTENT_PAGE_IDS),
    ("없음", ()),
)


def effective_page_ids(user: dict) -> list[str]:
    """계정 레코드 기준으로 보이는 메뉴 id. 관리자 예외는 여기서 다루지 않는다."""
    raw = user.get("pages")
    if not isinstance(raw, list):
        return list(DEFAULT_PAGE_IDS)
    picked = {item for item in raw if isinstance(item, str)}
    return [page_id for page_id in CONTENT_PAGE_IDS if page_id in picked]


def can_edit_data() -> bool:
    """업로드·삭제·가동조건 저장. 조회만 하는 계정은 False."""
    username = current_user()
    if not username:
        return False
    user = list_accounts().get(username)
    if not isinstance(user, dict):
        return False
    if user.get("role") == "admin":
        return True
    return bool(user.get("data_edit"))


def render_view_only_note() -> None:
    if can_edit_data():
        return
    st.caption("조회만 가능합니다. 업로드·삭제·저장은 데이터 수정 권한이 있는 아이디만 할 수 있습니다.")


def allowed_page_ids() -> list[str]:
    """지금 로그인한 아이디가 볼 수 있는 메뉴."""
    username = current_user()
    if not username:
        return []
    user = list_accounts().get(username)
    if not isinstance(user, dict):
        return []
    if user.get("role") == "admin":
        return list(CONTENT_PAGE_IDS)
    return effective_page_ids(user)


def enforce_page(page_id: str) -> None:
    """주소로 직접 열어도, 권한이 없으면 화면을 그리지 않는다."""
    if page_id == "access":
        user = list_accounts().get(current_user() or "")
        if not isinstance(user, dict) or user.get("role") != "admin":
            st.error("메뉴 권한은 관리자만 바꿀 수 있습니다.")
            st.stop()
        return
    if page_id not in set(allowed_page_ids()):
        st.error("이 메뉴 권한이 없습니다. 관리자에게 요청하세요.")
        st.stop()


def _login_page() -> None:
    render_auth_gate()


def _no_menu_page() -> None:
    st.warning("부여된 메뉴가 없습니다. 관리자에게 메뉴 권한을 요청하세요.")
    render_logout_controls()


def navigation_pages():
    """st.navigation 에 넘길 페이지 목록. 로그인 전이면 로그인만 둔다."""
    if not is_authenticated():
        return [st.Page(_login_page, title="로그인", icon="🔐", default=True)]

    allowed = set(allowed_page_ids())
    sections: dict[str, list] = {}
    first = True
    for page in CONTENT_PAGES:
        if page["id"] not in allowed:
            continue
        sections.setdefault(page["section"], []).append(
            st.Page(
                str(_APP_DIR / page["path"]),
                title=page["title"],
                icon=page["icon"],
                url_path=page["id"],
                default=first,
            )
        )
        first = False

    user = list_accounts().get(current_user() or "")
    if isinstance(user, dict) and user.get("role") == "admin":
        sections.setdefault("관리", []).append(
            st.Page(
                str(_APP_DIR / "screens" / "access.py"),
                title="메뉴 권한",
                icon="🔐",
                url_path="access",
                default=first,
            )
        )
        first = False

    if not sections:
        return [st.Page(_no_menu_page, title="메뉴 없음", icon="🚫", default=True)]
    return sections
