"""
pages/session.py — Sessione attiva di studio socratico
Loop: genera quiz → per ogni domanda → risposta1 → guida → risposta2 → valutazione → (contestazione) → prossima
"""

import streamlit as st
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.db.models import SessionLocal, Session as DbSession
from backend.agents.quiz_generator import generate_quiz
from backend.agents.socratic_tutor import SocraticTutor
from backend.agents.adaptive_engine import AdaptiveEngine
from backend.agents.report_generator import save_report


# ── Guards ─────────────────────────────────────────────────────────────────

def _require_auth():
    if not st.session_state.get("authenticated"):
        st.session_state.current_page = "login"
        st.rerun()


def _require_exam():
    if not st.session_state.get("current_exam"):
        st.session_state.current_page = "upload"
        st.rerun()


# ── Serializzazione attempt in formato piatto per history.py ───────────────

def _attempt_to_log_entry(tutor: SocraticTutor, final_score: int) -> dict:
    """
    Converte un QuestionAttempt nel formato piatto che history.py si aspetta:
      - question_text, difficulty, topic_hint  → chiavi dirette
      - student_answer_1, guiding_question, student_answer_2 → chiavi dirette
      - final_score → int
      - evaluation → dict con 'score', 'motivation'
      - contestation_result → dict o None
    """
    attempt = tutor.attempt
    if attempt is None:
        return {}

    entry: dict = {
        "question_id":      attempt.question_id,
        "question_text":    attempt.question_text,
        "difficulty":       attempt.difficulty,
        "topic_hint":       attempt.topic_hint,
        "student_answer_1": attempt.student_answer_1,
        "guiding_question": attempt.guiding_question,
        "positive_feedback": attempt.positive_feedback,
        "focus_area":       attempt.focus_area,
        "student_answer_2": attempt.student_answer_2,
        "final_score":      final_score,
    }

    if attempt.evaluation:
        entry["evaluation"] = {
            "score":                      attempt.evaluation.score,
            "motivation":                 attempt.evaluation.motivation,
            "correct_points":             attempt.evaluation.correct_points,
            "missing_points":             attempt.evaluation.missing_points,
            "improvement_after_guidance": attempt.evaluation.improvement_after_guidance,
        }
    else:
        entry["evaluation"] = {}

    if attempt.contestation_result:
        entry["contestation_result"] = {
            "final_score":              attempt.contestation_result.final_score,
            "score_changed":            attempt.contestation_result.score_changed,
            "score_delta":              attempt.contestation_result.score_delta,
            "contestation_assessment":  attempt.contestation_result.contestation_assessment,
            "final_motivation":         attempt.contestation_result.final_motivation,
            "response_to_student":      attempt.contestation_result.response_to_student,
        }
    else:
        entry["contestation_result"] = None

    return entry


# ── Navbar ─────────────────────────────────────────────────────────────────

def _navbar():
    exam = st.session_state.current_exam
    col1, col2 = st.columns([4, 1])
    with col1:
        st.markdown(f"""
        <span style="font-family:'Syne',sans-serif; font-size:1.1rem; font-weight:700; color:#6b7280;">
            🎓 Study Coach
        </span>
        <span style="color:#252a36; margin:0 0.5rem">›</span>
        <span style="font-family:'Syne',sans-serif; font-size:1.1rem; font-weight:800; color:#e8eaf0;">
            {exam['name']}
        </span>
        """, unsafe_allow_html=True)
    with col2:
        if st.button("← Esci", use_container_width=True):
            st.session_state.current_page = "upload"
            st.session_state.current_exam = None
            st.rerun()
    st.markdown("<hr style='border-color:#252a36; margin:0.5rem 0 1rem'>", unsafe_allow_html=True)


# ── Barra progresso ────────────────────────────────────────────────────────

def _progress_bar(current: int, total: int, scores: list):
    pct = int(current / total * 100) if total else 0
    avg = round(sum(scores) / len(scores), 1) if scores else 0
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        st.progress(pct)
    with col2:
        st.markdown(f"<div style='text-align:center; font-size:0.85rem; color:#6b7280;'>"
                    f"{current}/{total} domande</div>", unsafe_allow_html=True)
    with col3:
        css = "score-high" if avg >= 8 else ("score-mid" if avg >= 6 else "score-low")
        st.markdown(f"<div class='{css}' style='text-align:center; font-size:0.85rem;'>"
                    f"Media: {avg if scores else '—'}</div>", unsafe_allow_html=True)


