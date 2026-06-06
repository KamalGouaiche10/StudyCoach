"""
pages/session.py — Sessione attiva di studio socratico
Loop: genera quiz → per ogni domanda → risposta1 → guida → risposta2 → valutazione → (contestazione) → prossima
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.agents.adaptive_engine import AdaptiveEngine # pylint: disable=wrong-import-position
from backend.agents.quiz_generator import generate_quiz # pylint: disable=wrong-import-position
from backend.agents.report_generator import save_report # pylint: disable=wrong-import-position
from backend.agents.socratic_tutor import QuestionAttempt, SocraticTutor # pylint: disable=wrong-import-position
from backend.db.models import SessionLocal, Session as DbSession # pylint: disable=wrong-import-position


# ── Guards ─────────────────────────────────────────────────────────────────

def _require_auth() -> None:
    if not st.session_state.get("authenticated"):
        st.session_state.current_page = "login"
        st.rerun()


def _require_exam() -> None:
    if not st.session_state.get("current_exam"):
        st.session_state.current_page = "upload"
        st.rerun()


# ── Serializzazione attempt ────────────────────────────────────────────────

def _attempt_to_log_entry(attempt: QuestionAttempt, final_score: int) -> dict:
    """Converte un QuestionAttempt nel formato piatto atteso da history.py."""
    entry: dict = {
        "question_id":       attempt.question_id,
        "question_text":     attempt.question_text,
        "difficulty":        attempt.difficulty,
        "topic_hint":        attempt.topic_hint,
        "student_answer_1":  attempt.student_answer_1,
        "guiding_question":  attempt.guiding_question,
        "positive_feedback": attempt.positive_feedback,
        "focus_area":        attempt.focus_area,
        "student_answer_2":  attempt.student_answer_2,
        "final_score":       final_score,
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
            "final_score":             attempt.contestation_result.final_score,
            "score_changed":           attempt.contestation_result.score_changed,
            "score_delta":             attempt.contestation_result.score_delta,
            "contestation_assessment": attempt.contestation_result.contestation_assessment,
            "final_motivation":        attempt.contestation_result.final_motivation,
            "response_to_student":     attempt.contestation_result.response_to_student,
        }
    else:
        entry["contestation_result"] = None

    return entry


# ── Navbar ─────────────────────────────────────────────────────────────────

def _navbar() -> None:
    exam: dict = st.session_state.current_exam
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
            # FIX — se c'è una sessione parzialmente completata,
            # chiude la sessione nel DB (ended_at=now, qa_log parziale)
            # così non appare come "Non completata" senza dati in history.
            sess = st.session_state.get("current_session")
            if sess and sess.get("id"):
                _mark_session_interrupted(sess)
            st.session_state.current_page = "upload"
            st.session_state.current_exam = None
            st.rerun()
    st.markdown("<hr style='border-color:#252a36; margin:0.5rem 0 1rem'>", unsafe_allow_html=True)


def _mark_session_interrupted(sess: dict) -> None:
    """
    FIX — Marca una sessione interrotta (uscita prematura) nel DB:
    - imposta ended_at = now
    - salva il qa_log parziale (le domande già risposte)
    - NON genera report né imposta score_total (rimane NULL)
    Così in history la sessione mostra "Non completata" con i Q&A già fatti,
    invece di apparire completamente vuota.
    """
    session_id = sess.get("id")
    if not session_id:
        return
    attempts = sess.get("attempts", [])
    db = SessionLocal()
    try:
        db_sess = db.query(DbSession).filter(DbSession.id == session_id).first()
        if db_sess and db_sess.ended_at is None:
            db_sess.ended_at = datetime.now(timezone.utc)
            if attempts:
                db_sess.qa_log = json.dumps(attempts, ensure_ascii=False)
            db.commit()
    except Exception as e: # pylint: disable=broad-exception-caught
        db.rollback()
        print(f"[session.py] Errore _mark_session_interrupted: {e}")
    finally:
        db.close()


# ── Barra progresso ────────────────────────────────────────────────────────

def _progress_bar(current: int, total: int, scores: list) -> None:
    pct: int = int(current / total * 100) if total else 0
    avg: float = round(sum(scores) / len(scores), 1) if scores else 0.0
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        st.progress(pct)
    with col2:
        st.markdown(
            f"<div style='text-align:center; font-size:0.85rem; color:#6b7280;'>"
            f"{current}/{total} domande</div>",
            unsafe_allow_html=True,
        )
    with col3:
        css = "score-high" if avg >= 8 else ("score-mid" if avg >= 6 else "score-low")
        st.markdown(
            f"<div class='{css}' style='text-align:center; font-size:0.85rem;'>"
            f"Media: {avg if scores else '—'}</div>",
            unsafe_allow_html=True,
        )


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
        return int(sess.id)
    finally:
        db.close()


def _save_session(
    session_id: int,
    attempts: list,
    engine: AdaptiveEngine,
    exam: dict,
) -> Optional[str]:
    """
    Salva la sessione completata nel DB e genera report PDF + MD.
    Restituisce il path assoluto del PDF, o None in caso di errore.

    FIX: controlla che la sessione non sia già stata salvata (ended_at
    già impostato) per evitare doppi salvataggi in caso di rerun multipli.
    """
    db = SessionLocal()
    try:
        sess = db.query(DbSession).filter(DbSession.id == session_id).first()
        if not sess:
            st.error(f"Sessione {session_id} non trovata nel DB.")
            return None

        # Se sessione già chiusa e con report valido, evita doppi salvataggi.
        if sess.ended_at is not None and sess.score_total is not None and sess.report_path:
            existing_pdf = Path(str(sess.report_path))
            if existing_pdf.exists():
                st.session_state["_last_report_pdf"] = str(existing_pdf)
                return str(existing_pdf)

        report = engine.generate_session_report()
        if sess.ended_at is None:
            sess.ended_at = datetime.now(timezone.utc)
        if sess.score_total is None:
            sess.score_total = float(report["overall_avg"])
        sess.qa_log      = json.dumps(attempts, ensure_ascii=False)

        paths = save_report(report, session_id, str(exam.get("name", "Esame")))
        pdf_path = str(paths.get("pdf") or "")

        if pdf_path and Path(pdf_path).exists():
            sess.report_path = pdf_path
            st.session_state["_last_report_pdf"] = pdf_path
        else:
            sess.report_path = None
            st.session_state.pop("_last_report_pdf", None)
        db.commit()
        return str(sess.report_path) if sess.report_path else None

    except Exception as e: # pylint: disable=broad-exception-caught
        db.rollback()
        import traceback
        st.error(f"Errore salvataggio sessione: {type(e).__name__}: {e}")
        st.code(traceback.format_exc())
        return None
    finally:
        db.close()


# ── FASE 1: Generazione quiz ───────────────────────────────────────────────

def _render_quiz_generation() -> None:
    exam: dict = st.session_state.current_exam

    st.markdown("""
    <div style="text-align:center; padding:2.5rem 0;">
        <div style="font-size:2.5rem; margin-bottom:0.75rem;">📝</div>
        <h2 style="font-family:'Syne',sans-serif; margin-bottom:0.5rem;">Pronto per studiare?</h2>
        <p style="color:#6b7280; max-width:420px; margin:0 auto;">
            Generero domande a risposta aperta basate sul materiale che hai caricato,
            poi ti guidero con il metodo socratico.
        </p>
    </div>
    """, unsafe_allow_html=True)

    _l, col_c, _r = st.columns([1, 2, 1])
    with col_c:
        n_q: int = st.slider("Numero di domande", min_value=3, max_value=10, value=5, key="n_questions_slider")
        st.markdown("<div style='height:0.75rem'></div>", unsafe_allow_html=True)

        if st.button("🚀 Genera domande", type="primary", use_container_width=True):
            with st.spinner("Recupero materiale e genero le domande..."):
                try:
                    quiz = generate_quiz(
                        student_id=int(st.session_state.student_id),
                        exam_id=int(exam["id"]),
                        n_questions=n_q,
                        source_name=str(exam["name"]),
                    )
                    engine     = AdaptiveEngine(
                        student_id=int(st.session_state.student_id),
                        exam_id=int(exam["id"]),
                    )
                    session_id = _create_db_session(int(exam["id"]))

                    questions_dicts = [
                        {
                            "id":         q.id,
                            "text":       q.text,
                            "difficulty": q.difficulty,
                            "topic_hint": q.topic_hint,
                        }
                        for q in quiz.questions
                    ]

                    st.session_state.quiz_result     = quiz
                    st.session_state.adaptive_engine = engine
                    st.session_state.current_session = {
                        "id":        session_id,
                        "questions": questions_dicts,
                        "remaining": questions_dicts.copy(),
                        "attempts":  [],
                        "scores":    [],
                    }
                    st.session_state.tutor         = None
                    st.session_state.tutor_state   = "idle"
                    st.session_state.current_q_idx = 0
                    st.session_state.pop("_last_report_pdf", None)
                    st.rerun()

                except ValueError as e:
                    st.error(f"⚠️ {e}")
                    st.info("Assicurati di aver caricato il PDF dell'esame prima di avviare la sessione.")
                except Exception as e: # pylint: disable=broad-exception-caught
                    st.error(f"Errore inatteso: {e}")


# ── FASE 2: Loop socratico ─────────────────────────────────────────────────

def _render_active_session() -> None:
    sess:   dict           = st.session_state.current_session
    engine: AdaptiveEngine = st.session_state.adaptive_engine
    exam:   dict           = st.session_state.current_exam
    state:  str            = str(st.session_state.tutor_state)

    total_q: int  = len(sess["questions"])
    done_q:  int  = len(sess["attempts"])
    scores:  list = sess["scores"]

    _progress_bar(done_q, total_q, scores)

    if not sess["remaining"] and state in ("idle", "closed"):
        _render_session_complete()
        return

    if state == "idle":
        next_q: Optional[dict] = engine.pick_next_question(sess["remaining"])
        if not next_q:
            _render_session_complete()
            return

        new_tutor = SocraticTutor(
            student_id=int(st.session_state.student_id),
            exam_id=int(exam["id"]),
        )
        new_tutor.start(next_q)
        st.session_state.tutor         = new_tutor
        st.session_state.tutor_state   = "answer1"
        st.session_state["_current_q"] = next_q
        st.rerun()

    current_q: dict = st.session_state.get("_current_q") or {}
    q_num: int      = done_q + 1

    st.markdown(f"""
    <div class="sc-card" style="border-left:3px solid #6c63ff; margin-bottom:1.25rem;">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:0.5rem;">
            <span style="color:#6b7280; font-size:0.82rem; font-weight:600; letter-spacing:0.05em; text-transform:uppercase;">
                Domanda {q_num} di {total_q}
            </span>
            {_diff_badge(str(current_q.get('difficulty', 'intermedia')))}
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
        ans1: str = str(st.text_area(
            "Rispondi", key="input_ans1", height=130,
            placeholder="Scrivi qui la tua risposta...", label_visibility="collapsed",
        ) or "")
        if st.button("Invia risposta →", type="primary", key="btn_ans1"):
            if not ans1.strip():
                st.warning("Scrivi una risposta prima di procedere.")
            else:
                tutor: SocraticTutor = st.session_state.tutor
                with st.spinner("Il tutor elabora la tua risposta..."):
                    result = tutor.submit_answer_1(ans1)
                st.session_state["_guide_result"] = result
                st.session_state.tutor_state = "answer2"
                st.rerun()

    # ── Seconda risposta ───────────────────────────────────────────────────
    elif state == "answer2":
        guide: dict          = st.session_state.get("_guide_result") or {}
        tutor: SocraticTutor = st.session_state.tutor
        attempt: QuestionAttempt = tutor.attempt  # type: ignore[assignment]
        ans1_text: str = str(attempt.student_answer_1)

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

        focus_html: str = (
            f'<div style="margin-top:0.5rem; font-size:0.78rem; color:#6b7280;">Focus: {guide["focus_area"]}</div>'
            if guide.get("focus_area") else ""
        )
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
        ans2: str = str(st.text_area(
            "Seconda risposta", key="input_ans2", height=130,
            placeholder="Integra e approfondisci...", label_visibility="collapsed",
        ) or "")
        if st.button("Invia e valuta →", type="primary", key="btn_ans2"):
            if not ans2.strip():
                st.warning("Scrivi la tua risposta prima di procedere.")
            else:
                with st.spinner("Valutazione in corso..."):
                    eval_result = tutor.submit_answer_2(ans2)
                st.session_state["_eval_result"] = eval_result
                st.session_state.tutor_state = "evaluated"
                st.rerun()

    # ── Valutazione ────────────────────────────────────────────────────────
    elif state == "evaluated":
        ev:     dict          = st.session_state.get("_eval_result") or {}
        score:  int           = int(ev.get("score", 0))
        guide:  dict          = st.session_state.get("_guide_result") or {}
        tutor:  SocraticTutor = st.session_state.tutor
        attempt: QuestionAttempt = tutor.attempt  # type: ignore[assignment]
        border: str = "#10b981" if score >= 8 else ("#f59e0b" if score >= 6 else "#f43f5e")

        with st.expander("📜 Risposte date", expanded=False):
            st.markdown(f"**Prima risposta:** {str(attempt.student_answer_1)}")
            st.markdown(f"**Guida socratica:** *{guide.get('guiding_question', '')}*")
            st.markdown(f"**Seconda risposta:** {str(attempt.student_answer_2)}")

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
            contest_text: str = str(st.text_area(
                "La tua argomentazione", key="contest_input", height=100,
                placeholder="Spiega perche ritieni che il voto non sia corretto...",
            ) or "")
            if st.button("Invia contestazione", key="btn_contest"):
                if not contest_text.strip():
                    st.warning("Scrivi un'argomentazione per contestare.")
                else:
                    with st.spinner("Rivalutazione in corso..."):
                        cr = tutor.submit_contestation(contest_text)
                    st.session_state["_contest_result"] = cr
                    st.session_state.tutor_state = "contested"
                    st.rerun()

        col_next, _ = st.columns([1, 3])
        with col_next:
            if st.button("Prossima domanda →", type="primary", key="btn_next_eval"):
                _close_and_advance(engine, current_q, score, sess)

    # ── Dopo contestazione ─────────────────────────────────────────────────
    elif state == "contested":
        cr:          dict = st.session_state.get("_contest_result") or {}
        final_score: int  = int(cr.get("final_score", 0))
        delta:       int  = int(cr.get("score_delta", 0))
        assessment:  str  = str(cr.get("contestation_assessment", "non_valido"))
        color_map = {"valido": "#10b981", "parzialmente_valido": "#f59e0b", "non_valido": "#f43f5e"}
        color:       str  = color_map.get(assessment, "#6b7280")
        score_color: str  = "#10b981" if final_score >= 8 else ("#f59e0b" if final_score >= 6 else "#f43f5e")
        delta_text:  str  = f"+{delta} punto/i" if delta > 0 else "voto invariato"

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

