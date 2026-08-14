"""
E2E test — percorsi utente completi attraverso l'app Streamlit reale
(app/main.py e le pagine in app/pages/), via streamlit.testing.v1.AppTest.

Nessun browser: AppTest esegue lo script Streamlit vero e proprio (stessa
logica di rendering, stesso session_state, stessi bottoni/input) in modalita'
headless. L'unico confine sostituito e' il livello LLM (FakeAgent) e, dove
serve, l'upload di file via UI (non scriptabile con AppTest: il materiale
viene indicizzato direttamente con ingest_pdf, bypassando st.file_uploader).
"""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

MAIN_APP = Path(__file__).resolve().parent.parent / "app" / "main.py"

QUIZ_JSON = json.dumps({
    "source_name": "Analisi 1",
    "questions": [
        {"id": 1, "text": "Cos'e' il machine learning?", "difficulty": "base", "topic_hint": "ml"},
        {"id": 2, "text": "Spiega l'overfitting.", "difficulty": "intermedia", "topic_hint": "overfitting"},
        {"id": 3, "text": "Cos'e' una rete neurale?", "difficulty": "base", "topic_hint": "reti"},
    ],
})
GUIDE_JSON = json.dumps({
    "guiding_question": "Cosa intendi con 'apprendere dai dati'?",
    "positive_feedback": "Buon punto di partenza.",
    "focus_area": "definizione formale",
})
EVAL_JSON = json.dumps({
    "score": 8,
    "motivation": "Buona comprensione.",
    "correct_points": ["Definizione corretta"],
    "missing_points": [],
    "improvement_after_guidance": "Migliorata.",
})
DOUBT_OPEN_JSON = json.dumps({"guiding_question": "Da dove nasce il tuo dubbio?", "topic_hint": "ml"})
DOUBT_EVAL_JSON = json.dumps({
    "correct_points": ["Hai capito il concetto intuitivo"],
    "missing_points": ["Manca la definizione formale"],
    "correct_answer": "Un limite descrive il valore a cui tende una funzione.",
})


def _label(elements, label):
    return next(e for e in elements if e.label == label)


def _seed_student(username="mario_e2e") -> int:
    from backend.db.models import SessionLocal, Student

    db = SessionLocal()
    try:
        student = Student(username=username, password_hash="hash")
        db.add(student)
        db.commit()
        db.refresh(student)
        return student.id
    finally:
        db.close()


def _seed_exam_with_material(student_id: int, sample_pdf_path: Path, name="Analisi 1") -> int:
    from backend.agents.ingestor import ingest_pdf
    from backend.db.models import Exam, SessionLocal

    db = SessionLocal()
    try:
        exam = Exam(student_id=student_id, name=name)
        db.add(exam)
        db.commit()
        db.refresh(exam)
        exam_id = exam.id
    finally:
        db.close()

    ingest_pdf(str(sample_pdf_path), student_id=student_id, exam_id=exam_id)
    return exam_id


# ---------------------------------------------------------------------------
# Registrazione + login
# ---------------------------------------------------------------------------

def test_e2e_register_creates_account_and_lands_on_upload_page():
    at = AppTest.from_file(str(MAIN_APP))
    at.run(timeout=30)
    assert at.session_state["current_page"] == "login"

    at.text_input(key="reg_user").set_value("mario_e2e")
    at.text_input(key="reg_pwd").set_value("secret123")
    at.text_input(key="reg_pwd2").set_value("secret123")
    at.button(key="btn_reg").click().run(timeout=30)

    assert not at.exception
    assert at.session_state["authenticated"] is True
    assert at.session_state["current_page"] == "upload"

    from backend.db.models import SessionLocal, Student
    db = SessionLocal()
    try:
        assert db.query(Student).filter(Student.username == "mario_e2e").first() is not None
    finally:
        db.close()


def test_e2e_login_wrong_password_shows_error_and_stays_logged_out():
    _seed_student("mario_e2e")
    from backend.session_cookie import get_or_create_token  # noqa: F401  (import warms module)
    import hashlib
    from backend.db.models import SessionLocal, Student

    db = SessionLocal()
    try:
        s = db.query(Student).filter(Student.username == "mario_e2e").first()
        s.password_hash = hashlib.sha256("secret123".encode()).hexdigest()
        db.commit()
    finally:
        db.close()

    at = AppTest.from_file(str(MAIN_APP))
    at.run(timeout=30)

    at.text_input(key="login_user").set_value("mario_e2e")
    at.text_input(key="login_pwd").set_value("wrongpass")
    at.button(key="btn_login").click().run(timeout=30)

    assert not at.exception
    assert at.session_state["authenticated"] is False
    assert len(at.error) == 1