def _score_badge(score: int) -> str:
    css  = "score-high" if score >= 8 else ("score-mid" if score >= 6 else "score-low")
    icon = "🟢" if score >= 8 else ("🟡" if score >= 6 else "🔴")
    return f"<span class='{css}'>{icon} {score}/10</span>"


def _diff_badge(diff: str) -> str:
    cls = {"base": "badge-base", "intermedia": "badge-inter", "avanzata": "badge-avanzata"}.get(diff, "badge-inter")
    return f"<span class='badge {cls}'>{diff}</span>"


# ── DB helpers ─────────────────────────────────────────────────────────────

def _create_db_session(exam_id: int) -> int:
    db = SessionLocal()
    try:
        sess = DbSession(exam_id=exam_id)
        db.add(sess)
        db.commit()
        db.refresh(sess)
        return sess.id
    finally:
        db.close()


def _save_session(session_id: int, attempts: list, engine: AdaptiveEngine, exam: dict):
    db = SessionLocal()
    try:
        sess = db.query(DbSession).filter(DbSession.id == session_id).first()
        if not sess:
            return
        report = engine.generate_session_report()
        sess.ended_at    = datetime.now(timezone.utc)
        sess.score_total = report["overall_avg"]
        sess.qa_log      = json.dumps(attempts, ensure_ascii=False)
        paths = save_report(report, session_id, exam["name"])
        sess.report_path = paths.get("pdf", "")
        db.commit()
    except Exception as e:
        db.rollback()
        st.warning(f"Errore salvataggio sessione: {e}")
    finally:
        db.close()


# ── FASE 1: Generazione quiz ───────────────────────────────────────────────

def _render_quiz_generation():
    exam = st.session_state.current_exam

    st.markdown("""
    <div style="text-align:center; padding:2.5rem 0;">
        <div style="font-size:2.5rem; margin-bottom:0.75rem;">📝</div>
        <h2 style="font-family:'Syne',sans-serif; margin-bottom:0.5rem;">Pronto per studiare?</h2>
        <p style="color:#6b7280; max-width:420px; margin:0 auto;">
            Genererò domande a risposta aperta basate sul materiale che hai caricato,
            poi ti guiderò con il metodo socratico.
        </p>
    </div>
    """, unsafe_allow_html=True)

    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        n_q = st.slider("Numero di domande", min_value=3, max_value=10, value=5, key="n_questions_slider")
        st.markdown("<div style='height:0.75rem'></div>", unsafe_allow_html=True)

        if st.button("🚀 Genera domande", type="primary", use_container_width=True):
            with st.spinner("Recupero materiale e genero le domande..."):
                try:
                    quiz = generate_quiz(
                        student_id=st.session_state.student_id,
                        exam_id=exam["id"],
                        n_questions=n_q,
                        source_name=exam["name"],
                    )
                    engine     = AdaptiveEngine(student_id=st.session_state.student_id, exam_id=exam["id"])
                    session_id = _create_db_session(exam["id"])

                    questions_dicts = [
                        {"id": q.id, "text": q.text, "difficulty": q.difficulty, "topic_hint": q.topic_hint}
                        for q in quiz.questions
                    ]

                    st.session_state.quiz_result     = quiz
                    st.session_state.adaptive_engine = engine
                    st.session_state.current_session = {
                        "id":        session_id,
                        "questions": questions_dicts,
                        "remaining": questions_dicts.copy(),
                        "attempts":  [],   # lista di dict piatti (formato history.py)
                        "scores":    [],
                    }
                    st.session_state.tutor       = None
                    st.session_state.tutor_state = "idle"
                    st.session_state.current_q_idx = 0
                    st.rerun()
                except ValueError as e:
                    st.error(f"⚠️ {e}")
                    st.info("Assicurati di aver caricato il PDF dell'esame prima di avviare la sessione.")
                except Exception as e:
                    st.error(f"Errore inatteso: {e}")


# ── FASE 2: Loop socratico ─────────────────────────────────────────────────