def _close_and_advance(
    engine: AdaptiveEngine,
    current_q: dict,
    final_score: int,
    sess: dict,
) -> None:
    tutor: SocraticTutor     = st.session_state.tutor
    attempt: QuestionAttempt = tutor.attempt  # type: ignore[assignment]
    tutor.close()

    engine.record_answer(
        question_id=int(current_q["id"]),
        topic=str(current_q.get("topic_hint", "generale")),
        score=final_score,
    )

    log_entry = _attempt_to_log_entry(attempt, final_score)

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

    # FIX — salva la sessione appena finisce l'ultima domanda.
    # Il controllo ended_at in _save_session evita doppi salvataggi
    # in caso di rerun successivi di Streamlit.
    if not sess["remaining"]:
        _save_session(
            session_id=int(sess["id"]),
            attempts=sess["attempts"],
            engine=engine,
            exam=st.session_state.current_exam,
        )

    st.rerun()


# ── FASE 3: Sessione completata ────────────────────────────────────────────

def _render_session_complete() -> None:
    sess:   dict  = st.session_state.current_session
    scores: list  = sess["scores"]
    avg:    float = round(sum(scores) / len(scores), 1) if scores else 0.0

    # FIX — tenta il salvataggio anche qui, nel caso _close_and_advance
    # non l'avesse completato (edge case: rerun multipli o sessione
    # arrivata a questa fase senza passare da _close_and_advance).
    engine: Optional[AdaptiveEngine] = st.session_state.get("adaptive_engine")
    if engine and sess.get("id"):
        _save_session(
            session_id=int(sess["id"]),
            attempts=sess["attempts"],
            engine=engine,
            exam=st.session_state.current_exam,
        )

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
    q_map: dict = {q["id"]: q for q in sess["questions"]}

    for i, (attempt_entry, score) in enumerate(zip(sess["attempts"], scores), 1):
        q:     dict = q_map.get(attempt_entry.get("question_id"), {})
        text:  str  = str(q.get("text", ""))
        short: str  = text[:80] + ("…" if len(text) > 80 else "")
        st.markdown(f"""
        <div class="sc-card" style="padding:0.75rem 1rem;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div style="flex:1;">
                    <span style="color:#6b7280; font-size:0.78rem;">Q{i}</span>
                    <span style="margin-left:0.5rem; font-size:0.9rem;">{short}</span>
                </div>
                <div style="margin-left:1rem;">{_score_badge(int(score))}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Legge il path del PDF da session_state (salvato da _save_session)
    report_pdf: str = str(st.session_state.get("_last_report_pdf") or "")

    # Fallback: rilegge dal DB se session_state non ce l'ha
    if not report_pdf:
        db = SessionLocal()
        try:
            db_sess = db.query(DbSession).filter(DbSession.id == int(sess["id"])).first()
            if db_sess and db_sess.report_path:
                report_pdf = str(db_sess.report_path)
        finally:
            db.close()

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)

    with col1:
        pdf_path_obj = Path(report_pdf) if report_pdf else None
        if pdf_path_obj and pdf_path_obj.exists():
            with open(str(pdf_path_obj), "rb") as pdf_file:
                st.download_button(
                    "📥 Scarica report PDF",
                    data=pdf_file,
                    file_name=f"report_{sess['id']}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    type="primary",
                )
        else:
            if "_last_report_pdf" in st.session_state:
                # PDF generation fallì, ma sempre permetti il retry
                if st.button("🔄 Riprova generazione PDF", use_container_width=True, key="retry_pdf"):
                    with st.spinner("Rigenerazione PDF in corso..."):
                        pdf_path = _save_session(
                            session_id=int(sess["id"]),
                            attempts=sess["attempts"],
                            engine=engine,
                            exam=st.session_state.current_exam,
                        )
                        if pdf_path and Path(pdf_path).exists():
                            st.success("✅ PDF generato con successo! Ricarica la pagina.")
                        else:
                            st.error("❌ Impossibile generare il PDF. Verifica i log del server.")
            else:
                st.info("⏳ Report PDF in elaborazione... Ricarica la pagina tra poco.")

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
            st.session_state.pop("_last_report_pdf", None)
            st.rerun()


# ── Entry point ────────────────────────────────────────────────────────────

def render() -> None:
    _require_auth()
    _require_exam()
    _navbar()

    if st.session_state.current_session is None:
        _render_quiz_generation()
    elif (
        not st.session_state.current_session.get("remaining")
        and str(st.session_state.tutor_state) in ("idle", "closed")
    ):
        _render_session_complete()
    else:
        _render_active_session()