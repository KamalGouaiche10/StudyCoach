"""
backend/api/sessions.py — Router sessioni di studio

Flusso completo:
  1. POST /sessions                         → apre sessione (crea DbSession)
  2. POST /sessions/{id}/quiz               → genera quiz (QuizResult)
  3. POST /sessions/{id}/tutor/start        → inizia loop socratico per una domanda
  4. POST /sessions/{id}/tutor/answer1      → prima risposta → domanda guida
  5. POST /sessions/{id}/tutor/answer2      → seconda risposta → valutazione
  6. POST /sessions/{id}/tutor/contest      → (opzionale) contestazione
  7. POST /sessions/{id}/tutor/close        → chiude domanda, aggiorna AdaptiveEngine
  8. POST /sessions/{id}/next-question      → prossima domanda (AdaptiveEngine)
  9. POST /sessions/{id}/close              → chiude sessione, genera report
  10. GET /sessions/{id}                    → dettaglio sessione
  11. GET /sessions?exam_id=N               → lista sessioni per esame
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status

from backend.agents.adaptive_engine import AdaptiveEngine
from backend.agents.quiz_generator import generate_quiz
from backend.agents.report_generator import save_report
from backend.agents.socratic_tutor import SocraticTutor, TurnState
from backend.db.models import Session as DbSession
from backend.db.models import SessionLocal
from backend.models.schemas import (
    Answer1Request,
    Answer1Response,
    Answer2Request,
    Answer2Response,
    CloseQuestionRequest,
    CloseQuestionResponse,
    ContestRequest,
    ContestResponse,
    NextQuestionRequest,
    NextQuestionResponse,
    QuestionOut,
    QuizGenerateRequest,
    QuizGenerateResponse,
    SessionCloseRequest,
    SessionCreate,
    SessionListResponse,
    SessionReportResponse,
    SessionResponse,
    TopicBreakdown,
    TutorStartRequest,
    TutorStartResponse,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])

# ---------------------------------------------------------------------------
# In-memory store per tutor e adaptive engine attivi
# (in produzione usare Redis o un servizio esterno con TTL)
# ---------------------------------------------------------------------------

_active_tutors:  dict[str, SocraticTutor]  = {}   # key: f"{session_id}_{question_id}"
_active_engines: dict[int, AdaptiveEngine] = {}   # key: session_id


# ---------------------------------------------------------------------------
# Helpers DB
# ---------------------------------------------------------------------------

def _get_session_or_404(session_id: int) -> DbSession:
    db = SessionLocal()
    try:
        sess = db.query(DbSession).filter(DbSession.id == session_id).first()
        if not sess:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Sessione {session_id} non trovata.",
            )
        return sess
    finally:
        db.close()


def _session_to_response(sess: DbSession) -> SessionResponse:
    return SessionResponse(
        id=sess.id,
        exam_id=sess.exam_id,
        started_at=sess.started_at,
        ended_at=sess.ended_at,
        score_total=sess.score_total,
        report_path=sess.report_path,
    )


# ---------------------------------------------------------------------------
# 1 — Apri sessione
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Apre una nuova sessione di studio",
)
def create_session(
    payload: SessionCreate,
    student_id: int = Query(..., description="ID dello studente"),
) -> SessionResponse:
    """Crea una DbSession e inizializza l'AdaptiveEngine in memoria."""
    db = SessionLocal()
    try:
        sess = DbSession(exam_id=payload.exam_id)
        db.add(sess)
        db.commit()
        db.refresh(sess)

        # Inizializza AdaptiveEngine per questa sessione
        _active_engines[sess.id] = AdaptiveEngine(
            student_id=student_id,
            exam_id=payload.exam_id,
        )
        return _session_to_response(sess)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Errore creazione sessione: {exc}",
        ) from exc
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 2 — Genera quiz
# ---------------------------------------------------------------------------

@router.post(
    "/{session_id}/quiz",
    response_model=QuizGenerateResponse,
    summary="Genera il quiz per la sessione",
)
def generate_session_quiz(
    session_id: int,
    payload: QuizGenerateRequest,
    student_id: int = Query(..., description="ID dello studente"),
) -> QuizGenerateResponse:
    """
    Usa QuizGenerator (RAG + Gemini) per produrre N domande
    calibrate sul materiale indicizzato.
    """
    sess = _get_session_or_404(session_id)

    try:
        result = generate_quiz(
            student_id=student_id,
            exam_id=sess.exam_id,
            topic_query=payload.topic_query,
            n_questions=payload.n_questions,
            source_name=payload.source_name,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Errore generazione quiz: {exc}",
        ) from exc

    return QuizGenerateResponse(
        exam_id=result.exam_id,
        student_id=result.student_id,
        source_name=result.source_name,
        n_questions=result.n_questions,
        prompt_version=result.prompt_version,
        questions=[
            QuestionOut(
                id=q.id,
                text=q.text,
                difficulty=q.difficulty,
                topic_hint=q.topic_hint,
            )
            for q in result.questions
        ],
    )