def _render_active_session():
    sess   = st.session_state.current_session
    engine = st.session_state.adaptive_engine
    exam   = st.session_state.current_exam
    state  = st.session_state.tutor_state
    tutor  = st.session_state.tutor

    total_q = len(sess["questions"])
    done_q  = len(sess["attempts"])
    scores  = sess["scores"]

    _progress_bar(done_q, total_q, scores)

    # Sessione completata
    if not sess["remaining"] and state in ("idle", "closed"):
        _render_session_complete()
        return

    # Scegli prossima domanda
    if state == "idle":
        next_q = engine.pick_next_question(sess["remaining"])
        if not next_q:
            _render_session_complete()
            return

        new_tutor = SocraticTutor(student_id=st.session_state.student_id, exam_id=exam["id"])
        new_tutor.start(next_q)
        st.session_state.tutor       = new_tutor
        st.session_state.tutor_state = "answer1"
        st.session_state["_current_q"] = next_q
        st.rerun()

    current_q = st.session_state.get("_current_q", {})
    q_num     = done_q + 1

    st.markdown(f"""
    <div class="sc-card" style="border-left:3px solid #6c63ff; margin-bottom:1.25rem;">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:0.5rem;">
            <span style="color:#6b7280; font-size:0.82rem; font-weight:600; letter-spacing:0.05em; text-transform:uppercase;">
                Domanda {q_num} di {total_q}
            </span>
            {_diff_badge(current_q.get('difficulty','intermedia'))}
        </div>
        <p style="font-family:'Syne',sans-serif; font-size:1.1rem; font-weight:700; margin:0; line-height:1.5;">
            {current_q.get('text', '')}
        </p>
        <div style="color:#4b5563; font-size:0.78rem; margin-top:0.5rem;">
            🏷 {current_q.get('topic_hint', '')}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Prima risposta ─────────────────────────────────────────────────────
    if state == "answer1":
        st.markdown("**📝 La tua prima risposta:**")
        ans1 = st.text_area("Rispondi", key="input_ans1", height=130,
                             placeholder="Scrivi qui la tua risposta...", label_visibility="collapsed")
        if st.button("Invia risposta →", type="primary", key="btn_ans1"):
            if not ans1.strip():
                st.warning("Scrivi una risposta prima di procedere.")
            else:
                with st.spinner("Il tutor elabora la tua risposta..."):
                    result = st.session_state.tutor.submit_answer_1(ans1)
                st.session_state["_guide_result"] = result
                st.session_state.tutor_state = "answer2"
                st.rerun()

    # ── Seconda risposta ───────────────────────────────────────────────────
    elif state == "answer2":
        guide = st.session_state.get("_guide_result", {})

        ans1_text = st.session_state.tutor.attempt.student_answer_1
        st.markdown(f"""
        <div class="sc-card" style="background:#0f1319; margin-bottom:0.75rem;">
            <div style="font-size:0.78rem; color:#6b7280; margin-bottom:0.3rem; text-transform:uppercase; letter-spacing:0.05em;">
                La tua prima risposta
            </div>
            <p style="margin:0; color:#9ca3af; font-size:0.9rem;">{ans1_text}</p>
        </div>
        """, unsafe_allow_html=True)

        if guide.get("positive_feedback"):
            st.markdown(f"""
            <div style="padding:0.6rem 0.9rem; background:#1a1f2e; border-radius:8px; margin-bottom:0.5rem;
                        border-left:3px solid #00d4aa; font-size:0.88rem; color:#a7f3d0;">
                ✅ {guide['positive_feedback']}
            </div>
            """, unsafe_allow_html=True)

        focus_html = f'<div style="margin-top:0.5rem; font-size:0.78rem; color:#6b7280;">Focus: {guide["focus_area"]}</div>' if guide.get("focus_area") else ""
        st.markdown(f"""
        <div style="padding:0.9rem 1rem; background:#1a1a2e; border-radius:10px; margin-bottom:1rem;
                    border-left:3px solid #6c63ff;">
            <div style="font-size:0.78rem; color:#818cf8; margin-bottom:0.4rem; text-transform:uppercase;
                        letter-spacing:0.05em; font-weight:600;">🧠 Domanda guida socratica</div>
            <p style="margin:0; font-family:'Syne',sans-serif; font-weight:600; font-size:1rem; line-height:1.5;">
                {guide.get('guiding_question', '')}
            </p>
            {focus_html}
        </div>
        """, unsafe_allow_html=True)

        st.markdown("**✍️ La tua seconda risposta (dopo la guida):**")
        ans2 = st.text_area("Seconda risposta", key="input_ans2", height=130,
                             placeholder="Integra e approfondisci...", label_visibility="collapsed")
        if st.button("Invia e valuta →", type="primary", key="btn_ans2"):
            if not ans2.strip():
                st.warning("Scrivi la tua risposta prima di procedere.")
            else:
                with st.spinner("Valutazione in corso..."):
                    eval_result = st.session_state.tutor.submit_answer_2(ans2)
                st.session_state["_eval_result"] = eval_result
                st.session_state.tutor_state = "evaluated"
                st.rerun()

    # ── Valutazione ────────────────────────────────────────────────────────
    elif state == "evaluated":
        ev    = st.session_state.get("_eval_result", {})
        score = ev.get("score", 0)
        guide = st.session_state.get("_guide_result", {})
        border = "#10b981" if score >= 8 else ("#f59e0b" if score >= 6 else "#f43f5e")

        with st.expander("📜 Risposte date", expanded=False):
            st.markdown(f"**Prima risposta:** {st.session_state.tutor.attempt.student_answer_1}")
            st.markdown(f"**Guida socratica:** *{guide.get('guiding_question', '')}*")
            st.markdown(f"**Seconda risposta:** {st.session_state.tutor.attempt.student_answer_2}")

        st.markdown(f"""
        <div class="sc-card" style="border-left:3px solid {border};">
            <div style="display:flex; align-items:center; gap:1rem; margin-bottom:0.75rem;">
                <div style="font-size:2.5rem; font-family:'Syne',sans-serif; font-weight:800; color:{border};">
                    {score}/10
                </div>
                <div style="flex:1;">
                    <div style="font-size:0.82rem; color:#6b7280; margin-bottom:0.3rem;">Valutazione</div>
                    <div style="font-size:0.9rem;">{ev.get('motivation', '')}</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        col_pts1, col_pts2 = st.columns(2)
        with col_pts1:
            if ev.get("correct_points"):
                st.markdown("**✅ Punti corretti**")
                for p in ev["correct_points"]:
                    st.markdown(f"- {p}")
        with col_pts2:
            if ev.get("missing_points"):
                st.markdown("**❌ Punti mancanti**")
                for p in ev["missing_points"]:
                    st.markdown(f"- {p}")

        if ev.get("improvement_after_guidance"):
            st.markdown(f"""
            <div style="padding:0.6rem 0.9rem; background:#1a1f2e; border-radius:8px; margin-top:0.5rem;
                        font-size:0.88rem; color:#93c5fd; border-left:3px solid #3b82f6;">
                📈 <em>{ev['improvement_after_guidance']}</em>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<div style='height:0.75rem'></div>", unsafe_allow_html=True)

        with st.expander("⚖️ Vuoi contestare il voto?", expanded=False):
            contest_text = st.text_area("La tua argomentazione", key="contest_input", height=100,
                                         placeholder="Spiega perché ritieni che il voto non sia corretto...")
            if st.button("Invia contestazione", key="btn_contest"):
                if not contest_text.strip():
                    st.warning("Scrivi un'argomentazione per contestare.")
                else:
                    with st.spinner("Rivalutazione in corso..."):
                        cr = st.session_state.tutor.submit_contestation(contest_text)
                    st.session_state["_contest_result"] = cr
                    st.session_state.tutor_state = "contested"
                    st.rerun()

        col_next, _ = st.columns([1, 3])
        with col_next:
            if st.button("Prossima domanda →", type="primary", key="btn_next_eval"):
                _close_and_advance(engine, current_q, score, sess)

    # ── Dopo contestazione ─────────────────────────────────────────────────
    elif state == "contested":
        cr          = st.session_state.get("_contest_result", {})
        final_score = cr.get("final_score", 0)
        delta       = cr.get("score_delta", 0)
        assessment  = cr.get("contestation_assessment", "non_valido")
        color_map   = {"valido": "#10b981", "parzialmente_valido": "#f59e0b", "non_valido": "#f43f5e"}
        color       = color_map.get(assessment, "#6b7280")
        score_color = "#10b981" if final_score >= 8 else ("#f59e0b" if final_score >= 6 else "#f43f5e")
        delta_text  = f"+{delta} punto/i" if delta > 0 else "voto invariato"

        st.markdown(f"""
        <div class="sc-card" style="border-left:3px solid {color};">
            <div style="font-size:0.78rem; color:#6b7280; margin-bottom:0.5rem; text-transform:uppercase; letter-spacing:0.05em;">
                ⚖️ Contestazione: <span style="color:{color}; font-weight:700;">{assessment.replace('_', ' ')}</span>
                &nbsp;&mdash;&nbsp; {delta_text}
            </div>
            <div style="font-size:2rem; font-family:'Syne',sans-serif; font-weight:800; color:{score_color};">
                {final_score}/10
            </div>
            <p style="margin-top:0.5rem; font-size:0.9rem; color:#d1d5db;">
                {cr.get('response_to_student', '')}
            </p>
        </div>
        """, unsafe_allow_html=True)

        col_next, _ = st.columns([1, 3])
        with col_next:
            if st.button("Prossima domanda →", type="primary", key="btn_next_contest"):
                _close_and_advance(engine, current_q, final_score, sess)


# ── Avanza alla prossima domanda ───────────────────────────────────────────

def _close_and_advance(engine: AdaptiveEngine, current_q: dict, final_score: int, sess: dict):
    st.session_state.tutor.close()
    engine.record_answer(
        question_id=current_q["id"],
        topic=current_q.get("topic_hint", "generale"),
        score=final_score,
    )

    # Serializza in formato piatto compatibile con history.py
    log_entry = _attempt_to_log_entry(st.session_state.tutor, final_score)

    sess["remaining"] = [q for q in sess["remaining"] if q["id"] != current_q["id"]]
    sess["attempts"].append(log_entry)
    sess["scores"].append(final_score)
    st.session_state.current_session = sess

    st.session_state.tutor       = None
    st.session_state.tutor_state = "idle"
    st.session_state.pop("_current_q", None)
    st.session_state.pop("_guide_result", None)
    st.session_state.pop("_eval_result", None)
    st.session_state.pop("_contest_result", None)

    if not sess["remaining"]:
        _save_session(sess["id"], sess["attempts"], engine, st.session_state.current_exam)

    st.rerun()


# ── FASE 3: Sessione completata ────────────────────────────────────────────

def _render_session_complete():
    sess   = st.session_state.current_session
    engine = st.session_state.adaptive_engine
    scores = sess["scores"]
    avg    = round(sum(scores) / len(scores), 1) if scores else 0

    if avg >= 8:
        emoji, label, color = "🏆", "Ottimo!", "#10b981"
    elif avg >= 6:
        emoji, label, color = "👍", "Sufficiente", "#f59e0b"
    else:
        emoji, label, color = "📚", "Da rivedere", "#f43f5e"

    st.markdown(f"""
    <div style="text-align:center; padding:2rem 0 1.5rem;">
        <div style="font-size:3.5rem; margin-bottom:0.5rem;">{emoji}</div>
        <h2 style="font-family:'Syne',sans-serif; font-size:2rem; margin-bottom:0.25rem;">{label}</h2>
        <div style="font-size:3rem; font-weight:800; color:{color}; font-family:'Syne',sans-serif;">
            {avg}/10
        </div>
        <p style="color:#6b7280; margin-top:0.5rem;">
            {len(scores)} domande completate · sessione #{sess['id']}
        </p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### Riepilogo domande")
    questions = sess["questions"]
    q_map     = {q["id"]: q for q in questions}

    for i, (attempt, score) in enumerate(zip(sess["attempts"], scores), 1):
        q = q_map.get(attempt.get("question_id"), {})
        text = q.get("text", "")
        short = text[:80] + ("…" if len(text) > 80 else "")
        st.markdown(f"""
        <div class="sc-card" style="padding:0.75rem 1rem;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div style="flex:1;">
                    <span style="color:#6b7280; font-size:0.78rem;">Q{i}</span>
                    <span style="margin-left:0.5rem; font-size:0.9rem;">{short}</span>
                </div>
                <div style="margin-left:1rem;">{_score_badge(score)}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    report_path = None
    db = SessionLocal()
    try:
        db_sess = db.query(DbSession).filter(DbSession.id == sess["id"]).first()
        if db_sess:
            report_path = db_sess.report_path
    finally:
        db.close()

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)

    with col1:
        if report_path and Path(report_path).exists():
            with open(report_path, "rb") as f:
                st.download_button(
                    "📥 Scarica report PDF",
                    data=f,
                    file_name=f"report_{sess['id']}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    type="primary",
                )
        else:
            st.info("Report PDF in elaborazione...")

    with col2:
        if st.button("📋 Vai allo storico", use_container_width=True):
            st.session_state.current_page = "history"
            st.rerun()

    with col3:
        if st.button("🔄 Nuova sessione", use_container_width=True):
            st.session_state.quiz_result     = None
            st.session_state.adaptive_engine = None
            st.session_state.tutor           = None
            st.session_state.tutor_state     = "idle"
            st.session_state.current_session = None
            st.rerun()


# ── Entry point ────────────────────────────────────────────────────────────

def render():
    _require_auth()
    _require_exam()
    _navbar()

    if st.session_state.current_session is None:
        _render_quiz_generation()
    elif not st.session_state.current_session.get("remaining") and st.session_state.tutor_state in ("idle", "closed"):
        _render_session_complete()
    else:
        _render_active_session()