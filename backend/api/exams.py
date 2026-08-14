
from pathlib import Path
from sqlalchemy.exc import SQLAlchemyError
from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from backend.agents.ingestor import delete_exam_collection, ingest_pdf
from backend.db.models import Exam, Session as DbSession, SessionLocal
from backend.models.schemas import (
    ExamCreate,
    ExamListResponse,
    ExamResponse,
    IngestResponse,
)

router = APIRouter(prefix="/exams", tags=["exams"])

UPLOAD_DIR = Path("./data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers DB
# ---------------------------------------------------------------------------

def _get_exam_or_404(exam_id: int, student_id: int) -> Exam:
    db = SessionLocal()
    try:
        exam = (
            db.query(Exam)
            .filter(Exam.id == exam_id, Exam.student_id == student_id)
            .first()
        )
        if not exam:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Esame {exam_id} non trovato per lo studente {student_id}.",
            )
        return exam
    finally:
        db.close()


def _enrich_exam(exam: Exam, db) -> ExamResponse:
    """Aggiunge n_sessions e avg_score all'ExamResponse."""
    sessions = (
        db.query(DbSession)
        .filter(DbSession.exam_id == exam.id)
        .all()
    )
    n_sessions = len(sessions)
    scored = [s.score_total for s in sessions if s.score_total is not None]
    avg = round(sum(scored) / len(scored), 1) if scored else None

    return ExamResponse(
        id=exam.id,
        student_id=exam.student_id,
        name=exam.name,
        created_at=exam.created_at,
        n_sessions=n_sessions,
        avg_score=avg,
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=ExamListResponse,
    summary="Lista esami dello studente",
)
def list_exams(student_id: int = Query(..., description="ID dello studente")) -> ExamListResponse:
    """Restituisce tutti gli esami creati dallo studente, con statistiche aggregate."""
    db = SessionLocal()
    try:
        exams = (
            db.query(Exam)
            .filter(Exam.student_id == student_id)
            .order_by(Exam.created_at.desc())
            .all()
        )
        items = [_enrich_exam(e, db) for e in exams]
        return ExamListResponse(exams=items, total=len(items))
    finally:
        db.close()


@router.post(
    "",
    response_model=ExamResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crea un nuovo esame",
)
def create_exam(
    payload: ExamCreate,
    student_id: int = Query(..., description="ID dello studente"),
) -> ExamResponse:
    """Crea un nuovo esame vuoto. Il PDF viene caricato separatamente via /ingest."""
    db = SessionLocal()
    try:
        exam = Exam(student_id=student_id, name=payload.name)
        db.add(exam)
        db.commit()
        db.refresh(exam)
        return ExamResponse(
            id=exam.id,
            student_id=exam.student_id,
            name=exam.name,
            created_at=exam.created_at,
            n_sessions=0,
            avg_score=None,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Errore creazione esame: {exc}",
        ) from exc
    finally:
        db.close()


@router.delete(
    "/{exam_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Elimina un esame",
)
def delete_exam(
    exam_id: int,
    student_id: int = Query(..., description="ID dello studente"),
) -> None:
    """
    Elimina l'esame dal DB (cascade su sessioni) e rimuove la collection ChromaDB.
    """
    db = SessionLocal()
    try:
        exam = (
            db.query(Exam)
            .filter(Exam.id == exam_id, Exam.student_id == student_id)
            .first()
        )
        if not exam:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Esame {exam_id} non trovato.",
            )
        db.delete(exam)
        db.commit()
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Errore eliminazione esame: {exc}",
        ) from exc
    finally:
        db.close()

    # Rimuovi collection ChromaDB — separato dal blocco DB
    delete_exam_collection(student_id, exam_id)


@router.post(
    "/{exam_id}/ingest",
    response_model=IngestResponse,
    summary="Carica e indicizza un PDF per l'esame",
)
async def ingest_pdf_endpoint(
    exam_id: int,
    student_id: int = Query(..., description="ID dello studente"),
    file: UploadFile = File(..., description="File PDF del materiale di studio"),
) -> IngestResponse:
    """
    Carica un file PDF, lo salva temporaneamente e avvia l'indicizzazione
    tramite ChromaDB + Gemini Embeddings.

    Se la collection esiste già, i nuovi chunk vengono aggiunti a quelli esistenti.
    Per sostituire completamente il materiale, elimina l'esame e ricrealo.
    """
    # Verifica che l'esame appartenga allo studente
    _get_exam_or_404(exam_id, student_id)

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Il file deve essere un PDF (.pdf).",
        )

    # Salva il file su disco
    safe_name = f"s{student_id}_e{exam_id}_{file.filename}"
    pdf_path = UPLOAD_DIR / safe_name

    try:
        # FastAPI UploadFile supports async .read(); leggiamo i bytes
        content = await file.read()
        with pdf_path.open("wb") as dest:
            dest.write(content)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Errore salvataggio file: {exc}",
        ) from exc

    # Indicizzazione
    try:
        stats = ingest_pdf(str(pdf_path), student_id, exam_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Errore indicizzazione PDF: {exc}",
        ) from exc

    return IngestResponse(
        file=stats["file"],
        pages=stats["pages"],
        chunks=stats["chunks"],
        collection=stats["collection"],
    )