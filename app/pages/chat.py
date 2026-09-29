"""
pages/chat.py — Chatbot dubbi (tutor socratico avviato dallo studente)

Lo studente scrive un dubbio libero su un argomento del materiale caricato.
Il tutor NON risponde subito: fa una domanda guida socratica. Dopo la
risposta dello studente, mostra dove ha sbagliato e la risposta corretta
e migliorata, basandosi sui PDF caricati per l'esame.
"""

from app.ui import brand, page_heading, empty_state, agent_status

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.agents.socratic_tutor import DoubtTutor  # pylint: disable=wrong-import-position

ASSISTANT_AVATAR = ":material/school:"


# ── Guards ─────────────────────────────────────────────────────────────────

def _require_auth() -> None:
    if not st.session_state.get("authenticated"):
        st.session_state.current_page = "login"
        st.rerun()


def _require_exam() -> None:
    if not st.session_state.get("current_exam"):
        st.session_state.current_page = "upload"
        st.rerun()


# ── State ──────────────────────────────────────────────────────────────────

def _reset_chat_state() -> None:
    st.session_state.chat_messages = []
    st.session_state.chat_tutor = None
    st.session_state.chat_stage = "idle"  # idle | waiting_answer


def _ensure_chat_state() -> None:
    for key, default in (
        ("chat_messages", []),
        ("chat_tutor", None),
        ("chat_stage", "idle"),
    ):
        if key not in st.session_state:
            st.session_state[key] = default


# ── Render ─────────────────────────────────────────────────────────────────

def render() -> None:
    _require_auth()
    _require_exam()
    _ensure_chat_state()

    exam = st.session_state.current_exam
    student_id = st.session_state.student_id

    nav, back, reset = st.columns([3, 1, 1], vertical_alignment="center")
    with nav:
        brand(exam["name"])
        st.html('<span class="sc-reading-page" aria-hidden="true"></span>')
    with back:
        if st.button("Esame", icon=":material/arrow_back:", use_container_width=True):
            st.session_state.current_page = "exam"
            st.rerun()
    with reset:
        if st.button("Nuova chat", icon=":material/add:", use_container_width=True):
            _reset_chat_state()
            st.rerun()
    st.html('<hr class="sc-divider">')
    page_heading("Chiedi al tutor", "Un dubbio alla volta. Ragioniamo insieme a partire dalle fonti dell’esame.")
    if not st.session_state.chat_messages:
        empty_state("Da cosa vuoi partire?", "Descrivi un concetto che non ti è chiaro. Riceverai una domanda guida, poi un feedback sulla tua risposta.", "chat")
        st.caption("Per esempio: «Non capisco la differenza tra questi due concetti: …»")
    agent_status("Tutor socratico", "In attesa della tua risposta" if st.session_state.chat_stage == "waiting_answer" else "Pronto per un nuovo dubbio")

    for msg in st.session_state.chat_messages:
        avatar = ASSISTANT_AVATAR if msg["role"] == "assistant" else None
        with st.chat_message(msg["role"], avatar=avatar):
            st.caption("Tutor socratico" if msg["role"] == "assistant" else "Tu")
            st.markdown(msg["content"])

    stage = st.session_state.chat_stage
    placeholder = (
        "Scrivi qui il tuo dubbio..."
        if stage == "idle"
        else "Rispondi alla domanda guida..."
    )

    user_input = st.chat_input(placeholder)
    if not user_input:
        return

    st.session_state.chat_messages.append({"role": "user", "content": user_input})

    if stage == "idle":
        _handle_new_doubt(student_id, exam["id"], user_input)
    else:
        _handle_answer(user_input)

    st.rerun()


def _handle_new_doubt(student_id: int, exam_id: int, doubt_text: str) -> None:
    tutor = DoubtTutor(student_id=student_id, exam_id=exam_id)
    with st.spinner("Il tutor sta pensando a una domanda per te..."):
        try:
            data = tutor.start(doubt_text)
        except ValueError as e:
            st.session_state.chat_messages.append({"role": "assistant", "content": f"  {e}"})
            return
        except Exception as e:  # pylint: disable=broad-exception-caught
            st.session_state.chat_messages.append({
                "role": "assistant",
                "content": f"  Errore nel generare la domanda guida: {e}",
            })
            return

    st.session_state.chat_tutor = tutor
    st.session_state.chat_stage = "waiting_answer"
    st.session_state.chat_messages.append({
        "role": "assistant",
        "content": data["guiding_question"],
    })


def _handle_answer(answer: str) -> None:
    tutor: DoubtTutor | None = st.session_state.chat_tutor
    if tutor is None:
        st.session_state.chat_stage = "idle"
        st.session_state.chat_messages.append({
            "role": "assistant",
            "content": "  Sessione persa, scrivi di nuovo il tuo dubbio.",
        })
        return

    with st.spinner("Il tutor sta valutando la tua risposta..."):
        try:
            data = tutor.submit_answer(answer)
        except Exception as e:  # pylint: disable=broad-exception-caught
            st.session_state.chat_messages.append({
                "role": "assistant",
                "content": f"  Errore nella valutazione: {e}",
            })
            return

    parts = []
    if data["correct_points"]:
        parts.append("**Cosa hai capito bene:**\n" + "\n".join(f"- {p}" for p in data["correct_points"]))
    if data["missing_points"]:
        parts.append("**Dove hai sbagliato o cosa ti manca:**\n" + "\n".join(f"- {p}" for p in data["missing_points"]))
    parts.append("**Risposta corretta:**\n" + data["correct_answer"])
    parts.append("_Scrivi pure un nuovo dubbio quando vuoi._")

    st.session_state.chat_stage = "idle"
    st.session_state.chat_tutor = None
    st.session_state.chat_messages.append({"role": "assistant", "content": "\n\n".join(parts)})
