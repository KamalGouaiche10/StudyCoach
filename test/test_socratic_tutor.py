import sys
import types

if "agno.models.groq" not in sys.modules:
    groq_stub = types.ModuleType("agno.models.groq")

    class Groq:  # pragma: no cover - test stub
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    groq_stub.Groq = Groq
    sys.modules["agno.models.groq"] = groq_stub

import json

import pytest

from backend.agents import socratic_tutor as st_mod
from backend.agents.socratic_tutor import (
    DoubtState,
    DoubtTutor,
    EvaluationResult,
    QuestionAttempt,
    SocraticTutor,
    TurnState,
    _apply_consistency_guardrails,
    _apply_severity_guardrails,
    _has_no_real_gaps,
    _is_non_answer,
    _is_rate_limit_error,
    _parse_retry_after,
)


def _make_attempt(answer_2: str) -> QuestionAttempt:
    return QuestionAttempt(
        question_id=1,
        question_text="Che cos'e' il machine learning?",
        difficulty="base",
        topic_hint="ml",
        student_answer_1="forse e' qualcosa sui dati",
        guiding_question="Qual e' la definizione corretta?",
        student_answer_2=answer_2,
    )


def test_non_answer_detection_catches_common_phrases():
    assert _is_non_answer("non so")
    assert _is_non_answer("BOH")
    assert _is_non_answer("I don't know")
    assert not _is_non_answer("E' un modello che apprende dai dati.")


def test_severity_guardrails_force_zero_for_non_answer_second_reply():
    attempt = _make_attempt("non lo so")
    evaluation = EvaluationResult(
        score=4,
        motivation="Risposta incompleta.",
        correct_points=[],
        missing_points=[],
        improvement_after_guidance="Nessun miglioramento",
    )

    adjusted = _apply_severity_guardrails(attempt, evaluation)

    assert adjusted.score == 0
    assert "Valutazione severa applicata" in adjusted.motivation
    assert any("non valutabile" in point for point in adjusted.missing_points)


def test_severity_guardrails_leave_valid_answer_unchanged():
    attempt = _make_attempt("Il machine learning e' una branca dell'IA.")
    evaluation = EvaluationResult(
        score=6,
        motivation="Sufficiente.",
        correct_points=["Definizione generale corretta"],
        missing_points=["Mancano esempi"],
        improvement_after_guidance="Miglioramento parziale",
    )

    adjusted = _apply_severity_guardrails(attempt, evaluation)

    assert adjusted == evaluation


def test_doubt_tutor_submit_answer_before_start_raises():
    tutor = DoubtTutor(student_id=1, exam_id=1)
    with pytest.raises(RuntimeError):
        tutor.submit_answer("una risposta")


def test_doubt_tutor_start_raises_when_no_material(monkeypatch):
    monkeypatch.setattr(
        "backend.agents.socratic_tutor.retrieve_chunks",
        lambda **kwargs: [],
    )
    tutor = DoubtTutor(student_id=1, exam_id=1)
    with pytest.raises(ValueError):
        tutor.start("non capisco un argomento")


def test_doubt_tutor_submit_answer_twice_raises(monkeypatch):
    monkeypatch.setattr(
        "backend.agents.socratic_tutor.retrieve_chunks",
        lambda **kwargs: ["chunk di materiale"],
    )
    monkeypatch.setattr(
        "backend.agents.socratic_tutor._generate_opening_question",
        lambda doubt_text, context_chunks, model_name: {
            "guiding_question": "Cosa intendi per X?",
            "topic_hint": "X",
        },
    )
    monkeypatch.setattr(
        "backend.agents.socratic_tutor._evaluate_doubt",
        lambda attempt, context_chunks, model_name: type(
            "Ev", (), {"correct_points": [], "missing_points": [], "correct_answer": "La risposta e' Y."}
        )(),
    )

    tutor = DoubtTutor(student_id=1, exam_id=1)
    tutor.start("non capisco X")
    assert tutor.attempt.state == DoubtState.WAITING_ANSWER

    tutor.submit_answer("forse e' Y")
    assert tutor.attempt.state == DoubtState.ANSWERED

    with pytest.raises(RuntimeError):
        tutor.submit_answer("un'altra risposta")


# ---------------------------------------------------------------------------
# _is_rate_limit_error / _parse_retry_after
# ---------------------------------------------------------------------------

