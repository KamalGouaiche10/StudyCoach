"""
pages/upload.py — Gestione esami e upload PDF
"""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.agents.ingestor import delete_exam_collection # pylint: disable=wrong-import-position
from backend.db.models import Exam, Material, SessionLocal, Session as DbSession # pylint: disable=wrong-import-position
from backend.session_cookie import invalidate_token, render_clear_cookie # pylint: disable=wrong-import-position

logger = logging.getLogger(__name__)


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
        exam = Exam(student_id=student_id, name=(name or "").strip())
        db.add(exam)
        db.commit()
        db.refresh(exam)
        return exam
    finally:
        db.close()


def _rename_exam(exam_id: int, student_id: int, new_name: str) -> bool:
    """Rinomina un esame. Restituisce True se aggiornato."""
    db = SessionLocal()
    try:
        exam = db.query(Exam).filter(Exam.id == exam_id, Exam.student_id == student_id).first()
        if exam:
            exam.name = (new_name or "").strip()
            db.commit()
            db.refresh(exam)
            return True
        return False
    except SQLAlchemyError:
        logger.exception("Failed to rename exam id=%s for student_id=%s", exam_id, student_id)
        db.rollback()
        return False
    finally:
        db.close()


def _delete_exam(exam_id: int, student_id: int):
    db = SessionLocal()
    try:
        exam = db.query(Exam).filter(Exam.id == exam_id, Exam.student_id == student_id).first()
        if exam:
            db.delete(exam)
            db.commit()
    except SQLAlchemyError:
        logger.exception("Failed to delete exam id=%s for student_id=%s", exam_id, student_id)
        db.rollback()
    finally:
        db.close()

    # Delete the ChromaDB collection; this can raise ValueError which
    # `delete_exam_collection` already handles, but log unexpected errors.
    try:
        delete_exam_collection(student_id, exam_id)
    except ValueError as e:
        # delete_exam_collection already ignores ValueError when collection
        # does not exist; log for diagnostics.
        logger.debug("delete_exam_collection: %s", e)


def _get_exam_materials(exam_id: int) -> list:
    """Recupera tutti i materiali caricati per un esame."""
    db = SessionLocal()
    try:
        return db.query(Material).filter(Material.exam_id == exam_id).order_by(Material.uploaded_at.desc()).all()
    finally:
        db.close()


def _create_material_record(exam_id: int, filename: str, stored_path: str, chunks_count: int, pages_count: int) -> Material:
    """Registra un nuovo materiale nel database."""
    db = SessionLocal()
    try:
        material = Material(
            exam_id=exam_id,
            filename=filename,
            stored_path=stored_path,
            chunks_count=chunks_count,
            pages_count=pages_count
        )
        db.add(material)
        db.commit()
        db.refresh(material)
        return material
    finally:
        db.close()


def _delete_material(material_id: int, exam_id: int):
    """Elimina un materiale dal database e cancella il file."""
    db = SessionLocal()
    try:
        material = db.query(Material).filter(Material.id == material_id, Material.exam_id == exam_id).first()
        if material:
            try:
                Path(material.stored_path).unlink()
            except FileNotFoundError:
                pass
            db.delete(material)
            db.commit()
    except SQLAlchemyError:
        logger.exception("Failed to delete material id=%s", material_id)
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


