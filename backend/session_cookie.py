"""Persistent login: server validation and browser cookie synchronization."""

import secrets
from pathlib import Path
from typing import Optional

import streamlit as st

from backend.db.models import SessionLocal, Student

COOKIE_NAME = "sc_token"
COOKIE_MAX_AGE = 10 * 365 * 24 * 60 * 60


def get_or_create_token(student_id: int) -> Optional[str]:
    """Return the student's persistent token, creating it when needed."""
    with SessionLocal() as db:
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            return None
        if not student.session_token:
            student.session_token = secrets.token_urlsafe(32)
            db.commit()
            db.refresh(student)
        return student.session_token


def verify_token(token: str) -> Optional[Student]:
    if not isinstance(token, str) or not token:
        return None
    with SessionLocal() as db:
        return db.query(Student).filter(Student.session_token == token).first()


def invalidate_token(student_id: int) -> None:
    """Explicit logout revokes the credential even if cookie deletion fails."""
    if not student_id:
        return
    with SessionLocal() as db:
        student = db.query(Student).filter(Student.id == student_id).first()
        if student:
            student.session_token = None
            db.commit()


def _sync_cookie(value: str) -> None:
    """Write on the app origin and report whether the browser accepted it."""
    component = st.components.v2.component(
        "study_coach_session_cookie",
        js=Path(__file__).with_suffix(".js").read_text(encoding="utf-8"),
    )
    key = "_session_cookie_sync"
    previous = st.session_state.get(key, {})
    result = component(
        key=key,
        data={
            "name": COOKIE_NAME,
            "value": value,
            "maxAge": COOKIE_MAX_AGE if value else 0,
            "reported": previous.get("status"),
        },
        on_status_change=lambda: None,
        height="content",
    )
    if value and result.status == "blocked":
        st.warning("Il browser non salva il cookie di accesso. Consenti i cookie per questo sito per restare connesso dopo un aggiornamento.")


def render_set_cookie(token: str) -> None:
    """Call from the authenticated app shell, never immediately before rerun."""
    _sync_cookie(token)


def render_clear_cookie() -> None:
    """Call on the logged-out screen after invalidating the DB token."""
    _sync_cookie("")


def restore_login_from_cookie() -> bool:
    """A refresh opens a new WebSocket with the browser's saved cookie."""
    token = st.context.cookies.get(COOKIE_NAME, "")
    student = verify_token(token) if token else None
    if student is None:
        return False
    st.session_state.authenticated = True
    st.session_state.student_id = student.id
    st.session_state.username = student.username
    st.session_state.current_page = "upload"
    return True