def test_is_rate_limit_error_detects_common_phrases():
    assert _is_rate_limit_error("Rate limit reached, try again in 5s")
    assert _is_rate_limit_error("HTTP 429")
    assert not _is_rate_limit_error("Tutto ok")
    assert not _is_rate_limit_error("")


def test_parse_retry_after_hms_format():
    assert _parse_retry_after("try again in 1h2m3.5s") == 3723


def test_parse_retry_after_minutes_only():
    assert _parse_retry_after("wait 5 minutes") == 300


def test_parse_retry_after_seconds_only():
    assert _parse_retry_after("wait 45 seconds") == 45


def test_parse_retry_after_no_match_returns_none():
    assert _parse_retry_after("nessuna indicazione") is None


# ---------------------------------------------------------------------------
# _has_no_real_gaps / _apply_consistency_guardrails
# ---------------------------------------------------------------------------

def test_has_no_real_gaps_empty_list():
    assert _has_no_real_gaps([]) is True


def test_has_no_real_gaps_only_no_gap_phrases():
    assert _has_no_real_gaps(["Nessuna lacuna riscontrata"]) is True


def test_has_no_real_gaps_real_gap_present():
    assert _has_no_real_gaps(["Manca la definizione di derivata"]) is False


def test_apply_consistency_guardrails_bumps_score_when_no_real_gaps():
    evaluation = EvaluationResult(
        score=6,
        motivation="Sufficiente.",
        correct_points=["Concetti chiave coperti"],
        missing_points=["Nessuna lacuna significativa"],
        improvement_after_guidance="Buono",
    )
    adjusted = _apply_consistency_guardrails(evaluation)
    assert adjusted.score == 9
    assert "corretto automaticamente" in adjusted.motivation


def test_apply_consistency_guardrails_leaves_real_gap_unchanged():
    evaluation = EvaluationResult(
        score=6,
        motivation="Sufficiente.",
        correct_points=[],
        missing_points=["Manca la definizione di derivata"],
        improvement_after_guidance="Parziale",
    )
    adjusted = _apply_consistency_guardrails(evaluation)
    assert adjusted == evaluation


def test_apply_consistency_guardrails_leaves_high_score_unchanged():
    evaluation = EvaluationResult(
        score=9, motivation="Ottimo", correct_points=[], missing_points=[], improvement_after_guidance="",
    )
    assert _apply_consistency_guardrails(evaluation) == evaluation


# ---------------------------------------------------------------------------
# SocraticTutor — loop completo con FakeAgent (nessuna chiamata LLM reale)
# ---------------------------------------------------------------------------

GUIDE_JSON = json.dumps({
    "guiding_question": "Cosa intendi con 'apprendere dai dati'?",
    "positive_feedback": "Hai citato correttamente i dati.",
    "focus_area": "definizione formale",
})

EVAL_JSON = json.dumps({
    "score": 7,
    "motivation": "Buona comprensione con qualche imprecisione.",
    "correct_points": ["Definizione generale corretta"],
    "missing_points": ["Manca un esempio pratico"],
    "improvement_after_guidance": "Risposta migliorata rispetto al primo tentativo.",
})

CONTEST_JSON = json.dumps({
    "final_score": 8,
    "contestation_assessment": "parzialmente_valido",
    "final_motivation": "L'argomentazione aggiunge un punto valido.",
    "response_to_student": "Accolgo parzialmente la contestazione.",
})


@pytest.fixture
def question_data():
    return {"id": 1, "text": "Cos'e' il machine learning?", "difficulty": "base", "topic_hint": "ml"}


def test_socratic_tutor_full_happy_path(monkeypatch, fake_agent_factory, question_data):
    monkeypatch.setattr(st_mod, "retrieve_chunks", lambda **kwargs: ["chunk di materiale sul machine learning"])
    monkeypatch.setattr(st_mod, "_guide_agent", fake_agent_factory(GUIDE_JSON))
    monkeypatch.setattr(st_mod, "_eval_agent", fake_agent_factory(EVAL_JSON))
    monkeypatch.setattr(st_mod, "_contest_agent", fake_agent_factory(CONTEST_JSON))

    tutor = SocraticTutor(student_id=1, exam_id=1)

    question_text = tutor.start(question_data)
    assert question_text == question_data["text"]
    assert tutor.attempt.state == TurnState.WAITING_ANSWER_1

    guide = tutor.submit_answer_1("forse e' qualcosa sui dati")
    assert guide["guiding_question"] == "Cosa intendi con 'apprendere dai dati'?"
    assert tutor.attempt.state == TurnState.WAITING_ANSWER_2

    evaluation = tutor.submit_answer_2("E' un modello che apprende pattern dai dati.")
    assert evaluation["score"] == 7
    assert evaluation["can_contest"] is True
    assert tutor.attempt.state == TurnState.EVALUATED

    contestation = tutor.submit_contestation("Credo meritasse un punteggio piu' alto perche'...")
    assert contestation["final_score"] == 8
    assert tutor.attempt.state == TurnState.CONTESTED

    closed = tutor.close()
    assert closed.state == TurnState.CLOSED
    assert closed.final_score == 8  # la contestazione prevale sulla valutazione iniziale


