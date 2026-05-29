"""
pages/history.py — Storico sessioni per esame
"""

import streamlit as st
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.db.models import SessionLocal, Session as DbSession, Exam


# ── Guards ─────────────────────────────────────────────────────────────────

def _require_auth():
    if not st.session_state.get("authenticated"):
        st.session_state.current_page = "login"
        st.rerun()


# ── Helpers DB ─────────────────────────────────────────────────────────────

def _get_all_exams(student_id: int) -> list:
    db = SessionLocal()
    try:
        return db.query(Exam).filter(Exam.student_id == student_id).order_by(Exam.created_at.desc()).all()
    finally:
        db.close()


def _get_sessions(exam_id: int) -> list:
    db = SessionLocal()
    try:
        return (
            db.query(DbSession)
            .filter(DbSession.exam_id == exam_id)
            .order_by(DbSession.started_at.desc())
            .all()
        )
    finally:
        db.close()


def _delete_session(session_id: int):
    db = SessionLocal()
    try:
        sess = db.query(DbSession).filter(DbSession.id == session_id).first()
        if sess:
            db.delete(sess)
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _format_duration(started_at, ended_at) -> str:
    if not started_at or not ended_at:
        return "—"
    try:
        delta = ended_at - started_at
        minutes = int(delta.total_seconds() // 60)
        seconds = int(delta.total_seconds() % 60)
        if minutes == 0:
            return f"{seconds}s"
        return f"{minutes}m {seconds}s"
    except Exception:
        return "—"


def _score_color(score: float) -> str:
    if score >= 8:
        return "#10b981"
    elif score >= 6:
        return "#f59e0b"
    return "#f43f5e"


def _verdict_emoji(score: float) -> str:
    if score >= 8:
        return "🟢"
    elif score >= 6:
        return "🟡"
    return "🔴"


# ── Navbar ─────────────────────────────────────────────────────────────────

def _navbar():
    col1, col2 = st.columns([4, 1])
    with col1:
        st.markdown("""
        <span style="font-family:'Syne',sans-serif; font-size:1.3rem; font-weight:800;
              background:linear-gradient(135deg,#6c63ff,#00d4aa);
              -webkit-background-clip:text; -webkit-text-fill-color:transparent;">
            🎓 Study Coach
        </span>
        <span style="color:#6b7280; margin:0 0.5rem">›</span>
        <span style="font-family:'Syne',sans-serif; font-size:1.1rem; font-weight:700; color:#e8eaf0;">
            Storico sessioni
        </span>
        """, unsafe_allow_html=True)
    with col2:
        if st.button("← Esami", use_container_width=True):
            st.session_state.current_page = "upload"
            st.session_state.current_exam = None
            st.rerun()
    st.markdown("<hr style='border-color:#252a36; margin:0.5rem 0 1.5rem'>", unsafe_allow_html=True)


# ── Render sessione espansa ────────────────────────────────────────────────

def _is_valid_attempt(attempt: dict) -> bool:
    """Controlla che il dict abbia i campi minimi attesi (formato piatto)."""
    return isinstance(attempt, dict) and "question_text" in attempt


def _render_session_detail(sess: DbSession):
    if not sess.qa_log:
        st.info("Nessun log disponibile per questa sessione.")
        return
    try:
        attempts = json.loads(sess.qa_log)
    except Exception:
        st.warning("Impossibile caricare il log della sessione.")
        return

    if not attempts:
        st.info("Sessione senza domande registrate.")
        return

    valid = [a for a in attempts if _is_valid_attempt(a)]
    if not valid:
        st.info("Il log di questa sessione è in un formato precedente non visualizzabile.")
        return

    for i, attempt in enumerate(valid, 1):
        q_text   = attempt.get("question_text", f"Domanda {i}")
        score    = attempt.get("final_score", "—")
        diff     = attempt.get("difficulty", "")
        topic    = attempt.get("topic_hint", "")
        diff_css = {"base": "badge-base", "intermedia": "badge-inter", "avanzata": "badge-avanzata"}.get(diff, "badge-inter")

        badge_html = f'<span class="badge {diff_css}">{diff}</span>' if diff else ""
        topic_html = f'<div style="color:#6b7280; font-size:0.78rem;">🏷 {topic}</div>' if topic else ""
        score_color = _score_color(score) if isinstance(score, (int, float)) else "#6b7280"
        score_display = f"{score}/10" if isinstance(score, (int, float)) else str(score)

        st.markdown(f"""
        <div class="sc-card" style="margin-bottom:0.5rem;">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:0.6rem;">
                <div style="display:flex; align-items:center; gap:0.5rem;">
                    <span style="color:#6b7280; font-size:0.8rem; font-weight:600;">Q{i}</span>
                    {badge_html}
                </div>
                <span style="font-family:'Syne',sans-serif; font-weight:800; font-size:1.1rem; color:{score_color};">
                    {score_display}
                </span>
            </div>
            <p style="margin:0 0 0.5rem; font-weight:600; font-size:0.92rem;">{q_text}</p>
            {topic_html}
        </div>
        """, unsafe_allow_html=True)

        ans1       = attempt.get("student_answer_1", "")
        ans2       = attempt.get("student_answer_2", "")
        guiding    = attempt.get("guiding_question", "")
        evaluation = attempt.get("evaluation", {})
        motivation = evaluation.get("motivation", "") if isinstance(evaluation, dict) else ""

        with st.expander(f"Dettaglio domanda {i}", expanded=False):
            if ans1:
                st.markdown(f"**Prima risposta:** {ans1}")
            if guiding:
                st.markdown(f"**Domanda guida:** *{guiding}*")
            if ans2:
                st.markdown(f"**Seconda risposta:** {ans2}")
            if motivation:
                st.markdown(f"**Motivazione voto:** {motivation}")

            contest = attempt.get("contestation_result")
            if contest and isinstance(contest, dict):
                assessment  = contest.get("contestation_assessment", "")
                final_score = contest.get("final_score", "")
                resp        = contest.get("response_to_student", "")
                color_map   = {"valido": "#10b981", "parzialmente_valido": "#f59e0b", "non_valido": "#f43f5e"}
                c           = color_map.get(assessment, "#6b7280")
                label       = assessment.replace("_", " ")
                st.markdown(f"""
                <div style="padding:0.5rem 0.8rem; background:#1a1a2e; border-radius:8px;
                            margin-top:0.5rem; border-left:3px solid {c}; font-size:0.85rem;">
                    ⚖️ <strong>Contestazione {label}</strong>
                    &nbsp;→&nbsp; voto finale: <strong>{final_score}/10</strong><br/>
                    <span style="color:#9ca3af">{resp}</span>
                </div>
                """, unsafe_allow_html=True)


# ── Render principale ──────────────────────────────────────────────────────

def render():
    _require_auth()
    _navbar()

    student_id   = st.session_state.student_id
    current_exam = st.session_state.get("current_exam")
    exams        = _get_all_exams(student_id)

    if not exams:
        st.markdown("""
        <div style="text-align:center; padding:4rem; color:#4b5563;">
            <div style="font-size:3rem; margin-bottom:1rem;">📭</div>
            <p>Nessun esame trovato. Creane uno dalla pagina principale.</p>
        </div>
        """, unsafe_allow_html=True)
        return

    exam_options = {f"{e.name} (id {e.id})": e for e in exams}
    default_key  = None
    if current_exam:
        for k, e in exam_options.items():
            if e.id == current_exam["id"]:
                default_key = k
                break

    keys        = list(exam_options.keys())
    default_idx = keys.index(default_key) if default_key else 0

    selected_key  = st.selectbox("Seleziona esame", keys, index=default_idx, label_visibility="collapsed")
    selected_exam = exam_options[selected_key]
    sessions      = _get_sessions(selected_exam.id)

    st.markdown(f"""
    <div style="display:flex; align-items:center; gap:1rem; margin:1rem 0 0.75rem;">
        <h3 style="font-family:'Syne',sans-serif; margin:0;">{selected_exam.name}</h3>
        <span style="color:#6b7280; font-size:0.85rem;">{len(sessions)} sessioni</span>
    </div>
    """, unsafe_allow_html=True)

    if not sessions:
        st.markdown("""
        <div style="text-align:center; padding:3rem; color:#4b5563;">
            <div style="font-size:2.5rem; margin-bottom:0.75rem;">📂</div>
            <p>Nessuna sessione ancora per questo esame.</p>
        </div>
        """, unsafe_allow_html=True)
        col_start, _ = st.columns([1, 3])
        with col_start:
            if st.button("▶ Avvia prima sessione", type="primary", use_container_width=True):
                _go_to_session(selected_exam)
        return

    # ── Statistiche aggregate ──────────────────────────────────────────────
    completed = [s for s in sessions if s.score_total is not None]
    if completed:
        avg_all = round(sum(s.score_total for s in completed) / len(completed), 1)
        best    = max(s.score_total for s in completed)
        col1, col2, col3, col4 = st.columns(4)
        metrics = [
            ("Sessioni totali", len(sessions),   "#6b7280"),
            ("Completate",      len(completed),  "#6c63ff"),
            ("Media generale",  f"{avg_all}/10", _score_color(avg_all)),
            ("Miglior voto",    f"{best}/10",    _score_color(best)),
        ]
        for col, (label, value, color) in zip([col1, col2, col3, col4], metrics):
            with col:
                st.markdown(f"""
                <div class="sc-card" style="text-align:center; padding:1rem;">
                    <div style="font-size:1.5rem; font-weight:800; font-family:'Syne',sans-serif; color:{color};">
                        {value}
                    </div>
                    <div style="font-size:0.78rem; color:#6b7280; margin-top:0.2rem;">{label}</div>
                </div>
                """, unsafe_allow_html=True)
        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    # ── Lista sessioni ─────────────────────────────────────────────────────
    for sess in sessions:
        score     = sess.score_total
        has_score = score is not None
        duration  = _format_duration(sess.started_at, sess.ended_at)
        date_str  = sess.started_at.strftime("%d/%m/%Y %H:%M") if sess.started_at else "—"

        if has_score:
            verdict_icon  = _verdict_emoji(score)
            score_str     = f"{score}/10"
            score_color   = _score_color(score)
            border_color  = score_color
        else:
            verdict_icon  = "⏳"
            score_str     = "In corso"
            score_color   = "#6b7280"
            border_color  = "#252a36"

        has_report = bool(sess.report_path and Path(sess.report_path).exists())

        # ── FIX: card HTML separata dai widget Streamlit ──────────────────
        # In precedenza la card e i bottoni erano mescolati in un unico blocco
        # che Streamlit non riusciva a renderizzare correttamente quando
        # has_score=False, lasciando la riga visivamente vuota.
        st.markdown(f"""
        <div class="sc-card" style="border-left:3px solid {border_color}; margin-bottom:0.25rem;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <div style="font-size:0.78rem; color:#6b7280; margin-bottom:0.3rem;">
                        {verdict_icon} Sessione #{sess.id} &nbsp;·&nbsp; {date_str} &nbsp;·&nbsp; {duration}
                    </div>
                    <div style="font-family:'Syne',sans-serif; font-size:1.4rem; font-weight:800;
                                color:{score_color};">
                        {score_str}
                    </div>
                </div>
                {"<div style='font-size:0.82rem; color:#6b7280;'>📄 Report disponibile</div>" if has_report else "<div></div>"}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Bottoni sempre renderizzati fuori dall'HTML ───────────────────
        col_detail, col_notes, col_pdf, col_del = st.columns([2, 1.5, 1.5, 1])

        with col_detail:
            if sess.qa_log:
                with st.expander("📜 Dettaglio Q&A", expanded=False):
                    _render_session_detail(sess)
            else:
                # FIX: sessione "In corso" senza qa_log — mostra placeholder
                st.markdown(
                    "<p style='color:#6b7280; font-size:0.82rem; margin:0.4rem 0;'>"
                    "Sessione non ancora completata.</p>",
                    unsafe_allow_html=True,
                )

        with col_notes:
            if sess.qa_log:
                if st.button("📋 Appunti", key=f"notes_{sess.id}", use_container_width=True,
                             help="Visualizza gli appunti sintetici generati per questa sessione"):
                    st.session_state[f"show_notes_{sess.id}"] = not st.session_state.get(f"show_notes_{sess.id}", False)
                    st.rerun()

        with col_pdf:
            if has_report:
                with open(sess.report_path, "rb") as f:
                    st.download_button(
                        "📥 Report PDF",
                        data=f,
                        file_name=f"report_sessione_{sess.id}.pdf",
                        mime="application/pdf",
                        key=f"dl_{sess.id}",
                        use_container_width=True,
                    )

        with col_del:
            # FIX: il bottone "Elimina" era visibile solo per sessioni senza
            # score, ma una sessione "In corso" può non avere qa_log né score.
            # Ora il bottone compare per qualsiasi sessione incompleta
            # (ended_at assente), non solo per quelle senza score.
            if sess.ended_at is None:
                if st.button("🗑 Elimina", key=f"del_sess_{sess.id}", use_container_width=True,
                             help="Elimina sessione incompleta"):
                    _delete_session(sess.id)
                    st.rerun()

        # ── Pannello appunti sintetici ─────────────────────────────────────
        if st.session_state.get(f"show_notes_{sess.id}", False):
            _render_notes_panel(sess)

        st.markdown("<div style='height:0.1rem'></div>", unsafe_allow_html=True)

    # ── Bottone nuova sessione ─────────────────────────────────────────────
    st.markdown("<hr style='border-color:#252a36; margin:1.5rem 0 1rem'>", unsafe_allow_html=True)
    col_btn, _ = st.columns([1, 3])
    with col_btn:
        if st.button("▶ Nuova sessione", type="primary", use_container_width=True):
            _go_to_session(selected_exam)


def _render_notes_panel(sess: DbSession):
    """Pannello inline che mostra gli appunti sintetici per la sessione."""
    cache_key = f"_notes_cache_{sess.id}"

    if cache_key not in st.session_state:
        if not sess.qa_log:
            st.info("Nessun dato disponibile per generare appunti.")
            return
        try:
            from backend.agents.notes_generator import generate_notes_from_log
            attempts = json.loads(sess.qa_log)
            with st.spinner("Generazione appunti sintetici in corso..."):
                notes = generate_notes_from_log(attempts)
            st.session_state[cache_key] = notes
        except Exception as e:
            st.error(f"Errore generazione appunti: {e}")
            return

    notes = st.session_state.get(cache_key, "")
    if not notes:
        return

    # FIX: prima il testo degli appunti veniva interpolato dentro unsafe_allow_html
    # come stringa grezza, rompendo il Markdown (bullet, grassetto, titoli).
    # Ora la card del titolo è HTML, il contenuto è renderizzato via st.markdown nativo.
    st.markdown(f"""
    <div style="background:#0f1319; border:1px solid #252a36; border-radius:10px;
                padding:1.25rem 1.5rem 0.5rem; margin:0.5rem 0 0.25rem;">
        <div style="font-family:'Syne',sans-serif; font-weight:700; font-size:0.95rem;
                    color:#6c63ff; margin-bottom:0.5rem;">
            📋 Appunti sintetici — Sessione #{sess.id}
        </div>
    </div>
    """, unsafe_allow_html=True)
    # Il contenuto Markdown viene reso da Streamlit, non da HTML inline
    st.markdown(notes)


def _go_to_session(exam):
    st.session_state.current_exam    = {"id": exam.id, "name": exam.name}
    st.session_state.current_page    = "session"
    st.session_state.quiz_result     = None
    st.session_state.adaptive_engine = None
    st.session_state.tutor           = None
    st.session_state.current_q_idx   = 0
    st.session_state.tutor_state     = "idle"
    st.session_state.current_session = None
    st.rerun()