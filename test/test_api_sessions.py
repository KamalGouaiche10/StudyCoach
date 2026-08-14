"""
Integration test — backend/api/sessions.py (via FastAPI TestClient).

Il flusso reale (quiz -> loop socratico -> report) viene esercitato per
intero: solo il livello LLM (agenti Agno) e' sostituito da FakeAgent, tutto
il resto (DB, RAG su ChromaDB, AdaptiveEngine, generazione report) e' reale.
"""

import json

import pytest

from backend.agents import quiz_generator as qg_mod
from backend.agents import socratic_tutor as st_mod

QUIZ_JSON = json.dumps({
    "source_name": "Analisi 1",
    "questions": [
        {"id": 1, "text": "Cos'e' il machine learning?", "difficulty": "base", "topic_hint": "ml"},
        {"id": 2, "text": "Spiega l'overfitting.", "difficulty": "intermedia", "topic_hint": "overfitting"},
    ],
})

GUIDE_JSON = json.dumps({
    "guiding_question": "Cosa intendi con 'apprendere dai dati'?",
    "positive_feedback": "Buon punto di partenza.",
    "focus_area": "definizione formale",
})

EVAL_JSON = json.dumps({
    "score": 7,
    "motivation": "Buona comprensione con qualche imprecisione.",
    "correct_points": ["Definizione generale corretta"],
    "missing_points": ["Manca un esempio pratico"],
    "improvement_after_guidance": "Migliorata rispetto al primo tentativo.",
})

CONTEST_JSON = json.dumps({
    "final_score": 8,
    "contestation_assessment": "parzialmente_valido",
    "final_motivation": "L'argomentazione aggiunge un punto valido.",
    "response_to_student": "Accolgo parzialmente.",
})


def _setup_exam_with_material(api_client, sample_pdf_path) -> tuple[int, int]:
    student_id = api_client.post(
        "/auth/register", json={"username": "mario_rossi", "password": "secret123"}
    ).json()["student_id"]
    exam_id = api_client.post(
        "/exams", params={"student_id": student_id}, json={"name": "Analisi 1"}
    ).json()["id"]
    with open(sample_pdf_path, "rb") as f:
        api_client.post(
            f"/exams/{exam_id}/ingest",
            params={"student_id": student_id},
            files={"file": (sample_pdf_path.name, f, "application/pdf")},
        )
    return student_id, exam_id


def test_create_session_initializes_adaptive_engine(api_client, sample_pdf_path):
    student_id, exam_id = _setup_exam_with_material(api_client, sample_pdf_path)
    resp = api_client.post("/sessions", params={"student_id": student_id}, json={"exam_id": exam_id})
    assert resp.status_code == 201
    body = resp.json()
    assert body["exam_id"] == exam_id
    assert body["ended_at"] is None