# ---------------------------------------------------------------------------
# 3 — Avvia loop socratico per una domanda
# ---------------------------------------------------------------------------

@router.post(
    "/{session_id}/tutor/start",
    response_model=TutorStartResponse,
    summary="Avvia il tutor socratico per una domanda",
)
def tutor_start(
    session_id: int,
    payload: TutorStartRequest,
    student_id: int = Query(..., description="ID dello studente"),
) -> TutorStartResponse:
    """Inizializza il SocraticTutor e fa il pre-fetch dei chunk RAG."""
    sess = _get_session_or_404(session_id)

    tutor = SocraticTutor(
        student_id=student_id,
        exam_id=sess.exam_id,
    )
    q_dict = payload.question.model_dump()
    question_text = tutor.start(q_dict)

    key = f"{session_id}_{payload.question.id}"
    _active_tutors[key] = tutor

    return TutorStartResponse(
        question_text=question_text,
        difficulty=payload.question.difficulty,
        topic_hint=payload.question.topic_hint,
    )


# ---------------------------------------------------------------------------
# 4 — Prima risposta → domanda guida
# ---------------------------------------------------------------------------

@router.post(
    "/{session_id}/tutor/answer1",
    response_model=Answer1Response,
    summary="Invia la prima risposta, ricevi la domanda guida socratica",
)
def tutor_answer1(session_id: int, payload: Answer1Request) -> Answer1Response:
    key = f"{session_id}_{payload.question_id}"
    tutor = _active_tutors.get(key)
    if not tutor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nessun tutor attivo per sessione {session_id}, domanda {payload.question_id}.",
        )
    try:
        data = tutor.submit_answer_1(payload.answer)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Errore generazione domanda guida: {exc}",
        ) from exc

    return Answer1Response(
        guiding_question=data["guiding_question"],
        positive_feedback=data["positive_feedback"],
        focus_area=data["focus_area"],
    )


# ---------------------------------------------------------------------------
# 5 — Seconda risposta → valutazione
# ---------------------------------------------------------------------------

@router.post(
    "/{session_id}/tutor/answer2",
    response_model=Answer2Response,
    summary="Invia la seconda risposta, ricevi la valutazione",
)
def tutor_answer2(session_id: int, payload: Answer2Request) -> Answer2Response:
    key = f"{session_id}_{payload.question_id}"
    tutor = _active_tutors.get(key)
    if not tutor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nessun tutor attivo per sessione {session_id}, domanda {payload.question_id}.",
        )
    try:
        data = tutor.submit_answer_2(payload.answer)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Errore valutazione: {exc}",
        ) from exc

    return Answer2Response(
        score=data["score"],
        motivation=data["motivation"],
        correct_points=data["correct_points"],
        missing_points=data["missing_points"],
        improvement_after_guidance=data["improvement_after_guidance"],
        can_contest=data["can_contest"],
    )


# ---------------------------------------------------------------------------
# 6 — Contestazione (opzionale)
# ---------------------------------------------------------------------------

@router.post(
    "/{session_id}/tutor/contest",
    response_model=ContestResponse,
    summary="Contesta la valutazione ricevuta",
)
def tutor_contest(session_id: int, payload: ContestRequest) -> ContestResponse:
    key = f"{session_id}_{payload.question_id}"
    tutor = _active_tutors.get(key)
    if not tutor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nessun tutor attivo per sessione {session_id}, domanda {payload.question_id}.",
        )
    try:
        data = tutor.submit_contestation(payload.argumentation)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Errore rivalutazione: {exc}",
        ) from exc

    return ContestResponse(
        final_score=data["final_score"],
        score_changed=data["score_changed"],
        score_delta=data["score_delta"],
        contestation_assessment=data["contestation_assessment"],
        final_motivation=data["final_motivation"],
        response_to_student=data["response_to_student"],
    )


# ---------------------------------------------------------------------------
# 7 — Chiudi domanda + aggiorna AdaptiveEngine + persisti qa_log
# ---------------------------------------------------------------------------

@router.post(
    "/{session_id}/tutor/close",
    response_model=CloseQuestionResponse,
    summary="Chiude la domanda corrente e aggiorna l'engine adattivo",
)
def tutor_close(session_id: int, payload: CloseQuestionRequest) -> CloseQuestionResponse:
    """
    Chiude il loop socratico per la domanda corrente:
    1. Chiama tutor.close() → ottiene QuestionAttempt definitivo
    2. Aggiorna AdaptiveEngine con score e topic
    3. Appende il tentativo al qa_log nella DbSession
    """
    key = f"{session_id}_{payload.question_id}"
    tutor = _active_tutors.get(key)
    if not tutor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nessun tutor attivo per sessione {session_id}, domanda {payload.question_id}.",
        )
    try:
        attempt = tutor.close()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    final_score = attempt.final_score
    if final_score is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Impossibile chiudere: nessun voto disponibile.",
        )

    # Aggiorna AdaptiveEngine
    engine = _active_engines.get(session_id)
    if engine:
        engine.record_answer(
            question_id=attempt.question_id,
            topic=attempt.topic_hint,
            score=final_score,
        )

    # Persisti il tentativo nel qa_log della DbSession
    _append_attempt_to_log(session_id, tutor.to_dict())

    # Rimuovi il tutor dall'in-memory store
    del _active_tutors[key]

    return CloseQuestionResponse(
        final_score=final_score,
        topic_hint=attempt.topic_hint,
    )