def test_socratic_tutor_non_answer_second_reply_forces_zero(monkeypatch, fake_agent_factory, question_data):
    monkeypatch.setattr(st_mod, "retrieve_chunks", lambda **kwargs: ["chunk"])
    monkeypatch.setattr(st_mod, "_guide_agent", fake_agent_factory(GUIDE_JSON))
    monkeypatch.setattr(st_mod, "_eval_agent", fake_agent_factory(EVAL_JSON))  # score=7 dall'agente

    tutor = SocraticTutor(student_id=1, exam_id=1)
    tutor.start(question_data)
    tutor.submit_answer_1("forse e' qualcosa sui dati")
    evaluation = tutor.submit_answer_2("non lo so")

    # Il guardrail di severita' forza lo score a 0 nonostante l'agente abbia risposto 7.
    assert evaluation["score"] == 0


def test_socratic_tutor_cannot_skip_states(monkeypatch, fake_agent_factory, question_data):
    monkeypatch.setattr(st_mod, "retrieve_chunks", lambda **kwargs: ["chunk"])
    monkeypatch.setattr(st_mod, "_guide_agent", fake_agent_factory(GUIDE_JSON))
    monkeypatch.setattr(st_mod, "_eval_agent", fake_agent_factory(EVAL_JSON))

    tutor = SocraticTutor(student_id=1, exam_id=1)
    tutor.start(question_data)

    with pytest.raises(RuntimeError):
        tutor.submit_answer_2("risposta prematura")

    with pytest.raises(RuntimeError):
        tutor.close()


def test_socratic_tutor_retries_on_rate_limit_then_succeeds(monkeypatch, fake_agent_factory, question_data):
    monkeypatch.setattr(st_mod, "retrieve_chunks", lambda **kwargs: ["chunk"])
    monkeypatch.setattr(st_mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        st_mod,
        "_guide_agent",
        fake_agent_factory(["Rate limit reached, try again in 1s", GUIDE_JSON]),
    )

    tutor = SocraticTutor(student_id=1, exam_id=1)
    tutor.start(question_data)
    guide = tutor.submit_answer_1("una risposta")
    assert guide["guiding_question"] == "Cosa intendi con 'apprendere dai dati'?"


# ---------------------------------------------------------------------------
# DoubtTutor — loop completo attraverso il vero livello agente (FakeAgent)
# ---------------------------------------------------------------------------

DOUBT_OPEN_JSON = json.dumps({
    "guiding_question": "Da dove nasce il tuo dubbio sui limiti?",
    "topic_hint": "limiti",
})

DOUBT_EVAL_JSON = json.dumps({
    "correct_points": ["Hai capito il concetto intuitivo"],
    "missing_points": ["Manca la definizione formale con epsilon-delta"],
    "correct_answer": "Un limite descrive il valore a cui tende una funzione, definito formalmente con epsilon-delta.",
})


def test_doubt_tutor_full_flow_via_agent_layer(monkeypatch, fake_agent_factory):
    monkeypatch.setattr(st_mod, "retrieve_chunks", lambda **kwargs: ["chunk sui limiti"])
    monkeypatch.setattr(st_mod, "_doubt_agent", fake_agent_factory([DOUBT_OPEN_JSON, DOUBT_EVAL_JSON]))

    tutor = DoubtTutor(student_id=1, exam_id=1)
    opening = tutor.start("non capisco bene i limiti")
    assert opening["guiding_question"] == "Da dove nasce il tuo dubbio sui limiti?"
    assert opening["topic_hint"] == "limiti"

    result = tutor.submit_answer("credo sia il valore finale della funzione")
    assert result["correct_answer"].startswith("Un limite descrive")
    assert "definizione formale" in result["missing_points"][0]
    assert tutor.attempt.state == DoubtState.ANSWERED