def test_generate_session_quiz_returns_questions(api_client, sample_pdf_path, monkeypatch, fake_agent_factory):
    student_id, exam_id = _setup_exam_with_material(api_client, sample_pdf_path)
    session_id = api_client.post(
        "/sessions", params={"student_id": student_id}, json={"exam_id": exam_id}
    ).json()["id"]

    monkeypatch.setattr(qg_mod, "_make_quiz_agent", fake_agent_factory(QUIZ_JSON))

    resp = api_client.post(
        f"/sessions/{session_id}/quiz",
        params={"student_id": student_id},
        json={"topic_query": "concetti principali", "n_questions": 2, "source_name": "Analisi 1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["n_questions"] == 2
    assert body["questions"][0]["text"] == "Cos'e' il machine learning?"


def test_generate_quiz_for_unknown_session_returns_404(api_client):
    resp = api_client.post("/sessions/999999/quiz", params={"student_id": 1}, json={})
    assert resp.status_code == 404


def _full_tutor_loop(api_client, session_id, student_id, question, monkeypatch, fake_agent_factory):
    monkeypatch.setattr(st_mod, "_guide_agent", fake_agent_factory(GUIDE_JSON))
    monkeypatch.setattr(st_mod, "_eval_agent", fake_agent_factory(EVAL_JSON))
    monkeypatch.setattr(st_mod, "_contest_agent", fake_agent_factory(CONTEST_JSON))

    resp = api_client.post(
        f"/sessions/{session_id}/tutor/start",
        params={"student_id": student_id},
        json={"session_id": session_id, "question": question},
    )
    assert resp.status_code == 200
    assert resp.json()["question_text"] == question["text"]

    resp = api_client.post(
        f"/sessions/{session_id}/tutor/answer1",
        json={"session_id": session_id, "question_id": question["id"], "answer": "forse riguarda i dati"},
    )
    assert resp.status_code == 200
    assert resp.json()["guiding_question"] == "Cosa intendi con 'apprendere dai dati'?"

    resp = api_client.post(
        f"/sessions/{session_id}/tutor/answer2",
        json={"session_id": session_id, "question_id": question["id"], "answer": "e' un modello che apprende pattern"},
    )
    assert resp.status_code == 200
    eval_body = resp.json()
    assert eval_body["score"] == 7
    assert eval_body["can_contest"] is True

    resp = api_client.post(
        f"/sessions/{session_id}/tutor/contest",
        json={"session_id": session_id, "question_id": question["id"], "argumentation": "meritavo di piu' perche'..."},
    )
    assert resp.status_code == 200
    assert resp.json()["final_score"] == 8

    resp = api_client.post(
        f"/sessions/{session_id}/tutor/close",
        json={"session_id": session_id, "question_id": question["id"]},
    )
    assert resp.status_code == 200
    close_body = resp.json()
    assert close_body["final_score"] == 8
    assert close_body["topic_hint"] == question["topic_hint"]
    return close_body


def test_full_session_flow_quiz_tutor_report(api_client, sample_pdf_path, monkeypatch, fake_agent_factory):
    student_id, exam_id = _setup_exam_with_material(api_client, sample_pdf_path)
    session_id = api_client.post(
        "/sessions", params={"student_id": student_id}, json={"exam_id": exam_id}
    ).json()["id"]

    monkeypatch.setattr(qg_mod, "_make_quiz_agent", fake_agent_factory(QUIZ_JSON))
    quiz = api_client.post(
        f"/sessions/{session_id}/quiz",
        params={"student_id": student_id},
        json={"n_questions": 2},
    ).json()

    first_question = quiz["questions"][0]
    _full_tutor_loop(api_client, session_id, student_id, first_question, monkeypatch, fake_agent_factory)

    # Prossima domanda suggerita dall'AdaptiveEngine tra quelle rimanenti.
    remaining = quiz["questions"][1:]
    resp = api_client.post(f"/sessions/{session_id}/next-question", json={
        "session_id": session_id,
        "remaining_questions": remaining,
    })
    assert resp.status_code == 200
    next_body = resp.json()
    assert next_body["question"]["id"] == remaining[0]["id"]
    assert next_body["is_last"] is True

    # Chiusura sessione + report finale.
    resp = api_client.post(f"/sessions/{session_id}/close", json={
        "session_id": session_id,
        "exam_name": "Analisi 1",
    })
    assert resp.status_code == 200
    report = resp.json()
    assert report["session_id"] == session_id
    assert report["n_questions_answered"] == 1
    assert report["overall_avg"] == 8.0
    assert report["report_md_path"] is not None
    assert report["report_pdf_path"] is not None

    # Dettaglio e lista sessioni riflettono lo stato finale.
    resp = api_client.get(f"/sessions/{session_id}")
    assert resp.status_code == 200
    assert resp.json()["score_total"] == 8.0

    resp = api_client.get("/sessions", params={"exam_id": exam_id})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_tutor_answer1_without_start_returns_404(api_client):
    resp = api_client.post(
        "/sessions/1/tutor/answer1",
        json={"session_id": 1, "question_id": 1, "answer": "qualcosa"},
    )
    assert resp.status_code == 404


def test_tutor_answer2_before_answer1_returns_409(api_client, sample_pdf_path, monkeypatch, fake_agent_factory):
    student_id, exam_id = _setup_exam_with_material(api_client, sample_pdf_path)
    session_id = api_client.post(
        "/sessions", params={"student_id": student_id}, json={"exam_id": exam_id}
    ).json()["id"]

    monkeypatch.setattr(st_mod, "_guide_agent", fake_agent_factory(GUIDE_JSON))
    monkeypatch.setattr(st_mod, "_eval_agent", fake_agent_factory(EVAL_JSON))

    question = {"id": 1, "text": "Domanda?", "difficulty": "base", "topic_hint": "x"}
    api_client.post(
        f"/sessions/{session_id}/tutor/start",
        params={"student_id": student_id},
        json={"session_id": session_id, "question": question},
    )

    resp = api_client.post(
        f"/sessions/{session_id}/tutor/answer2",
        json={"session_id": session_id, "question_id": 1, "answer": "risposta prematura"},
    )
    assert resp.status_code == 409


def test_close_session_without_engine_returns_404(api_client):
    resp = api_client.post("/sessions/999999/close", json={"session_id": 999999})
    assert resp.status_code == 404


def test_next_question_without_engine_returns_404(api_client):
    resp = api_client.post("/sessions/999999/next-question", json={
        "session_id": 999999,
        "remaining_questions": [],
    })
    assert resp.status_code == 404


def test_get_unknown_session_returns_404(api_client):
    resp = api_client.get("/sessions/999999")
    assert resp.status_code == 404
