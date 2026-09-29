"""
backend/session_cookie.py — Login persistente tramite cookie di sessione
"""

import secrets
from typing import Optional

import streamlit as st

from backend.db.models import SessionLocal, Student

COOKIE_NAME = "sc_token"
COOKIE_MAX_AGE = 10 * 365 * 24 * 60 * 60  # ~10 anni: emula "nessuna scadenza"


# ---------------------------------------------------------------------------
# Gestione token lato DB
# ---------------------------------------------------------------------------
""" return il token persistente dello studente generandolo se assente"""
def get_or_create_token(student_id: int) -> Optional[str]:

    db = SessionLocal()
    try:
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            return None
        if not student.session_token:
            student.session_token = secrets.token_urlsafe(32)
            db.commit()
            db.refresh(student)
        return student.session_token
    finally:
        db.close()

"""Return lo Student associato al token, se valido."""
def verify_token(token: str) -> Optional[Student]:

    if not token:
        return None
    db = SessionLocal()
    try:
        return db.query(Student).filter(Student.session_token == token).first()
    finally:
        db.close()

"""Invalida il token lato server (usato al logout esplicito)."""
def invalidate_token(student_id: int) -> None:

    if not student_id:
        return
    db = SessionLocal()
    try:
        student = db.query(Student).filter(Student.id == student_id).first()
        if student:
            student.session_token = None
            db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Snippet JS lato client
# ---------------------------------------------------------------------------
"""Scrive il cookie di sessione nel browser (da chiamare dopo il login)."""
def render_set_cookie(token: str) -> None:

    st.iframe(
        f"""
        <script>
            document.cookie = "{COOKIE_NAME}={token}; Max-Age={COOKIE_MAX_AGE}; Path=/; SameSite=Lax";
        </script>
        """,
        height=1,
        width=1,
    )

"""Cancella il cookie di sessione (da chiamare al logout esplicito)."""
def render_clear_cookie() -> None:

    st.iframe(
        f"""
        <script>
            document.cookie = "{COOKIE_NAME}=; Max-Age=0; Path=/; SameSite=Lax";
        </script>
        """,
        height=1,
        width=1,
    )


def render_cookie_autologin_probe() -> None:
    st.iframe(
        f"""
        <script>
            (function() {{
                var match = document.cookie.match(new RegExp('(^| ){COOKIE_NAME}=([^;]+)'));
                var token = match ? match[2] : null;
                var loc = window.parent.location;
                var search = loc.search || "";
                if (token && search.indexOf("token=") === -1) {{
                    var sep = search.length ? "&" : "?";
                    loc.search = search + sep + "token=" + token;
                }}
            }})();
        </script>
        """,
        height=1,
        width=1,
    )
