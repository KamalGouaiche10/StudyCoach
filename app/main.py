"""
Study Coach — Entry point Streamlit
=====================================
Avvia con: streamlit run app/main.py
"""

import sys
from pathlib import Path

import streamlit as st

# Aggiunge il root al path per import backend (session_cookie, db.models, ...)
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.db.models import init_db  # pylint: disable=wrong-import-position
from backend.session_cookie import (  # pylint: disable=wrong-import-position
    render_clear_cookie,
    render_set_cookie,
    get_or_create_token,
    restore_login_from_cookie,
    verify_token,
)

# Crea le tabelle (e applica la migrazione di session_token) prima di tutto.
init_db()

# ── Configurazione pagina ──────────────────────────────────────────────────
st.set_page_config(
    page_title="Study Coach",
    page_icon=Path(__file__).parent / "assets" / "logo.svg",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS globale ────────────────────────────────────────────────────────────
from app.ui import load_styles

load_styles()

# ── Inizializzazione session_state ────────────────────────────────────────
defaults = {
    "authenticated": False,
    "student_id":    None,
    "username":      None,
    "current_page":  "login",
    "current_exam":  None,   # {"id": int, "name": str}
    "current_session": None, # {"id": int, "questions": [...], "attempts": [...]}
    "quiz_result":   None,
    "adaptive_engine": None,
    "tutor":         None,
    "current_q_idx": 0,
    "tutor_state":   "idle",  # idle | answer1 | answer2 | evaluated | contested | closed
    "chat_messages": [],      # storico chatbot dubbi: [{"role", "content"}, ...]
    "chat_tutor":    None,    # DoubtTutor attivo per il dubbio corrente
    "chat_stage":    "idle",  # idle | waiting_answer
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Login automatico da cookie persistente ─────────────────────────────────
# Se lo studente non risulta autenticato in session_state (es. dopo un
# refresh forte, un riavvio del browser o una disconnessione del websocket
# che ha azzerato lo stato), proviamo a recuperare il login dal cookie del
# browser invece di rimandarlo forzatamente alla pagina di login.
if not st.session_state.authenticated:
    token = st.query_params.get("token")
    if token:
        student = verify_token(token)
        if student:
            st.session_state.authenticated = True
            st.session_state.student_id    = student.id
            st.session_state.username      = student.username
            st.session_state.current_page  = "upload"
        else:
            # Token non valido/scaduto lato server: ripulisci anche il
            # cookie lato browser per evitare tentativi di auto-login
            # ripetuti ad ogni futuro caricamento.
            st.session_state._clear_session_cookie = True
        del st.query_params["token"]
    else:
        restore_login_from_cookie()

# Keep the writer in the final screen: the login handler's immediate rerun
# must not unmount it before the browser has saved the cookie.
if st.session_state.authenticated:
    token = get_or_create_token(st.session_state.student_id)
    if token:
        render_set_cookie(token)
elif st.session_state.get("_clear_session_cookie") or st.context.cookies.get("sc_token"):
    render_clear_cookie()

# ── Router ────────────────────────────────────────────────────────────────
page = st.session_state.current_page

if page == "login":
    from pages.login import render
    render()
elif page == "upload":
    from pages.upload import render
    render()
elif page == "session":
    from pages.session import render
    render()
elif page == "chat":
    from pages.chat import render
    render()
elif page == "history":
    from pages.history import render
    render()
elif page == "exam":
    from pages.exam import render
    render()
else:
    st.error(f"Pagina sconosciuta: {page}")
