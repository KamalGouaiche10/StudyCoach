"""Unit/integration test — backend/agents/quiz_generator.py."""

import json

import pytest

from backend.agents import quiz_generator as qg

VALID_QUIZ_JSON = json.dumps({
    "source_name": "Analisi 1",
    "questions": [
        {"id": 1, "text": "Cos'e' un limite?", "difficulty": "base", "topic_hint": "limiti"},
        {"id": 2, "text": "Spiega la derivata.", "difficulty": "intermedia", "topic_hint": "derivate"},
    ],
})


# ---------------------------------------------------------------------------
# _parse_llm_response
# ---------------------------------------------------------------------------

def test_parse_llm_response_valid_json():
    data = qg._parse_llm_response(VALID_QUIZ_JSON)
    assert data["source_name"] == "Analisi 1"
    assert len(data["questions"]) == 2


def test_parse_llm_response_strips_markdown_fences():
    wrapped = f"```json\n{VALID_QUIZ_JSON}\n```"
    data = qg._parse_llm_response(wrapped)
    assert len(data["questions"]) == 2


def test_parse_llm_response_strips_surrounding_text():
    wrapped = f"Ecco il JSON richiesto:\n{VALID_QUIZ_JSON}\nSpero vada bene!"
    data = qg._parse_llm_response(wrapped)
    assert len(data["questions"]) == 2


def test_parse_llm_response_repairs_trailing_commas():
    broken = '{"questions": [{"id": 1, "text": "domanda?", "difficulty": "base", "topic_hint": "x"},]}'
    data = qg._parse_llm_response(broken)
    assert len(data["questions"]) == 1


def test_parse_llm_response_empty_raises():
    with pytest.raises(ValueError, match="vuota"):
        qg._parse_llm_response("")


def test_parse_llm_response_missing_questions_field_raises():
    with pytest.raises(ValueError, match="questions"):
        qg._parse_llm_response('{"source_name": "x"}')


def test_parse_llm_response_questions_not_a_list_raises():
    with pytest.raises(ValueError):
        qg._parse_llm_response('{"questions": "not a list"}')


# ---------------------------------------------------------------------------
# _is_rate_limit_error
# ---------------------------------------------------------------------------

def test_is_rate_limit_error_detects_common_phrases():
    assert qg._is_rate_limit_error("Rate limit exceeded, try again in 5s")
    assert qg._is_rate_limit_error("HTTP 429 Too Many Requests")
    assert not qg._is_rate_limit_error("Tutto ok")
    assert not qg._is_rate_limit_error("")


# ---------------------------------------------------------------------------
# generate_quiz (integrazione con FakeAgent + RAG finto)
# ---------------------------------------------------------------------------

def test_generate_quiz_raises_without_indexed_material(monkeypatch):
    monkeypatch.setattr(qg, "retrieve_chunks", lambda **kwargs: [])
    with pytest.raises(ValueError, match="Nessun chunk trovato"):
        qg.generate_quiz(student_id=1, exam_id=1)


def test_generate_quiz_returns_parsed_questions(monkeypatch, fake_agent_factory):
    monkeypatch.setattr(qg, "retrieve_chunks", lambda **kwargs: ["chunk di materiale sui limiti"])
    monkeypatch.setattr(qg, "_make_quiz_agent", fake_agent_factory(VALID_QUIZ_JSON))

    result = qg.generate_quiz(student_id=1, exam_id=2, n_questions=2, source_name="Analisi 1")

    assert result.exam_id == 2
    assert result.student_id == 1
    assert result.n_questions == 2
    assert result.questions[0].text == "Cos'e' un limite?"
    assert result.questions[0].difficulty == "base"


def test_generate_quiz_retries_until_enough_valid_questions(monkeypatch, fake_agent_factory):
    monkeypatch.setattr(qg, "retrieve_chunks", lambda **kwargs: ["chunk"])
    monkeypatch.setattr(qg.time, "sleep", lambda *_: None)

    too_few = json.dumps({"source_name": "x", "questions": [
        {"id": 1, "text": "una sola domanda", "difficulty": "base", "topic_hint": "x"},
    ]})
    monkeypatch.setattr(qg, "_make_quiz_agent", fake_agent_factory([too_few, VALID_QUIZ_JSON]))

    result = qg.generate_quiz(student_id=1, exam_id=1, n_questions=2)
    assert result.n_questions == 2


def test_quiz_to_dict_and_json_roundtrip(monkeypatch, fake_agent_factory):
    monkeypatch.setattr(qg, "retrieve_chunks", lambda **kwargs: ["chunk"])
    monkeypatch.setattr(qg, "_make_quiz_agent", fake_agent_factory(VALID_QUIZ_JSON))

    result = qg.generate_quiz(student_id=1, exam_id=1, n_questions=2)
    d = qg.quiz_to_dict(result)
    assert d["exam_id"] == 1

    payload = qg.quiz_to_json(result)
    reparsed = json.loads(payload)
    assert reparsed["student_id"] == 1