def _close_orphan_sessions(exam_id: int) -> int:
    """
    Sessioni 'In corso': chiude tutte le sessioni senza ended_at
    per questo esame prima di avviarne una nuova.
    Le sessioni orfane si creano quando l'utente chiude il browser o
    naviga via senza completare la sessione.
    Ritorna il numero di sessioni chiuse.
    """
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
    except SQLAlchemyError:
        logger.exception("Failed to close orphan sessions for exam_id=%s", exam_id)
        db.rollback()
        return 0
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
            # Logout esplicito: invalida il token lato DB e cancella il
            # cookie lato browser, così il login persistente termina
            # davvero solo qui, e non per un semplice refresh/disconnessione.
            invalidate_token(st.session_state.get("student_id"))
            render_clear_cookie()
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
    # Inizializza lo stato dell'expander se non esiste
    if "create_exam_expanded" not in st.session_state:
        st.session_state.create_exam_expanded = False
    
    # Pulisci il campo se l'esame è stato appena creato
    if st.session_state.get("just_created_exam", False):
        st.session_state.exam_name_input = ""
        st.session_state.just_created_exam = False
    
    with st.expander("➕ Crea nuovo esame", expanded=st.session_state.create_exam_expanded):
        col_name, col_btn = st.columns([3, 1])
        with col_name:
            exam_name = st.text_input("Nome esame", placeholder="es. Programmazione AI a.a. 2025/26", label_visibility="collapsed", key="exam_name_input")
        with col_btn:
            create_clicked = st.button("Crea", type="primary", use_container_width=True)

        if create_clicked:
            exam_name_val = (exam_name or "").strip()
            if not exam_name_val:
                st.error("Inserisci un nome per l'esame.")
            else:
                _create_exam(student_id, exam_name_val)
                st.success(f"Esame «{exam_name_val}» creato!")
                st.session_state.create_exam_expanded = False
                st.session_state.just_created_exam = True
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

    # Rendi la homepage simile alla schermata: riga di card (3 per riga) con nome, data e numero fonti, e un bottone Apri sotto ogni card.
    cols_per_row = 3

    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    # Render tiles 3 per riga
    for i in range(0, len(exams), cols_per_row):
        row = exams[i:i + cols_per_row]
        cols = st.columns(len(row), gap="large")
        for col, exam in zip(cols, row):
            with col:
                materials = _get_exam_materials(exam.id)
                n_sources = len(materials) if materials else 0
                created = exam.created_at.strftime('%d/%m/%Y') if exam.created_at else '—'

                st.markdown(f"""
                <div class="sc-card" style="min-height:7rem; display:flex; flex-direction:column; justify-content:center;">
                    <div style="font-family:'Syne',sans-serif; font-weight:700; font-size:1.05rem;">{exam.name}</div>
                    <div style="color:#6b7280; font-size:0.78rem; margin-top:0.35rem;">{created} · {n_sources} fonti</div>
                </div>
                """, unsafe_allow_html=True)

                # Azioni: Apri | Modifica | Elimina
                col_a, col_b, col_c = st.columns([1.2, 1, 1])
                with col_a:
                    if st.button("Apri", key=f"open_{exam.id}", use_container_width=True):
                        st.session_state.current_exam = {"id": exam.id, "name": exam.name}
                        st.session_state.current_page = "exam"
                        st.rerun()
                with col_b:
                    if st.button("Modifica", key=f"edit_{exam.id}", use_container_width=True):
                        st.session_state[f"editing_exam_{exam.id}"] = True
                        st.rerun()
                with col_c:
                    if st.button("Elimina", key=f"del_{exam.id}_tile", use_container_width=True):
                        _delete_exam(exam.id, student_id)
                        st.warning(f"Esame «{exam.name}» eliminato.")
                        st.rerun()

                # Inline editor per rinominare l'esame
                if st.session_state.get(f"editing_exam_{exam.id}", False):
                    new_name = st.text_input("Nuovo nome esame", value=exam.name, key=f"edit_name_{exam.id}")
                    c1, c2 = st.columns([1, 1])
                    with c1:
                        if st.button("Salva", key=f"save_edit_{exam.id}", use_container_width=True):
                            ok = _rename_exam(exam.id, student_id, new_name)
                            st.session_state[f"editing_exam_{exam.id}"] = False
                            if ok:
                                st.success("Nome esame aggiornato.")
                            else:
                                st.error("Impossibile aggiornare il nome esame.")
                            st.rerun()
                    with c2:
                        if st.button("Annulla", key=f"cancel_edit_{exam.id}", use_container_width=True):
                            st.session_state[f"editing_exam_{exam.id}"] = False
                            st.rerun()

                st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    st.markdown("<div style='height:0.25rem'></div>", unsafe_allow_html=True)


def _render_notes_panel(exam: Exam, student_id: int):
    """Genera e mostra appunti sintetici dal materiale RAG dell'esame."""
    cache_key = f"_notes_cache_exam_{exam.id}"

    if cache_key not in st.session_state:
        try:
            from backend.agents.notes_generator import generate_notes
        except ImportError as e:
            logger.exception("notes_generator import failed: %s", e)
            st.error("Modulo per generare appunti non disponibile.")
            return

        try:
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
        except Exception as e: # pylint: disable=broad-exception-caught
            logger.exception("generate_notes failed for exam %s: %s", exam.id, e)
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