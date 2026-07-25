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
    render_cookie_autologin_probe,
    verify_token,
)

# Crea le tabelle (e applica la migrazione di session_token) prima di tutto.
init_db()

# ── Configurazione pagina ──────────────────────────────────────────────────
st.set_page_config(
    page_title="Study Coach",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS globale ────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=Inter:wght@300;400;500&display=swap');

:root {
    --bg:        #0d0f14;
    --surface:   #161923;
    --border:    #252a36;
    --accent:    #6c63ff;
    --accent2:   #00d4aa;
    --text:      #e8eaf0;
    --muted:     #6b7280;
    --danger:    #f43f5e;
    --warning:   #f59e0b;
    --success:   #10b981;
}

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
    background-color: var(--bg);
    color: var(--text);
}

h1, h2, h3, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
    font-family: 'Syne', sans-serif !important;
    font-weight: 800;
}

/* Nascondi sidebar di default */
[data-testid="stSidebar"] { display: none; }

/* Input fields */
.stTextInput input, .stTextArea textarea, .stSelectbox select {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    color: var(--text) !important;
    border-radius: 8px !important;
}

/* Bottoni primari */
.stButton > button[kind="primary"] {
    background: var(--accent) !important;
    border: none !important;
    border-radius: 8px !important;
    font-family: 'Syne', sans-serif !important;
    font-weight: 700 !important;
    letter-spacing: 0.03em;
    transition: all 0.2s ease;
}
.stButton > button[kind="primary"]:hover {
    background: #5a52e0 !important;
    transform: translateY(-1px);
    box-shadow: 0 4px 20px rgba(108, 99, 255, 0.35);
}

/* Bottoni secondari */
.stButton > button {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    color: var(--text) !important;
    font-family: 'Inter', sans-serif !important;
}

/* Card generica */
.sc-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 0.75rem;
}

/* Badge difficoltà */
.badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}
.badge-base     { background: #1e3a2f; color: var(--success); }
.badge-inter    { background: #2d2700; color: var(--warning); }
.badge-avanzata { background: #2d1520; color: var(--danger); }

/* Score colori */
.score-high { color: var(--success); font-weight: 700; }
.score-mid  { color: var(--warning); font-weight: 700; }
.score-low  { color: var(--danger);  font-weight: 700; }

/* Divider */
.sc-divider { border: none; border-top: 1px solid var(--border); margin: 1.5rem 0; }
</style>
""", unsafe_allow_html=True)

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
            render_clear_cookie()
        st.query_params.clear()
    else:
        render_cookie_autologin_probe()

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
elif page == "history":
    from pages.history import render
    render()
elif page == "exam":
    from pages.exam import render
    render()
else:
    st.error(f"Pagina sconosciuta: {page}")