"""
app/pages/exam.py — Pagina dettagli esame
Mostra azioni: Avvia sessione, Aggiungi fonti, Crea appunti, Storico
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.ui import brand, page_heading, section, source_row, agent_status

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
        st.session_state.current_page = "upload"
        st.rerun()

    student_id = st.session_state.student_id
    nav, back = st.columns([4, 1], vertical_alignment="center")
    with nav:
        brand("Spazio di studio")
    with back:
        if st.button("Esami", icon=":material/arrow_back:", use_container_width=True):
            st.session_state.current_page = "upload"
            st.rerun()
    st.html('<hr class="sc-divider">')

    db = SessionLocal()
    try:
        materials = db.query(Material).filter(Material.exam_id == exam['id']).all()
    finally:
        db.close()

    page_heading(exam['name'], "Le tue fonti, un percorso di studio. Scegli come iniziare.", "SPAZIO DI STUDIO")
    sources, workspace = st.columns([1, 1.8], gap="large")

    with sources:
        section("Fonti", f"{len(materials)} documenti · disponibili per questo esame")
        _render_upload(exam, student_id)
        if materials:
            rows = []
            prefix = f"s{student_id}_e{exam['id']}_"
            for material in materials:
                name = material.filename.removeprefix(prefix)
                rows.append(source_row(name, material.pages_count or 0, bool(material.chunks_count)))
            with st.container(height=420, border=False):
                st.html(''.join(rows))
        else:
            st.info("Carica il primo PDF: il tutor userà il suo contenuto per domande e appunti.")

    with workspace:
        section("Studia con il tutor", "Domande, ragionamento e feedback basati sui tuoi materiali.")
        with st.container(border=True):
            section("Sessione guidata", "Metti alla prova ciò che sai. Il tutor ti aiuta a ragionare e valuta le tue risposte.")
            if st.button("▶ Avvia sessione", type="primary", use_container_width=True, key=f"exam_start_{exam['id']}"):
                _close_orphan_sessions(exam['id'])
                st.session_state.current_exam = {"id": exam['id'], "name": exam['name']}
                st.session_state.current_page = "session"
                st.session_state.quiz_result = None
                st.session_state.adaptive_engine = None
                st.session_state.tutor = None
                st.session_state.current_q_idx = 0
                st.session_state.tutor_state = "idle"
                st.session_state.current_session = None
                st.rerun()
        tutor, notes = st.columns(2, gap="medium")
        with tutor:
            section("Chiarisci un dubbio", "Approfondisci un concetto con una conversazione socratica.")
            if st.button("Chiedi al tutor", icon=":material/chat_bubble_outline:", use_container_width=True, key=f"exam_chat_{exam['id']}"):
                st.session_state.chat_messages = []
                st.session_state.chat_tutor = None
                st.session_state.chat_stage = "idle"
                st.session_state.current_page = "chat"
                st.rerun()
        with notes:
            section("Prepara il ripasso", "Raccogli i concetti principali delle fonti in un PDF.")
            _render_notes(exam, student_id, materials)
        st.divider()
        section("Il tuo percorso", "Rivedi risposte, valutazioni e report delle sessioni precedenti.")
        if st.button("Storico sessioni", icon=":material/history:", key=f"exam_history_{exam['id']}"):
            st.session_state.current_page = "history"
            st.rerun()
        agent_status("Fonti dell'esame", "Il tutor usa i materiali indicizzati di questo spazio")


def _render_upload(exam, student_id):
    # Usa un contatore per cambiare la chiave del file_uploader dopo il caricamento
    # così il widget viene ricreato e non mantiene i vecchi file.
    if "upload_counter" not in st.session_state:
        st.session_state.upload_counter = 0

    upload_key = f"exam_add_pdf_{exam['id']}_{st.session_state.upload_counter}"
    uploaded = st.file_uploader(
        "Aggiungi PDF",
        type="pdf",
        key=upload_key,
        accept_multiple_files=True,
        label_visibility="collapsed"
    )

    if uploaded:
        files: Iterable = uploaded if isinstance(uploaded, list) else [uploaded]
        upload_dir = Path(__file__).parent.parent.parent / "data" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        success_files = []
        for file_obj in files:
            try:
                pdf_path = upload_dir / f"s{student_id}_e{exam['id']}_{file_obj.name}"
                pdf_path.write_bytes(file_obj.read())
            except Exception as e:
                st.error(f"Errore salvataggio file {file_obj.name}: {e}")
                continue

            with st.spinner(f"Indicizzazione {file_obj.name} in corso..."):
                try:
                    stats = ingest_pdf(str(pdf_path), student_id, exam['id'])
                    # Registra il materiale nel DB
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
                    success_files.append(file_obj.name)
                except Exception as e:
                    st.error(f"Errore indicizzazione {file_obj.name}: {e}")

        if success_files:
            st.success(f"✅ {len(success_files)} file caricati con successo: {', '.join(success_files)}")
            # Cambia la chiave per il prossimo upload
            st.session_state.upload_counter += 1
            # Ricarica la pagina per mostrare i materiali aggiornati
            st.rerun()



def _render_notes(exam, student_id, materials):
    if st.button("Crea appunti PDF", icon=":material/description:", use_container_width=True, key=f"exam_notes_{exam['id']}"):
        try:
            from backend.agents.notes_generator import generate_notes_pdf_from_materials
        except ImportError:
            st.error("Modulo per generare appunti non disponibile.")
            return

        with st.spinner(f"Generazione PDF appunti per «{exam['name']}»..."):
            try:
                st.session_state[f"notes_pdf_file_{exam['id']}"] = generate_notes_pdf_from_materials(
                    student_id=student_id,
                    exam_id=exam['id'],
                    materials=materials,
                    exam_name_fallback=exam['name']
                )
                st.session_state[f"notes_pdf_name_{exam['id']}"] = f"appunti_{exam['name'].replace(' ', '_')}.pdf"
            except Exception as e:
                st.error(f"Errore generazione appunti: {e}")

    pdf_bytes = st.session_state.get(f"notes_pdf_file_{exam['id']}")
    pdf_name = st.session_state.get(f"notes_pdf_name_{exam['id']}")
    if pdf_bytes and pdf_name:
        st.download_button(
            "Scarica appunti PDF",
            icon=":material/download:",
            data=pdf_bytes,
            file_name=pdf_name,
            mime="application/pdf",
            use_container_width=True,
            key=f"download_notes_{exam['id']}",
        )