def _append_attempt_to_log(session_id: int, attempt_dict: dict) -> None:
    """Aggiunge il tentativo serializzato al qa_log della sessione nel DB."""
    db = SessionLocal()
    try:
        sess = db.query(DbSession).filter(DbSession.id == session_id).first()
        if not sess:
            return
        existing: list = json.loads(sess.qa_log) if sess.qa_log else []
        existing.append(attempt_dict)
        sess.qa_log = json.dumps(existing, ensure_ascii=False)
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[sessions.py] Errore append qa_log: {exc}")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 8 — Prossima domanda (AdaptiveEngine)
# ---------------------------------------------------------------------------

@router.post(
    "/{session_id}/next-question",
    response_model=NextQuestionResponse,
    summary="Ottieni la prossima domanda suggerita dall'AdaptiveEngine",
)
def next_question(session_id: int, payload: NextQuestionRequest) -> NextQuestionResponse:
    """
    L'AdaptiveEngine analizza i topic deboli e sceglie la domanda successiva
    tra quelle rimanenti, prioritizzando gli argomenti carenti.
    """
    engine = _active_engines.get(session_id)
    if not engine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nessun engine attivo per sessione {session_id}.",
        )

    remaining = [q.model_dump() for q in payload.remaining_questions]
    chosen = engine.pick_next_question(remaining)

    if chosen is None:
        return NextQuestionResponse(
            question=None,
            is_last=True,
            message="Tutte le domande sono state completate.",
        )

    return NextQuestionResponse(
        question=QuestionOut(**chosen),
        is_last=len(remaining) == 1,
        message=f"Prossima domanda su: {chosen.get('topic_hint', '')}",
    )


# ---------------------------------------------------------------------------
# 9 — Chiudi sessione + genera report
# ---------------------------------------------------------------------------

@router.post(
    "/{session_id}/close",
    response_model=SessionReportResponse,
    summary="Chiude la sessione e genera il report finale",
)
def close_session(session_id: int, payload: SessionCloseRequest) -> SessionReportResponse:
    """
    1. Genera il report da AdaptiveEngine
    2. Salva Markdown e PDF su disco
    3. Aggiorna DbSession (ended_at, score_total, report_path)
    4. Pulisce l'engine dall'in-memory store
    """
    engine = _active_engines.get(session_id)
    if not engine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nessun engine attivo per sessione {session_id}.",
        )

    report = engine.generate_session_report()
    paths = save_report(report, session_id, payload.exam_name)

    # Aggiorna DB
    db = SessionLocal()
    try:
        sess = db.query(DbSession).filter(DbSession.id == session_id).first()
        if sess:
            sess.ended_at    = datetime.now(timezone.utc)
            sess.score_total = report["overall_avg"]
            sess.report_path = paths.get("pdf")
            db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[sessions.py] Errore aggiornamento sessione al close: {exc}")
    finally:
        db.close()

    # Pulisci l'engine
    _active_engines.pop(session_id, None)

    return SessionReportResponse(
        session_id=session_id,
        student_id=report["student_id"],
        exam_id=report["exam_id"],
        overall_avg=report["overall_avg"],
        n_questions_answered=report["n_questions_answered"],
        weak_topics=report["weak_topics"],
        strong_topics=report["strong_topics"],
        topic_breakdown=[TopicBreakdown(**t) for t in report["topic_breakdown"]],
        summary=report["summary"],
        report_md_path=paths.get("md"),
        report_pdf_path=paths.get("pdf"),
    )


# ---------------------------------------------------------------------------
# 10 — Dettaglio sessione
# ---------------------------------------------------------------------------

@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Dettaglio sessione",
)
def get_session(session_id: int) -> SessionResponse:
    sess = _get_session_or_404(session_id)
    return _session_to_response(sess)


# ---------------------------------------------------------------------------
# 11 — Lista sessioni per esame
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=SessionListResponse,
    summary="Lista sessioni per un esame",
)
def list_sessions(
    exam_id: int = Query(..., description="ID dell'esame"),
) -> SessionListResponse:
    db = SessionLocal()
    try:
        sessions = (
            db.query(DbSession)
            .filter(DbSession.exam_id == exam_id)
            .order_by(DbSession.started_at.desc())
            .all()
        )
        items = [_session_to_response(s) for s in sessions]
        return SessionListResponse(sessions=items, total=len(items))
    finally:
        db.close()