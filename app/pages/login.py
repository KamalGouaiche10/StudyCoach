"""
pages/login.py — Login e Registrazione
"""

from app.ui import logo

import hashlib
import sys
from pathlib import Path
from typing import Optional

import streamlit as st

# Aggiunge il root al path per import backend
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.db.models import SessionLocal, Student, init_db # pylint: disable=wrong-import-position


# ── Helpers ────────────────────────────────────────────────────────────────

def _hash_password(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()


def _login(username: Optional[str], password: Optional[str]) -> tuple[bool, str]:
    """Verifica credenziali. Ritorna (successo, messaggio)."""
    # streamlit text_input can return None in some type stubs; normalizziamo
    username = (username or "").strip()
    password = password or ""

    if not username or not password:
        return False, "Compila tutti i campi."

    db = SessionLocal()
    try:
        student = db.query(Student).filter(Student.username == username.strip()).first()
        if not student:
            return False, "Utente non trovato."
        if student.password_hash != _hash_password(password):
            return False, "Password errata."
        st.session_state.authenticated = True
        st.session_state.student_id    = student.id
        st.session_state.username      = student.username
        st.session_state.current_page  = "upload"
        return True, "ok"
    finally:
        db.close()


def _register(username: Optional[str], password: Optional[str], confirm: Optional[str]) -> tuple[bool, str]:
    """Crea un nuovo account. Ritorna (successo, messaggio)."""
    # Normalizza possibili None provenienti da Streamlit
    username = (username or "").strip()
    password = password or ""
    confirm = confirm or ""

    if not username or not password or not confirm:
        return False, "Compila tutti i campi."
    if len(username) < 3:
        return False, "Username troppo corto (min 3 caratteri)."
    if len(password) < 6:
        return False, "Password troppo corta (min 6 caratteri)."
    if password != confirm:
        return False, "Le password non coincidono."

    db = SessionLocal()
    try:
        existing = db.query(Student).filter(Student.username == username.strip()).first()
        if existing:
            return False, "Username già in uso."
        student = Student(
            username=username.strip(),
            password_hash=_hash_password(password),
        )
        db.add(student)
        db.commit()
        db.refresh(student)
        st.session_state.authenticated = True
        st.session_state.student_id    = student.id
        st.session_state.username      = student.username
        st.session_state.current_page  = "upload"
        return True, "ok"
    except Exception as e: # pylint: disable=broad-exception-caught
        db.rollback()
        return False, f"Errore database: {e}"
    finally:
        db.close()


# ── Render ─────────────────────────────────────────────────────────────────

def render():
    init_db()  # crea tabelle se non esistono

    # Se già autenticato, reindirizza
    if st.session_state.get("authenticated"):
        st.session_state.current_page = "upload"
        st.rerun()

    st.html(f'''<div class="sc-login sc:text-center"><div class="sc:flex sc:justify-center sc:mb-6">{logo(56)}</div><div class="sc-eyebrow">STUDY COACH</div><h1>Fai spazio a ciò che impari.</h1><p class="sc:text-muted sc:text-sm">I tuoi materiali, le domande giuste, un passo avanti ogni giorno.</p></div>''')

    # Tabs Login / Registrazione
    col_center = st.columns([1, 3, 1])[1]

    with col_center:
        tab_login, tab_reg = st.tabs(["Accedi", "Registrati"])

        # ── TAB LOGIN ──────────────────────────────────────────────────────
        with tab_login:
            st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
            username = st.text_input("Username", key="login_user", placeholder="Il tuo username")
            password = st.text_input("Password", type="password", key="login_pwd", placeholder="••••••••")

            st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

            if st.button("Accedi", type="primary", use_container_width=True, key="btn_login"):
                ok, msg = _login(username, password)
                if ok:
                    st.success("Bentornato!")
                    st.rerun()
                else:
                    st.error(msg)

        # ── TAB REGISTRAZIONE ──────────────────────────────────────────────
        with tab_reg:
            st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
            new_user = st.text_input("Username", key="reg_user", placeholder="Scegli uno username")
            new_pwd  = st.text_input("Password", type="password", key="reg_pwd", placeholder="Min. 6 caratteri")
            new_pwd2 = st.text_input("Conferma password", type="password", key="reg_pwd2", placeholder="Ripeti la password")

            st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

            if st.button("Crea account", type="primary", use_container_width=True, key="btn_reg"):
                ok, msg = _register(new_user, new_pwd, new_pwd2)
                if ok:
                    st.success("Account creato! Benvenuto 🎉")
                    st.rerun()
                else:
                    st.error(msg)

        # Footer
        st.markdown("""
        <div style="text-align:center; margin-top:2rem; color:var(--quiet); font-size:0.8rem;">
            Il tuo spazio personale per preparare gli esami.
        </div>
        """, unsafe_allow_html=True)
