"""
pages/upload.py — Gestione esami e upload PDF
"""

import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.db.models import SessionLocal, Exam, Session as DbSession
from backend.agents.ingestor import ingest_pdf, delete_exam_collection


# ── Guards ─────────────────────────────────────────────────────────────────

def _require_auth():
    if not st.session_state.get("authenticated"):
        st.session_state.current_page = "login"
        st.rerun()


# ── Helpers DB ─────────────────────────────────────────────────────────────

def _get_exams(student_id: int) -> list:
    db = SessionLocal()
    try:
        return db.query(Exam).filter(Exam.student_id == student_id).order_by(Exam.created_at.desc()).all()
    finally:
        db.close()


def _create_exam(student_id: int, name: str) -> Exam:
    db = SessionLocal()
    try:
        exam = Exam(student_id=student_id, name=name.strip())
        db.add(exam)
        db.commit()
        db.refresh(exam)
        return exam
    finally:
        db.close()


def _delete_exam(exam_id: int, student_id: int):
    db = SessionLocal()
    try:
        exam = db.query(Exam).filter(Exam.id == exam_id, Exam.student_id == student_id).first()
        if exam:
            db.delete(exam)
            db.commit()
        delete_exam_collection(student_id, exam_id)
    except Exception:
        db.rollback()
    finally:
        db.close()


def _session_count(exam_id: int) -> int:
    db = SessionLocal()
    try:
        return db.query(DbSession).filter(DbSession.exam_id == exam_id).count()
    finally:
        db.close()


def _avg_score(exam_id: int) -> float | None:
    db = SessionLocal()
    try:
        sessions = db.query(DbSession).filter(
            DbSession.exam_id == exam_id,
            DbSession.score_total.isnot(None)
        ).all()
        if not sessions:
            return None
        return round(sum(s.score_total for s in sessions) / len(sessions), 1)
    finally:
        db.close()


# ── Navbar ─────────────────────────────────────────────────────────────────

def _navbar():
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        st.markdown("""
        <span style="font-family:'Syne',sans-serif; font-size:1.3rem; font-weight:800;
              background:linear-gradient(135deg,#6c63ff,#00d4aa);
              -webkit-background-clip:text; -webkit-text-fill-color:transparent;">
            🎓 Study Coach
        </span>
        """, unsafe_allow_html=True)
    with col2:
        if st.button("📋 Storico", use_container_width=True):
            st.session_state.current_page = "history"
            st.session_state.current_exam = None
            st.rerun()
    with col3:
        if st.button("🚪 Esci", use_container_width=True):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()
    st.markdown("<hr style='border-color:#252a36; margin:0.5rem 0 1.5rem'>", unsafe_allow_html=True)


# ── Render ─────────────────────────────────────────────────────────────────

