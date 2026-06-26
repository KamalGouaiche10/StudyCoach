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

from backend.agents.socratic_tutor import (
    EvaluationResult,
    QuestionAttempt,
    _apply_severity_guardrails,
    _is_non_answer,
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
