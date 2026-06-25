"""
app/pages/exam.py — Pagina dettagli esame
Mostra azioni: Avvia sessione, Aggiungi fonti, Crea appunti, Storico
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import streamlit as st

from backend.agents.ingestor import ingest_pdf
from backend.db.models import SessionLocal, Session as DbSession, Material


def _close_orphan_sessions(exam_id: int) -> int:
    db = SessionLocal()
    try:
        orphans = db.query(DbSession).filter(
            DbSession.exam_id == exam_id,
            DbSession.ended_at.is_(None),
        ).all()
        now = datetime.now(timezone.utc)
        for s in orphans:
            s.ended_at = now
        db.commit()
        return len(orphans)
    except Exception:
        db.rollback()
        return 0
    finally:
        db.close()


def render():
    if not st.session_state.get("authenticated"):
        st.session_state.current_page = "login"
        st.rerun()

    exam = st.session_state.get("current_exam")
    if not exam:
        st.error("Nessun esame selezionato.")
        return

    student_id = st.session_state.student_id

    st.markdown(f"""
    <h2 style=\"font-family:'Syne',sans-serif; margin-bottom:0.2rem;\">📘 {exam['name']}</h2>
    <p style=\"color:#6b7280; margin-bottom:1.5rem;\">Azioni disponibili per l'esame.</p>
    """, unsafe_allow_html=True)

    col_start, col_sources, col_notes, col_history = st.columns([1.2, 1.6, 1.6, 1])

    with col_start:
        if st.button("▶ Avvia sessione", use_container_width=True, key=f"exam_start_{exam['id']}"):
            closed = _close_orphan_sessions(exam['id'])
            if closed:
                print(f"[exam.py] Chiuse {closed} sessioni orfane per exam_id={exam['id']}")

            st.session_state.current_exam = {"id": exam['id'], "name": exam['name']}
            st.session_state.current_page = "session"
            st.session_state.quiz_result = None
            st.session_state.adaptive_engine = None
            st.session_state.tutor = None
            st.session_state.current_q_idx = 0
            st.session_state.tutor_state = "idle"
            st.session_state.current_session = None
            st.rerun()

    with col_sources:
        st.markdown("**Aggiungi fonti (PDF)**")
        # Permetti più file per esame
        uploaded = st.file_uploader("Aggiungi PDF", type="pdf", key=f"exam_add_pdf_{exam['id']}", accept_multiple_files=True)
        if uploaded:
            files: Iterable = uploaded if isinstance(uploaded, list) else [uploaded]
            upload_dir = Path(__file__).parent.parent.parent / "data" / "uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            for file_obj in files:
                try:
                    pdf_path = upload_dir / f"s{student_id}_e{exam['id']}_{file_obj.name}"
                    pdf_path.write_bytes(file_obj.read())
                except Exception as e:
                    st.error("Errore salvataggio file: %s" % e)
                    continue

                with st.spinner("Indicizzazione PDF in corso..."):
                    try:
                        stats = ingest_pdf(str(pdf_path), student_id, exam['id'])
                        # Registra il materiale nel DB (pages_count, chunks_count)
                        db = SessionLocal()
                        try:
                            mat = Material(
                                exam_id=exam['id'],
                                filename=pdf_path.name,
                                stored_path=str(pdf_path),
                                chunks_count=stats.get('chunks', 0),
                                pages_count=stats.get('pages', 0),
                            )
                            db.add(mat)
                            db.commit()
                        finally:
                            db.close()
                        st.success(f"✅ {stats['chunks']} chunk indicizzati da {stats['pages']} pagine per {file_obj.name}")
                    except Exception as e:
                        st.error(f"Errore indicizzazione: {e}")

    with col_notes:
        if st.button("📋 Crea appunti (.pdf)", use_container_width=True, key=f"exam_notes_{exam['id']}"):
            try:
                from backend.agents.notes_generator import generate_notes_pdf_from_materials
            except ImportError:
                st.error("Modulo per generare appunti non disponibile.")
                return

            # Calcola il numero di fonti caricate per questo esame
            db = SessionLocal()
            try:
                materials = db.query(Material).filter(Material.exam_id == exam['id']).all()
            finally:
                db.close()

            with st.spinner(f"Generazione PDF appunti per «{exam['name']}»..."):
                try:
                    st.session_state[f"notes_pdf_file_{exam['id']}"] = generate_notes_pdf_from_materials(
                        student_id=student_id,
                        exam_id=exam['id'],
                        materials=materials,
                    )
                    st.session_state[f"notes_pdf_name_{exam['id']}"] = f"appunti_{exam['name'].replace(' ', '_')}.pdf"
                except Exception as e:
                    st.error(f"Errore generazione appunti: {e}")

        pdf_bytes = st.session_state.get(f"notes_pdf_file_{exam['id']}")
        pdf_name = st.session_state.get(f"notes_pdf_name_{exam['id']}")
        if pdf_bytes and pdf_name:
            st.download_button(
                "📥 Scarica appunti (.pdf)",
                data=pdf_bytes,
                file_name=pdf_name,
                mime="application/pdf",
                use_container_width=True,
                key=f"download_notes_{exam['id']}",
            )

    with col_history:
        if st.button("📋 Storico", use_container_width=True, key=f"exam_history_{exam['id']}"):
            st.session_state.current_page = "history"
            st.rerun()

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

    if st.button("🔙 Indietro", use_container_width=True):
        st.session_state.current_page = "upload"
        st.rerun()