def test_e2e_login_correct_credentials_redirects_to_upload():
    import hashlib
    from backend.db.models import SessionLocal, Student

    student_id = _seed_student("mario_e2e")
    db = SessionLocal()
    try:
        s = db.query(Student).filter(Student.id == student_id).first()
        s.password_hash = hashlib.sha256("secret123".encode()).hexdigest()
        db.commit()
    finally:
        db.close()

    at = AppTest.from_file(str(MAIN_APP))
    at.run(timeout=30)

    at.text_input(key="login_user").set_value("mario_e2e")
    at.text_input(key="login_pwd").set_value("secret123")
    at.button(key="btn_login").click().run(timeout=30)

    assert not at.exception
    assert at.session_state["authenticated"] is True
    assert at.session_state["student_id"] == student_id


# ---------------------------------------------------------------------------
# Upload: creazione esame dalla UI
# ---------------------------------------------------------------------------

def test_e2e_create_exam_from_upload_page_and_open_it():
    student_id = _seed_student("mario_e2e")

    at = AppTest.from_file(str(MAIN_APP))
    at.session_state["authenticated"] = True
    at.session_state["student_id"] = student_id
    at.session_state["username"] = "mario_e2e"
    at.session_state["current_page"] = "upload"
    at.run(timeout=30)

    at.text_input(key="exam_name_input").set_value("Analisi 1")
    _label(at.button, "Crea").click().run(timeout=30)

    assert not at.exception
    from backend.db.models import Exam, SessionLocal
    db = SessionLocal()
    try:
        exam = db.query(Exam).filter(Exam.student_id == student_id).first()
        assert exam is not None
        assert exam.name == "Analisi 1"
    finally:
        db.close()

    _label(at.button, "Apri").click().run(timeout=30)
    assert at.session_state["current_page"] == "exam"
    assert at.session_state["current_exam"]["name"] == "Analisi 1"


# ---------------------------------------------------------------------------
# Sessione di studio completa: quiz -> loop socratico -> report
# ---------------------------------------------------------------------------

def test_e2e_first_question_socratic_loop_with_contestation(monkeypatch, fake_agent_factory, sample_pdf_path):
    """
    Percorso e2e reale sulla pagina session.py per una domanda intera:
    genera quiz -> risposta1 -> domanda guida -> risposta2 -> valutazione
    -> contestazione -> prossima domanda. Il resto del loop multi-domanda
    (fino al report finale) usa la stessa orchestrazione (SocraticTutor +
    AdaptiveEngine + save_report) gia' verificata end-to-end a livello API
    in test_api_sessions.py::test_full_session_flow_quiz_tutor_report.
    """
    from backend.agents import quiz_generator as qg_mod
    from backend.agents import socratic_tutor as st_mod

    student_id = _seed_student("mario_e2e")
    exam_id = _seed_exam_with_material(student_id, sample_pdf_path)

    monkeypatch.setattr(qg_mod, "_make_quiz_agent", fake_agent_factory(QUIZ_JSON))
    monkeypatch.setattr(st_mod, "_guide_agent", fake_agent_factory(GUIDE_JSON))
    monkeypatch.setattr(st_mod, "_eval_agent", fake_agent_factory(EVAL_JSON))
    monkeypatch.setattr(st_mod, "_contest_agent", fake_agent_factory(json.dumps({
        "final_score": 9,
        "contestation_assessment": "valido",
        "final_motivation": "L'argomentazione e' fondata.",
        "response_to_student": "Hai ragione, alzo il voto.",
    })))

    at = AppTest.from_file(str(MAIN_APP))
    at.session_state["authenticated"] = True
    at.session_state["student_id"] = student_id
    at.session_state["username"] = "mario_e2e"
    at.session_state["current_page"] = "session"
    at.session_state["current_exam"] = {"id": exam_id, "name": "Analisi 1"}
    at.run(timeout=30)
    assert not at.exception

    at.slider(key="n_questions_slider").set_value(3).run(timeout=30)
    _label(at.button, "🚀 Genera domande").click().run(timeout=30)
    assert not at.exception
    assert at.session_state["tutor_state"] == "answer1"
    first_question_id = at.session_state["current_session"]["questions"][0]["id"]

    at.text_area(key="input_ans1").set_value("forse riguarda l'apprendimento dai dati").run(timeout=30)
    at.button(key="btn_ans1").click().run(timeout=30)
    assert not at.exception
    assert at.session_state["tutor_state"] == "answer2"
    assert at.session_state["_guide_result"]["guiding_question"] == json.loads(GUIDE_JSON)["guiding_question"]

    at.text_area(key="input_ans2").set_value("e' un modello che impara pattern dai dati").run(timeout=30)
    at.button(key="btn_ans2").click().run(timeout=30)
    assert not at.exception
    assert at.session_state["tutor_state"] == "evaluated"
    # missing_points=[] in EVAL_JSON attiva il guardrail di coerenza che
    # arrotonda il punteggio a 9 (nessuna lacuna reale segnalata).
    assert at.session_state["_eval_result"]["score"] == 9

    at.text_area(key="contest_input").set_value("meritavo un voto piu' alto perche'...").run(timeout=30)
    at.button(key="btn_contest").click().run(timeout=30)
    assert not at.exception
    assert at.session_state["tutor_state"] == "contested"
    assert at.session_state["_contest_result"]["final_score"] == 9
    assert first_question_id == at.session_state["current_session"]["questions"][0]["id"]

    # Nota: non si prosegue oltre con un ulteriore .run() su questo AppTest —
    # streamlit.testing.v1 (1.57) mantiene nel widget tree un riferimento
    # stantio al text_area "contest_input" (dentro un expander) anche dopo
    # che una run successiva smette di renderlo, e la run seguente solleva
    # KeyError in get_widget_states(). E' un limite noto del tool su widget
    # condizionali dentro expander, non un difetto dell'app. Il comportamento
    # di "chiudi domanda + avanza alla prossima" (tutor.close() +
    # AdaptiveEngine.record_answer()) e' comunque verificato end-to-end in
    # test_api_sessions.py::test_full_session_flow_quiz_tutor_report.