def render():
    _require_auth()
    _navbar()

    student_id = st.session_state.student_id
    username   = st.session_state.username

    st.markdown(f"""
    <h2 style="font-family:'Syne',sans-serif; margin-bottom:0.2rem;">
        Ciao, <span style="color:#6c63ff">{username}</span> 👋
    </h2>
    <p style="color:#6b7280; margin-bottom:1.5rem;">Gestisci i tuoi esami e avvia una sessione di studio.</p>
    """, unsafe_allow_html=True)

    # ── CREA NUOVO ESAME ───────────────────────────────────────────────────
    with st.expander("➕ Crea nuovo esame", expanded=False):
        col_name, col_btn = st.columns([3, 1])
        with col_name:
            exam_name = st.text_input("Nome esame", placeholder="es. Programmazione AI a.a. 2025/26", label_visibility="collapsed")
        with col_btn:
            create_clicked = st.button("Crea", type="primary", use_container_width=True)

        if create_clicked:
            if not exam_name.strip():
                st.error("Inserisci un nome per l'esame.")
            else:
                _create_exam(student_id, exam_name)
                st.success(f"Esame «{exam_name}» creato!")
                st.rerun()

    # ── LISTA ESAMI ────────────────────────────────────────────────────────
    exams = _get_exams(student_id)

    if not exams:
        st.markdown("""
        <div style="text-align:center; padding:4rem; color:#4b5563;">
            <div style="font-size:3rem; margin-bottom:1rem;">📚</div>
            <p>Nessun esame ancora. Creane uno per iniziare!</p>
        </div>
        """, unsafe_allow_html=True)
        return

    st.markdown(f"<p style='color:#6b7280; font-size:0.9rem;'>{len(exams)} esame/i</p>", unsafe_allow_html=True)

    for exam in exams:
        n_sessions = _session_count(exam.id)
        avg        = _avg_score(exam.id)
        avg_str    = f"{avg}/10" if avg is not None else "—"

        with st.container():
            st.markdown(f"""
            <div class="sc-card">
                <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                    <div>
                        <div style="font-family:'Syne',sans-serif; font-weight:700; font-size:1.05rem;">
                            📖 {exam.name}
                        </div>
                        <div style="color:#6b7280; font-size:0.82rem; margin-top:0.3rem;">
                            Creato il {exam.created_at.strftime('%d/%m/%Y') if exam.created_at else '—'}
                            &nbsp;·&nbsp; {n_sessions} sessioni
                            &nbsp;·&nbsp; Media: <strong>{avg_str}</strong>
                        </div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            col_upload, col_start, col_notes, col_hist, col_del = st.columns([2, 1.5, 1.5, 1.5, 1])

            with col_upload:
                uploaded = st.file_uploader(
                    f"PDF esame_{exam.id}",
                    type="pdf",
                    key=f"pdf_{exam.id}",
                    label_visibility="collapsed",
                )
                if uploaded:
                    upload_dir = Path(__file__).parent.parent.parent / "data" / "uploads"
                    upload_dir.mkdir(parents=True, exist_ok=True)
                    pdf_path = upload_dir / f"s{student_id}_e{exam.id}_{uploaded.name}"
                    pdf_path.write_bytes(uploaded.read())
                    with st.spinner("Indicizzazione PDF in corso..."):
                        try:
                            stats = ingest_pdf(str(pdf_path), student_id, exam.id)
                            st.success(f"✅ {stats['chunks']} chunk indicizzati da {stats['pages']} pagine")
                        except Exception as e:
                            st.error(f"Errore indicizzazione: {e}")

            with col_start:
                if st.button("▶ Avvia sessione", key=f"start_{exam.id}", type="primary", use_container_width=True):
                    st.session_state.current_exam  = {"id": exam.id, "name": exam.name}
                    st.session_state.current_page  = "session"
                    st.session_state.quiz_result   = None
                    st.session_state.adaptive_engine = None
                    st.session_state.tutor         = None
                    st.session_state.current_q_idx = 0
                    st.session_state.tutor_state   = "idle"
                    st.session_state.current_session = None
                    st.rerun()

            with col_notes:
                # Bottone per generare appunti sintetici dal materiale RAG
                if st.button("📋 Genera appunti", key=f"notes_{exam.id}", use_container_width=True,
                             help="Genera appunti sintetici dal materiale caricato"):
                    st.session_state[f"show_notes_{exam.id}"] = not st.session_state.get(f"show_notes_{exam.id}", False)
                    if st.session_state[f"show_notes_{exam.id}"]:
                        # Invalida cache per rigenerare
                        st.session_state.pop(f"_notes_cache_exam_{exam.id}", None)
                    st.rerun()

            with col_hist:
                if st.button("📋 Storico", key=f"hist_{exam.id}", use_container_width=True):
                    st.session_state.current_exam  = {"id": exam.id, "name": exam.name}
                    st.session_state.current_page  = "history"
                    st.rerun()

            with col_del:
                if st.button("🗑", key=f"del_{exam.id}", use_container_width=True, help="Elimina esame"):
                    _delete_exam(exam.id, student_id)
                    st.warning(f"Esame «{exam.name}» eliminato.")
                    st.rerun()

            # ── Pannello appunti sintetici da materiale RAG ────────────────
            if st.session_state.get(f"show_notes_{exam.id}", False):
                _render_notes_panel(exam, student_id)

            st.markdown("<div style='height:0.25rem'></div>", unsafe_allow_html=True)


def _render_notes_panel(exam: Exam, student_id: int):
    """Genera e mostra appunti sintetici dal materiale RAG dell'esame."""
    cache_key = f"_notes_cache_exam_{exam.id}"

    if cache_key not in st.session_state:
        try:
            from backend.agents.notes_generator import generate_notes
            with st.spinner(f"Generazione appunti per «{exam.name}»..."):
                notes = generate_notes(
                    student_id=student_id,
                    exam_id=exam.id,
                    topic_query="concetti principali del corso",
                    source_name=exam.name,
                )
            st.session_state[cache_key] = notes
        except ValueError as e:
            st.warning(f"⚠️ {e}")
            return
        except Exception as e:
            st.error(f"Errore generazione appunti: {e}")
            return

    notes = st.session_state.get(cache_key, "")
    if not notes:
        return

    st.markdown(f"""
    <div style="background:#0f1319; border:1px solid #252a36; border-radius:10px;
                padding:1.25rem 1.5rem; margin:0.5rem 0 1rem;">
        <div style="font-family:'Syne',sans-serif; font-weight:700; font-size:0.95rem;
                    color:#00d4aa; margin-bottom:0.75rem;">
            📋 Appunti sintetici — {exam.name}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Usiamo st.markdown nativo per il contenuto Markdown degli appunti
    # (non unsafe_allow_html) così intestazioni e bullet vengono renderizzati correttamente
    st.markdown(notes)

    col_dl, _ = st.columns([1, 3])
    with col_dl:
        st.download_button(
            "📥 Scarica appunti (.md)",
            data=notes.encode("utf-8"),
            file_name=f"appunti_{exam.name.replace(' ', '_')}.md",
            mime="text/markdown",
            key=f"dl_notes_{exam.id}",
            use_container_width=True,
        )