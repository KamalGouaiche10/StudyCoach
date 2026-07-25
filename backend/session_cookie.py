"""
backend/session_cookie.py — Login persistente tramite cookie di sessione
==========================================================================
Nessuna libreria esterna: il cookie viene scritto e letto lato client con
piccoli snippet JS iniettati tramite st.components.v1.html (già incluso in
Streamlit). Il valore del cookie è un token casuale associato allo studente
e verificato lato server contro backend.db.models.Student.session_token.

Flusso:
  1. Al login/registrazione: get_or_create_token() genera (o riusa) un
     token persistente per lo studente, salvato nel DB. render_set_cookie()
     lo scrive nel browser con una scadenza lunghissima (~10 anni, la cosa
     più vicina a "nessuna scadenza" che un cookie possa avere).
  2. Ad ogni caricamento pagina, se lo studente NON risulta autenticato in
     session_state (es. dopo un refresh, riavvio del browser o
     disconnessione del websocket che ha azzerato session_state), main.py:
       - se l'URL contiene già ?token=..., verifica il token e logga
         automaticamente lo studente;
       - altrimenti chiama render_cookie_autologin_probe(), che legge il
         cookie lato JS e — se presente — ricarica la pagina aggiungendo
         il token come query param, permettendo così al backend Python
         (che non può leggere i cookie direttamente) di recuperarlo.
  3. Al logout esplicito: invalidate_token() cancella il token nel DB e
     render_clear_cookie() rimuove il cookie dal browser. Da quel momento
     nessun dispositivo con quel vecchio cookie potrà più auto-loggarsi.
"""

import secrets
from typing import Optional

import streamlit.components.v1 as components

from backend.db.models import SessionLocal, Student

COOKIE_NAME = "sc_token"
COOKIE_MAX_AGE = 10 * 365 * 24 * 60 * 60  # ~10 anni: emula "nessuna scadenza"


# ---------------------------------------------------------------------------
# Gestione token lato DB
# ---------------------------------------------------------------------------

def get_or_create_token(student_id: int) -> Optional[str]:
    """Restituisce il token persistente dello studente, generandolo se assente."""
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


def verify_token(token: str) -> Optional[Student]:
    """Restituisce lo Student associato al token, se valido."""
    if not token:
        return None
    db = SessionLocal()
    try:
        return db.query(Student).filter(Student.session_token == token).first()
    finally:
        db.close()


def invalidate_token(student_id: int) -> None:
    """Invalida il token lato server (usato al logout esplicito)."""
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

def render_set_cookie(token: str) -> None:
    """Scrive il cookie di sessione nel browser (da chiamare dopo il login)."""
    components.html(
        f"""
        <script>
            document.cookie = "{COOKIE_NAME}={token}; Max-Age={COOKIE_MAX_AGE}; Path=/; SameSite=Lax";
        </script>
        """,
        height=0,
        width=0,
    )


def render_clear_cookie() -> None:
    """Cancella il cookie di sessione (da chiamare al logout esplicito)."""
    components.html(
        f"""
        <script>
            document.cookie = "{COOKIE_NAME}=; Max-Age=0; Path=/; SameSite=Lax";
        </script>
        """,
        height=0,
        width=0,
    )


def render_cookie_autologin_probe() -> None:
    """
    Da chiamare quando lo studente NON è autenticato in session_state e
    l'URL non contiene già ?token=. Se il browser possiede un cookie di
    sessione valido, ricarica la pagina aggiungendo il token come query
    param, così il backend Python può recuperarlo e loggare lo studente
    automaticamente, senza che debba reinserire le credenziali.
    """
    components.html(
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
        height=0,
        width=0,
    )