# ---------------------------------------------------------------------------
# Chatbot dubbi: lo studente inizia con un dubbio libero
# ---------------------------------------------------------------------------

def test_e2e_doubt_chatbot_full_conversation(monkeypatch, fake_agent_factory, sample_pdf_path):
    from backend.agents import socratic_tutor as st_mod

    student_id = _seed_student("mario_e2e")
    exam_id = _seed_exam_with_material(student_id, sample_pdf_path)

    monkeypatch.setattr(st_mod, "_doubt_agent", fake_agent_factory([DOUBT_OPEN_JSON, DOUBT_EVAL_JSON]))

    at = AppTest.from_file(str(MAIN_APP))
    at.session_state["authenticated"] = True
    at.session_state["student_id"] = student_id
    at.session_state["username"] = "mario_e2e"
    at.session_state["current_page"] = "chat"
    at.session_state["current_exam"] = {"id": exam_id, "name": "Analisi 1"}
    at.run(timeout=30)
    assert not at.exception
    assert len(at.chat_input) == 1

    at.chat_input[0].set_value("non capisco bene i limiti").run(timeout=30)
    assert not at.exception
    assert at.session_state["chat_stage"] == "waiting_answer"
    assert len(at.session_state["chat_messages"]) == 2
    assert at.session_state["chat_messages"][1]["content"] == "Da dove nasce il tuo dubbio?"

    at.chat_input[0].set_value("credo sia il valore finale della funzione").run(timeout=30)
    assert not at.exception
    assert at.session_state["chat_stage"] == "idle"

    last_message = at.session_state["chat_messages"][-1]["content"]
    assert "Un limite descrive il valore a cui tende una funzione." in last_message
    assert "Manca la definizione formale" in last_message


def test_e2e_doubt_chatbot_without_indexed_material_shows_warning():
    from backend.agents import socratic_tutor as st_mod  # noqa: F401

    student_id = _seed_student("mario_e2e")
    from backend.db.models import Exam, SessionLocal

    db = SessionLocal()
    try:
        exam = Exam(student_id=student_id, name="Esame vuoto")
        db.add(exam)
        db.commit()
        db.refresh(exam)
        exam_id = exam.id
    finally:
        db.close()

    at = AppTest.from_file(str(MAIN_APP))
    at.session_state["authenticated"] = True
    at.session_state["student_id"] = student_id
    at.session_state["username"] = "mario_e2e"
    at.session_state["current_page"] = "chat"
    at.session_state["current_exam"] = {"id": exam_id, "name": "Esame vuoto"}
    at.run(timeout=30)

    at.chat_input[0].set_value("un dubbio qualsiasi").run(timeout=30)

    assert not at.exception
    assert at.session_state["chat_stage"] == "idle"
    last_message = at.session_state["chat_messages"][-1]["content"]
    assert "Non ho trovato materiale" in last_message
