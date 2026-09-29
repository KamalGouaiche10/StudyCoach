"""
E2E test — percorsi utente completi attraverso l'app Streamlit reale
(app/main.py e le pagine in app/pages/), via streamlit.testing.v1.AppTest.
"""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

MAIN_APP = Path(__file__).resolve().parent.parent / "app" / "main.py"


@pytest.fixture(autouse=True)
def browser_request_cookies(monkeypatch):
    # AppTest has no real HTTP request; its default context cookies are mocks.
    from streamlit.runtime.context import ContextProxy
    monkeypatch.setattr(ContextProxy, "cookies", property(lambda self: {}))

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
    at.button(key="generate_questions").click().run(timeout=30)
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


def test_e2e_exam_notes_and_history_remain_accessible(monkeypatch, sample_pdf_path):
    """The new workspace keeps notes, source metadata and history reachable."""
    from datetime import datetime, timezone
    from backend.agents import notes_generator
    from backend.db.models import Exam, Material, Session, SessionLocal

    student_id = _seed_student()
    with SessionLocal() as db:
        exam = Exam(student_id=student_id, name="Algoritmi & strutture")
        db.add(exam)
        db.flush()
        exam_id = exam.id
        db.add(Material(
            exam_id=exam_id, filename="grafi.pdf", stored_path=str(sample_pdf_path),
            pages_count=2, chunks_count=3,
        ))
        session = Session(
            exam_id=exam_id, score_total=8,
            ended_at=datetime.now(timezone.utc),
            qa_log=json.dumps([{
                "question_text": "Come rappresenti un grafo?", "final_score": 8,
                "difficulty": "base", "student_answer_1": "Con una lista di adiacenza.",
            }]),
        )
        db.add(session)
        db.commit()

    monkeypatch.setattr(
        notes_generator, "generate_notes_pdf_from_materials",
        lambda **kwargs: sample_pdf_path.read_bytes(),
    )
    at = AppTest.from_file(str(MAIN_APP))
    at.session_state["authenticated"] = True
    at.session_state["student_id"] = student_id
    at.session_state["username"] = "mario_e2e"
    at.session_state["current_page"] = "exam"
    at.session_state["current_exam"] = {"id": exam_id, "name": "Algoritmi & strutture"}
    at.run(timeout=30)
    assert not at.exception
    assert len(at.get("file_uploader")) == 1

    at.button(key=f"exam_notes_{exam_id}").click().run(timeout=30)
    assert not at.exception
    assert len(at.get("download_button")) == 1
    assert at.session_state[f"notes_pdf_file_{exam_id}"] == sample_pdf_path.read_bytes()

    at.button(key=f"exam_history_{exam_id}").click().run(timeout=30)
    assert not at.exception
    assert at.session_state["current_page"] == "history"
    assert any(e.label == "Risposte e feedback" for e in at.expander)
    assert any("Come rappresenti un grafo?" in item.value for item in at.markdown)


def test_e2e_empty_history_can_start_first_session():
    from backend.db.models import Exam, SessionLocal

    student_id = _seed_student()
    with SessionLocal() as db:
        exam = Exam(student_id=student_id, name="Esame nuovo")
        db.add(exam)
        db.commit()
        exam_id = exam.id

    at = AppTest.from_file(str(MAIN_APP))
    at.session_state["authenticated"] = True
    at.session_state["student_id"] = student_id
    at.session_state["username"] = "mario_e2e"
    at.session_state["current_page"] = "history"
    at.session_state["current_exam"] = {"id": exam_id, "name": "Esame nuovo"}
    at.run(timeout=30)
    assert not at.exception
    _label(at.button, "▶ Avvia prima sessione").click().run(timeout=30)
    assert not at.exception
    assert at.session_state["current_page"] == "session"
    assert at.slider(key="n_questions_slider").value == 5


def test_e2e_refresh_restores_login_but_explicit_logout_revokes_cookie(monkeypatch):
    """A fresh Streamlit session authenticates from the request cookie only."""
    from streamlit.runtime.context import ContextProxy
    from backend.session_cookie import COOKIE_NAME, get_or_create_token, verify_token

    student_id = _seed_student("refresh_user")
    token = get_or_create_token(student_id)
    monkeypatch.setattr(ContextProxy, "cookies", property(lambda self: {COOKIE_NAME: token}))

    # No session_state carried over: this is the refresh/reconnect boundary.
    refreshed = AppTest.from_file(str(MAIN_APP)).run(timeout=30)
    assert not refreshed.exception
    assert refreshed.session_state["authenticated"] is True
    assert refreshed.session_state["student_id"] == student_id
    assert refreshed.session_state["username"] == "refresh_user"
    assert refreshed.session_state["current_page"] == "upload"
    assert "token" not in refreshed.query_params
    assert all(field.key != "login_user" for field in refreshed.text_input)

    _label(refreshed.button, "Esci").click().run(timeout=30)
    assert not refreshed.exception
    assert refreshed.session_state["authenticated"] is False
    assert verify_token(token) is None

    # Even a browser still sending the old cookie cannot restore a logout.
    after_logout = AppTest.from_file(str(MAIN_APP)).run(timeout=30)
    assert not after_logout.exception
    assert after_logout.session_state["authenticated"] is False
    assert after_logout.session_state["current_page"] == "login"


def test_e2e_login_keeps_cookie_writer_mounted_after_rerun():
    """Regression: previously the login handler unmounted its own writer."""
    import hashlib
    from backend.db.models import SessionLocal, Student
    from backend.session_cookie import get_or_create_token

    student_id = _seed_student("persistent_user")
    with SessionLocal() as db:
        student = db.get(Student, student_id)
        student.password_hash = hashlib.sha256(b"secret123").hexdigest()
        db.commit()

    at = AppTest.from_file(str(MAIN_APP)).run(timeout=30)
    at.text_input(key="login_user").set_value("persistent_user")
    at.text_input(key="login_pwd").set_value("secret123")
    at.button(key="btn_login").click().run(timeout=30)
    assert not at.exception
    assert at.session_state["current_page"] == "upload"
    components = at.get("bidi_component")
    assert len(components) == 1
    assert get_or_create_token(student_id) in str(components[0].proto)
